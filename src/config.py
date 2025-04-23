# config.py
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Feature flags
FEATURES = {
    'voice_transcription': os.getenv('ENABLE_VOICE_TRANSCRIPTION', 'true').lower() == 'true',
    'gemini_ai': os.getenv('ENABLE_GEMINI_AI', 'false').lower() == 'true',
    'commands': {
        'hi': True,
        'ai': os.getenv('ENABLE_COMMAND_AI', 'false').lower() == 'true',
    },
    'message_handling': os.getenv('ENABLE_MESSAGE_HANDLING', 'true').lower() == 'true',
    'schedule_events': os.getenv('ENABLE_SCHEDULE_EVENTS', 'false').lower() == 'true',
}

# AI Provider settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AI_PROVIDER = os.getenv("AI_PROVIDER", "whisper").lower()

# Google Calendar settings
CALENDAR_AI_PROVIDER = os.getenv("CALENDAR_AI_PROVIDER", "gemini-1.5-flash-latest").lower()
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

# Allowed users/groups
ALLOWED_CHAT_IDS = os.getenv("ALLOWED_CHAT_IDS", "").split(",") if os.getenv("ALLOWED_CHAT_IDS") else []

PROMPT_PREFIX = os.getenv("PROMPT_PREFIX", "")