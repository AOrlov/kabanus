"""OpenAI provider implementation built from focused helper components."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterator

from openai import APIStatusError, AuthenticationError, OpenAI

from src.providers.contracts import (
    CapabilityName,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
)
from src.providers.errors import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderError,
)
from src.providers.openai.client import OpenAIClientFactory
from src.providers.openai.request_builder import (
    DEFAULT_ASSISTANT_INSTRUCTION,
    build_event_user_content,
    build_input_items,
    build_ocr_user_content,
    build_reaction_user_content,
    build_text_user_content,
    encode_image_bytes,
)
from src.providers.openai.response_parser import (
    extract_response_text,
    iter_stream_text_snapshots,
    parse_event_payload,
)

logger = logging.getLogger(__name__)


class OpenAIProvider:
    def __init__(
        self,
        settings: Any,
        *,
        client_factory: OpenAIClientFactory | None = None,
    ) -> None:
        self._settings = settings.ai.openai
        self._language = settings.language
        self._client_factory = client_factory or OpenAIClientFactory(self._settings)

    def _is_auth_error(self, exc: Exception) -> bool:
        if isinstance(exc, AuthenticationError):
            return True
        if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) in {
            401,
            403,
        }:
            return True
        status_code = getattr(exc, "status_code", None)
        if status_code in {401, 403}:
            return True
        text = str(exc).lower()
        return "401" in text or "unauthorized" in text or "invalid api key" in text

    def _is_quota_error(self, exc: Exception) -> bool:
        if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 429:
            return True
        if getattr(exc, "status_code", None) == 429:
            return True
        text = str(exc).lower()
        return any(
            marker in text
            for marker in ("429", "quota", "rate limit", "resource exhausted")
        )

    def _as_provider_error(
        self,
        exc: Exception,
        *,
        capability: CapabilityName,
    ) -> Exception:
        if isinstance(exc, ProviderError):
            return exc
        if self._is_auth_error(exc):
            return ProviderAuthError(
                str(exc),
                provider="openai",
                capability=capability,
            )
        if self._is_quota_error(exc):
            return ProviderQuotaError(
                str(exc),
                provider="openai",
                capability=capability,
            )
        return exc

    def _should_attempt_refresh(self, exc: Exception) -> bool:
        text = str(exc).lower()
        permission_markers = [
            "insufficient permissions",
            "missing scopes",
            "api.responses.write",
            "forbidden",
        ]
        if any(marker in text for marker in permission_markers):
            return False
        return self._is_auth_error(exc)

    def _is_codex_model_mismatch_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "not supported when using codex with a chatgpt account" in text
            or "model is not supported when using codex" in text
        )

    def _create_response(
        self,
        *,
        client: OpenAI,
        codex_mode: bool,
        model: str,
        user_content: Any,
        system_instruction: str = "",
    ) -> Any:
        input_items = build_input_items(
            user_content=user_content,
            system_instruction=system_instruction,
        )
        if codex_mode:
            kwargs: Dict[str, Any] = {
                "model": model,
                "input": input_items,
                "instructions": system_instruction or DEFAULT_ASSISTANT_INSTRUCTION,
                "store": False,
            }
            with client.responses.stream(**kwargs) as stream:
                stream.until_done()
                return stream.get_final_response()

        kwargs = {
            "model": model,
            "input": input_items,
        }
        if system_instruction:
            kwargs["instructions"] = system_instruction
        return client.responses.create(**kwargs)

    def _run_text_request(
        self,
        *,
        capability: CapabilityName,
        model: str,
        user_content: Any,
        system_instruction: str = "",
    ) -> str:
        client, client_options = self._client_factory.get_client_context()
        try:
            response = self._create_response(
                client=client,
                codex_mode=client_options.codex_mode,
                model=model,
                user_content=user_content,
                system_instruction=system_instruction,
            )
        except Exception as exc:
            if client_options.codex_mode and self._is_codex_model_mismatch_error(exc):
                fallback_model = self._settings.codex_default_model
                if fallback_model and fallback_model != model:
                    logger.warning(
                        "OpenAI Codex model '%s' is incompatible; retrying with '%s'",
                        model,
                        fallback_model,
                    )
                    try:
                        response = self._create_response(
                            client=client,
                            codex_mode=client_options.codex_mode,
                            model=fallback_model,
                            user_content=user_content,
                            system_instruction=system_instruction,
                        )
                    except Exception as fallback_exc:
                        raise self._as_provider_error(
                            fallback_exc,
                            capability=capability,
                        ) from fallback_exc
                else:
                    raise self._as_provider_error(
                        exc,
                        capability=capability,
                    ) from exc
            elif client_options.refreshable and self._should_attempt_refresh(exc):
                logger.warning(
                    "OpenAI auth failed; attempting token refresh from auth.json"
                )
                refreshed_client, refreshed_options = (
                    self._client_factory.get_client_context(force_refresh=True)
                )
                try:
                    response = self._create_response(
                        client=refreshed_client,
                        codex_mode=refreshed_options.codex_mode,
                        model=model,
                        user_content=user_content,
                        system_instruction=system_instruction,
                    )
                except Exception as refresh_exc:
                    raise self._as_provider_error(
                        refresh_exc,
                        capability=capability,
                    ) from refresh_exc
            else:
                raise self._as_provider_error(
                    exc,
                    capability=capability,
                ) from exc
        return extract_response_text(response)

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterator[str]:
        client, client_options = self._client_factory.get_client_context()
        input_items = build_input_items(
            user_content=build_text_user_content(request.prompt),
        )
        emitted = False

        def _stream_model_response(
            active_client: OpenAI,
            request_model: str,
            codex_mode: bool,
        ) -> Iterator[str]:
            kwargs: Dict[str, Any] = {
                "model": request_model,
                "input": input_items,
            }
            if codex_mode:
                kwargs["instructions"] = DEFAULT_ASSISTANT_INSTRUCTION
                kwargs["store"] = False
            with active_client.responses.stream(**kwargs) as stream:
                last_snapshot = ""
                try:
                    for snapshot in iter_stream_text_snapshots(stream):
                        last_snapshot = snapshot
                        yield snapshot
                except TypeError:
                    pass
                until_done = getattr(stream, "until_done", None)
                if callable(until_done):
                    until_done()
                final_text = extract_response_text(stream.get_final_response())
                if final_text and final_text != last_snapshot:
                    yield final_text

        def _emit(
            active_client: OpenAI,
            request_model: str,
            *,
            codex_mode: bool,
        ) -> Iterator[str]:
            nonlocal emitted
            for snapshot in _stream_model_response(
                active_client,
                request_model,
                codex_mode,
            ):
                emitted = True
                yield snapshot

        try:
            yield from _emit(
                client,
                self._settings.text_model,
                codex_mode=client_options.codex_mode,
            )
        except Exception as exc:
            if emitted:
                raise self._as_provider_error(
                    exc,
                    capability="streaming_text_generation",
                ) from exc
            if client_options.codex_mode and self._is_codex_model_mismatch_error(exc):
                fallback_model = self._settings.codex_default_model
                if fallback_model and fallback_model != self._settings.text_model:
                    logger.warning(
                        "OpenAI Codex model '%s' is incompatible; retrying with '%s'",
                        self._settings.text_model,
                        fallback_model,
                    )
                    try:
                        yield from _emit(
                            client,
                            fallback_model,
                            codex_mode=client_options.codex_mode,
                        )
                    except Exception as fallback_exc:
                        raise self._as_provider_error(
                            fallback_exc,
                            capability="streaming_text_generation",
                        ) from fallback_exc
                    return
                raise self._as_provider_error(
                    exc,
                    capability="streaming_text_generation",
                ) from exc
            if client_options.refreshable and self._should_attempt_refresh(exc):
                logger.warning(
                    "OpenAI auth failed; attempting token refresh from auth.json"
                )
                refreshed_client, refreshed_options = (
                    self._client_factory.get_client_context(force_refresh=True)
                )
                try:
                    yield from _emit(
                        refreshed_client,
                        self._settings.text_model,
                        codex_mode=refreshed_options.codex_mode,
                    )
                except Exception as refresh_exc:
                    raise self._as_provider_error(
                        refresh_exc,
                        capability="streaming_text_generation",
                    ) from refresh_exc
                return
            raise self._as_provider_error(
                exc,
                capability="streaming_text_generation",
            ) from exc

    def generate_text(self, request: TextGenerationRequest) -> str:
        return self._run_text_request(
            capability="text_generation",
            model=self._settings.text_model,
            user_content=build_text_user_content(request.prompt),
        )

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return self._run_text_request(
            capability="low_cost_text_generation",
            model=self._settings.low_cost_model,
            user_content=build_text_user_content(request.prompt),
        )

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        text = self._run_text_request(
            capability="reaction_selection",
            model=self._settings.reaction_model,
            system_instruction=(
                "You are a Telegram reactions selector. "
                "Return exactly one emoji from the allowed list."
            ),
            user_content=build_reaction_user_content(request),
        ).strip()
        if text in request.allowed_reactions:
            return text
        logger.warning("OpenAI returned unsupported reaction: %s", text)
        return ""

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        with open(request.image_path, "rb") as file_obj:
            image_bytes = file_obj.read()
        text = self._run_text_request(
            capability="event_parsing",
            model=self._settings.text_model,
            user_content=build_event_user_content(encode_image_bytes(image_bytes)),
        )
        try:
            return parse_event_payload(text)
        except json.JSONDecodeError:
            logger.warning("OpenAI returned non-JSON event payload")
            return {}

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return self._run_text_request(
            capability="ocr",
            model=self._settings.low_cost_model,
            user_content=build_ocr_user_content(
                encoded_image=encode_image_bytes(request.image_bytes),
                mime_type=request.mime_type,
                language=self._language,
            ),
        )
