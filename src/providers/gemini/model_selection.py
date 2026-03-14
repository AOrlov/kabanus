"""Gemini model-role selection and quota tracking."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Optional, Sequence

from src.providers.errors import ProviderConfigurationError
from src.settings_models import ModelSpec

logger = logging.getLogger(__name__)


@dataclass
class ModelUsage:
    minute_window_start: float = 0.0
    minute_count: int = 0
    day: Optional[date] = None
    day_count: int = 0
    exhausted_until_day: Optional[date] = None

    def _reset_minute_if_needed(self, now: float) -> None:
        if now - self.minute_window_start >= 60:
            self.minute_window_start = now
            self.minute_count = 0

    def _reset_day_if_needed(self, today: date) -> None:
        if self.day != today:
            self.day = today
            self.day_count = 0
            self.exhausted_until_day = None

    def can_use(self, spec: ModelSpec, now: float, today: date) -> bool:
        self._reset_minute_if_needed(now)
        self._reset_day_if_needed(today)
        if self.exhausted_until_day == today:
            return False
        if spec.rpm is not None and self.minute_count >= spec.rpm:
            return False
        if spec.rpd is not None and self.day_count >= spec.rpd:
            return False
        return True

    def record_request(self, now: float, today: date) -> None:
        self._reset_minute_if_needed(now)
        self._reset_day_if_needed(today)
        self.minute_count += 1
        self.day_count += 1

    def mark_exhausted(self, today: date) -> None:
        self._reset_day_if_needed(today)
        self.exhausted_until_day = today


class GeminiModelSelector:
    def __init__(
        self,
        *,
        model_specs: Sequence[ModelSpec],
        default_model: str,
        low_cost_model: str,
        reaction_model: str,
    ) -> None:
        self._model_specs = list(model_specs)
        self._default_model = default_model.strip().lower()
        self._low_cost_model = low_cost_model.strip().lower()
        self._reaction_model = reaction_model.strip().lower()
        self._usage_by_model: Dict[str, ModelUsage] = {}
        self._specs_by_name: Dict[str, ModelSpec] = {}

        for spec in self._model_specs:
            model_name = spec.name.strip().lower()
            if not model_name:
                raise ProviderConfigurationError(
                    "Gemini model spec name cannot be empty",
                    provider="gemini",
                )
            if model_name in self._specs_by_name:
                raise ProviderConfigurationError(
                    f"Duplicate Gemini model spec configured: '{model_name}'",
                    provider="gemini",
                )
            self._specs_by_name[model_name] = spec

    def text_generation_specs(self) -> list[ModelSpec]:
        return self._ordered_specs(self._default_model)

    def low_cost_specs(self) -> list[ModelSpec]:
        return self._ordered_specs(self._low_cost_model)

    def reaction_specs(self) -> list[ModelSpec]:
        return self._ordered_specs(self._reaction_model)

    def multimodal_specs(self) -> list[ModelSpec]:
        return self._ordered_specs(self._default_model)

    def pick_model(self, specs: Sequence[ModelSpec]) -> Optional[ModelSpec]:
        now = time.monotonic()
        today = datetime.now().date()
        for spec in specs:
            usage = self._usage_by_model.setdefault(spec.name, ModelUsage())
            if usage.can_use(spec, now, today):
                return spec
        logger.error(
            "All configured Gemini models are exhausted for RPM/RPD limits.",
            extra={
                "event": "model_exhausted",
                "models": [spec.name for spec in specs],
            },
        )
        return None

    def record_request(self, spec: ModelSpec) -> None:
        usage = self._usage_by_model.setdefault(spec.name, ModelUsage())
        usage.record_request(time.monotonic(), datetime.now().date())

    def mark_exhausted(self, spec: ModelSpec) -> None:
        usage = self._usage_by_model.setdefault(spec.name, ModelUsage())
        usage.mark_exhausted(datetime.now().date())

    def _ordered_specs(self, preferred_model: str) -> list[ModelSpec]:
        if not self._model_specs:
            raise ProviderConfigurationError(
                "No Gemini models are configured",
                provider="gemini",
            )
        model_name = preferred_model.strip().lower()
        if not model_name:
            raise ProviderConfigurationError(
                "Gemini model role is empty",
                provider="gemini",
            )
        preferred_spec = self._specs_by_name.get(model_name)
        if preferred_spec is None:
            raise ProviderConfigurationError(
                f"Gemini model '{model_name}' is not present in GEMINI_MODELS",
                provider="gemini",
            )
        ordered = [preferred_spec]
        ordered.extend(
            spec for spec in self._model_specs if spec.name != preferred_spec.name
        )
        return ordered
