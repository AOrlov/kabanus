# message_store.py
"""
In-memory message storage for context-aware Telegram bot extension.
"""
import json
import logging
import os
from typing import Dict, List, Optional

from src import config

logger = logging.getLogger(__name__)


# Message object schema
def make_message(sender: str, text: str, is_bot: bool) -> Dict:
    return {
        'sender': sender.strip() if not is_bot else 'Bot',  # sender's first name or `Bot` for bot messages
        'text': text.strip(),  # message text
    }


# File to persist messages (JSON Lines format)
def _get_store_path(chat_id: str) -> str:
    settings = config.get_settings()
    if os.path.isabs(settings.chat_messages_store_path):
        base_path = settings.chat_messages_store_path
    else:
        base_path = os.path.join(os.path.dirname(__file__), settings.chat_messages_store_path)
    if not chat_id:
        raise ValueError("chat_id is required for message storage")
    base_dir = base_path
    stem = "messages"
    ext = ".jsonl"
    safe_chat_id = str(chat_id).strip()
    path = os.path.join(base_dir, f"{stem}_{safe_chat_id}{ext}")
    # Ensure the file exists
    if not os.path.exists(path):
        # Create the file and its parent directory if needed
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'a', encoding='utf-8'):
            pass
    return path


def _load_messages(chat_id: str):
    path = _get_store_path(chat_id)
    logger.debug("Loading messages from file", extra={"chat_id": chat_id, "path": path})

    messages = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            messages.append(json.loads(line))
    logger.debug("Loaded messages", extra={"chat_id": chat_id, "count": len(messages)})
    return messages


def _append_message(msg: Dict, chat_id: str):
    path = _get_store_path(chat_id)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(msg, ensure_ascii=False) + '\n')


# In-memory list for message storage, keyed by chat id
_message_store_by_chat: Dict[str, List[Dict]] = {}


def _ensure_loaded(chat_id: str) -> List[Dict]:
    if not chat_id:
        raise ValueError("chat_id is required for message storage")
    if chat_id not in _message_store_by_chat:
        _message_store_by_chat[chat_id] = _load_messages(chat_id)
    return _message_store_by_chat[chat_id]


def get_last_message(chat_id: str) -> Optional[Dict]:
    """Retrieve the last message from the in-memory store."""
    messages = _ensure_loaded(chat_id)
    if messages:
        return messages[-1]
    return None


def add_message(sender: str, text: str, chat_id: str, is_bot: bool = False):
    """Add a message to the in-memory store and append to file."""
    msg = make_message(sender, text, is_bot)
    messages = _ensure_loaded(chat_id)
    messages.append(msg)
    _append_message(msg, chat_id)


def get_all_messages(chat_id: str) -> List[Dict]:
    """Retrieve all stored messages."""
    messages = _ensure_loaded(chat_id)
    return list(messages)


def estimate_token_count(text: str) -> int:
    """Estimate token count for a message (simple word count as proxy)."""
    return len(text)//4


# TODO: optimize to not assemble every time
def assemble_context(messages: list, token_limit: Optional[int] = None) -> str:
    """Assemble most recent messages up to the token limit"""
    if token_limit is None:
        token_limit = config.get_settings().token_limit
    context_lines = []
    total_tokens = 0
    logger.debug("Assembling context with token limit", extra={"token_limit": token_limit})
    # Traverse messages in reverse (most recent first)
    for msg in reversed(messages):
        sender = msg.get('sender')
        line = f"{sender}:{msg.get('text', '')}"
        tokens = estimate_token_count(line)
        if total_tokens + tokens > token_limit:
            break
        context_lines.append(line)
        total_tokens += tokens
    # Reverse again to restore chronological order
    context_lines.reverse()
    logger.debug(
        "Assembled context",
        extra={"message_count": len(context_lines), "token_count": total_tokens},
    )
    return '\n'.join(context_lines)
