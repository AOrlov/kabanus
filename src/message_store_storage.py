import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from src import config

logger = logging.getLogger(__name__)


_message_store_by_chat: Dict[str, List[Dict[str, Any]]] = {}


def safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def make_message(
    sender: str,
    text: str,
    is_bot: bool,
    telegram_message_id: Optional[int] = None,
    reply_to_telegram_message_id: Optional[int] = None,
) -> Dict[str, Any]:
    message: Dict[str, Any] = {
        "id": f"{int(time.time() * 1000)}-{os.getpid()}",
        "ts": int(time.time()),
        "kind": "bot" if is_bot else "user",
        "sender": sender.strip() if not is_bot else "Bot",
        "text": text.strip(),
    }
    safe_message_id = safe_int(telegram_message_id)
    if safe_message_id is not None:
        message["telegram_message_id"] = safe_message_id
    safe_reply_to_message_id = safe_int(reply_to_telegram_message_id)
    if safe_reply_to_message_id is not None:
        message["reply_to_telegram_message_id"] = safe_reply_to_message_id
    return message


def get_store_path(chat_id: str) -> str:
    settings = config.get_settings()
    if os.path.isabs(settings.chat_messages_store_path):
        base_path = settings.chat_messages_store_path
    else:
        base_path = os.path.join(
            os.path.dirname(__file__), settings.chat_messages_store_path
        )
    if not chat_id:
        raise ValueError("chat_id is required for message storage")
    root, ext = os.path.splitext(base_path)
    if ext:
        base_dir = os.path.dirname(base_path) or "."
        stem = os.path.basename(root) or "messages"
    else:
        base_dir = base_path
        stem = "messages"
    safe_chat_id = str(chat_id).strip()
    path = os.path.join(base_dir, f"{stem}_{safe_chat_id}.jsonl")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
    return path


def load_messages(chat_id: str) -> List[Dict[str, Any]]:
    path = get_store_path(chat_id)
    logger.debug("Loading messages from file", extra={"chat_id": chat_id, "path": path})

    messages: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            messages.append(json.loads(line))
    logger.debug("Loaded messages", extra={"chat_id": chat_id, "count": len(messages)})
    return messages


def append_message(msg: Dict[str, Any], chat_id: str) -> None:
    path = get_store_path(chat_id)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(msg, ensure_ascii=False) + "\n")


def ensure_loaded(chat_id: str) -> List[Dict[str, Any]]:
    if not chat_id:
        raise ValueError("chat_id is required for message storage")
    if chat_id not in _message_store_by_chat:
        _message_store_by_chat[chat_id] = load_messages(chat_id)
    return _message_store_by_chat[chat_id]


def get_last_message(chat_id: str) -> Optional[Dict[str, Any]]:
    messages = ensure_loaded(chat_id)
    if messages:
        return messages[-1]
    return None


def add_message(
    sender: str,
    text: str,
    chat_id: str,
    is_bot: bool = False,
    telegram_message_id: Optional[int] = None,
    reply_to_telegram_message_id: Optional[int] = None,
) -> None:
    msg = make_message(
        sender,
        text,
        is_bot,
        telegram_message_id=telegram_message_id,
        reply_to_telegram_message_id=reply_to_telegram_message_id,
    )
    messages = ensure_loaded(chat_id)
    messages.append(msg)
    append_message(msg, chat_id)


def get_all_messages(chat_id: str) -> List[Dict[str, Any]]:
    messages = ensure_loaded(chat_id)
    return list(messages)


def get_message_by_telegram_message_id(
    chat_id: str, telegram_message_id: int
) -> Optional[Dict[str, Any]]:
    target_id = safe_int(telegram_message_id)
    if target_id is None:
        return None
    messages = ensure_loaded(chat_id)
    for msg in reversed(messages):
        current_id = safe_int(msg.get("telegram_message_id"))
        if current_id == target_id:
            return msg
    return None
