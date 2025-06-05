# config.py
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Feature flags
FEATURES = {
    'commands': {
        'hi': True,
    },
    'message_handling': os.getenv('ENABLE_MESSAGE_HANDLING', 'false').lower() == 'true',
    'schedule_events': os.getenv('ENABLE_SCHEDULE_EVENTS', 'false').lower() == 'true',
}

# AI Provider settings
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").lower()

# Google Calendar settings
if FEATURES['schedule_events']:
    # TODO
    print("Google Calendar integration is enabled. Ensure credentials are set up correctly.")


GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# Allowed users/groups
ALLOWED_CHAT_IDS = os.environ["ALLOWED_CHAT_IDS"].split(",")

PROMPT_PREFIX = os.getenv("PROMPT_PREFIX", "")

BOT_ALIASES = [alias.lower() for alias in os.getenv("BOT_ALIASES", "").split(",") if alias]
LANGUAGE = os.getenv("LANGUAGE", "ru").lower()

TOKEN_LIMIT = int(os.getenv("TOKEN_LIMIT", 500_000))
CHAT_MESSAGES_STORE_PATH = os.getenv("CHAT_MESSAGES_STORE_PATH", "messages.jsonl")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == 'true'
