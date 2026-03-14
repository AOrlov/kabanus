---
# Refactor AI Providers Around Explicit Capabilities

## Overview
Replace the current monolithic AI provider abstraction with explicit capability-based services, provider-specific packages, and fail-fast routing/configuration. This plan intentionally allows backward-incompatible cleanup: remove hidden fallback behavior, delete compatibility-oriented abstractions that keep providers coupled, and tighten credential/error handling for maintainability, supportability, and security.

## Context
- Files involved: `src/model_provider.py`, `src/providers/contracts.py`, `src/provider_factory.py`, `src/openai_provider.py`, `src/gemini_provider.py`, `src/openai_auth.py`, `src/settings_models.py`, `src/settings_loader.py`, `src/bot/contracts.py`, `src/bot/app.py`, `src/bot/features/message_flow.py`, `src/bot/features/events.py`, `src/bot/services/reply_service.py`, `src/bot/services/media_service.py`, `src/bot/services/reaction_service.py`, `src/bot/handlers/message_handler.py`, `src/bot/handlers/events_handler.py`
- Related patterns: typed request contracts in `src/providers/contracts.py`, protocol boundaries in `src/bot/contracts.py`, architecture-boundary tests in `tests/test_architecture_boundaries.py` and `tests/test_bot_contract_boundaries.py`
- Dependencies: `openai`, `google-genai`, `python-telegram-bot`, dotenv-based settings loading, `scripts/onboard_openai.py`

## Development Approach
- Testing approach: TDD (lock required behavior with focused characterization tests, then refactor to the new contracts)
- Complete each task fully before moving to the next
- Prefer deletion over adapters when an abstraction only exists for backward compatibility
- Inject immutable settings/dependencies into provider components; concrete providers should not call `config.get_settings()` during request handling
- Fail fast at startup on invalid capability routing, unsupported capability/provider combinations, or missing credentials
- CRITICAL: every task MUST include new/updated tests
- CRITICAL: all tests must pass before starting next task

## Implementation Steps

### Task 1: Replace the Monolithic Provider Contract

**Files:**
- Modify: `src/providers/contracts.py`
- Modify: `src/bot/contracts.py`
- Modify: `tests/test_provider_contracts.py`
- Modify: `tests/test_bot_contract_boundaries.py`
- Create: `src/providers/capabilities.py`
- Create: `src/providers/errors.py`
- Delete or retire: `src/model_provider.py`

- [x] Split the all-in-one provider API into capability-specific protocols for text generation, streaming text, low-cost generation, transcription, OCR, reaction selection, and event parsing
- [x] Keep typed request objects, but introduce explicit provider error types so auth/quota/configuration failures are not handled as generic exceptions
- [x] Remove the legacy `ModelProvider` base class once bot/runtime consumers are migrated
- [x] Add contract and boundary tests for the new capability interfaces
- [x] write tests for this task
- [x] run project test suite - must pass before task 2

### Task 2: Replace Flat Provider Settings and Hidden Routing

**Files:**
- Modify: `src/settings_models.py`
- Modify: `src/settings_loader.py`
- Modify: `src/config.py`
- Modify: `src/provider_factory.py`
- Modify: `tests/test_settings_loader.py`
- Modify: `tests/test_config_openai.py`
- Modify: `tests/test_config_compat_contract.py`
- Modify: `tests/test_provider_factory.py`

- [x] Replace the flat OpenAI/Gemini settings bag with nested provider settings plus an explicit per-capability routing configuration
- [x] Remove hard-coded routing rules such as “OpenAI primary with Gemini transcription fallback” and replace them with validated startup composition
- [x] Construct provider components with injected settings/dependencies instead of letting concrete providers read global config on demand
- [x] Rewrite configuration tests around the new contract rather than preserving old compatibility semantics
- [x] write tests for this task
- [x] run project test suite - must pass before task 3

### Task 3: Split and Harden OpenAI Integration

**Files:**
- Create: `src/providers/openai/*`
- Modify or delete: `src/openai_provider.py`
- Modify: `src/openai_auth.py`
- Modify: `scripts/onboard_openai.py`
- Modify: `tests/test_openai_provider.py`
- Modify: `tests/test_openai_auth.py`
- Modify: `tests/test_onboard_openai.py`

- [x] Break OpenAI integration into focused components for client construction, auth/token refresh, request building, streaming, and response parsing
- [x] Keep only supported capabilities wired into runtime composition instead of shipping placeholder methods that raise at call time
- [x] Tighten secret handling around `auth.json`, path validation, file permissions, and logging hygiene
- [x] Preserve the worthwhile behaviors of API-key mode and auth.json/Codex mode without carrying legacy branches only for compatibility
- [x] write tests for this task
- [x] run project test suite - must pass before task 4

### Task 4: Split and Harden Gemini Integration

**Files:**
- Create: `src/providers/gemini/*`
- Modify or delete: `src/gemini_provider.py`
- Modify: `tests/test_gemini_provider.py`
- Modify: `tests/test_provider_factory.py`

- [x] Extract model selection/quota tracking, system-instruction loading, request assembly, and response parsing into smaller units with isolated tests
- [x] Remove implicit global environment mutation for Gemini credentials and keep client construction explicit and local
- [x] Normalize empty/invalid model responses so failures are observable and typed instead of silently returning empty strings where that hides real problems
- [x] Make model-role decisions explicit in configuration rather than relying on incidental `GEMINI_MODELS` ordering side effects
- [x] write tests for this task
- [x] run project test suite - must pass before task 5

### Task 5: Update Runtime and Bot Services to Consume Capabilities

**Files:**
- Modify: `src/bot/app.py`
- Modify: `src/bot/contracts.py`
- Modify: `src/bot/features/message_flow.py`
- Modify: `src/bot/features/events.py`
- Modify: `src/bot/services/reply_service.py`
- Modify: `src/bot/services/media_service.py`
- Modify: `src/bot/services/reaction_service.py`
- Modify: `src/bot/handlers/message_handler.py`
- Modify: `src/bot/handlers/events_handler.py`
- Modify: `tests/test_bot_reply_service.py`
- Modify: `tests/test_bot_message_handler.py`
- Modify: `tests/test_bot_events_handler.py`
- Modify: `tests/test_bot_app.py`

- [ ] Inject only the capabilities each service needs instead of passing a full provider object everywhere
- [ ] Remove provider-name checks such as `model_provider == "openai"` and gate features on actual capability availability, such as streaming support for drafts
- [ ] Fail fast during runtime assembly when a configured flow requires a capability that is not available
- [ ] Keep product-layer boundaries clean by depending on provider capability protocols and composition objects rather than concrete OpenAI/Gemini modules
- [ ] write tests for this task
- [ ] run project test suite - must pass before task 6

### Task 6: Verify Acceptance Criteria

- [ ] manual test: OpenAI text generation and streaming work through the new capability composition
- [ ] manual test: Gemini transcription, OCR, and event parsing work when those capabilities are routed to Gemini
- [ ] manual test: invalid capability routing or missing credentials fails at startup with a clear error
- [ ] run full test suite (`pytest -q`)
- [ ] run linter (`pylint src tests`)
- [ ] run type checks (`mypy src`)
- [ ] verify test coverage meets 80%+

### Task 7: Update Documentation

- [ ] update `README.md` for the new provider configuration and routing model
- [ ] update `docs/architecture/refactor-overview.md` to reflect the new AI provider boundaries and dropped compatibility guarantees
- [ ] update `CLAUDE.md` if internal provider/refactor guidance changes
- [ ] update provider onboarding documentation or helper scripts impacted by the new settings shape
- [ ] move this plan to `docs/plans/completed/`
---
