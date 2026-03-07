# Telegram Speech-to-Text & Event Bot

Telegram bot for group interaction, voice message transcription, and (optionally) Google Calendar event creation from event poster photos. Supports OpenAI and Gemini model providers with runtime switching. Designed for easy Docker deployment and notifies an admin on critical errors.

## Features
- Listens for voice and text messages in Telegram groups
- Transcribes speech to text using Gemini
- Replies with the transcription or an error message
- Supports OpenAI/Gemini for text generation and context-aware replies
- Supports context memory optimization with recent-window + optional long-term summaries
- Can auto-react to messages using Gemini (optional)
- Optional multi-model Gemini routing with per-model RPM/RPD limits
- Provider fallback: when OpenAI is selected, Gemini is used as fallback and for transcription
- Can create Google Calendar events from event poster photos (optional)
- Notifies admin on critical errors
- Logs to stdout and temporary files
- Access control via allowed chat/user IDs
- Configurable via environment variables

## Requirements
- Docker (recommended) or Python 3.9+
- Telegram bot token
- Allowed chat/user IDs (for access control)
- OpenAI API key (for OpenAI provider)
- Google Gemini API key (optional; required only for Gemini provider/fallback and transcription)
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

### 3. Create and Activate Virtual Environment (Local Development)
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 4. Configure Environment Variables
Create a `.env` file or set environment variables:
```
# Core
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
ALLOWED_CHAT_IDS=comma,separated,chat,ids
ADMIN_CHAT_ID=your-admin-chat-id           # Optional, for error notifications

# Provider selection
MODEL_PROVIDER=openai                       # Optional, openai|gemini (default: openai)
OPENAI_API_KEY=your-openai-api-key         # Required when MODEL_PROVIDER=openai
OPENAI_AUTH_JSON_PATH=path/to/auth.json    # Optional alternative to OPENAI_API_KEY (refresh-token flow)
OPENAI_REFRESH_URL=https://auth.openai.com/oauth/token # Optional token refresh endpoint for OPENAI_AUTH_JSON_PATH
OPENAI_REFRESH_CLIENT_ID=                  # Optional refresh client_id override
OPENAI_REFRESH_GRANT_TYPE=refresh_token    # Optional refresh grant type
OPENAI_AUTH_LEEWAY_SECS=60                 # Optional pre-expiry refresh window
OPENAI_AUTH_TIMEOUT_SECS=20                # Optional refresh HTTP timeout
OPENAI_CODEX_BASE_URL=https://chatgpt.com/backend-api # Optional Codex backend base URL for auth.json tokens
OPENAI_CODEX_DEFAULT_MODEL=gpt-5.3-codex   # Optional default model used for auth.json Codex sessions
OPENAI_MODEL=gpt-5.3-codex                 # Optional. For auth.json flow, defaults to OPENAI_CODEX_DEFAULT_MODEL when unset
OPENAI_LOW_COST_MODEL=gpt-5.3-codex        # Optional. Defaults to OPENAI_MODEL (or Codex default in auth.json flow)
OPENAI_REACTION_MODEL=gpt-5.3-codex        # Optional. Defaults to OPENAI_LOW_COST_MODEL

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
ENABLE_SCHEDULE_EVENTS=false               # Enable event creation from photos (default: false)
                                           # NOTE: ENABLE_MESSAGE_HANDLING and ENABLE_SCHEDULE_EVENTS are mutually exclusive
REACTION_ENABLED=false                     # Optional, enable auto-reactions
REACTION_COOLDOWN_SECS=600                 # Optional, seconds between reactions
REACTION_DAILY_BUDGET=50                   # Optional, max reactions per day
REACTION_MESSAGES_THRESHOLD=10             # Optional, messages between reactions
REACTION_GEMINI_MODEL=gemini-2.0-flash     # Optional, defaults to GEMINI_MODEL
REACTION_CONTEXT_TURNS=8                   # Optional, recent dialogue lines considered for reaction choice
REACTION_CONTEXT_TOKEN_LIMIT=1200          # Optional, token budget for reaction context prompt

# Google Calendar
GOOGLE_CALENDAR_ID=your-calendar-id        # Required for event creation
GOOGLE_CREDENTIALS_PATH=path/to/creds.json # or use GOOGLE_CREDENTIALS_JSON
GOOGLE_CREDENTIALS_JSON='{"type": "..."}'  # Optional, inlined credentials JSON

# Bot behavior
BOT_ALIASES=bot,бот,ботик                  # Optional, comma-separated aliases
TELEGRAM_FORMAT_AI_REPLIES=true            # Optional, send AI replies as Telegram HTML (default: true)
TELEGRAM_USE_MESSAGE_DRAFTS=false          # Optional, stream OpenAI replies via Bot API sendMessageDraft in private chats
TELEGRAM_DRAFT_UPDATE_INTERVAL_SECS=0.15   # Optional, minimum seconds between draft updates
CHAT_MESSAGES_STORE_PATH=messages.jsonl    # Optional, history message store file

# Memory/context optimization
MEMORY_ENABLED=true                        # Optional, enable structured context builder
MEMORY_RECENT_TURNS=20                     # Optional, keep last N messages in recent section
MEMORY_RECENT_BUDGET_RATIO=0.85            # Optional, token budget share for recent dialogue
MEMORY_SUMMARY_ENABLED=false               # Optional, enable long-term summary section
MEMORY_SUMMARY_BUDGET_RATIO=0.15           # Optional, token budget share for summaries
MEMORY_SUMMARY_CHUNK_SIZE=16               # Optional, messages per summary chunk
MEMORY_SUMMARY_MAX_ITEMS=4                 # Optional, max summary items injected per request
MEMORY_SUMMARY_MAX_CHUNKS_PER_RUN=1        # Optional, new chunks summarized per runtime call

# Runtime and debugging
DEBUG_MODE=true                            # Optional, enable debug logging
THIRD_PARTY_LOG_LEVEL=WARNING              # Optional, external libs log level (httpx/httpcore/telegram/google_genai)
DOTENV_PATH=path/to/.env                   # Optional, override .env location
SETTINGS_CACHE_TTL=1.0                     # Optional, settings cache TTL in seconds
SETTINGS_REFRESH_INTERVAL=1.0              # Optional, refresh interval (used if job enabled)
```

### 5. Build and Run with Docker
```
docker build -t kabanus .
docker run --env-file .env kabanus
```

### 6. OpenAI Onboarding Wizard (Optional)

Generate `scripts/openai.auth.json` and validate your OpenAI key with a live smoke test:

```bash
PYTHONPATH=. python3 -m scripts.onboard_openai
```

The wizard prints `export ...` lines for runtime. Apply them before starting the bot.
Use `--open-browser` to open the OpenAI API keys page automatically.

For OpenAI Codex OAuth flow (local callback on `http://localhost:1455/auth/callback`):

```bash
PYTHONPATH=. python3 -m scripts.openai_codex_oauth
```

For remote/VPS sessions (manual redirect paste):

```bash
PYTHONPATH=. python3 -m scripts.openai_codex_oauth --remote
```

Supported OpenAI models in this setup:

1. `gpt-5.3-codex` (current) - Latest frontier agentic coding model.
2. `gpt-5.2-codex` - Frontier agentic coding model.
3. `gpt-5.1-codex-max` - Codex-optimized flagship for deep and fast reasoning.
4. `gpt-5.2` - Frontier model with improvements across knowledge, reasoning, and coding.
5. `gpt-5.1-codex-mini` - Optimized for Codex, cheaper and faster.

### 6.1 OpenAI `auth.json` Refresh Behavior

When `OPENAI_AUTH_JSON_PATH` is set, runtime auth uses access+refresh tokens from `auth.json`
instead of `OPENAI_API_KEY`.

- Token is read for each request and refreshed lazily (on demand), not in a background job.
- Refresh triggers when token is missing, expiring soon (`OPENAI_AUTH_LEEWAY_SECS`), or when
  an auth error requires forced refresh.
- Refresh request is `application/x-www-form-urlencoded` to `OPENAI_REFRESH_URL`
  (default `https://auth.openai.com/oauth/token`) with `grant_type`, `refresh_token`,
  and optional `client_id`.
- Refreshed tokens are written back into the same `auth.json`.

Supported shapes include top-level keys and `tokens.*` keys. Minimal recommended shape:

```json
{
  "tokens": {
    "access_token": "eyJ...",
    "refresh_token": "def...",
    "expires_at": 1762000000,
    "token_url": "https://auth.openai.com/oauth/token",
    "client_id": "app_...",
    "grant_type": "refresh_token"
  }
}
```

### 7. Run Locally (for development)
With the virtual environment activated:
```bash
source .venv/bin/activate
python -m src.main
```

## Usage
- If `ENABLE_SCHEDULE_EVENTS=true`, send a photo of an event poster to create a Google Calendar event (requires calendar credentials and ID).
- If `ENABLE_MESSAGE_HANDLING=true`, send a voice, text, or image to interact with the bot. Mention the bot or reply to its message for a response.
- Use `/summary` (alias: `/view_summary`) to inspect per-chat summary chunks created by memory summary.
  Examples:
  `/summary` (first 3 chunks), `/summary 5`, `/summary tail 5`, `/summary index 42`, `/summary budget api`, `/summary --head 10 --grep budget`.
  `/summary help` shows command usage.
  Summary command requests and responses are not saved into chat history.
- If `GEMINI_MODELS` is set, the bot tries models in order of desirability and skips any that hit RPM/RPD limits.
- If `REACTION_ENABLED=true`, the bot may react to messages within configured budget/cooldown and considers recent dialogue context when choosing emoji.

## Utilities
- `scripts/dump_chat.py`: Dump Telegram chat history to JSONL (see script for usage).
- `scripts/backfill_summaries.py`: Backfill `*.summary.json` from existing JSONL history.
- `scripts/view_summary.py`: Inspect summary files quickly from CLI.
- `scripts/onboard_openai.py`: Interactive OpenAI onboarding and auth JSON generation.
- `scripts/openai_codex_oauth.py`: OpenAI Codex OAuth login and auth.json writer.
- `scripts/README.md`: Detailed script usage and examples.

## Architecture
The codebase has been modularized into focused components while preserving runtime behavior.

- Runtime entrypoint is still `python -m src.main`.
- Telegram flow logic lives under `src/bot/handlers/*` and `src/bot/services/*`.
- Memory internals live in `src/memory/*` and are exposed through compatibility facade `src/message_store.py`.
- Settings parsing internals live in `src/settings_loader.py` and `src/settings_models.py`, with compatibility facade `src/config.py`.
- Provider routing and typed contracts are in `src/provider_factory.py` and `src/providers/contracts.py`.

Detailed module boundaries, extension points, compatibility guarantees, and migration notes:
- `docs/architecture/refactor-overview.md`

## Backward Compatibility Guarantees
- Environment variable names/defaults and validation semantics are preserved.
- Existing `src.config` API remains available (`Settings`, `ModelSpec`, `get_settings(force=...)`, legacy module attributes).
- Existing `src.message_store` call surface remains available for history/context operations.
- Provider routing behavior remains equivalent to previous `RoutedModelProvider` semantics.

## Migration Notes (Internal Integrations)
- If you imported private internals from monolithic modules, migrate to new focused modules:
  - Bot flow internals: `src/bot/handlers/*`, `src/bot/services/*`
  - Memory internals: `src/memory/history_store.py`, `src/memory/summary_store.py`, `src/memory/context_builder.py`
  - Settings internals: `src/settings_loader.py`, `src/settings_models.py`
- Prefer typed provider request wrappers from `src/providers/contracts.py` for new provider integrations.
- Keep compatibility facades (`src/main.py`, `src/config.py`, `src/message_store.py`) for legacy callers unless a deliberate breaking change is documented.

## Memory and Backfill

The bot stores raw messages as JSONL and can optionally use long-term compressed summaries:

- Raw history file pattern: `messages_<chat_id>.jsonl`
- Summary file pattern: `messages_<chat_id>.summary.json`

When `MEMORY_SUMMARY_ENABLED=true`, context assembly can include both:

- recent dialogue window (verbatim)
- relevant long-term summary chunks

### Backfill existing history

Use backfill when you already have large history and want summary files immediately.

Example with local Ollama:

```bash
. .venv/bin/activate
set -a && source dev.stack.env && set +a
MEMORY_SUMMARY_ENABLED=true PYTHONPATH=. python3 -m scripts.backfill_summaries \
  --chat-id=-{chat_id} \
  --source-jsonl src/data/messages_-{chat_id}.jsonl \
  --provider ollama \
  --ollama-url http://127.0.0.1:11434/api/generate \
  --ollama-model gemma3:4b
```

For a quick experiment on first chunks only:

```bash
MEMORY_SUMMARY_ENABLED=true PYTHONPATH=. python3 -m scripts.backfill_summaries \
  --chat-id=-{chat_id} \
  --source-jsonl src/data/messages_-{chat_id}.jsonl \
  --force-rebuild \
  --provider ollama \
  --max-chunks 20
```

## VS Code Debugging
A `.vscode/launch.json` is provided. Use the "Run Telegram Bot (src.main)" or "Debug Unit Tests" configurations from the Run & Debug panel.

## Notes
- Imports in `src/` use package-qualified paths (for example `from src import config`).
- Do not run files in `src/` directly; always use the `-m` module syntax from the project root.
- OpenAI provider uses `OPENAI_API_KEY` (official API key auth).
- Optional `OPENAI_AUTH_JSON_PATH` can be used to load/refresh bearer tokens from `auth.json` (refresh token required).
- In `OPENAI_AUTH_JSON_PATH` mode, runtime automatically uses Codex-compatible request flags
  (`instructions`, `store=false`, streaming) and defaults models to `OPENAI_CODEX_DEFAULT_MODEL`
  when `OPENAI_MODEL` is not explicitly set.
- Gemini support requires a valid API key from Google AI Studio.
- Google Calendar event creation requires a valid calendar ID and service account credentials.
- `ALLOWED_CHAT_IDS` is required; if empty, the bot denies all users.
- `DEBUG_MODE` controls your app debug logs (`src.*`, `__main__`).
- Use `THIRD_PARTY_LOG_LEVEL` to reduce dependency noise (default: `WARNING`).

## License
MIT
