"""Typed provider errors."""

from __future__ import annotations

from typing import Optional

from src.providers.contracts import CapabilityName, ProviderName


class ProviderError(Exception):
    """Base class for provider failures that callers may want to handle explicitly."""

    def __init__(
        self,
        message: str,
        *,
        provider: ProviderName,
        capability: Optional[CapabilityName] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.capability = capability


class ProviderConfigurationError(ProviderError):
    """Raised when provider configuration is invalid or incomplete."""


class ProviderAuthError(ProviderError):
    """Raised when provider authentication fails."""


class ProviderQuotaError(ProviderError):
    """Raised when the provider refuses a request due to quota or rate limits."""


class ProviderCapabilityError(ProviderError):
    """Raised when a provider does not support the requested capability."""


class ProviderResponseError(ProviderError):
    """Raised when a provider returns an empty or invalid response payload."""
