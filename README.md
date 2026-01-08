# Telegram Speech-to-Text & Event Bot

Telegram bot for group interaction, voice message transcription, and (optionally) Google Calendar event creation from event poster photos. Uses Google Gemini for speech-to-text and text generation. Designed for easy Docker deployment and notifies an admin on critical errors.

## Features
- Listens for voice and text messages in Telegram groups
- Transcribes speech to text using Gemini
- Replies with the transcription or an error message
- Supports Gemini for text generation and context-aware replies
- Can auto-react to messages using Gemini (optional)
- Optional multi-model Gemini routing with per-model RPM/RPD limits
- Can create Google Calendar events from event poster photos (optional)
- Notifies admin on critical errors
- Logs to stdout and temporary files
- Access control via allowed chat/user IDs
- Configurable via environment variables

## Requirements
- Docker (recommended) or Python 3.9+
- Telegram bot token
- Allowed chat/user IDs (for access control)
- Google Gemini API key (for Gemini features)
- (Optional) Admin Telegram chat ID (for error notifications)
- (Optional) Google Calendar credentials and calendar ID (for event creation)

## Setup

### 1. Create a Telegram Bot
- Talk to [@BotFather](https://t.me/botfather) on Telegram
- Create a new bot and get the token
- (Optional) Disable privacy mode to allow group message access

### 2. Clone the Repository
```
git clone <your-repo-url>
cd kabanus
```

### 3. Configure Environment Variables
Create a `.env` file or set environment variables:
```
# Core
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
ALLOWED_CHAT_IDS=comma,separated,chat,ids
ADMIN_CHAT_ID=your-admin-chat-id           # Optional, for error notifications

# Gemini and AI behavior
GEMINI_API_KEY=your-gemini-api-key         # Required for Gemini support
GOOGLE_API_KEY=your-google-api-key         # Optional, defaults to GEMINI_API_KEY if unset
GEMINI_MODEL=gemini-2.0-flash              # Optional, default is gemini-2.0-flash
GEMINI_MODELS=[{"name":"gemini-2.5-flash","rpm":60,"rpd":1000}] # Optional JSON list ordered by preference, overrides GEMINI_MODEL
THINKING_BUDGET=0                          # Optional, Gemini thinking budget
USE_GOOGLE_SEARCH=false                    # Optional, enable Gemini grounding with Google Search
SYSTEM_INSTRUCTIONS_PATH=system_instructions.txt # Optional, path (relative to src/) for system prompt
LANGUAGE=ru                                # Optional, bot response language (default: ru)
TOKEN_LIMIT=500000                         # Optional, context token limit

# Features
ENABLE_MESSAGE_HANDLING=true               # Enable text/voice message handling (default: false)
ENABLE_SCHEDULE_EVENTS=true                # Enable event creation from photos (default: false)
REACTION_ENABLED=false                     # Optional, enable auto-reactions
REACTION_COOLDOWN_SECS=600                 # Optional, seconds between reactions
REACTION_DAILY_BUDGET=50                   # Optional, max reactions per day
REACTION_MESSAGES_THRESHOLD=10             # Optional, messages between reactions
REACTION_GEMINI_MODEL=gemini-2.0-flash     # Optional, defaults to GEMINI_MODEL

# Google Calendar
GOOGLE_CALENDAR_ID=your-calendar-id        # Required for event creation
GOOGLE_CREDENTIALS_PATH=path/to/creds.json # or use GOOGLE_CREDENTIALS_JSON
GOOGLE_CREDENTIALS_JSON='{"type": "..."}'  # Optional, inlined credentials JSON

# Bot behavior
BOT_ALIASES=bot,бот,ботик                  # Optional, comma-separated aliases
CHAT_MESSAGES_STORE_PATH=messages.jsonl    # Optional, history message store file

# Runtime and debugging
DEBUG_MODE=true                            # Optional, enable debug logging
DOTENV_PATH=path/to/.env                   # Optional, override .env location
SETTINGS_CACHE_TTL=1.0                     # Optional, settings cache TTL in seconds
SETTINGS_REFRESH_INTERVAL=1.0              # Optional, refresh interval (used if job enabled)
```

### 4. Build and Run with Docker
```
docker build -t kabanus .
docker run --env-file .env kabanus
```

### 5. Run Locally (for development)
Install dependencies:
```
pip install -r requirements.txt
```
Run the bot:
```
python -m src.main
```

## Usage
- If `ENABLE_SCHEDULE_EVENTS=true`, send a photo of an event poster to create a Google Calendar event (requires calendar credentials and ID).
- If `ENABLE_MESSAGE_HANDLING=true`, send a voice, text, or image to interact with the bot. Mention the bot or reply to its message for a response.
- If `GEMINI_MODELS` is set, the bot tries models in order of desirability and skips any that hit RPM/RPD limits.
- If `REACTION_ENABLED=true`, the bot may react to messages using Gemini within the configured budget/cooldown.

## Utilities
- `scripts/dump_chat.py`: Dump Telegram chat history to JSONL (see script for usage).

## VS Code Debugging
A `.vscode/launch.json` is provided. Use the "Run Telegram Bot (src.main)" or "Debug Unit Tests" configurations from the Run & Debug panel.

## Notes
- All imports in `src/` use relative imports (e.g., `from .config import ...`).
- Do not run files in `src/` directly; always use the `-m` module syntax from the project root.
- Gemini support requires a valid API key from Google AI Studio.
- Google Calendar event creation requires a valid calendar ID and service account credentials.
- `ALLOWED_CHAT_IDS` is required; if empty, the bot denies all users.

## License
MIT
