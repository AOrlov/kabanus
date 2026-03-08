Refactor Plan: Simplify Architecture and Remove Dead Code (Config-
  Compatible)

  ## Overview

  Refactor the runtime, memory, and provider layers to reduce duplication and
  file bloat, remove unused methods, and improve readability/maintainability.
  Keep current configuration compatibility (same env vars/defaults/validation
  behavior), while allowing internal/public Python API changes where they
  simplify the system.

  ## Context

  • Files involved:
    • Runtime/wiring: src/main.py, src/bot/app.py, src/bot/handlers/.py,
    src/bot/services/.py
    • Config/settings: src/config.py, src/settings_loader.py,
    src/settings_models.py, tests/test_config_*.py, tests/test_settings_loader.
    py
    • Memory/store: src/message_store.py, src/memory/history_store.py,
    src/memory/context_builder.py, src/memory/summary_store.py,
    tests/test_message_store.py, tests/test_memory_*.py
    • Provider layer: src/model_provider.py, src/provider_factory.py,
    src/providers/contracts.py, src/openai_provider.py, src/gemini_provider.py,
    src/openai_auth.py, tests/test_provider_*.py, tests/test_openai_provider.
    py, tests/test_gemini_provider.py
    • Integration contracts: tests/test_main*.py, tests/test_bot_*.py
    • Docs: README.md, docs/architecture/refactor-overview.md
  • Related patterns:
    • Dependency injection already exists via build_runtime(...) in
    src/bot/app.py.
    • Compatibility facades currently exist in src/config.py and
    src/message_store.py.
    • Large modules with mixed concerns still exist (notably src/main.py,
    src/memory/summary_store.py, provider modules).
  • Dependencies:
    • No new runtime dependencies required.
    • Optional dev-only dead-code tooling may be added if needed for safer
    removal workflow.


  ## Development Approach

  • Testing approach: Regular (code first, then tests), with characterization
  tests first for risky behavior.
  • Complete each task fully before moving to the next.
  • Preserve only configuration compatibility contract (env var
  names/defaults/validation), as requested.
  • API cleanup is allowed where it reduces complexity.
  • CRITICAL: every task MUST include new/updated tests.
  • CRITICAL: all tests must pass before starting next task.

  ## Implementation Steps

  ### Task 1: Define and lock the compatibility baseline

  Files:

  • Modify: tests/test_config_compat_contract.py
  • Modify: tests/test_settings_loader.py
  • Modify: tests/test_main_flow_contracts.py
  • Modify: tests/test_provider_contracts.py
  • Modify: tests/test_message_store.py
  [x] Add/adjust characterization tests for the required non-negotiable
  contract: configuration compatibility only.
  [x] Explicitly mark legacy API tests that are no longer required (or rewrite
  them to new intended behavior).
  [x] Add a short contract note in tests describing what must remain stable vs
  what may change.
  [x] Run project tests for this scope before Task 2.

  ### Task 2: Collapse duplicate runtime wiring and shrink entrypoint

  Files:

  • Modify: src/main.py
  • Modify: src/bot/app.py
  • Modify: tests/test_main.py
  • Modify: tests/test_bot_app.py
  [x] Make src/bot/app.py the single runtime composition location.
  [x] Reduce src/main.py to a thin entrypoint (startup/logging/run), removing
  duplicated handler/service wrappers.
  [x] Remove duplicated reaction/runtime globals that are now owned by
  service/runtime objects.
  [x] Update runtime tests to validate behavior through one path.
  [x] Run project tests for runtime/bot modules before Task 3.

  ### Task 3: Simplify settings/config internals while preserving config
  behavior

  Files:

  • Modify: src/config.py
  • Modify: src/settings_loader.py
  • Modify: src/settings_models.py
  • Modify: tests/test_config_compat_contract.py
  • Modify: tests/test_config_openai.py
  • Modify: tests/test_settings_loader.py
  [x] Remove cache-state duplication between facade and loader by establishing
  one source of truth.
  [x] Keep env var names, defaults, parsing, and validation semantics
  unchanged.
  [x] Replace brittle/manual compatibility mapping with a clearer, tested
  mapping mechanism.
  [x] Keep only configuration-facing compatibility guarantees; remove
  unnecessary legacy-only internals.
  [x] Run config/settings tests before Task 4.

  ### Task 4: Replace overgrown message facade with explicit memory APIs

  Files:

  • Modify: src/message_store.py
  • Modify: src/memory/history_store.py
  • Modify: src/memory/context_builder.py
  • Modify: src/memory/summary_store.py
  • Modify: tests/test_message_store.py
  • Modify: tests/test_memory_history_store.py
  • Modify: tests/test_memory_context_builder.py
  • Modify: tests/test_memory_summary_store.py
  [x] Stop re-exporting private memory internals through src/message_store.py.
  [x] Define a small explicit public memory API and move helper-only internals
  behind module boundaries.
  [x] Break large summary logic into smaller pure helpers where complexity is
  highest.
  [x] Remove dead/unused memory helpers after usage verification.
  [x] Run memory/message-store tests before Task 5.

  ### Task 5: Unify provider contracts and remove dead provider code

  Files:

  • Modify: src/model_provider.py
  • Modify: src/providers/contracts.py
  • Modify: src/provider_factory.py
  • Modify: src/openai_provider.py
  • Modify: src/gemini_provider.py
  • Modify: src/openai_auth.py
  • Modify: tests/test_provider_contracts.py
  • Modify: tests/test_provider_factory.py
  • Modify: tests/test_openai_provider.py
  • Modify: tests/test_gemini_provider.py
  [x] Choose one primary provider interface style (typed-first) and reduce
  adapter indirection.
  [x] Remove truly unused provider methods (for example currently unreferenced
  helpers) only after test-backed confirmation.
  [x] Keep routing/fallback semantics intact where they are still required for
  behavior.
  [x] Consolidate duplicated response/request handling logic in provider
  implementations.
  [x] Run provider tests before Task 6.

  ### Task 6: Repository-wide dead code sweep and readability cleanup

  Files:

  • Modify: src/**/*.py (targeted)
  • Modify: tests/**/*.py (targeted)
  • Optional create/modify: scripts/* (dead-code audit helper), requirements-
  dev.txt (if tooling is added)
  [x] Run dead-code/unused-symbol analysis and produce a reviewed deletion
  list.
  [x] Remove unused methods/imports/constants across runtime, memory, and
  provider modules.
  [x] Enforce simpler module boundaries and naming consistency (no hidden
  cross-module private calls).
  [x] Add or update tests for each deletion that could affect behavior.
  [x] Run full project tests and static checks before Task 7.

  ### Task 7: Verify acceptance criteria and update documentation

  Files:

  • Modify: README.md
  • Modify: docs/architecture/refactor-overview.md
  • Move: docs/plans/.md -> docs/plans/completed/
  [x] Manual verification: bot still starts with python -m src.main and honors
  existing env configuration.
  [x] Manual verification: message handling, summary command, and provider
  fallback still work with new structure.
  [x] Run full test suite (pytest -q).
  [x] Run linter/type checks (pylint src tests, mypy src).
  [x] Verify test coverage is at least 80%.
  [x] Update docs to reflect new architecture and removed legacy APIs.
  [x] Move the completed plan file to docs/plans/completed/.
