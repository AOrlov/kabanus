# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/`.
- `src/main.py` is the runtime entrypoint (`python -m src.main`).
- Provider and domain modules are split by concern (for example `gemini_provider.py`, `calendar_provider.py`, `message_store.py`, `config.py`).
- Shared helpers are in `src/utils.py`, `src/retry_utils.py`, and `src/logging_utils.py`.

Tests live in `tests/` and follow `test_*.py` naming. Utility scripts are in `scripts/` (for example `scripts/dump_chat.py`). Container files are at repo root (`Dockerfile`, `docker-compose.yml`).

## Build, Test, and Development Commands
- `pip install -r requirements.txt` installs runtime dependencies.
- `pip install -r requirements-dev.txt` installs dev tools (`pytest`, `black`, `mypy`, `pylint`).
- `python -m src.main` runs the bot locally (run from repo root).
- `pytest -q` runs unit tests.
- `black src tests` formats code.
- `pylint src tests` runs lint checks (`max-line-length=120`).
- `mypy src` runs static type checks.
- `docker build -t kabanus . && docker run --env-file .env kabanus` builds/runs in Docker.

## Coding Style & Naming Conventions
Use Python 3.9+ style with 4-space indentation and type hints on new/changed code. Keep modules focused by feature/provider area. Use:
- `snake_case` for functions, variables, and module files.
- `PascalCase` for classes.
- Clear, explicit config names matching environment variables.

Use `black` as formatter and keep code pylint-clean under repo config.

## Testing Guidelines
Use `pytest`; place tests in `tests/` as `test_<module>.py` and test functions as `test_<behavior>()`. Prefer small, deterministic unit tests around provider/config logic. Run `pytest -q` before opening a PR; add regression tests for bug fixes.

## Commit & Pull Request Guidelines
Recent history favors short, imperative commit subjects (for example: `Update deps`, `Better logging`, `Add support of GEMINI_MODELS...`). Follow that style:
- One focused change per commit.
- Subject in imperative mood, concise but specific.

PRs should include:
- What changed and why.
- Any env/config updates (`README`/sample env updates when relevant).
- Test evidence (at minimum `pytest` output).
- Logs or screenshots only when behavior/observability changes materially.

## Security & Configuration Tips
Do not commit secrets. Keep API keys and chat IDs in environment files (`.env`, `*.env`) excluded by `.gitignore`. Validate access controls (`ALLOWED_CHAT_IDS`) when testing locally.
