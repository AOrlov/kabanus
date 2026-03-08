# Refactor Overview: Modularization and Current Contracts

## Goals
- Reduce coupling in previously large modules (`main.py`, memory facade, config facade, provider routing).
- Keep bot runtime behavior stable for end users.
- Keep configuration compatibility stable (env names/defaults/parsing/validation).
- Make wiring, provider fallback, and memory/context logic easier to test and evolve.

## Module Boundaries
| Area | Primary Modules | Responsibility | Current Stable Contract |
| --- | --- | --- | --- |
| Runtime entrypoint | `src/main.py`, `src/bot/app.py` | Startup, logging bootstrap, runtime composition, polling | `python -m src.main` remains the runtime command |
| Telegram handlers | `src/bot/handlers/*` | Command/message update routing (`/summary`, addressed messages, event photos) | User-facing command/message behavior |
| Bot services | `src/bot/services/*` | Reply generation, media extraction/transcription, reaction gating/state | Runtime behavior covered by tests; service internals are not API |
| Settings | `src/settings_loader.py`, `src/settings_models.py`, `src/config.py` | Typed settings model, env parsing/validation, cache | Env variable names/defaults/parsing/validation semantics |
| Memory/context | `src/memory/*`, `src/message_store.py` | History persistence, summary rollup/view, prompt context assembly | Exported `src.message_store` functions only |
| Providers | `src/model_provider.py`, `src/providers/contracts.py`, `src/provider_factory.py`, `src/openai_provider.py`, `src/gemini_provider.py` | Typed provider calls and deterministic fallback routing | OpenAI/Gemini routing and fallback semantics |

## Compatibility Scope
The required compatibility contract is intentionally narrow:

- Stable:
  - Configuration behavior (environment variable names/defaults/parsing/validation).
  - Runtime invocation via `python -m src.main`.
  - Provider fallback behavior in `RoutedModelProvider`.
- Not guaranteed:
  - Legacy module-level aliases or private helper exports.
  - Internal function/class layout inside runtime, memory, and provider modules.
  - Characterization-only test snapshots of old internals.

## Intentional API Changes
- `src/main.py` is a thin entrypoint; runtime composition moved to `src/bot/app.py`.
- `src/message_store.py` now exposes an explicit, small API and no longer re-exports private memory internals.
- Provider layer is typed-first; adapter indirection and dead helper methods were removed.
- Settings/cache ownership is centralized in `src/settings_loader.py`; `src/config.py` is a facade.

## Migration Guidance (Internal Callers)
- If you imported private helpers from monolithic modules, migrate to focused modules under:
  - `src/bot/handlers/` and `src/bot/services/`
  - `src/memory/`
  - `src/settings_loader.py` and `src/settings_models.py`
- For memory calls, rely only on exported `src.message_store` functions.
- For provider integration, implement/consume typed request contracts in `src/providers/contracts.py`.
- Avoid depending on underscore-prefixed helpers or module-level compatibility aliases.

## Validation Summary
Refactor acceptance is guarded by:
- full test suite (`pytest -q`)
- static checks (`pylint src tests`, `mypy src`)
- coverage threshold (>=80%)
- focused behavior verification for startup, summary/message handling, and provider fallback
