# Telegram Speech-to-Text & Event Bot

A Telegram bot for fun to interact with group members. Also, the bot listens for voice messages in a Telegram group and replies with a text transcription using Google Gemini model. It can also create Google Calendar events from photo messages (if enabled). Designed for easy deployment in a Docker container and notifies an admin in case of critical errors.

## Features
- Listens for voice messages in a Telegram group
- Transcribes speech to text using Gemini
- Replies with the transcription or an error message
- Supports Gemini for text generation
- Can create Google Calendar events from event photo images (optional)
- Notifies admin on critical errors
- Logs to stdout and temporary files

## Requirements
- Docker (recommended)
- Telegram bot token
- Admin Telegram chat ID (for error notifications)
- Allowed chat/user IDs (for access control)
- (Optional) Google Gemini API key for Gemini support
- (Optional) Google Calendar credentials and calendar ID for event creation

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
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
ADMIN_CHAT_ID=your-admin-chat-id
ALLOWED_CHAT_IDS=comma,separated,chat,ids
GEMINI_API_KEY=your-gemini-api-key         # Optional, for Gemini support
GEMINI_MODEL=gemini-2.5-flash              # Optional, default is gemini-2.5-flash
ENABLE_MESSAGE_HANDLING=true                # Enable text/voice message handling (default: false)
ENABLE_SCHEDULE_EVENTS=true                 # Enable event creation from photos (default: false)
GOOGLE_CALENDAR_ID=your-calendar-id        # Required for event creation
GOOGLE_CREDENTIALS_PATH=path/to/creds.json # or use GOOGLE_CREDENTIALS_JSON
PROMPT_PREFIX=Your prompt prefix           # Optional, a prompt prefix for bot's behavior customization
BOT_ALIASES=bot,бот,ботик                  # Optional, comma-separated aliases
LANGUAGE=ru                                # Optional, the language for the bot to respond in (default: ru)
TOKEN_LIMIT=10_000                         # Optional, context token limit
CHAT_MESSAGES_STORE_PATH=messages.jsonl    # Optional, history message store file
DEBUG_MODE=true                            # Optional, enable debug logging
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

## Utilities
- `scripts/dump_chat.py`: Dump Telegram chat history to JSONL (see script for usage).

## VS Code Debugging

A `.vscode/launch.json` is provided. Use the "Run Telegram Bot (src.main)" or "Debug Unit Tests" configurations from the Run & Debug panel.

## Notes
- All imports in `src/` use relative imports (e.g., `from .config import ...`).
- Do not run files in `src/` directly; always use the `-m` module syntax from the project root.
- Gemini support requires a valid API key from Google AI Studio.
- Google Calendar event creation requires a valid calendar ID and service account credentials.

## License
MIT
