# Copilot Instructions

## Python Environment

- Always use the project virtual environment at `.venv`.
- If it does not exist, create it first:
  - `python3 -m venv .venv`
- Activate before running Python tooling:
  - `source .venv/bin/activate`

## Dependency Installation

- Install dependencies inside `.venv` only:
  - `pip install -r requirements.txt`
  - `pip install -r requirements-dev.txt`

## Project Layout

- Runtime entrypoint is `src/main.py` (`python -m src.main`).
- `src/main.py` should stay thin: bootstrap, handler wiring, and compatibility wrappers.
- Telegram bot logic is under `src/bot/`:
  - `app.py` for application assembly
  - `commands.py`, `summary_handler.py`, `message_handler.py`, `schedule_handler.py` for handlers
  - `media.py`, `reaction_service.py`, `draft_service.py`, `response_service.py` for orchestration helpers/services
- Provider/domain modules remain in `src/` (for example `openai_provider.py`, `gemini_provider.py`, `message_store.py`, `config.py`).

## Running Commands

- Prefer virtual environment binaries explicitly:
  - `.venv/bin/python -m src.main`
  - `PYTHONPATH=. .venv/bin/pytest -q`
  - `PYTHONPATH=. .venv/bin/mypy src`
  - `PYTHONPATH=. .venv/bin/pylint --persistent=n src tests`
  - `.venv/bin/pip list`

## Code Change Expectations

- Preserve runtime behavior unless the task explicitly requests behavior changes.
- Keep `src/main.py` small; put new behavior into `src/bot/*` modules.
- Add or update tests for bug fixes and flow changes.
- Run `pytest` and `mypy` before finalizing.
- Use `black` formatting and keep code consistent with repository lint settings.
