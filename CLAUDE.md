# Kabanus Contributor Notes (Claude)

## Current Architecture Baseline
- Keep `python -m src.main` as the entrypoint.
- Keep `src/main.py` thin (`configure_bootstrap` + `src.bot.app.run()`).
- Keep framework/runtime-generic Telegram logic in `src/telegram_framework/*`.
- Keep product composition and registration in `src/bot/app.py` and `src/bot/features/*`.
- Add/extend bot behavior in focused product modules:
  - Handlers: `src/bot/handlers/*`
  - Services: `src/bot/services/*`
- Keep cross-layer contracts explicit in `src/bot/contracts.py` (constructor-injected dependencies only).
- Keep memory concerns split:
  - `src/memory/history_store.py`
  - `src/memory/summary_store.py`
  - `src/memory/context_builder.py`
- Keep settings parsing in `src/settings_loader.py` and types in `src/settings_models.py`.
- Keep provider contracts, errors, and routing in:
  - `src/providers/contracts.py`
  - `src/providers/capabilities.py`
  - `src/providers/errors.py`
  - `src/provider_factory.py`
  - `src/providers/openai/*`
  - `src/providers/gemini/*`

## Compatibility Rules
- Do not rename or silently change env var semantics without explicit migration notes.
- Preserve `config.get_settings(force=...)` behavior. Do not reintroduce module-level dynamic config attributes.
- Preserve existing `message_store` callable surface unless a deliberate break is documented.
- Preserve the startup contract (`python -m src.main` -> `src.main.run` -> `src.bot.app.run`).
- Keep provider routing explicit per capability and fail fast on unsupported combinations or missing credentials.
- Use typed provider request contracts, capability protocols, and provider errors; do not reintroduce a monolithic `ModelProvider` abstraction or fallback-driven routing.

## Testing and Validation
- Add or update targeted unit tests for every behavior change.
- Run and keep green:
  - `pytest -q`
  - `pylint src tests`
  - `mypy src`
  - `python3 scripts/dead_code_audit.py`
  - `coverage run -m pytest -q && coverage report --fail-under=80`
- Current tooling config includes `pylint` `errors-only = yes`, targeted mypy `ignore_errors = True` module overrides, and `vulture`-based dead-code checks; avoid adding broader suppressions.
- Keep cross-module boundaries explicit: do not call private (`_name`) helpers across `src/*` module boundaries.

## Refactor Documentation
- See `docs/architecture/refactor-overview.md` for boundaries, extension points, and migration notes.
- See `docs/architecture/telegram-framework-target.md` for framework vs product ownership and dependency rules.
