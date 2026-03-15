---
# Plan: Add Hermetic End-to-End Bot Tests

## Overview
Add a hermetic pytest e2e layer that exercises the composed bot runtime with synthetic Telegram updates, fake providers, temp-backed message storage, and fake Telegram I/O. The goal is to verify a few critical user journeys across runtime composition, handler registration, persistence, and reply side effects without requiring a real Telegram bot token or live AI/calendar services.

## Context
- Files involved: `src/bot/app.py`, `src/telegram_framework/application.py`, `src/bot/features/message_flow.py`, `src/bot/features/summary.py`, `src/bot/features/events.py`, `src/message_store.py`, `tests/test_bot_app.py`, `tests/test_bot_feature_registration.py`, `tests/test_message_store.py`, `tests/test_bot_e2e.py`
- Related patterns: runtime composition in `src/bot/app.build_runtime()` and `src/bot/app.build_application()`, current test style using `SimpleNamespace`/`monkeypatch`/`tmp_path`, temp-path persistence patterns in `tests/test_message_store.py`
- Dependencies: existing `pytest` plus current `asyncio.run` test style, fake provider doubles, fake Telegram I/O, temp-backed storage, no live Telegram/API dependencies

## Development Approach
- Testing approach: Regular (build the harness first, then add scenario coverage)
- Complete each task fully before moving to the next
- Define e2e narrowly as real runtime composition plus real handler registration plus synthetic updates plus fake external I/O
- Prefer the smallest reusable harness that still exercises registered PTB handler objects; do not invent a second bot architecture just for tests
- Keep the scenario set representative rather than exhaustive; unit tests should continue owning edge-case combinatorics
- CRITICAL: every task MUST include new/updated tests
- CRITICAL: all tests must pass before starting the next task

## Implementation Steps

### Task 1: Build a Minimal Hermetic E2E Harness

**Files:**
- Modify: `src/bot/app.py` (only if a tiny test seam is needed for deterministic application dispatch)
- Modify: `src/telegram_framework/application.py` (only if app construction needs a narrow injection point)
- Modify: `tests/test_bot_app.py`
- Create: `tests/test_bot_e2e.py`

- [x] Define a single test harness in `tests/test_bot_e2e.py` that composes the real runtime with fake providers, fake Telegram bot/context methods, and temp-backed settings
- [x] Reuse `build_runtime()` and `build_application()` so the e2e layer covers composition and handler registration, not just direct handler calls
- [x] Dispatch synthetic command/message/photo updates through registered handlers using the smallest stable mechanism available
- [x] If current seams are insufficient, add only the narrowest application-builder or dispatch hook required to keep the tests hermetic
- [x] Write harness smoke tests proving one registered handler can be driven end-to-end
- [x] Run `pytest -q tests/test_bot_app.py tests/test_bot_e2e.py` and keep it green before adding more scenarios

### Task 2: Cover Command and Conversation Happy Paths

**Files:**
- Modify: `tests/test_bot_e2e.py`
- Modify: `tests/test_message_store.py` (only if a missing test helper or pattern needs to be codified)

- [x] Add a `/hi` or `/summary` command scenario that proves command routing, callback execution, and reply capture work through the composed application
- [x] Add a group-text addressed-message scenario that proves mention detection, context assembly, provider invocation, reply sending, and message persistence all happen in one flow
- [x] Verify stored history and reply outputs with the real `message_store` API against a temporary store path instead of ad hoc in-memory assertions
- [x] Keep provider doubles behavior-focused: one fake for generated text, one fake for low-cost text, no routing cross-product explosion
- [x] Write tests for this task
- [x] Run `pytest -q tests/test_bot_e2e.py tests/test_message_store.py` and keep it green before moving on

### Task 3: Cover Media and Event Scheduling Flows

**Files:**
- Modify: `tests/test_bot_e2e.py`
- Modify: `tests/test_bot_events_handler.py` (only if an existing helper can be reused or tightened)

- [x] Add one media-based conversation scenario, choosing the highest-value path among voice, photo OCR, or image document, and drive it through the same composed harness
- [x] Add one event-scheduling photo scenario that uses a fake event parser and fake calendar provider and verifies both the success reply and created event payload
- [x] Verify Telegram file-download interactions stay fake and temp-file cleanup remains observable in the hermetic test path
- [x] Resist adding all media permutations to e2e; leave detailed branch coverage in the existing handler or service tests
- [x] Write tests for this task
- [x] Run `pytest -q tests/test_bot_e2e.py tests/test_bot_events_handler.py` and keep it green before moving on

### Task 4: Add High-Value Negative and Gating Scenarios

**Files:**
- Modify: `tests/test_bot_e2e.py`

- [x] Add one disallowed-chat or disabled-feature scenario that verifies the composed app produces no reply and no persistence side effects
- [x] Add one failure-path scenario for event parsing or downstream provider failure that verifies the user-facing fallback and admin notification path
- [x] Add one command-parse or malformed-update scenario only if it exercises cross-component behavior not already owned by unit tests
- [x] Keep negative-path coverage focused on regressions that could break production behavior across module boundaries
- [x] Write tests for this task
- [x] Run `pytest -q tests/test_bot_e2e.py` and keep it green before moving on

### Task 5: Verify Acceptance Criteria

- [x] Manual test: inspect the e2e suite and confirm every scenario uses synthetic Telegram updates plus fake external services only
- [x] Run full test suite with `pytest -q`
- [x] Run linter with `pylint src tests`
- [x] Verify the new e2e tests cover runtime composition, handler registration, persistence, and at least one non-text path without live network calls
- [x] Verify test coverage meets 80%+

### Task 6: Update Documentation

- [x] Update `README.md` only if contributor test workflow or recommended commands changed
- [x] Update `CLAUDE.md` if internal test-layer guidance or workflow expectations changed
- [x] Update any internal contributor notes if the repo documents test-layer boundaries elsewhere
- [x] Move this plan to `docs/plans/completed/` after the work lands
---
