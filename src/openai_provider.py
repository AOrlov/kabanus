import base64
import json
import logging
from typing import Any, Dict, Iterator, Optional, Tuple

from openai import APIStatusError, AuthenticationError, OpenAI

from src import config, utils
from src.openai_auth import OpenAIAuthManager
from src.model_provider import ModelProvider
from src.providers.contracts import (
    AudioTranscriptionRequest,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
    build_reaction_prompt,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(ModelProvider):
    def __init__(self) -> None:
        self._client: Optional[OpenAI] = None
        self._client_signature: Optional[Tuple[str, str, str]] = None
        self._auth_manager: Optional[OpenAIAuthManager] = None
        self._auth_manager_path: Optional[str] = None

    def _get_auth_manager(
        self, settings: config.Settings
    ) -> Optional[OpenAIAuthManager]:
        auth_json_path = settings.openai_auth_json_path.strip()
        if not auth_json_path:
            return None
        if self._auth_manager is None or self._auth_manager_path != auth_json_path:
            self._auth_manager = OpenAIAuthManager(
                auth_json_path=auth_json_path,
                refresh_url_default=settings.openai_refresh_url,
                client_id_default=settings.openai_refresh_client_id,
                grant_type_default=settings.openai_refresh_grant_type,
                leeway_secs=settings.openai_auth_leeway_secs,
                timeout_secs=settings.openai_auth_timeout_secs,
            )
            self._auth_manager_path = auth_json_path
        return self._auth_manager

    def _resolve_api_key(
        self, settings: config.Settings, force_refresh: bool = False
    ) -> str:
        auth_manager = self._get_auth_manager(settings)
        if auth_manager is not None:
            return auth_manager.get_access_token(force_refresh=force_refresh)
        return settings.openai_api_key

    def _extract_chatgpt_account_id(self, token: str) -> str:
        parts = token.split(".")
        if len(parts) < 2:
            return ""
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        except Exception:
            return ""
        auth_claim = claims.get("https://api.openai.com/auth")
        if not isinstance(auth_claim, dict):
            return ""
        account_id = auth_claim.get("chatgpt_account_id")
        return account_id if isinstance(account_id, str) else ""

    def _resolve_client_options(
        self,
        settings: config.Settings,
        *,
        force_refresh: bool = False,
    ) -> Tuple[str, Optional[str], Dict[str, str]]:
        api_key = self._resolve_api_key(settings, force_refresh=force_refresh)
        if not api_key:
            return "", None, {}
        auth_manager = self._get_auth_manager(settings)
        if auth_manager is None:
            return api_key, None, {}

        account_id = self._extract_chatgpt_account_id(api_key)
        if not account_id:
            logger.warning(
                "auth.json token has no chatgpt_account_id claim; using default OpenAI API endpoint"
            )
            return api_key, None, {}

        base_url = settings.openai_codex_base_url.rstrip("/")
        if not base_url:
            base_url = "https://chatgpt.com/backend-api"
        if not base_url.endswith("/codex"):
            base_url = f"{base_url}/codex"
        default_headers = {
            "chatgpt-account-id": account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": "pi",
        }
        return api_key, base_url, default_headers

    def _get_client(
        self, force_refresh: bool = False
    ) -> tuple[OpenAI, config.Settings]:
        settings = config.get_settings()
        api_key, base_url, default_headers = self._resolve_client_options(
            settings, force_refresh=force_refresh
        )
        if not api_key:
            raise RuntimeError(
                "OpenAI auth is not configured (missing API key and auth.json token)"
            )
        signature = (
            api_key,
            base_url or "",
            json.dumps(default_headers, sort_keys=True) if default_headers else "",
        )
        if self._client is None or signature != self._client_signature:
            kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            if default_headers:
                kwargs["default_headers"] = default_headers
            self._client = OpenAI(**kwargs)
            self._client_signature = signature
        if self._client is None:
            raise RuntimeError("Failed to initialize OpenAI client")
        return self._client, settings

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

    def _should_attempt_refresh(self, exc: Exception) -> bool:
        text = str(exc).lower()
        # Scope/permission errors are not fixed by refresh and only add noise.
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

    def _extract_text(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text.strip()

        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return "\n".join(chunks).strip()

    def _build_input_items(
        self, *, user_content: Any, system_instruction: str = ""
    ) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        if system_instruction:
            input_items.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_instruction}],
                }
            )
        input_items.append({"role": "user", "content": user_content})
        return input_items

    def _iter_stream_text_snapshots(self, stream: Any) -> Iterator[str]:
        accumulated = ""
        for event in stream:
            event_type = str(getattr(event, "type", ""))
            if event_type != "response.output_text.delta":
                continue
            delta = getattr(event, "delta", None)
            if not isinstance(delta, str) or not delta:
                continue
            accumulated += delta
            yield accumulated

    def _responses_create(
        self, *, model: str, user_content: Any, system_instruction: str = ""
    ) -> str:
        input_items = self._build_input_items(
            user_content=user_content,
            system_instruction=system_instruction,
        )
        client, settings = self._get_client()
        codex_mode = bool(settings.openai_auth_json_path)
        instructions = (
            system_instruction if system_instruction else "You are a helpful assistant."
        )

        def _create_response(request_model: str) -> Any:
            if codex_mode:
                kwargs: Dict[str, Any] = {
                    "model": request_model,
                    "input": input_items,
                    "instructions": instructions,
                    "store": False,
                }
                with client.responses.stream(**kwargs) as stream:
                    stream.until_done()
                    return stream.get_final_response()
            kwargs = {
                "model": request_model,
                "input": input_items,
            }
            if system_instruction:
                kwargs["instructions"] = instructions
            return client.responses.create(**kwargs)

        try:
            response = _create_response(model)
        except Exception as exc:
            if codex_mode and self._is_codex_model_mismatch_error(exc):
                fallback_model = settings.openai_codex_default_model
                if fallback_model and fallback_model != model:
                    logger.warning(
                        "OpenAI Codex model '%s' is incompatible; retrying with '%s'",
                        model,
                        fallback_model,
                    )
                    response = _create_response(fallback_model)
                else:
                    raise
            # For auth.json-based flow, attempt one forced refresh and retry.
            elif settings.openai_auth_json_path and self._should_attempt_refresh(exc):
                logger.warning(
                    "OpenAI auth failed; attempting token refresh from auth.json"
                )
                client, _ = self._get_client(force_refresh=True)
                response = _create_response(model)
            else:
                raise
        return self._extract_text(response)

    def _text_user_content(self, prompt: str) -> list[dict[str, str]]:
        return [{"type": "input_text", "text": prompt}]

    def _encode_image_bytes(self, image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("ascii")

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        _ = request
        raise NotImplementedError(
            "OpenAI transcription is intentionally disabled in this iteration"
        )

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterator[str]:
        client, settings = self._get_client()
        codex_mode = bool(settings.openai_auth_json_path)
        instructions = "You are a helpful assistant."
        input_items = self._build_input_items(
            user_content=self._text_user_content(request.prompt),
            system_instruction="",
        )
        emitted = False

        def _stream_model_response(
            active_client: OpenAI, request_model: str
        ) -> Iterator[str]:
            kwargs: Dict[str, Any] = {
                "model": request_model,
                "input": input_items,
            }
            if codex_mode:
                kwargs["instructions"] = instructions
                kwargs["store"] = False
            with active_client.responses.stream(**kwargs) as stream:
                last_snapshot = ""
                try:
                    for snapshot in self._iter_stream_text_snapshots(stream):
                        last_snapshot = snapshot
                        yield snapshot
                except TypeError:
                    # Older SDK variants may not expose stream events as an iterator.
                    pass
                until_done = getattr(stream, "until_done", None)
                if callable(until_done):
                    until_done()
                final_text = self._extract_text(stream.get_final_response())
                if final_text and final_text != last_snapshot:
                    yield final_text

        def _emit(active_client: OpenAI, request_model: str) -> Iterator[str]:
            nonlocal emitted
            for snapshot in _stream_model_response(active_client, request_model):
                emitted = True
                yield snapshot

        try:
            yield from _emit(client, settings.openai_model)
        except Exception as exc:
            if emitted:
                raise
            if codex_mode and self._is_codex_model_mismatch_error(exc):
                fallback_model = settings.openai_codex_default_model
                if fallback_model and fallback_model != settings.openai_model:
                    logger.warning(
                        "OpenAI Codex model '%s' is incompatible; retrying with '%s'",
                        settings.openai_model,
                        fallback_model,
                    )
                    yield from _emit(client, fallback_model)
                    return
                raise
            if settings.openai_auth_json_path and self._should_attempt_refresh(exc):
                logger.warning(
                    "OpenAI auth failed; attempting token refresh from auth.json"
                )
                refreshed_client, _ = self._get_client(force_refresh=True)
                yield from _emit(refreshed_client, settings.openai_model)
                return
            raise

    def generate_text(self, request: TextGenerationRequest) -> str:
        _, settings = self._get_client()
        return self._responses_create(
            model=settings.openai_model,
            user_content=self._text_user_content(request.prompt),
        )

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        _, settings = self._get_client()
        return self._responses_create(
            model=settings.openai_low_cost_model,
            user_content=self._text_user_content(request.prompt),
        )

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        _, settings = self._get_client()
        text = self._responses_create(
            model=settings.openai_reaction_model,
            system_instruction=(
                "You are a Telegram reactions selector. "
                "Return exactly one emoji from the allowed list."
            ),
            user_content=[
                {
                    "type": "input_text",
                    "text": build_reaction_prompt(request),
                }
            ],
        ).strip()
        if text in request.allowed_reactions:
            return text
        logger.warning("OpenAI returned unsupported reaction: %s", text)
        return ""

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        _, settings = self._get_client()
        with open(request.image_path, "rb") as f:
            image_bytes = f.read()
        encoded = self._encode_image_bytes(image_bytes)
        text = self._responses_create(
            model=settings.openai_model,
            user_content=[
                {
                    "type": "input_text",
                    "text": (
                        "Extract event data from image and return JSON only with fields: "
                        "title (string), date (YYYY-MM-DD), time (HH:MM or null), "
                        "location (string or null), description (string or null), "
                        "confidence (float 0..1). If unknown use null."
                    ),
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                },
            ],
        )
        if not text:
            return {}
        try:
            return json.loads(utils.strip_markdown_to_json(text))
        except json.JSONDecodeError:
            logger.warning("OpenAI returned non-JSON event payload")
            return {}

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        _, settings = self._get_client()
        encoded = self._encode_image_bytes(request.image_bytes)
        return self._responses_create(
            model=settings.openai_low_cost_model,
            user_content=[
                {
                    "type": "input_text",
                    "text": (
                        f"Extract all visible text and describe key visual details in {settings.language}. "
                        "Return plain text only."
                    ),
                },
                {
                    "type": "input_image",
                    "image_url": f"data:{request.mime_type};base64,{encoded}",
                },
            ],
        )
