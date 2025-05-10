# message_store.py
"""
In-memory message storage for context-aware Telegram bot extension.
"""
from typing import Dict, List

from pyparsing import Optional


# Message object schema
def make_message(sender: str, text: str, is_bot: bool) -> Dict:
    return {
        'sender': sender,
        'text': text,
        'is_bot': is_bot
    }

# In-memory list for message storage
_message_store: List[Dict] = []

def get_last_message() -> Dict:
    """Retrieve the last message from the in-memory store."""
    if _message_store:
        return _message_store[-1]
    return None

def add_message(sender: str, text: str, is_bot: bool = False):
    """Add a message to the in-memory store."""
    msg = make_message(sender, text, is_bot)
    _message_store.append(msg)


def get_all_messages() -> List[Dict]:
    """Retrieve all stored messages."""
    return list(_message_store)


def clear_messages():
    """Clear all stored messages (for testing or reset)."""
    _message_store.clear()


def estimate_token_count(text: str) -> int:
    """Estimate token count for a message (simple word count as proxy)."""
    return len(text.split())

TOKEN_LIMIT = 500_000

def assemble_context(messages: list, token_limit: int = TOKEN_LIMIT) -> str:
    """Assemble most recent messages up to the token limit, formatted as 'Sender: message'."""
    context_lines = []
    total_tokens = 0
    # Traverse messages in reverse (most recent first)
    for msg in reversed(messages):
        sender = 'Bot' if msg.get('is_bot') else msg.get('sender', 'Unknown')
        line = f"{sender}: {msg.get('text', '').strip()}"
        tokens = estimate_token_count(line)
        if total_tokens + tokens > token_limit:
            break
        context_lines.append(line)
        total_tokens += tokens
    # Reverse again to restore chronological order
    context_lines.reverse()
    return '\n'.join(context_lines)
