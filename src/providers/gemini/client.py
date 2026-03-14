"""Gemini client construction with explicit API-key injection."""

from __future__ import annotations

from typing import Any, Optional

from google import genai

from src.providers.errors import ProviderConfigurationError


class GeminiClientFactory:
    def __init__(
        self,
        settings: Any,
        *,
        client_cls: type[genai.Client] = genai.Client,
    ) -> None:
        self._settings = settings
        self._client_cls = client_cls
        self._client: Optional[genai.Client] = None
        self._client_api_key: Optional[str] = None

    def get_client(self) -> genai.Client:
        api_key = self._settings.api_key.strip()
        if not api_key:
            raise ProviderConfigurationError(
                "Gemini API key is not configured",
                provider="gemini",
            )
        if self._client is None or api_key != self._client_api_key:
            self._client = self._client_cls(api_key=api_key)
            self._client_api_key = api_key
        return self._client
