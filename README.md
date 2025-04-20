# Telegram Speech-to-Text Bot

This bot listens for Russian voice messages in a Telegram group and replies with a text transcription using OpenAI Whisper or Google Gemini Flash 2.0 (cheapest Gemini model). It is designed for easy deployment in a Docker container and notifies an admin in case of critical errors.

## Features
- Listens for voice messages in a Telegram group
- Transcribes Russian speech to text using Whisper (small model) or Gemini Flash 2.0
- Modular: easily switch between Whisper and Gemini for speech-to-text
- Replies with the transcription or an error message
- Supports Gemini for text generation via `/gemini` command
- Notifies admin on critical errors
- Logs to stdout and temporary files

## Requirements
- Docker (recommended)
- Telegram bot token
- Admin Telegram chat ID (for error notifications)
- (Optional) Google Gemini API key for Gemini support

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
GEMINI_API_KEY=your-gemini-api-key  # Optional, for Gemini support
PROVIDER_AI=whisper                 # or "gemini" to use Gemini for speech-to-text
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
git clone https://github.com/openai/whisper.git
pip install ./whisper
brew install ffmpeg  # or use your OS package manager
```
Run the bot:
```
python main.py
```

## Usage

- By default, the bot uses Whisper for speech-to-text.  
- To use Gemini for speech-to-text, set `PROVIDER_AI=gemini` in your environment.

## Testing
Run the test suite:
```
python -m unittest test_main.py
```

## Deployment
- Deploy the Docker container on your server or Raspberry Pi 3 (4GB recommended)
- Monitor logs via stdout or Docker logs

## Notes
- The bot does not store any audio or transcription data permanently
- Only Russian voice messages are supported
- For best results, ensure ffmpeg and Whisper dependencies are installed
- Gemini support requires a valid API key from Google AI Studio

## License
MIT
