---
# Refactor Telegram Bot into an Extractable Framework Architecture

## Overview
Refactor the current bot into two clear layers:
- a reusable Telegram framework layer that owns polling, update routing, access policy, and error/reporting plumbing
- a product layer (Kabanus) that owns AI, memory, calendar, and bot-specific behavior

This plan intentionally allows backward-incompatible internal API changes so the framework can be cleanly extracted into a separate repo later with minimal churn.

## Context
- Files involved:
  - Runtime/composition: `src/main.py`, `src/bot/app.py`, `src/bot/handlers/common.py`
  - Product handlers/services: `src/bot/handlers/message_handler.py`, `src/bot/handlers/summary_handler.py`, `src/bot/handlers/events_handler.py`, `src/bot/services/reply_service.py`, `src/bot/services/reaction_service.py`, `src/bot/services/media_service.py`
  - Domain integrations: `src/message_store.py`, `src/model_provider.py`, `src/provider_factory.py`, `src/calendar_provider.py`
  - Settings: `src/config.py`, `src/settings_loader.py`, `src/settings_models.py`
  - Tests: `tests/test_bot_app.py`, `tests/test_main.py`, `tests/test_bot_message_handler.py`, `tests/test_bot_summary_handler.py`, `tests/test_bot_events_handler.py`, `tests/test_provider_contracts.py`
  - Docs: `README.md`, `docs/architecture/refactor-overview.md`
- Related patterns:
  - Dependency injection already exists in `build_runtime()`, but framework concerns and product concerns are still mixed in `src/bot/app.py`.
  - Handlers/services are testable, but they still rely on implicit globals in several places.
- Dependencies:
  - Keep current runtime dependencies (`python-telegram-bot`, OpenAI/Gemini provider stack, Google Calendar stack).
  - No new runtime dependency is required for the refactor.

## Development Approach
- **Testing approach**: TDD for new framework seams, characterization tests first for current bot behavior
- Complete each task fully before moving to the next
- Prefer explicit interfaces/protocols over global module state
- Backward compatibility for internal imports is not required
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Lock behavioral baseline and define target boundaries

**Files:**
- Modify: `tests/test_bot_app.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_bot_message_handler.py`
- Modify: `tests/test_bot_summary_handler.py`
- Modify: `tests/test_bot_events_handler.py`
- Create: `tests/test_architecture_boundaries.py`
- Create: `docs/architecture/telegram-framework-target.md`

- [x] Add/adjust characterization tests for externally visible behavior (command routing, addressed-message flow, summary flow, event flow, admin error notification)
- [x] Add architecture boundary tests that fail if framework code imports product modules
- [x] Write target architecture doc defining what belongs to framework vs product
- [x] write tests for this task
- [x] run project test suite - must pass before task 2

### Task 2: Extract reusable Telegram framework kernel

**Files:**
- Create: `src/telegram_framework/__init__.py`
- Create: `src/telegram_framework/runtime.py`
- Create: `src/telegram_framework/application.py`
- Create: `src/telegram_framework/policy.py`
- Create: `src/telegram_framework/error_reporting.py`
- Modify: `src/bot/app.py`
- Modify: `src/bot/handlers/common.py`
- Create: `tests/test_telegram_framework_runtime.py`
- Create: `tests/test_telegram_framework_policy.py`

- [x] Move generic runtime concerns out of `src/bot/app.py` into framework modules (application creation, handler registration hook points, polling bootstrap)
- [x] Move generic access-policy and update-log-context helpers into framework policy utilities
- [x] Move generic error formatting/admin notification plumbing into framework error-reporting utilities
- [x] Keep framework free of provider/memory/calendar product logic
- [x] write tests for this task
- [x] run project test suite - must pass before task 3

### Task 3: Recompose Kabanus as product modules on top of the framework

**Files:**
- Create: `src/bot/features/__init__.py`
- Create: `src/bot/features/commands.py`
- Create: `src/bot/features/message_flow.py`
- Create: `src/bot/features/summary.py`
- Create: `src/bot/features/events.py`
- Modify: `src/bot/app.py`
- Modify: `src/main.py`
- Modify: `tests/test_bot_app.py`
- Modify: `tests/test_main.py`
- Create: `tests/test_bot_feature_registration.py`

- [x] Replace ad-hoc handler wiring with explicit product feature registration modules
- [x] Keep Kabanus-specific wiring (provider, memory, calendar, prompt logic) in product modules only
- [x] Make `src/main.py` a thin startup entrypoint that delegates composition to product app wiring
- [x] write tests for this task
- [x] run project test suite - must pass before task 4

### Task 4: Remove implicit globals at framework boundaries

**Files:**
- Create: `src/bot/contracts.py`
- Modify: `src/bot/handlers/message_handler.py`
- Modify: `src/bot/handlers/summary_handler.py`
- Modify: `src/bot/handlers/events_handler.py`
- Modify: `src/bot/services/reply_service.py`
- Modify: `src/bot/services/reaction_service.py`
- Modify: `src/bot/services/media_service.py`
- Modify: `tests/test_bot_message_handler.py`
- Modify: `tests/test_bot_reply_service.py`
- Modify: `tests/test_bot_events_handler.py`
- Modify: `tests/test_bot_summary_handler.py`
- Modify: `tests/test_bot_media_service.py`

- [x] Introduce explicit product contracts/protocols for settings, provider access, and message-store operations
- [x] Remove direct config lookups from reusable path code; pass dependencies through constructors
- [x] Ensure framework-side code has zero dependency on product config/provider modules
- [x] write tests for this task
- [x] run project test suite - must pass before task 5

### Task 5: Make breaking API cleanup explicit for extraction readiness

**Files:**
- Modify: `src/config.py`
- Modify: `src/model_provider.py`
- Modify: `src/provider_factory.py`
- Modify: `tests/test_provider_contracts.py`
- Modify: `tests/test_config_compat_contract.py`

- [ ] Remove legacy compatibility shims that encourage hidden coupling (module-level dynamic config attribute access, legacy provider convenience wrappers where no longer needed)
- [ ] Migrate internal call sites to explicit typed contracts/interfaces
- [ ] Keep only the runtime behavior contract and env parsing contract required for operation
- [ ] write tests for this task
- [ ] run project test suite - must pass before task 6

### Task 6: Verify acceptance criteria

- [ ] manual test: private chat flow (mention/reply, AI response, optional drafts)
- [ ] manual test: group chat flow (addressing rules, summary command behavior)
- [ ] manual test: event-photo flow when feature enabled
- [ ] run full test suite (`pytest -q`)
- [ ] run linter (`pylint src tests`)
- [ ] run type checks (`mypy src`)
- [ ] verify test coverage meets 80%+

### Task 7: Update documentation

- [ ] update `README.md` if user-facing behavior or architecture docs changed
- [ ] update `CLAUDE.md` if internal patterns changed
- [ ] move this plan to `docs/plans/completed/`
