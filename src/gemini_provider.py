# gemini_provider.py
import json
import logging
import os
import time
from datetime import datetime
import re
from typing import List

from google import genai
from google.genai import types, errors

from src import config, utils

from .model_provider import ModelProvider

logger = logging.getLogger(__name__)


class GeminiProvider(ModelProvider):

    def __init__(self):
        self._client = None
        self._client_api_key = None
        self._system_instructions = ""
        self._system_instructions_path = None
        self._system_instructions_mtime = None

    def _get_client(self):
        settings = config.get_settings()
        api_key = settings.google_api_key
        if self._client is None or api_key != self._client_api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            self._client = genai.Client()
            self._client_api_key = api_key
        return self._client, settings

    def _get_system_instructions(self, settings):
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

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[f"Transcribe this audio to {settings.language} text.",
                      types.Part.from_bytes(
                          data=audio_bytes,
                          mime_type="audio/ogg",
            )],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=settings.thinking_budget)
            )
        )

        return response.text.strip() if response.text else ""

    def generate(self, prompt: str) -> str:
        client, settings = self._get_client()
        system_instructions = self._get_system_instructions(settings)
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        logger.debug("Generating content with model: %s", settings.gemini_model)
        for attempt in range(1, 6):
            try:
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instructions,
                        thinking_config=types.ThinkingConfig(thinking_budget=settings.thinking_budget),
                        tools=[grounding_tool] if settings.use_google_search else None,
                    ),
                )
                break
            except errors.ClientError as e:
                if e.status == "NOT_FOUND":
                    all_models = " ,".join(f"'{m}'" for m in client.models.list())
                    logger.error("Gemini model %s not found. Available models: %s", settings.gemini_model, all_models)
                    raise
                if e.status == "RESOURCE_EXHAUSTED":
                    logger.error(
                        "Gemini model %s quota exhausted. Retry %s/5 in 60s.",
                        settings.gemini_model,
                        attempt,
                    )
                    logger.debug("ClientError details: %s", e)
                    if attempt < 5:
                        time.sleep(60)
                        continue
                raise

        return response.text.strip() if response.text else ""

    def choose_reaction(self, message: str, allowed_reactions: List[str]) -> str:
        client, settings = self._get_client()
        system_instruction = (
            "You are a Telegram reactions selector. "
            "Pick a single reaction emoji that fits the user message. "
            "Return only the emoji, nothing else."
        )
        prompt = f"Message: {message}\nAllowed reactions: {', '.join(allowed_reactions)}"
        logger.debug("Choosing reaction with model: %s", settings.reaction_gemini_model)
        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model=settings.reaction_gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        thinking_config=types.ThinkingConfig(thinking_budget=settings.thinking_budget),
                    ),
                )
                break
            except errors.ClientError as e:
                if e.status == "RESOURCE_EXHAUSTED":
                    logger.error(
                        "Gemini model %s quota exhausted while choosing reaction. Retry %s/3 in 5s.",
                        settings.reaction_gemini_model,
                        attempt,
                    )
                    logger.debug("ClientError details: %s", e)
                    if attempt < 3:
                        time.sleep(5)
                        continue
                raise

        return response.text.strip() if response.text else ""

    def parse_image_to_event(self, image_path: str) -> dict:
        client, settings = self._get_client()
        system_instructions = self._get_system_instructions(settings)
        with open(image_path, "rb") as f:
            image_data = f.read()

        response = client.models.generate_content(
            model='gemini-pro-vision',
            contents=[
                "Analyze this image and extract event information. " +
                "Provide a JSON response with the following fields: " +
                "title (string), date (YYYY-MM-DD), time (HH:MM), " +
                "location (string), description (string), " +
                "confidence (float between 0 and 1). " +
                "If any field is unclear, set it to null." +
                f"If there is no year, set it to current year ({datetime.now().year})",
                {"mime_type": "image/jpeg", "data": image_data}
            ],
            config=types.GenerateContentConfig(
                system_instruction=system_instructions,
                thinking_config=types.ThinkingConfig(thinking_budget=settings.thinking_budget),
            ),
        )
        event_data = json.loads(utils.strip_markdown_to_json(response.text or ""))
        logger.info(f"Event data from model: {event_data}")

        return event_data

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        """Extracts readable content from image bytes and returns plain text."""
        client, settings = self._get_client()
        system_instructions = self._get_system_instructions(settings)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                (
                    f"Extract all visible text from the image and, if helpful, "
                    f"briefly describe important visual content. Respond in {settings.language}. "
                    f"Return plain text only without any markdown or JSON."
                ),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                system_instruction=system_instructions,
                thinking_config=types.ThinkingConfig(thinking_budget=settings.thinking_budget),
            ),
        )
        return (response.text or "").strip()

    def list_models(self) -> List[str]:
        client, _ = self._get_client()
        return [model.name for model in client.models.list() if model.name is not None]
