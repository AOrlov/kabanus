"""Gemini provider implementation built from focused helper components."""

from __future__ import annotations

import functools
from typing import Any, Callable

from google.genai import errors

from src import retry_utils
from src.providers.contracts import (
    AudioTranscriptionRequest,
    CapabilityName,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
)
from src.providers.errors import (
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderQuotaError,
)
from src.providers.gemini.client import GeminiClientFactory
from src.providers.gemini.instructions import SystemInstructionLoader
from src.providers.gemini.model_selection import GeminiModelSelector
from src.providers.gemini.request_builder import (
    REACTION_SYSTEM_INSTRUCTION,
    build_audio_transcription_contents,
    build_event_contents,
    build_generation_config,
    build_ocr_contents,
    build_reaction_contents,
    build_text_contents,
    prepare_contents,
)
from src.providers.gemini.response_parser import (
    extract_text_response,
    parse_event_payload,
    parse_reaction_response,
)
from src.settings_models import ModelSpec


class GeminiProvider:
    def __init__(
        self,
        settings: Any,
        *,
        client_factory: GeminiClientFactory | None = None,
        model_selector: GeminiModelSelector | None = None,
        instruction_loader: SystemInstructionLoader | None = None,
    ) -> None:
        self._settings = settings.ai.gemini
        self._language = settings.language
        self._client_factory = client_factory or GeminiClientFactory(self._settings)
        self._model_selector = model_selector or GeminiModelSelector(
            model_specs=self._settings.model_specs,
            default_model=self._settings.default_model,
            low_cost_model=self._settings.low_cost_model,
            reaction_model=self._settings.reaction_model,
        )
        self._instruction_loader = instruction_loader or SystemInstructionLoader(
            self._settings.system_instructions_path,
        )

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        with open(request.audio_path, "rb") as file_obj:
            audio_bytes = file_obj.read()
        response, model_name = self._generate_content(
            capability="audio_transcription",
            specs=self._model_selector.multimodal_specs(),
            build_contents=lambda: build_audio_transcription_contents(
                audio_bytes=audio_bytes,
                language=self._language,
            ),
            system_instruction="",
            thinking_budget=self._settings.thinking_budget,
            max_attempts=5,
        )
        return extract_text_response(
            response,
            capability="audio_transcription",
            model_name=model_name,
        )

    def generate_text(self, request: TextGenerationRequest) -> str:
        response, model_name = self._generate_content(
            capability="text_generation",
            specs=self._model_selector.text_generation_specs(),
            build_contents=lambda: build_text_contents(request.prompt),
            system_instruction=self._instruction_loader.load(),
            thinking_budget=self._settings.thinking_budget,
            use_google_search=self._settings.use_google_search,
            max_attempts=5,
        )
        return extract_text_response(
            response,
            capability="text_generation",
            model_name=model_name,
        )

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        response, model_name = self._generate_content(
            capability="low_cost_text_generation",
            specs=self._model_selector.low_cost_specs(),
            build_contents=lambda: build_text_contents(request.prompt),
            system_instruction=self._instruction_loader.load(),
            thinking_budget=self._settings.thinking_budget,
            use_google_search=self._settings.use_google_search,
            max_attempts=5,
        )
        return extract_text_response(
            response,
            capability="low_cost_text_generation",
            model_name=model_name,
        )

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        response, model_name = self._generate_content(
            capability="reaction_selection",
            specs=self._model_selector.reaction_specs(),
            build_contents=lambda: build_reaction_contents(request),
            system_instruction=REACTION_SYSTEM_INSTRUCTION,
            thinking_budget=0,
            max_attempts=3,
        )
        return parse_reaction_response(
            response,
            model_name=model_name,
            allowed_reactions=request.allowed_reactions,
        )

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        with open(request.image_path, "rb") as file_obj:
            image_bytes = file_obj.read()
        response, model_name = self._generate_content(
            capability="event_parsing",
            specs=self._model_selector.multimodal_specs(),
            build_contents=lambda: build_event_contents(image_bytes=image_bytes),
            system_instruction=self._instruction_loader.load(),
            thinking_budget=self._settings.thinking_budget,
            max_attempts=5,
        )
        return parse_event_payload(response, model_name=model_name)

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        response, model_name = self._generate_content(
            capability="ocr",
            specs=self._model_selector.multimodal_specs(),
            build_contents=lambda: build_ocr_contents(
                image_bytes=request.image_bytes,
                mime_type=request.mime_type,
                language=self._language,
            ),
            system_instruction=self._instruction_loader.load(),
            thinking_budget=self._settings.thinking_budget,
            max_attempts=5,
        )
        return extract_text_response(
            response,
            capability="ocr",
            model_name=model_name,
        )

    def _generate_content(
        self,
        *,
        capability: CapabilityName,
        specs: list[ModelSpec],
        build_contents: Callable[[], Any],
        system_instruction: str,
        thinking_budget: int,
        max_attempts: int,
        use_google_search: bool = False,
    ) -> tuple[Any, str]:
        client = self._client_factory.get_client()
        base_contents = build_contents()
        selected_model = ""

        def run_request(spec: ModelSpec) -> Any:
            nonlocal selected_model
            selected_model = spec.name
            self._model_selector.record_request(spec)
            contents, request_instruction = prepare_contents(
                spec.name,
                base_contents,
                system_instruction,
            )
            return client.models.generate_content(
                model=spec.name,
                contents=contents,
                config=build_generation_config(
                    spec.name,
                    system_instruction=request_instruction,
                    thinking_budget=thinking_budget,
                    use_google_search=use_google_search,
                ),
            )

        response = self._run_with_retry(
            capability=capability,
            specs=specs,
            max_attempts=max_attempts,
            run_request=run_request,
        )
        return response, selected_model

    def _run_with_retry(
        self,
        *,
        capability: CapabilityName,
        specs: list[ModelSpec],
        max_attempts: int,
        run_request: Callable[[ModelSpec], Any],
    ) -> Any:
        response = retry_utils.retry_with_item(
            max_attempts=max_attempts,
            pick_item=lambda: self._model_selector.pick_model(specs),
            run=run_request,
            on_error=functools.partial(self._on_generate_error, capability),
        )
        if response is None:
            raise ProviderQuotaError(
                "No Gemini models are currently available for the requested capability",
                provider="gemini",
                capability=capability,
            )
        return response

    def _on_generate_error(
        self,
        capability: CapabilityName,
        spec: ModelSpec,
        attempt: int,
        max_attempts: int,
        exc: Exception,
    ) -> bool:
        if not isinstance(exc, errors.ClientError):
            return False

        if exc.status in {"UNAUTHENTICATED", "PERMISSION_DENIED"} or exc.code in {
            401,
            403,
        }:
            raise ProviderAuthError(
                exc.message or str(exc),
                provider="gemini",
                capability=capability,
            ) from exc

        if exc.status == "NOT_FOUND":
            raise ProviderConfigurationError(
                f"Gemini model '{spec.name}' is not available",
                provider="gemini",
                capability=capability,
            ) from exc

        if exc.status in {"INVALID_ARGUMENT", "FAILED_PRECONDITION"}:
            raise ProviderConfigurationError(
                exc.message or str(exc),
                provider="gemini",
                capability=capability,
            ) from exc

        if exc.status != "RESOURCE_EXHAUSTED" and exc.code != 429:
            return False

        self._model_selector.mark_exhausted(spec)
        if attempt < max_attempts:
            return True
        raise ProviderQuotaError(
            "Gemini model quota exhausted",
            provider="gemini",
            capability=capability,
        ) from exc
