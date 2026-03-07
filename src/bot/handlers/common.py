import logging
from typing import Any, Callable, Optional

from telegram import Update

from src import config

logger = logging.getLogger(__name__)


def log_context(update: Optional[Update]) -> dict:
    if update is None:
        return {}
    context = {}
    if update.effective_user is not None:
        context["user_id"] = update.effective_user.id
    if update.effective_chat is not None:
        context["chat_id"] = update.effective_chat.id
    if update.update_id is not None:
        context["update_id"] = update.update_id
    return context


def storage_id(update: Update) -> Optional[str]:
    if update.effective_user is None or update.effective_chat is None:
        return None
    if update.effective_chat.type == "private":
        return str(update.effective_user.id)
    return str(update.effective_chat.id)


def is_allowed(
    update: Update,
    *,
    settings_getter: Callable[[], config.Settings] = config.get_settings,
    logger_override: Optional[logging.Logger] = None,
    log_context_fn: Callable[[Optional[Update]], dict] = log_context,
) -> bool:
    logger_instance = logger_override or logger
    if update.effective_chat is None or update.effective_user is None:
        return False

    settings = settings_getter()
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    if settings.allowed_chat_ids:
        if (
            chat_id not in settings.allowed_chat_ids
            and user_id not in settings.allowed_chat_ids
        ):
            logger_instance.warning(
                "Unauthorized access attempt",
                extra={"user_id": user_id, "chat_id": chat_id},
            )
            return False
        return True

    logger_instance.info(
        "No allowed_chat_ids configured, disallowing all users",
        extra=log_context_fn(update),
    )
    return False
