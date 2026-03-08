"""Reusable runtime bootstrap primitives for Telegram polling applications."""

import inspect
import logging
from typing import Any, Callable, Optional

from telegram.ext import Application

logger = logging.getLogger(__name__)


def supports_force_kwarg(settings_getter: Callable[..., Any]) -> bool:
    try:
        getter_signature = inspect.signature(settings_getter)
    except (TypeError, ValueError):
        return True

    force_param = getter_signature.parameters.get("force")
    if force_param and force_param.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    ):
        return True

    return any(
        parameter.kind
        in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
        for parameter in getter_signature.parameters.values()
    )


class SettingsResolver:
    def __init__(self, settings_getter: Callable[..., Any]) -> None:
        self._settings_getter = settings_getter
        self._settings_getter_accepts_force = supports_force_kwarg(settings_getter)

    def get(self, force: bool = False) -> Any:
        if self._settings_getter_accepts_force:
            return self._settings_getter(force=force)
        return self._settings_getter()


class PollingRuntime:
    def __init__(
        self,
        *,
        settings_getter: Callable[..., Any],
        build_application_fn: Callable[[Any], Application],
        logger_override: Optional[logging.Logger] = None,
        startup_log_message: str = "Bot started with features: %s",
        startup_log_value_fn: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._settings = SettingsResolver(settings_getter)
        self._build_application_fn = build_application_fn
        self._logger = logger_override or logger
        self._startup_log_message = startup_log_message
        self._startup_log_value_fn = (
            startup_log_value_fn or (lambda settings: getattr(settings, "features", {}))
        )

    def get_settings(self, force: bool = False) -> Any:
        return self._settings.get(force=force)

    def build_application(self, *, settings: Optional[Any] = None) -> Application:
        active_settings = settings or self.get_settings()
        return self._build_application_fn(active_settings)

    def run_polling(self) -> None:
        settings = self.get_settings()
        app = self.build_application(settings=settings)
        self._logger.info(
            self._startup_log_message,
            self._startup_log_value_fn(settings),
        )
        app.run_polling()
