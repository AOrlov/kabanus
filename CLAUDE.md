# Kabanus Contributor Notes (Claude)

## Current Architecture Baseline
- Keep `python -m src.main` as the entrypoint.
- Treat `src/main.py`, `src/config.py`, and `src/message_store.py` as compatibility facades.
- Add new bot behavior in focused modules:
  - Handlers: `src/bot/handlers/*`
  - Services: `src/bot/services/*`
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
- Preserve `config.get_settings(force=...)` behavior and legacy module attribute access.
- Preserve existing `message_store` callable surface unless a deliberate break is documented.
- Preserve legacy `src.main` helper/wrapper exports used by tests or integrations, or document migration/deprecation explicitly.
- Preserve provider fallback semantics in `RoutedModelProvider`.

## Testing and Validation
- Add or update targeted unit tests for every behavior change.
- Run and keep green:
  - `pytest -q`
  - `pylint src tests`
  - `mypy src`
  - `coverage run -m pytest -q && coverage report --fail-under=80`

## Refactor Documentation
- See `docs/architecture/refactor-overview.md` for boundaries, extension points, and migration notes.
