import logging
from typing import Any, Callable, Optional

from telegram import Update

from src import config


def log_context(update: Optional[Update]) -> dict[str, Any]:
    if update is None:
        return {}
    context: dict[str, Any] = {}
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
    settings_getter: Callable[..., config.Settings] = config.get_settings,
    logger: Optional[logging.Logger] = None,
) -> bool:
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
            if logger is not None:
                logger.warning(
                    "Unauthorized access attempt",
                    extra={"user_id": user_id, "chat_id": chat_id},
                )
            return False
        return True

    if logger is not None:
        logger.info(
            "No allowed_chat_ids configured, disallowing all users",
            extra=log_context(update),
        )
    return False
