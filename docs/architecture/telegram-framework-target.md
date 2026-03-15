# Telegram Framework Target Architecture

## Goal
Split the bot into two layers:

1. Telegram framework layer
2. Kabanus product layer

The framework layer should be extractable into a standalone repository with minimal changes.

## Layer Responsibilities

### Framework Layer (`src/telegram_framework/*`)
- Own Telegram runtime bootstrap and polling lifecycle.
- Own update routing primitives (command/message handler registration).
- Own access-policy hooks (allowed user/chat decisions).
- Own generic error reporting and admin-notification formatting.
- Own generic update logging context helpers.
- Depend only on telegram runtime primitives and explicit interfaces passed in from the product.

### Product Layer (`src/bot/*`, provider/calendar/memory/config modules)
- Own Kabanus-specific features and business behavior:
  - AI prompt building and response orchestration
  - Memory/history/summary behavior
  - Calendar event extraction and scheduling behavior
  - Feature flags and product configuration model
- Compose framework hooks with concrete product handlers/services.

## Dependency Rules
- Framework code must not import product modules.
- Product code may import framework modules.
- Cross-layer integration must happen through constructor-injected callables/protocols.
- No implicit module-level globals for cross-layer dependencies.

## Runtime Composition Target
- `src/main.py` should stay a thin startup entrypoint.
- Product composition should build:
  - product services/handlers
  - framework runtime/application
  - polling startup

## Extraction Readiness Criteria
- Framework package can be copied to another repo without product code.
- Framework tests pass with fake/injected product handlers.
- Product tests validate feature behavior independently of framework internals.

## Test Layer Guidance
- Framework-layer tests should continue using fake or injected product handlers.
- Product-level bot integration coverage should live in the hermetic e2e layer in `tests/test_bot_e2e.py`.
- That e2e layer composes `src.bot.app.build_runtime()` and `src.bot.app.build_application()`, dispatches synthetic Telegram `Update` objects through registered handlers, and fakes provider, calendar, and Telegram I/O.
- Persistence assertions in that layer should go through exported `src.message_store` APIs against temp-backed store paths. Live Telegram credentials and live external services do not belong in this test layer.
