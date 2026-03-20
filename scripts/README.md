# Scripts

Utility scripts for chat history export, summary backfill, and summary inspection.

## Setup

Run from repo root.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

Some scripts need env vars from your stack file:

```bash
set -a && source dev.stack.env && set +a
```

## `dump_chat.py`

Dump Telegram chat history to JSONL.

```bash
python3 -m scripts.dump_chat \
  --api-id <id> \
  --api-hash <hash> \
  --chat <chat_username_or_id> \
  --output <output.jsonl>
```

Output lines are JSON objects with `sender` and `text`.

## `backfill_summaries.py`

Create `*.summary.json` chunk summaries from chat JSONL history.

### Common usage

Backfill with Ollama:

```bash
MEMORY_SUMMARY_ENABLED=true PYTHONPATH=. python3 -m scripts.backfill_summaries \
  --chat-id=-{chat_id} \
  --source-jsonl src/data/messages_-{chat_id}.jsonl \
  --provider ollama \
  --ollama-url http://127.0.0.1:11434/api/generate \
  --ollama-model gemma3:12b
```

Backfill with cheapest Gemini model (from `GEMINI_MODELS`):

```bash
MEMORY_SUMMARY_ENABLED=true PYTHONPATH=. python3 -m scripts.backfill_summaries \
  --chat-id=-{chat_id} \
  --source-jsonl src/data/messages_-{chat_id}.jsonl \
  --provider gemini
```

Offline fallback (no model):

```bash
MEMORY_SUMMARY_ENABLED=true PYTHONPATH=. python3 -m scripts.backfill_summaries \
  --chat-id=-{chat_id} \
  --source-jsonl src/data/messages_-{chat_id}.jsonl \
  --no-model
```

### Useful flags

- `--force-rebuild`: recreate summary from scratch.
- `--max-chunks N`: process only first `N` pending chunks (good for experiments).
- `--parallel-workers N`: concurrent chunk requests.
- `--request-retries N`: retries per chunk request before fallback.
- `--retry-backoff-sec S`: linear backoff base between retries.

Ollama:

- `--ollama-url URL`
- `--ollama-model MODEL`
- `--ollama-num-thread N`
- `--ollama-timeout-sec S`

Preflight cost (Gemini mode):

- `--input-price-per-1m`
- `--output-price-per-1m`
- `--avg-output-tokens`

Benchmark mode:

```bash
MEMORY_SUMMARY_ENABLED=true PYTHONPATH=. python3 -m scripts.backfill_summaries \
  --chat-id=-{chat_id} \
  --source-jsonl src/data/messages_-{chat_id}.jsonl \
  --provider ollama \
  --ollama-model gemma3:4b \
  --benchmark-workers 1,2,4,8 \
  --benchmark-chunks 40 \
  --benchmark-only
```

## `view_summary.py`

Inspect summary JSON quickly.

```bash
PYTHONPATH=. python3 -m scripts.view_summary src/messages_-{chat_id}.summary.json --head 3
PYTHONPATH=. python3 -m scripts.view_summary src/messages_-{chat_id}.summary.json --tail 3
PYTHONPATH=. python3 -m scripts.view_summary src/messages_-{chat_id}.summary.json --index 42
PYTHONPATH=. python3 -m scripts.view_summary src/messages_-{chat_id}.summary.json --grep budget --head 10
```

## `onboard_openai.py`

Interactive wizard for OpenAI API key onboarding.

```bash
PYTHONPATH=. python3 -m scripts.onboard_openai
```

The wizard writes the auth file with private permissions and prints the OpenAI-side
runtime exports, including `OPENAI_TRANSCRIPTION_MODEL`. If you intentionally route
some capabilities to Gemini, add the matching `AI_PROVIDER_*` overrides plus
`GEMINI_API_KEY` or `GOOGLE_API_KEY`.

## `openai_codex_oauth.py`

OpenAI Codex OAuth login flow (OpenClaw-style) that writes/updates `auth.json`
for refresh-token based runtime auth.

Local callback mode (`http://localhost:1455/auth/callback`):

```bash
PYTHONPATH=. python3 -m scripts.openai_codex_oauth
```

Remote/VPS mode (open URL on local machine and paste redirect URL):

```bash
PYTHONPATH=. python3 -m scripts.openai_codex_oauth --remote
```

This helper also prints the OpenAI-side runtime exports. Mixed-provider routing is still
configured through the main environment, so add any Gemini-specific `AI_PROVIDER_*`
overrides and credentials separately when that routing is intentional.

## Notes

- `backfill_summaries.py` writes summary state once per run, not per chunk.
- If you change summarization logic, rerun with `--force-rebuild`.
- Existing files in `scripts/` ending with `.session` are local session artifacts; keep private.
