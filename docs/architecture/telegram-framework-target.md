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
