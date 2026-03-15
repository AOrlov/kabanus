"""OpenAI client construction for API-key and auth.json modes."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from openai import OpenAI

from src.providers.errors import ProviderConfigurationError
from src.providers.openai.auth import OpenAIAuthManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenAIClientOptions:
    api_key: str
    base_url: Optional[str] = None
    default_headers: Dict[str, str] = field(default_factory=dict)
    codex_mode: bool = False
    refreshable: bool = False

    def signature(self) -> Tuple[str, str, str]:
        return (
            self.api_key,
            self.base_url or "",
            (
                json.dumps(self.default_headers, sort_keys=True)
                if self.default_headers
                else ""
            ),
        )


class OpenAIClientFactory:
    def __init__(
        self,
        settings: Any,
        *,
        auth_manager: Optional[OpenAIAuthManager] = None,
        client_cls: type[OpenAI] = OpenAI,
    ) -> None:
        self._settings = settings
        self._client_cls = client_cls
        self._auth_manager = auth_manager
        if self._auth_manager is None and self._settings.auth_json_path.strip():
            self._auth_manager = OpenAIAuthManager(
                auth_json_path=self._settings.auth_json_path,
                refresh_url_default=self._settings.refresh_url,
                client_id_default=self._settings.refresh_client_id,
                grant_type_default=self._settings.refresh_grant_type,
                leeway_secs=self._settings.auth_leeway_secs,
                timeout_secs=self._settings.auth_timeout_secs,
            )
        if self._auth_manager is not None:
            self._auth_manager.validate_standard_api_credentials()
        self._client: Optional[OpenAI] = None
        self._client_signature: Optional[Tuple[str, str, str]] = None

    def resolve_client_options(
        self,
        *,
        force_refresh: bool = False,
        use_codex: bool = True,
    ) -> OpenAIClientOptions:
        api_key = self._resolve_api_key(force_refresh=force_refresh)
        if not api_key:
            return OpenAIClientOptions(api_key="")
        refreshable = False
        if self._auth_manager is None:
            return OpenAIClientOptions(api_key=api_key)
        refreshable = self._auth_manager.has_refresh_token()
        if not use_codex:
            return OpenAIClientOptions(
                api_key=api_key,
                refreshable=refreshable,
            )

        account_id = self._extract_chatgpt_account_id(api_key)
        if not account_id:
            if refreshable:
                raise ProviderConfigurationError(
                    (
                        "OpenAI auth.json refresh-token mode requires a token with "
                        "chatgpt_account_id; re-run scripts/openai_codex_oauth.py"
                    ),
                    provider="openai",
                )
            return OpenAIClientOptions(
                api_key=api_key,
                refreshable=refreshable,
            )

        base_url = self._settings.codex_base_url.rstrip("/")
        if not base_url:
            base_url = "https://chatgpt.com/backend-api"
        if not base_url.endswith("/codex"):
            base_url = f"{base_url}/codex"
        return OpenAIClientOptions(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "chatgpt-account-id": account_id,
                "OpenAI-Beta": "responses=experimental",
                "originator": "pi",
            },
            codex_mode=True,
            refreshable=refreshable,
        )

    def get_client_context(
        self,
        *,
        force_refresh: bool = False,
        use_codex: bool = True,
    ) -> tuple[OpenAI, OpenAIClientOptions]:
        options = self.resolve_client_options(
            force_refresh=force_refresh,
            use_codex=use_codex,
        )
        if not options.api_key:
            raise ProviderConfigurationError(
                "OpenAI auth is not configured (missing API key and auth.json token)",
                provider="openai",
            )
        signature = options.signature()
        if self._client is None or signature != self._client_signature:
            kwargs: Dict[str, Any] = {"api_key": options.api_key}
            if options.base_url:
                kwargs["base_url"] = options.base_url
            if options.default_headers:
                kwargs["default_headers"] = options.default_headers
            try:
                self._client = self._client_cls(**kwargs)
            except Exception as exc:
                raise ProviderConfigurationError(
                    "Failed to initialize OpenAI client",
                    provider="openai",
                ) from exc
            self._client_signature = signature
        if self._client is None:
            raise ProviderConfigurationError(
                "Failed to initialize OpenAI client",
                provider="openai",
            )
        return self._client, options

    def _resolve_api_key(self, *, force_refresh: bool = False) -> str:
        if self._auth_manager is not None:
            return self._auth_manager.get_access_token(force_refresh=force_refresh)
        return self._settings.api_key

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
