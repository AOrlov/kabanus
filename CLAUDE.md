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
- Keep provider contracts and routing in:
  - `src/providers/contracts.py`
  - `src/model_provider.py`
  - `src/provider_factory.py`

## Compatibility Rules
- Do not rename or silently change env var semantics without explicit migration notes.
- Preserve `config.get_settings(force=...)` behavior. Do not reintroduce module-level dynamic config attributes.
- Preserve existing `message_store` callable surface unless a deliberate break is documented.
- Preserve the startup contract (`python -m src.main` -> `src.main.run` -> `src.bot.app.run`).
- Preserve provider fallback semantics in `RoutedModelProvider`.
- Use typed provider request contracts; do not add legacy untyped convenience wrapper methods back to `ModelProvider`.

## Testing and Validation
- Add or update targeted unit tests for every behavior change.
- Run and keep green:
  - `pytest -q`
  - `pylint src tests`
  - `mypy src`
  - `coverage run -m pytest -q && coverage report --fail-under=80`
- Current tooling config includes `pylint` `errors-only = yes` and targeted mypy `ignore_errors = True` module overrides; avoid adding broader suppressions.

## Refactor Documentation
- See `docs/architecture/refactor-overview.md` for boundaries, extension points, and migration notes.
- See `docs/architecture/telegram-framework-target.md` for framework vs product ownership and dependency rules.
