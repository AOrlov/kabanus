---
# Add OpenAI Support to All Bot Capabilities

## Overview
Implement OpenAI audio transcription so every shipped bot capability can run on OpenAI, including both existing OpenAI auth modes: `OPENAI_API_KEY` and `OPENAI_AUTH_JSON_PATH`. The change should remove the current contract mismatch where `MODEL_PROVIDER=openai` already routes `audio_transcription` to OpenAI by default, but runtime validation, onboarding helpers, and documentation still treat that route as unsupported.

## Context
- Files involved: `src/providers/openai/provider.py`, `src/providers/openai/client.py`, `src/provider_factory.py`, `src/settings_models.py`, `src/settings_loader.py`, `scripts/onboard_openai.py`, `scripts/openai_codex_oauth.py`, `README.md`, `docs/architecture/refactor-overview.md`, `scripts/README.md`
- Related tests: `tests/test_openai_provider.py`, `tests/test_provider_factory.py`, `tests/test_provider_acceptance.py`, `tests/test_settings_loader.py`, `tests/test_config_openai.py`, `tests/test_config_compat_contract.py`, `tests/test_onboard_openai.py`, `tests/test_openai_codex_oauth.py`
- Related patterns: capability routing and fail-fast validation in `src/provider_factory.py`, OpenAI auth-mode branching in `src/providers/openai/client.py`, typed provider errors in `src/providers/errors.py`, onboarding export printers in the OpenAI helper scripts
- Dependencies: existing `openai` SDK in `requirements.txt`, plus official OpenAI speech-to-text docs and API reference for the current transcription endpoint/model surface: https://platform.openai.com/docs/guides/speech-to-text and https://platform.openai.com/docs/api-reference/audio/createTranscription

## Development Approach
- Testing approach: TDD (lock the missing OpenAI transcription behavior before changing routing and onboarding contracts)
- Complete each task fully before moving to the next
- Keep the existing `AudioTranscriptionRequest(audio_path)` contract unless the OpenAI API proves it insufficient
- Reuse the current OpenAI auth/client abstractions; do not introduce a second provider or a Gemini fallback for transcription
- Add only the minimum new OpenAI config needed for speech-to-text, because transcription models are a different model family than the existing Codex/text defaults
- CRITICAL: every task MUST include new/updated tests
- CRITICAL: all tests must pass before starting next task

## Implementation Steps

### Task 1: Implement OpenAI Audio Transcription in the Provider Stack

**Files:**
- Modify: `src/providers/openai/provider.py`
- Modify: `src/providers/openai/client.py`
- Modify: `src/providers/openai/__init__.py` if exported client/provider helpers change
- Modify: `requirements.txt` if the repo needs a pinned/updated `openai` SDK version for `audio.transcriptions`
- Modify: `tests/test_openai_provider.py`

- [x] Add `OpenAIProvider.transcribe_audio()` using the OpenAI audio transcription API while preserving the current `AudioTranscriptionRequest(audio_path)` contract
- [x] Extend `OpenAIClientFactory` so transcription can obtain a standard API client context in both auth modes instead of always forcing Codex `/codex` routing and headers
- [x] Keep auth refresh and typed error mapping consistent with the rest of the OpenAI provider surface for auth, quota, and configuration failures
- [x] Cover both `OPENAI_API_KEY` and `OPENAI_AUTH_JSON_PATH` transcription paths in provider tests, including failure and retry/refresh behavior
- [x] write tests for this task
- [x] run project test suite - must pass before task 2

### Task 2: Align Settings and Routing with Full OpenAI Capability Support

**Files:**
- Modify: `src/settings_models.py`
- Modify: `src/settings_loader.py`
- Modify: `src/provider_factory.py`
- Modify: `tests/test_provider_factory.py`
- Modify: `tests/test_provider_acceptance.py`
- Modify: `tests/test_settings_loader.py`
- Modify: `tests/test_config_openai.py`
- Modify: `tests/test_config_compat_contract.py`

- [x] Add a dedicated `OPENAI_TRANSCRIPTION_MODEL` setting with an OpenAI speech-to-text-capable default rather than reusing the existing Codex/text model fields
- [x] Update the OpenAI supported-capability matrix so `audio_transcription=openai` is a valid routed combination and startup validation no longer contradicts the current default `MODEL_PROVIDER=openai` routing
- [x] Preserve fail-fast validation for truly invalid cases such as missing OpenAI credentials, malformed auth files, or auth modes that cannot initialize a transcription-capable client
- [x] Extend acceptance coverage to a pure-OpenAI provider composition that exercises text, streaming, low-cost text, transcription, OCR, reaction selection, and event parsing together
- [x] write tests for this task
- [x] run project test suite - must pass before task 3

### Task 3: Update OpenAI Onboarding and Auth Tooling

**Files:**
- Modify: `scripts/onboard_openai.py`
- Modify: `scripts/openai_codex_oauth.py`
- Modify: `tests/test_onboard_openai.py`
- Modify: `tests/test_openai_codex_oauth.py`

- [ ] Update the API-key onboarding wizard to collect or emit `OPENAI_TRANSCRIPTION_MODEL` and stop printing the hard-coded Gemini transcription override
- [ ] Update the Codex OAuth helper exports so `OPENAI_AUTH_JSON_PATH` users can configure a full-OpenAI deployment without separate Gemini instructions
- [ ] Keep both scripts secret-safe: no API keys or refresh tokens in printed output, and no regression in private-file handling
- [ ] Add regression tests that both onboarding flows now describe full OpenAI support rather than mixed-provider-only support
- [ ] write tests for this task
- [ ] run project test suite - must pass before task 4

### Task 4: Verify Acceptance Criteria

- [ ] manual test: with only `OPENAI_API_KEY` configured, run the bot through a text reply, streamed draft reply, voice transcription, OCR/photo message, reaction selection, and event image parse flow
- [ ] manual test: with only `OPENAI_AUTH_JSON_PATH` configured, run the same flows and verify transcription still works after a forced token refresh
- [ ] run full test suite (`pytest -q`)
- [ ] run linter (`pylint src tests`)
- [ ] run type checks (`mypy src`)
- [ ] verify test coverage meets 80%+

### Task 5: Update Documentation

- [ ] update `README.md` support matrix, example env blocks, onboarding text, and OpenAI model guidance to reflect full OpenAI capability support
- [ ] update `docs/architecture/refactor-overview.md` and `scripts/README.md` so they no longer describe Gemini as mandatory for audio transcription
- [ ] update `CLAUDE.md` only if internal contributor guidance about provider/auth setup changes materially
- [ ] move this plan to `docs/plans/completed/`
---
