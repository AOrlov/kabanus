# Telegram Speech-to-Text & Event Bot

Telegram bot for group interaction, AI replies, voice transcription, OCR, and optional Google Calendar event creation from event poster photos. AI behavior is assembled from explicit provider capabilities: each capability is routed to OpenAI or Gemini at startup, validated up front, and exposed to the bot through narrow contracts instead of a monolithic provider abstraction.

## Features
- Listens for voice and text messages in Telegram groups
- Supports context-aware AI replies for text, voice, and images
- Explicit per-capability AI routing with fail-fast startup validation
- OpenAI capabilities: text generation, streaming drafts, low-cost text generation, OCR, reaction selection, event parsing
- Gemini capabilities: text generation, low-cost text generation, audio transcription, OCR, reaction selection, event parsing
- Typed provider failures for auth, quota, capability, configuration, and invalid responses
- Supports context memory optimization with recent-window + optional long-term summaries
- Optional multi-model Gemini quota handling with explicit model roles
- Can auto-react to messages (optional)
- Can create Google Calendar events from event poster photos (optional)
- Notifies admin on critical errors
- Logs to stdout and temporary files
- Access control via allowed chat/user IDs
- Configurable via environment variables

## Requirements
- Docker (recommended) or Python 3.9+
- Telegram bot token
- Allowed chat/user IDs (for access control)
- OpenAI API key or `auth.json` credentials when any routed capability uses OpenAI
- Google Gemini API key when any routed capability uses Gemini
- For the full shipped capability map, both providers are usually required because OpenAI does not implement audio transcription and Gemini does not implement streaming text generation
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

# AI routing
MODEL_PROVIDER=openai                       # Default provider for all capabilities: openai|gemini
AI_PROVIDER_TEXT_GENERATION=openai          # Optional override; defaults to MODEL_PROVIDER
AI_PROVIDER_STREAMING_TEXT_GENERATION=openai
AI_PROVIDER_LOW_COST_TEXT_GENERATION=openai
AI_PROVIDER_AUDIO_TRANSCRIPTION=gemini
AI_PROVIDER_OCR=openai
AI_PROVIDER_REACTION_SELECTION=openai
AI_PROVIDER_EVENT_PARSING=openai

# OpenAI settings
OPENAI_API_KEY=your-openai-api-key         # API-key mode
OPENAI_AUTH_JSON_PATH=path/to/auth.json    # Optional alternative to OPENAI_API_KEY
OPENAI_REFRESH_URL=https://auth.openai.com/oauth/token
OPENAI_REFRESH_CLIENT_ID=
OPENAI_REFRESH_GRANT_TYPE=refresh_token
OPENAI_AUTH_LEEWAY_SECS=60
OPENAI_AUTH_TIMEOUT_SECS=20
OPENAI_CODEX_BASE_URL=https://chatgpt.com/backend-api
OPENAI_CODEX_DEFAULT_MODEL=gpt-5.3-codex
OPENAI_MODEL=gpt-5.3-codex
OPENAI_LOW_COST_MODEL=gpt-5.3-codex
OPENAI_REACTION_MODEL=gpt-5.3-codex

# Gemini settings
GEMINI_API_KEY=your-gemini-api-key         # GOOGLE_API_KEY is also accepted
GOOGLE_API_KEY=your-google-api-key         # Optional alias; wins over GEMINI_API_KEY when set
GEMINI_MODEL=gemini-2.0-flash              # Preferred text + multimodal Gemini model
GEMINI_LOW_COST_MODEL=gemini-2.0-flash     # Preferred low-cost Gemini model
REACTION_GEMINI_MODEL=gemini-2.0-flash     # Preferred Gemini model for reaction selection
GEMINI_MODELS=[{"name":"gemini-2.0-flash","rpm":60,"rpd":1000}]
THINKING_BUDGET=0
USE_GOOGLE_SEARCH=false
SYSTEM_INSTRUCTIONS_PATH=system_instructions.txt
LANGUAGE=ru
TOKEN_LIMIT=500000

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

### 4.1 Capability Routing and Provider Support

`MODEL_PROVIDER` seeds the routing map, and each `AI_PROVIDER_*` variable can override one capability.
Startup rejects unsupported routing or missing credentials before the bot begins polling.

| Capability | Env var | OpenAI | Gemini |
| --- | --- | --- | --- |
| Text generation | `AI_PROVIDER_TEXT_GENERATION` | Yes | Yes |
| Streaming text generation | `AI_PROVIDER_STREAMING_TEXT_GENERATION` | Yes | No |
| Low-cost text generation | `AI_PROVIDER_LOW_COST_TEXT_GENERATION` | Yes | Yes |
| Audio transcription | `AI_PROVIDER_AUDIO_TRANSCRIPTION` | No | Yes |
| OCR | `AI_PROVIDER_OCR` | Yes | Yes |
| Reaction selection | `AI_PROVIDER_REACTION_SELECTION` | Yes | Yes |
| Event parsing | `AI_PROVIDER_EVENT_PARSING` | Yes | Yes |

OpenAI-first baseline:

```dotenv
MODEL_PROVIDER=openai
AI_PROVIDER_AUDIO_TRANSCRIPTION=gemini
OPENAI_API_KEY=...
GEMINI_API_KEY=...
```

Gemini-first baseline:

```dotenv
MODEL_PROVIDER=gemini
AI_PROVIDER_STREAMING_TEXT_GENERATION=openai
OPENAI_API_KEY=...
GEMINI_API_KEY=...
```

If `GEMINI_MODELS` is set, the preferred role models named by `GEMINI_MODEL`,
`GEMINI_LOW_COST_MODEL`, and `REACTION_GEMINI_MODEL` must appear in that list.
The preferred model is tried first and the remaining configured Gemini models act as
same-provider quota fallbacks.

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
It now prints the required `AI_PROVIDER_AUDIO_TRANSCRIPTION=gemini` override for the
current capability map, but you still need Gemini credentials in the environment.
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
- Runtime rejects non-file paths and overly broad permissions; refresh writes are atomic
  and enforce private file mode (`0600`) on best effort.
- Refresh-token/Codex mode also requires an access token that carries
  `chatgpt_account_id`; use `scripts/openai_codex_oauth.py` to generate that file shape.
  Runtime now rejects malformed refresh-token files instead of silently falling back to
  the standard API endpoint.

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

## Testing
- `pytest -q` runs the full test suite.
- `pytest -q tests/test_bot_e2e.py` runs the hermetic bot end-to-end layer.
- `pylint src tests` and `mypy src` cover linting and type checks.
- The hermetic e2e suite composes the real runtime through `src.bot.app.build_runtime()` and `src.bot.app.build_application()`, dispatches synthetic Telegram updates through registered handlers, uses fake provider/calendar/Telegram I/O only, and verifies persistence against temp-backed `src.message_store` paths.

## Usage
- If `ENABLE_SCHEDULE_EVENTS=true`, send a photo of an event poster to create a Google Calendar event (requires calendar credentials and ID).
- If `ENABLE_MESSAGE_HANDLING=true`, send a voice, text, or image to interact with the bot. Mention the bot or reply to its message for a response.
- Use `/summary` (alias: `/tldr`) to inspect per-chat summary chunks created by memory summary.
  Examples:
  `/summary` (last chunk), `/summary 5`, `/summary index 42`, `/summary budget api`, `/summary --head 10 --grep budget`.
  `/summary help` shows command usage.
  Summary command requests and responses are not saved into chat history.
- If `GEMINI_MODELS` is set, Gemini uses the explicit role models from `GEMINI_MODEL`,
  `GEMINI_LOW_COST_MODEL`, and `REACTION_GEMINI_MODEL` first, then falls back to the
  remaining configured Gemini models when RPM/RPD limits are exhausted.
- If `REACTION_ENABLED=true`, the bot may react to messages within configured budget/cooldown and considers recent dialogue context when choosing emoji.

## Utilities
- `scripts/dump_chat.py`: Dump Telegram chat history to JSONL (see script for usage).
- `scripts/backfill_summaries.py`: Backfill `*.summary.json` from existing JSONL history.
- `scripts/view_summary.py`: Inspect summary files quickly from CLI.
- `scripts/dead_code_audit.py`: Run dead-code and boundary checks (`python3 scripts/dead_code_audit.py`).
- `scripts/onboard_openai.py`: Interactive OpenAI onboarding and auth JSON generation.
- `scripts/openai_codex_oauth.py`: OpenAI Codex OAuth login and auth.json writer.
- `scripts/README.md`: Detailed script usage and examples.
- Dev tooling includes `vulture` in `requirements-dev.txt` for dead-code auditing.

## Architecture
The codebase now separates a reusable Telegram framework layer from Kabanus product code.

- Runtime entrypoint remains `python -m src.main`; `src/main.py` only configures bootstrap logging and delegates startup to `src/bot/app.py`.
- Reusable framework layer lives in `src/telegram_framework/*`:
  - `application.py`: application assembly helpers
  - `runtime.py`: polling bootstrap and settings resolver
  - `policy.py`: access policy and update context helpers
  - `error_reporting.py`: admin notification and exception formatting
- Product composition lives in `src/bot/app.py` and feature registration modules in `src/bot/features/*`.
- Product behavior lives in `src/bot/handlers/*` and `src/bot/services/*`.
- Cross-layer dependencies use explicit protocols and capability bundles in `src/bot/contracts.py` (no implicit module-level globals).
- Memory internals live in `src/memory/*`; `src/message_store.py` exposes the public memory API.
- Settings parsing internals live in `src/settings_loader.py` and `src/settings_models.py`; `src/config.py` is a thin facade around `get_settings(force=...)`.
- Provider routing and typed contracts are in `src/provider_factory.py`, `src/providers/contracts.py`, `src/providers/capabilities.py`, and `src/providers/errors.py`.
- Concrete provider implementations live in `src/providers/openai/*` and `src/providers/gemini/*`.

Detailed module boundaries, extension points, compatibility guarantees, and migration notes:
- `docs/architecture/refactor-overview.md`

## Compatibility and Migration
- Bot startup entrypoint remains `python -m src.main`.
- `config.get_settings(force=...)` remains the public settings facade.
- Provider configuration is now explicit per capability. Hidden fallback routing is gone.
- Legacy monolithic modules such as `src/model_provider.py`, `src/openai_provider.py`,
  and `src/gemini_provider.py` were removed in favor of provider packages and capability
  protocols.
- Runtime and provider consumers should handle typed provider errors instead of catching
  broad generic exceptions.

Removed internal compatibility shims include:
- `config.<UPPERCASE_ENV_NAME>` module-level dynamic attribute access
- Monolithic provider wrappers in favor of typed request contracts and capability protocols

## Migration Notes (Internal Integrations)
- If you imported private internals from monolithic modules, migrate to new focused modules:
  - Framework internals: `src/telegram_framework/*`
  - Product feature registration: `src/bot/features/*`
  - Bot flow internals: `src/bot/handlers/*`, `src/bot/services/*`
  - Memory internals: `src/memory/history_store.py`, `src/memory/summary_store.py`, `src/memory/context_builder.py`
  - Settings internals: `src/settings_loader.py`, `src/settings_models.py`
- Provider internals: `src/providers/openai/*`, `src/providers/gemini/*`, `src/providers/capabilities.py`, `src/providers/errors.py`
- Use `config.get_settings(force=...)` and `Settings` fields directly; do not rely on module-level env-var aliases.
- Prefer typed provider request wrappers from `src/providers/contracts.py` for provider integrations.
- Keep framework modules product-agnostic; compose product handlers/services via `src/bot/features/*` and `src/bot/app.py`.
- Do not rely on private module helpers or module-level legacy aliases.
- For memory usage, rely on `src/message_store.py` exported functions only:
  `add_message`, `get_last_message`, `get_all_messages`, `get_message_by_telegram_message_id`,
  `get_summary_view_text`, `build_context`, `assemble_context`, `clear_memory_state`.

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
- A valid routing map must be fully supported at startup even if some product features are disabled.
- OpenAI uses `OPENAI_API_KEY` or `OPENAI_AUTH_JSON_PATH` (refresh token required for auth refresh).
- In `OPENAI_AUTH_JSON_PATH` mode, runtime automatically uses Codex-compatible request flags
  (`instructions`, `store=false`, streaming) and defaults models to `OPENAI_CODEX_DEFAULT_MODEL`
  when `OPENAI_MODEL` is not explicitly set.
- OpenAI auth file handling requires an existing file path and private permissions (`0600`) on non-Windows hosts.
- Gemini support requires a valid API key from Google AI Studio.
- `GOOGLE_API_KEY` overrides `GEMINI_API_KEY` when both are set.
- The OpenAI onboarding helpers only provision OpenAI credentials; keep the printed
  `AI_PROVIDER_AUDIO_TRANSCRIPTION=gemini` override and add Gemini credentials separately.
- Google Calendar event creation requires a valid calendar ID and service account credentials.
- `ALLOWED_CHAT_IDS` is required; if empty, the bot denies all users.
- `DEBUG_MODE` controls your app debug logs (`src.*`, `__main__`).
- Use `THIRD_PARTY_LOG_LEVEL` to reduce dependency noise (default: `WARNING`).

## License
MIT
