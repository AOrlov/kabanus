"""System-instruction loading for Gemini requests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.providers.errors import ProviderConfigurationError

logger = logging.getLogger(__name__)


class SystemInstructionLoader:
    def __init__(
        self,
        path: str,
        *,
        base_dir: Optional[Path] = None,
    ) -> None:
        self._raw_path = path.strip()
        self._base_dir = base_dir or Path.cwd()
        self._cached_path: Optional[Path] = None
        self._cached_mtime: Optional[float] = None
        self._cached_text = ""
        self._warned_missing_path = False

    def load(self) -> str:
        if not self._raw_path:
            if not self._warned_missing_path:
                logger.warning(
                    "AI system instructions path is not set.",
                    extra={"event": "missing_system_instructions"},
                )
                self._warned_missing_path = True
            return ""

        path = self._resolve_path()
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            raise ProviderConfigurationError(
                f"Failed to stat Gemini system instructions: {path}",
                provider="gemini",
            ) from exc

        if path != self._cached_path or mtime != self._cached_mtime:
            try:
                self._cached_text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ProviderConfigurationError(
                    f"Failed to read Gemini system instructions: {path}",
                    provider="gemini",
                ) from exc
            self._cached_path = path
            self._cached_mtime = mtime
        return self._cached_text

    def _resolve_path(self) -> Path:
        path = Path(self._raw_path).expanduser()
        if not path.is_absolute():
            path = (self._base_dir / path).resolve()
        else:
            path = path.resolve()
        if not path.is_file():
            raise ProviderConfigurationError(
                f"Gemini system instructions path must point to a file: {path}",
                provider="gemini",
            )
        return path
