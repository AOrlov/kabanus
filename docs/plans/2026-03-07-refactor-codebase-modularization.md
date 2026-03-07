---
# Refactor Kabanus Into Modular, Maintainable Architecture (Config-Compatible)

## Overview
Refactor the codebase to reduce complexity and improve maintainability by splitting large modules into focused components, introducing clearer boundaries, and tightening tests. Keep current configuration fully backward compatible (same environment variables, defaults, and behavior), while allowing internal and product API reshaping where it improves design.

## Context
- Files involved:
  - src/main.py
  - src/message_store.py
  - src/config.py
  - src/provider_factory.py
  - src/model_provider.py
  - src/openai_provider.py
  - src/gemini_provider.py
  - src/calendar_provider.py
  - src/telegram_drafts.py
  - tests/test_main.py
  - tests/test_message_store.py
  - tests/test_config_openai.py
  - tests/test_provider_factory.py
  - tests/test_openai_provider.py
  - tests/test_gemini_provider.py
- Related patterns:
  - Existing Settings dataclass and get_settings cache pattern in src/config.py
  - Existing provider abstraction via ModelProvider and RoutedModelProvider
  - Existing unit-test style with monkeypatch and SimpleNamespace fakes
- Dependencies:
  - Existing runtime stack only (python-telegram-bot, openai, google-genai, google-api-python-client)
  - No new external dependencies for the refactor unless strictly required and justified in-task

## Development Approach
- Testing approach: Regular (code first, then tests), with characterization tests added first as a safety net
- Complete each task fully before moving to the next
- Keep migration incremental; avoid a big-bang rewrite
- Preserve compatibility via facades at current module entry points while internals are extracted
- CRITICAL: every task MUST include new/updated tests
- CRITICAL: all tests must pass before starting next task

## Implementation Steps

### Task 1: Build a Refactor Safety Net (Characterization Tests)

**Files:**
- Modify: `tests/test_main.py`
- Modify: `tests/test_message_store.py`
- Modify: `tests/test_config_openai.py`
- Modify: `tests/test_provider_factory.py`
- Create: `tests/test_main_flow_contracts.py`
- Create: `tests/test_config_compat_contract.py`

- [x] Add characterization tests for current externally observable behavior (message handling trigger matrix, summary command parsing forms, drafts fallback behavior, reaction gating, and context limits)
- [x] Add config compatibility contract tests that lock current env var names/defaults and module-level config attribute access behavior
- [x] Add tests that validate old callers of message_store and provider factory still behave identically
- [x] Run `pytest -q` and fix regressions before task 2

### Task 2: Isolate Configuration Parsing and Keep Legacy Compatibility Surface

**Files:**
- Modify: `src/config.py`
- Create: `src/settings_models.py`
- Create: `src/settings_loader.py`
- Create: `tests/test_settings_loader.py`

- [x] Move parsing, validation, and cache internals out of `src/config.py` into focused loader/model modules
- [x] Keep `src/config.py` as compatibility facade exposing `Settings`, `ModelSpec`, `get_settings(force=...)`, and legacy module attribute mapping (`__getattr__`)
- [x] Preserve all existing env var names, defaults, and validation rules
- [x] Write tests comparing legacy config behavior before/after extraction
- [x] Run `pytest -q` and fix regressions before task 3

### Task 3: Split Message Store Into Focused Components With Compatibility Wrappers

**Files:**
- Modify: `src/message_store.py`
- Create: `src/memory/history_store.py`
- Create: `src/memory/summary_store.py`
- Create: `src/memory/context_builder.py`
- Create: `tests/test_memory_history_store.py`
- Create: `tests/test_memory_summary_store.py`
- Create: `tests/test_memory_context_builder.py`

- [x] Extract JSONL history persistence and retrieval into `history_store`
- [x] Extract summary state I/O and chunk rollup logic into `summary_store`
- [x] Extract prompt context assembly logic into `context_builder`
- [x] Keep `src/message_store.py` as a backward-compatible facade delegating to new modules
- [x] Add targeted tests per module plus compatibility tests for existing `message_store` API
- [x] Run `pytest -q` and fix regressions before task 4

### Task 4: Decompose main.py Into Telegram Handlers and Application Services

**Files:**
- Modify: `src/main.py`
- Create: `src/bot/app.py`
- Create: `src/bot/handlers/message_handler.py`
- Create: `src/bot/handlers/summary_handler.py`
- Create: `src/bot/handlers/events_handler.py`
- Create: `src/bot/handlers/common.py`
- Create: `src/bot/services/reaction_service.py`
- Create: `src/bot/services/reply_service.py`
- Create: `src/bot/services/media_service.py`
- Create: `tests/test_bot_message_handler.py`
- Create: `tests/test_bot_summary_handler.py`
- Create: `tests/test_bot_events_handler.py`
- Create: `tests/test_bot_reply_service.py`

- [x] Move mixed concerns from `main.py` into focused handler and service modules
- [x] Replace global mutable runtime state with explicit service state objects where needed
- [x] Keep `python -m src.main` as runtime entrypoint, delegating to bot app bootstrap module
- [x] Preserve current user-visible behavior unless a deliberate API change is documented
- [x] Add handler/service unit tests and one app-wiring smoke test
- [x] Run `pytest -q` and fix regressions before task 5

### Task 5: Simplify Provider Layer Boundaries and Wiring

**Files:**
- Modify: `src/model_provider.py`
- Modify: `src/provider_factory.py`
- Modify: `src/openai_provider.py`
- Modify: `src/gemini_provider.py`
- Create: `src/providers/contracts.py`
- Create: `tests/test_provider_contracts.py`

- [x] Define a clearer provider contract surface (typed inputs/outputs where practical)
- [x] Keep fallback routing behavior equivalent to current `RoutedModelProvider` semantics
- [x] Remove duplicated operation scaffolding where possible without changing behavior
- [x] Ensure provider factory composition remains deterministic and testable
- [x] Add or expand tests for routing, fallback, streaming, and reaction context propagation
- [x] Run `pytest -q` and fix regressions before task 6

### Task 6: Verify acceptance criteria

- [ ] Manual test: run the bot locally and verify key flows (standard text reply, voice/image extraction path, summary command, optional schedule events)
- [ ] run full test suite (`pytest -q`)
- [ ] run linter (`pylint src tests`)
- [ ] run type checks (`mypy src`)
- [ ] verify test coverage meets 80%+ (`coverage run -m pytest -q && coverage report --fail-under=80`)

### Task 7: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` (if internal architecture conventions are updated)
- Create: `docs/architecture/refactor-overview.md`

- [ ] update README.md if user-facing changes
- [ ] update CLAUDE.md if internal patterns changed
- [ ] document new module boundaries and extension points
- [ ] document config backward compatibility guarantees explicitly
- [ ] document intentional API changes and migration notes
- [ ] move this plan to `docs/plans/completed/`
