# Refactor Overview: Capability-Based AI Providers

## Goals
- Reduce coupling in previously large modules (`main.py`, memory facade, config facade, provider routing).
- Keep bot runtime behavior stable for end users.
- Keep configuration parsing explicit and testable.
- Replace hidden provider fallback behavior with explicit per-capability routing and fail-fast validation.
- Keep provider wiring, auth handling, and memory/context logic easier to test and evolve.

## Module Boundaries
| Area | Primary Modules | Responsibility | Current Stable Contract |
| --- | --- | --- | --- |
| Runtime entrypoint | `src/main.py`, `src/bot/app.py` | Startup, logging bootstrap, runtime composition, polling | `python -m src.main` remains the runtime command |
| Telegram handlers | `src/bot/handlers/*` | Command/message update routing (`/summary`, addressed messages, event photos) | User-facing command/message behavior |
| Bot services | `src/bot/services/*`, `src/bot/contracts.py` | Reply generation, media extraction/transcription, reaction gating/state, runtime capability bundles | Runtime behavior covered by tests; service internals are not API |
| Settings | `src/settings_loader.py`, `src/settings_models.py`, `src/config.py` | Nested provider settings, per-capability routing, env parsing/validation, cache | `config.get_settings(force=...)` and documented env variables |
| Memory/context | `src/memory/*`, `src/message_store.py` | History persistence, summary rollup/view, prompt context assembly | Exported `src.message_store` functions only |
| Providers | `src/providers/contracts.py`, `src/providers/capabilities.py`, `src/providers/errors.py`, `src/provider_factory.py`, `src/providers/openai/*`, `src/providers/gemini/*` | Typed request contracts, capability protocols, typed provider errors, explicit routing, provider-specific implementations | Capability routing and startup validation |

## Capability Routing

`MODEL_PROVIDER` seeds the routing map. `AI_PROVIDER_*` overrides one capability at a time.
`src/provider_factory.py` validates the entire routing map before runtime assembly:

| Capability | Env var | OpenAI | Gemini |
| --- | --- | --- | --- |
| Text generation | `AI_PROVIDER_TEXT_GENERATION` | Yes | Yes |
| Streaming text generation | `AI_PROVIDER_STREAMING_TEXT_GENERATION` | Yes | No |
| Low-cost text generation | `AI_PROVIDER_LOW_COST_TEXT_GENERATION` | Yes | Yes |
| Audio transcription | `AI_PROVIDER_AUDIO_TRANSCRIPTION` | No | Yes |
| OCR | `AI_PROVIDER_OCR` | Yes | Yes |
| Reaction selection | `AI_PROVIDER_REACTION_SELECTION` | Yes | Yes |
| Event parsing | `AI_PROVIDER_EVENT_PARSING` | Yes | Yes |

Key consequences:

- Unsupported capability/provider combinations fail fast with `ProviderCapabilityError`.
- Missing credentials for any routed provider fail fast with `ProviderConfigurationError`.
- `src/bot/app.py` performs a second validation pass for feature-specific runtime requirements such as message handling, reactions, event scheduling, and streaming drafts.
- The routed provider composition intentionally does not preserve the old OpenAI-primary-with-Gemini-fallback behavior.

## Compatibility Scope
The required compatibility contract is intentionally narrow:

- Stable:
  - Runtime invocation via `python -m src.main`.
  - Public settings access through `config.get_settings(force=...)`.
  - Typed request objects in `src/providers/contracts.py`.
- Deliberate breaks:
  - `src/model_provider.py`, `src/openai_provider.py`, and `src/gemini_provider.py` were removed.
  - Hidden fallback routing is gone; routing must now be explicit per capability.
  - Provider failures are surfaced as typed provider errors instead of being normalized into generic fallback behavior.
- Not guaranteed:
  - Legacy module-level aliases or private helper exports.
  - Internal function/class layout inside runtime, memory, and provider modules.
  - Characterization-only test snapshots of old internals.

## Intentional API Changes
- `src/main.py` is a thin entrypoint; runtime composition moved to `src/bot/app.py`.
- `src/message_store.py` now exposes an explicit, small API and no longer re-exports private memory internals.
- Provider routing is capability-first: `src/providers/capabilities.py` defines the protocols and `src/providers/errors.py` defines typed failures.
- Provider implementations are split into focused packages under `src/providers/openai/*` and `src/providers/gemini/*`.
- Settings/cache ownership is centralized in `src/settings_loader.py`; `src/config.py` is a facade.
- Concrete providers receive immutable settings in constructors; request handling does not call global config loaders.

## Migration Guidance (Internal Callers)
- If you imported private helpers from monolithic modules, migrate to focused modules under:
  - `src/bot/handlers/` and `src/bot/services/`
  - `src/memory/`
  - `src/settings_loader.py` and `src/settings_models.py`
  - `src/providers/openai/` and `src/providers/gemini/`
- For memory calls, rely only on exported `src.message_store` functions.
- For provider integration, consume typed request contracts from `src/providers/contracts.py`, capability protocols from `src/providers/capabilities.py`, and typed provider errors from `src/providers/errors.py`.
- Avoid depending on underscore-prefixed helpers or module-level compatibility aliases.
- If you use the onboarding helpers, remember they only provision OpenAI credentials; explicit routing still determines whether Gemini credentials are also required.

## Validation Summary
Refactor acceptance is guarded by:
- full test suite (`pytest -q`)
- static checks (`pylint src tests`, `mypy src`)
- coverage threshold (`coverage run -m pytest -q && coverage report --fail-under=80`)
- focused behavior verification for OpenAI text + streaming, Gemini multimodal capabilities, and startup failure on invalid routing or missing credentials
