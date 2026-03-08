import logging
from typing import Callable, Optional

from telegram import Update

from src import config
from src.telegram_framework import policy

logger = logging.getLogger(__name__)


def log_context(update: Optional[Update]) -> dict:
    return policy.log_context(update)


def storage_id(update: Update) -> Optional[str]:
    return policy.storage_id(update)


def is_allowed(
    update: Update,
    *,
    settings_getter: Callable[[], config.Settings] = config.get_settings,
    logger_override: Optional[logging.Logger] = None,
    log_context_fn: Callable[[Optional[Update]], dict] = log_context,
) -> bool:
    return policy.is_allowed(
        update,
        settings_getter=settings_getter,
        logger_override=logger_override or logger,
        log_context_fn=log_context_fn,
    )
