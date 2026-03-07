# Refactor Overview: Modularization and Compatibility

## Goals
- Reduce coupling in large modules (`main.py`, `message_store.py`, `config.py`, provider wiring).
- Keep externally observable bot behavior stable.
- Preserve existing configuration and compatibility entry points for legacy callers.
- Make new features easier to add and test with explicit boundaries and dependency injection.

## Module Boundaries
| Area | Primary Modules | Responsibility | Compatibility Surface |
| --- | --- | --- | --- |
| Runtime entrypoint | `src/main.py`, `src/bot/app.py` | Startup, app wiring, runtime object composition | `python -m src.main` remains the runtime command |
| Telegram handlers | `src/bot/handlers/message_handler.py`, `src/bot/handlers/summary_handler.py`, `src/bot/handlers/events_handler.py`, `src/bot/handlers/common.py` | Update routing and user-facing command/message behavior | `src.main` still re-exports handler helpers used by legacy tests/callers |
| Bot services | `src/bot/services/reply_service.py`, `src/bot/services/media_service.py`, `src/bot/services/reaction_service.py` | Focused operational logic: response sending, media parsing/transcription, reaction gating/state | Services are constructed by runtime wiring and remain transparent to users |
| Settings | `src/settings_models.py`, `src/settings_loader.py`, `src/config.py` | Typed settings model + env parsing/cache internals + facade | `src.config` still exposes `Settings`, `ModelSpec`, `get_settings(force=...)`, and legacy `__getattr__` mapping |
| Memory/context | `src/memory/history_store.py`, `src/memory/summary_store.py`, `src/memory/context_builder.py`, `src/message_store.py` | Message persistence, summary rollup/view, prompt context assembly | `src.message_store` remains the backward-compatible facade |
| Providers | `src/providers/contracts.py`, `src/model_provider.py`, `src/provider_factory.py`, `src/openai_provider.py`, `src/gemini_provider.py` | Typed request contracts, legacy provider abstraction, deterministic routing/fallback | Legacy `ModelProvider` methods and provider factory behavior are preserved |

## Extension Points
- Add or swap model providers:
  - Implement `ModelProvider` and/or typed methods in `TypedProviderContract`.
  - Extend provider routing in `src/provider_factory.py`.
- Customize bot behavior:
  - Inject dependencies via `src/bot/app.py::build_runtime(...)` function arguments.
  - Add new handlers under `src/bot/handlers/` and register in app wiring.
- Extend memory strategy:
  - Reuse `src/memory/*` primitives.
  - Adjust context and summary policy via settings and `context_builder`.
- Add settings safely:
  - Add fields to `Settings` dataclass in `src/settings_models.py`.
  - Parse/validate in `src/settings_loader.py`.
  - Expose legacy mapping in `src/config.py` when compatibility is required.

## Backward Compatibility Guarantees
- Environment variable names, defaults, and validation behavior are preserved.
- `src.config` public/legacy surface is preserved:
  - `Settings`, `ModelSpec`
  - `get_settings(force=False)`
  - module-level attribute mapping via `__getattr__`
- `src.message_store` public API remains available and delegates to extracted modules.
- Routing semantics in `RoutedModelProvider` are preserved:
  - OpenAI-primary mode can fall back to Gemini
  - Gemini-primary mode can fall back to OpenAI
  - streaming fallback keeps partial-output behavior
- Runtime invocation remains `python -m src.main`.

## Intentional API Changes and Migration Notes
These are internal/API-shape changes, not user-facing behavior changes.

- Internal extraction from monoliths:
  - Former mixed concerns in `src/main.py` now live in handlers/services under `src/bot/`.
  - Former memory internals now live in `src/memory/`.
  - Former settings internals now live in `src/settings_loader.py` and `src/settings_models.py`.
- Provider typing enhancements:
  - Typed request wrappers (`TextGenerationRequest`, `ReactionSelectionRequest`, and others) were introduced in `src/providers/contracts.py`.
  - Legacy provider methods remain supported; wrappers delegate to legacy methods for compatibility.
- Migration guidance for internal callers:
  - If code imported private helper functions from monolithic files, migrate to the corresponding focused module.
  - Keep using `src.config` and `src.message_store` for stable public compatibility entry points.

## Validation and Safety Net
Behavior was locked with characterization and compatibility tests across:
- message trigger matrix, summary command parsing forms, reaction gating, context limits
- config env/default contract and legacy module attribute access
- message store and provider factory compatibility behavior
