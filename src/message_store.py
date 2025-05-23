# message_store.py
"""
In-memory message storage for context-aware Telegram bot extension.
"""
import json
import logging
import os
from typing import Dict, List, Optional

from src.config import CHAT_MESSAGES_STORE_PATH, TOKEN_LIMIT

logger = logging.getLogger(__name__)


# Message object schema
def make_message(sender: str, text: str, is_bot: bool) -> Dict:
    return {
        'sender': sender.strip() if not is_bot else 'Bot',  # sender's first name or `Bot` for bot messages
        'text': text.strip(),  # message text
        'is_bot': is_bot  # True if the message is from the bot
    }


# File to persist messages (JSON Lines format)
def _get_store_path():
    path = os.path.join(os.path.dirname(__file__), CHAT_MESSAGES_STORE_PATH)
    # Ensure the file exists
    if not os.path.exists(path):
        # Create the file and its parent directory if needed
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8'):
            pass
    return path


def _load_messages():
    path = _get_store_path()
    logger.debug(f"Loading messages from file {path}")

    messages = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            messages.append(json.loads(line))
    logger.debug(f"Loaded {len(messages)} messages.")
    return messages


def _append_message(msg: Dict):
    path = _get_store_path()
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(msg, ensure_ascii=False) + '\n')


# In-memory list for message storage
_message_store: List[Dict] = _load_messages()


def get_last_message() -> Optional[Dict]:
    """Retrieve the last message from the in-memory store."""
    if _message_store:
        return _message_store[-1]
    return None


def add_message(sender: str, text: str, is_bot: bool = False):
    """Add a message to the in-memory store and append to file."""
    msg = make_message(sender, text, is_bot)
    _message_store.append(msg)
    _append_message(msg)


def get_all_messages() -> List[Dict]:
    """Retrieve all stored messages."""
    return list(_message_store)


def estimate_token_count(text: str) -> int:
    """Estimate token count for a message (simple word count as proxy)."""
    return len(text.split())


# TODO: optimize to not assemble every time
def assemble_context(messages: list, token_limit: int = TOKEN_LIMIT) -> str:
    """Assemble most recent messages up to the token limit"""
    context_lines = []
    total_tokens = 0
    # Traverse messages in reverse (most recent first)
    for msg in reversed(messages):
        sender = 'Bot' if msg.get('is_bot') else msg.get('sender', 'Unknown')
        line = f"{sender}: {msg.get('text', '')}"
        tokens = estimate_token_count(line)
        if total_tokens + tokens > token_limit:
            break
        context_lines.append(line)
        total_tokens += tokens
    # Reverse again to restore chronological order
    context_lines.reverse()
    return '\n'.join(context_lines)
