# gemini_provider.py
import json
import logging
import os
import time
from datetime import datetime
import re
import functools
from typing import Dict, List, Optional

from google import genai
from google.genai import types, errors

from src import config, retry_utils, utils

from .model_provider import ModelProvider

logger = logging.getLogger(__name__)


class _ModelUsage:
    def __init__(self) -> None:
        self.minute_window_start = 0.0
        self.minute_count = 0
        self.day = None
        self.day_count = 0
        self.cooldown_until = 0.0
        self.exhausted_until_day = None

    def _reset_minute_if_needed(self, now: float) -> None:
        if now - self.minute_window_start >= 60:
            self.minute_window_start = now
            self.minute_count = 0

    def _reset_day_if_needed(self, today) -> None:
        if self.day != today:
            self.day = today
            self.day_count = 0
            self.exhausted_until_day = None

    def can_use(self, spec: config.ModelSpec, now: float, today) -> bool:
        self._reset_minute_if_needed(now)
        self._reset_day_if_needed(today)
        if self.cooldown_until and now < self.cooldown_until:
            return False
        if self.exhausted_until_day == today:
            return False
        if spec.rpm is not None and self.minute_count >= spec.rpm:
            return False
        if spec.rpd is not None and self.day_count >= spec.rpd:
            return False
        return True

    def record_request(self, now: float, today) -> None:
        self._reset_minute_if_needed(now)
        self._reset_day_if_needed(today)
        self.minute_count += 1
        self.day_count += 1

    def mark_exhausted(self, today) -> None:
        self.exhausted_until_day = today


class _ModelRouter:
    def __init__(self) -> None:
        self._usage_by_model: Dict[str, _ModelUsage] = {}

    def pick_model(self, specs: List[config.ModelSpec]) -> Optional[config.ModelSpec]:
        now = time.monotonic()
        today = datetime.now().date()
        for spec in specs:
            usage = self._usage_by_model.setdefault(spec.name, _ModelUsage())
            if usage.can_use(spec, now, today):
                return spec
        logger.error("All configured models exhausted for RPM/RPD limits.")
        return None

    def record_request(self, spec: config.ModelSpec) -> None:
        usage = self._usage_by_model.setdefault(spec.name, _ModelUsage())
        usage.record_request(time.monotonic(), datetime.now().date())

    def mark_exhausted(self, spec: config.ModelSpec) -> None:
        usage = self._usage_by_model.setdefault(spec.name, _ModelUsage())
        usage.mark_exhausted(datetime.now().date())


class GeminiProvider(ModelProvider):

    def __init__(self):
        self._client = None
        self._client_api_key = None
        self._system_instructions = ""
        self._system_instructions_path = None
        self._system_instructions_mtime = None
        self._model_router = _ModelRouter()

    def _supports_system_instruction(self, model_name: str) -> bool:
        return "gemma" not in model_name.lower()

    def _supports_tools(self, model_name: str) -> bool:
        return "gemma" not in model_name.lower()

    def _supports_thinking_config(self, model_name: str) -> bool:
        return "gemma" not in model_name.lower()

    def _prefer_gemma_first(self, specs: List[config.ModelSpec]) -> List[config.ModelSpec]:
        return sorted(specs, key=lambda spec: "gemma" not in spec.name.lower())

    def _prepare_contents(
        self,
        spec: config.ModelSpec,
        contents,
        system_instruction: str,
    ):
        if not system_instruction:
            return contents, None
        if self._supports_system_instruction(spec.name):
            return contents, system_instruction
        if isinstance(contents, str):
            return f"{system_instruction}\n\n{contents}", None
        if isinstance(contents, list) and contents:
            if isinstance(contents[0], str):
                contents = [f"{system_instruction}\n\n{contents[0]}"] + contents[1:]
            else:
                contents = [system_instruction] + contents
        return contents, None

    def _prepare_config(
        self,
        spec: config.ModelSpec,
        *,
        system_instruction: Optional[str],
        thinking_budget: int,
        tools=None,
    ) -> types.GenerateContentConfig:
        if not self._supports_thinking_config(spec.name):
            thinking_budget = 0
        if not self._supports_tools(spec.name):
            tools = None
        if thinking_budget > 0:
            thinking_config = types.ThinkingConfig(thinking_budget=thinking_budget)
        else:
            thinking_config = None
        return types.GenerateContentConfig(
            system_instruction=system_instruction,
            thinking_config=thinking_config,
            tools=tools,
        )


    def _on_generate_error(
        self,
        client: genai.Client,
        spec: config.ModelSpec,
        attempt: int,
        max_attempts: int,
        exc: Exception,
    ) -> bool:
        """
        Handles errors during content generation.
        Returns True to retry with another model, False to stop retrying.
        """
        if not isinstance(exc, errors.ClientError):
            return False
        if exc.status == "NOT_FOUND":
            all_models = " ,".join(f"'{m}'" for m in client.models.list())
            logger.error("Gemini model %s not found. Available models: %s", spec.name, all_models)
            raise exc
        if exc.status != "RESOURCE_EXHAUSTED":
            return False
        logger.error(
            "Gemini model %s quota exhausted. Retry %s/%s with next model.",
            spec.name,
            attempt,
            max_attempts,
        )
        logger.debug("ClientError details: %s", exc)
        self._model_router.mark_exhausted(spec)
        if attempt < max_attempts:
            return True
        return False

    def _get_client(self):
        settings = config.get_settings()
        api_key = settings.google_api_key
        if self._client is None or api_key != self._client_api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            self._client = genai.Client()
            self._client_api_key = api_key
        return self._client, settings

    def _get_system_instructions(self, settings):
        if settings.ai_system_instructions_path == "":
            logger.warning("AI system instructions path is not set.")
            return ""
        path = os.path.join(os.path.dirname(__file__), settings.ai_system_instructions_path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if path != self._system_instructions_path or mtime != self._system_instructions_mtime:
            with open(path, "r", encoding="utf-8") as f:
                self._system_instructions = f.read()
            self._system_instructions_path = path
            self._system_instructions_mtime = mtime
        return self._system_instructions

    def transcribe(self, audio_path: str) -> str:
        client, settings = self._get_client()
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        def run_request(spec: config.ModelSpec):
            self._model_router.record_request(spec)
            return client.models.generate_content(
                model=spec.name,
                contents=[
                    f"Transcribe this audio to {settings.language} text.",
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type="audio/ogg",
                    ),
                ],
                config=self._prepare_config(
                    spec,
                    system_instruction=None,
                    thinking_budget=settings.thinking_budget,
                ),
            )

        response = retry_utils.retry_with_item(
            max_attempts=5,
            pick_item=lambda: self._model_router.pick_model(settings.gemini_models),
            run=run_request,
            on_error=functools.partial(self._on_generate_error, client),
        )
        if response is None:
            return ""

        return response.text.strip() if response.text else ""

    def generate(self, prompt: str) -> str:
        client, settings = self._get_client()
        system_instructions = self._get_system_instructions(settings)
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        def run_request(spec: config.ModelSpec):
            logger.debug("Generating content with model: %s", spec.name)
            self._model_router.record_request(spec)
            contents, system_instruction = self._prepare_contents(
                spec,
                prompt,
                system_instructions,
            )
            return client.models.generate_content(
                model=spec.name,
                contents=contents,
                config=self._prepare_config(
                    spec,
                    system_instruction=system_instruction,
                    thinking_budget=settings.thinking_budget,
                    tools=[grounding_tool] if settings.use_google_search else None,
                ),
            )

        response = retry_utils.retry_with_item(
            max_attempts=5,
            pick_item=lambda: self._model_router.pick_model(settings.gemini_models),
            run=run_request,
            on_error=functools.partial(self._on_generate_error, client),
        )
        if response is None:
            return ""

        return response.text.strip() if response.text else ""

    def choose_reaction(self, message: str, allowed_reactions: List[str]) -> str:
        client, settings = self._get_client()
        system_instruction = (
            "You are a Telegram reactions selector. "
            "Pick a single reaction emoji that fits the user message. "
            "Return only the emoji, nothing else."
        )
        prompt = f"Message: {message}\nAllowed reactions: {', '.join(allowed_reactions)}"
        reaction_specs = self._prefer_gemma_first(settings.gemini_models)

        def run_request(spec: config.ModelSpec):
            logger.debug("Choosing reaction with model: %s", spec.name)
            self._model_router.record_request(spec)
            contents, instruction = self._prepare_contents(
                spec,
                prompt,
                system_instruction,
            )
            return client.models.generate_content(
                model=spec.name,
                contents=contents,
                config=self._prepare_config(
                    spec,
                    system_instruction=instruction,
                    thinking_budget=settings.thinking_budget,
                ),
            )

        response = retry_utils.retry_with_item(
            max_attempts=3,
            pick_item=lambda: self._model_router.pick_model(reaction_specs),
            run=run_request,
            on_error=functools.partial(self._on_generate_error, client),
        )
        if response is None:
            return ""

        return response.text.strip() if response.text else ""

    def parse_image_to_event(self, image_path: str) -> dict:
        client, settings = self._get_client()
        system_instructions = self._get_system_instructions(settings)
        with open(image_path, "rb") as f:
            image_data = f.read()

        def run_request(spec: config.ModelSpec):
            self._model_router.record_request(spec)
            contents, system_instruction = self._prepare_contents(
                spec,
                [
                    "Analyze this image and extract event information. " +
                    "Provide a JSON response with the following fields: " +
                    "title (string), date (YYYY-MM-DD), time (HH:MM), " +
                    "location (string), description (string), " +
                    "confidence (float between 0 and 1). " +
                    "If any field is unclear, set it to null." +
                    f"If there is no year, set it to current year ({datetime.now().year})",
                    {"mime_type": "image/jpeg", "data": image_data}
                ],
                system_instructions,
            )
            return client.models.generate_content(
                model=spec.name,
                contents=contents,
                config=self._prepare_config(
                    spec,
                    system_instruction=system_instruction,
                    thinking_budget=settings.thinking_budget,
                ),
            )

        response = retry_utils.retry_with_item(
            max_attempts=5,
            pick_item=lambda: self._model_router.pick_model(settings.gemini_models),
            run=run_request,
            on_error=functools.partial(self._on_generate_error, client),
        )
        if response is None:
            return {}
        event_data = json.loads(utils.strip_markdown_to_json(response.text or ""))
        logger.info(f"Event data from model: {event_data}")

        return event_data

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        """Extracts readable content from image bytes and returns plain text."""
        client, settings = self._get_client()
        system_instructions = self._get_system_instructions(settings)
        def run_request(spec: config.ModelSpec):
            self._model_router.record_request(spec)
            contents, system_instruction = self._prepare_contents(
                spec,
                [
                    (
                        f"Extract all visible text from the image and, if helpful, "
                        f"briefly describe important visual content. Respond in {settings.language}. "
                        f"Return plain text only without any markdown or JSON."
                    ),
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                system_instructions,
            )
            return client.models.generate_content(
                model=spec.name,
                contents=contents,
                config=self._prepare_config(
                    spec,
                    system_instruction=system_instruction,
                    thinking_budget=settings.thinking_budget,
                ),
            )

        response = retry_utils.retry_with_item(
            max_attempts=5,
            pick_item=lambda: self._model_router.pick_model(settings.gemini_models),
            run=run_request,
            on_error=functools.partial(self._on_generate_error, client),
        )
        if response is None:
            return ""
        return (response.text or "").strip()

    def list_models(self) -> List[str]:
        client, _ = self._get_client()
        return [model.name for model in client.models.list() if model.name is not None]
