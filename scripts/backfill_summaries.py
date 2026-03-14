import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, List

from src import config
from src.message_store import estimate_token_count, maybe_rollup_summary
from src.providers.contracts import TextGenerationRequest


def load_messages(path: str) -> List[Dict]:
    messages: List[Dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                messages.append(item)
    return messages


def summary_store_path(chat_id: str) -> str:
    settings = config.get_settings()
    configured = settings.chat_messages_store_path
    if os.path.isabs(configured):
        base_path = configured
    else:
        base_path = os.path.join(os.path.dirname(config.__file__), configured)
    root, ext = os.path.splitext(base_path)
    if ext:
        base_dir = os.path.dirname(base_path) or "."
        stem = os.path.basename(root) or "messages"
    else:
        base_dir = base_path
        stem = "messages"
    msg_path = os.path.join(base_dir, f"{stem}_{str(chat_id).strip()}.jsonl")
    if msg_path.endswith(".jsonl"):
        return msg_path[:-6] + ".summary.json"
    return msg_path + ".summary.json"


def load_last_processed_count(chat_id: str) -> int:
    path = summary_store_path(chat_id)
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return 0
    count = state.get("last_message_count", 0)
    if isinstance(count, int) and count >= 0:
        return count
    return 0


def estimate_input_tokens(messages: List[Dict], start: int, chunk_size: int) -> int:
    total = 0
    end = start + ((len(messages) - start) // chunk_size) * chunk_size
    for offset in range(start, end, chunk_size):
        chunk = messages[offset : offset + chunk_size]
        dialogue = "\n".join(
            f"{msg.get('sender', 'Unknown')}: {msg.get('text', '')}" for msg in chunk
        )
        prompt = (
            "Summarize this chat dialogue chunk. Return JSON only, no markdown.\n"
            "Schema:\n"
            "{\n"
            '  "summary": string,\n'
            '  "facts": string[],\n'
            '  "decisions": string[],\n'
            '  "open_items": string[]\n'
            "}\n"
            "Rules:\n"
            "- Keep summary under 80 words.\n"
            "- facts: durable preferences/profile/context facts only.\n"
            "- decisions: concrete choices made.\n"
            "- open_items: unresolved asks/tasks/questions.\n"
            "- If unknown, return empty arrays.\n\n"
            "Dialogue:\n"
            f"{dialogue}"
        )
        total += estimate_token_count(prompt)
    return total


def make_ollama_summarize_fn(
    ollama_url: str,
    ollama_model: str,
    timeout_sec: int,
    ollama_num_thread: int,
):
    def summarize(prompt: str) -> str:
        options = {
            "temperature": 0.1,
        }
        if ollama_num_thread > 0:
            options["num_thread"] = ollama_num_thread
        payload = {
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        req = urllib.request.Request(
            ollama_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return str(parsed.get("response", ""))
        return ""

    return summarize


def check_ollama_ready(ollama_url: str, timeout_sec: int) -> None:
    # /api/generate -> /api/tags for a lightweight health probe.
    if ollama_url.endswith("/api/generate"):
        tags_url = ollama_url[: -len("/api/generate")] + "/api/tags"
    else:
        tags_url = ollama_url.rstrip("/") + "/api/tags"
    req = urllib.request.Request(tags_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"Ollama health check failed with status {resp.status}"
                )
            body = resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama health check failed: {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama health check returned invalid JSON") from exc
    if not isinstance(parsed, dict) or "models" not in parsed:
        raise RuntimeError("Ollama health check response missing 'models'")


def print_progress(done: int, total: int, width: int = 30) -> None:
    if total <= 0:
        return
    clamped_done = min(max(done, 0), total)
    ratio = clamped_done / total
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r[{bar}] {clamped_done}/{total} ({ratio * 100:5.1f}%)")
    sys.stdout.flush()


def parse_workers(value: str) -> List[int]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    workers = []
    for part in parts:
        workers.append(max(1, int(part)))
    if not workers:
        raise ValueError("benchmark_workers must contain at least one integer")
    return workers


def make_retrying_summarize_fn(
    summarize_fn,
    request_retries: int,
    retry_backoff_sec: float,
):
    attempts = max(1, request_retries)
    backoff = max(0.0, retry_backoff_sec)

    def summarize(prompt: str) -> str:
        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                return summarize_fn(prompt)
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                sleep_for = backoff * attempt if backoff > 0 else 0.0
                if sleep_for > 0:
                    time.sleep(sleep_for)
        if last_exc is not None:
            raise last_exc
        return ""

    return summarize


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill chunk summaries from existing JSONL history."
    )
    parser.add_argument(
        "--chat-id", required=True, help="Chat id used for the summary state filename."
    )
    parser.add_argument(
        "--source-jsonl", required=True, help="Path to history JSONL file."
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Use placeholder summaries (no Gemini API call).",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Rebuild summary file from scratch.",
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "ollama", "none"],
        default=os.getenv("SUMMARY_PROVIDER", "gemini"),
        help="Summarization provider (ignored when --no-model is used).",
    )
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        help="Ollama generate endpoint URL.",
    )
    parser.add_argument(
        "--ollama-model",
        default=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        help="Local Ollama model name.",
    )
    parser.add_argument(
        "--ollama-timeout-sec",
        type=int,
        default=int(os.getenv("OLLAMA_TIMEOUT_SEC", "120")),
        help="Timeout for each Ollama request in seconds.",
    )
    parser.add_argument(
        "--ollama-num-thread",
        type=int,
        default=int(os.getenv("OLLAMA_NUM_THREAD", "0")),
        help="Thread count hint for Ollama (0 keeps Ollama default).",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=int(os.getenv("SUMMARY_PARALLEL_WORKERS", "1")),
        help="Number of chunk summarization workers.",
    )
    parser.add_argument(
        "--input-price-per-1m",
        type=float,
        default=float(os.getenv("SUMMARY_INPUT_PRICE_PER_1M", "0")),
        help="Estimated input token price in USD per 1M tokens.",
    )
    parser.add_argument(
        "--output-price-per-1m",
        type=float,
        default=float(os.getenv("SUMMARY_OUTPUT_PRICE_PER_1M", "0")),
        help="Estimated output token price in USD per 1M tokens.",
    )
    parser.add_argument(
        "--avg-output-tokens",
        type=int,
        default=int(os.getenv("SUMMARY_AVG_OUTPUT_TOKENS", "90")),
        help="Assumed average output tokens per chunk for cost estimation.",
    )
    parser.add_argument(
        "--benchmark-workers",
        default=os.getenv("SUMMARY_BENCHMARK_WORKERS", ""),
        help="Comma-separated worker counts for throughput benchmark (e.g. 1,2,4,8).",
    )
    parser.add_argument(
        "--benchmark-chunks",
        type=int,
        default=int(os.getenv("SUMMARY_BENCHMARK_CHUNKS", "32")),
        help="Number of chunks to process in each benchmark trial.",
    )
    parser.add_argument(
        "--benchmark-only",
        action="store_true",
        help="Run benchmark and exit without full backfill.",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=0,
        help="Process at most N chunks in this run (0 means all pending chunks).",
    )
    parser.add_argument(
        "--request-retries",
        type=int,
        default=int(os.getenv("SUMMARY_REQUEST_RETRIES", "3")),
        help="Retry attempts per chunk request before fallback.",
    )
    parser.add_argument(
        "--retry-backoff-sec",
        type=float,
        default=float(os.getenv("SUMMARY_RETRY_BACKOFF_SEC", "1.0")),
        help="Linear backoff base in seconds between retries.",
    )
    args = parser.parse_args()

    settings = config.get_settings()
    if not settings.memory_summary_enabled:
        raise RuntimeError("MEMORY_SUMMARY_ENABLED must be true to backfill summaries.")

    messages = load_messages(args.source_jsonl)
    if not messages:
        print("No messages loaded; nothing to summarize.")
        return

    chunk_size = settings.memory_summary_chunk_size
    processed = (
        0
        if args.force_rebuild
        else min(load_last_processed_count(args.chat_id), len(messages))
    )
    pending_messages = max(0, len(messages) - processed)
    pending_chunks = pending_messages // chunk_size

    print("Backfill preflight:")
    print(f"- source: {args.source_jsonl}")
    print(f"- chat_id: {args.chat_id}")
    print(f"- total_messages: {len(messages)}")
    print(f"- already_processed_messages: {processed}")
    print(f"- chunk_size: {chunk_size}")
    print(f"- chunks_to_process: {pending_chunks}")
    if args.max_chunks > 0:
        print(f"- max_chunks_limit: {args.max_chunks}")
    print(f"- parallel_workers: {max(1, args.parallel_workers)}")
    print(f"- request_retries: {max(1, args.request_retries)}")
    print(f"- retry_backoff_sec: {max(0.0, args.retry_backoff_sec)}")

    provider_name = "none" if args.no_model else args.provider
    print(f"- provider: {provider_name}")

    if provider_name == "gemini":
        in_tokens = estimate_input_tokens(
            messages, start=processed, chunk_size=chunk_size
        )
        out_tokens = max(0, args.avg_output_tokens) * pending_chunks
        input_cost = (in_tokens / 1_000_000.0) * max(0.0, args.input_price_per_1m)
        output_cost = (out_tokens / 1_000_000.0) * max(0.0, args.output_price_per_1m)
        print(f"- estimated_input_tokens: {in_tokens}")
        print(f"- estimated_output_tokens: {out_tokens}")
        print(f"- input_price_per_1m_usd: {args.input_price_per_1m}")
        print(f"- output_price_per_1m_usd: {args.output_price_per_1m}")
        print(f"- estimated_cost_usd: {input_cost + output_cost:.6f}")
    elif provider_name == "ollama":
        print(f"- ollama_url: {args.ollama_url}")
        print(f"- ollama_model: {args.ollama_model}")
        print(f"- ollama_num_thread: {max(0, args.ollama_num_thread)}")
        print("- estimated_cost_usd: local (not estimated)")
    else:
        print("- model_mode: disabled (--no-model), estimated_cost_usd: 0")

    summarize_fn = None
    if provider_name == "gemini":
        from src.providers.gemini import GeminiProvider

        provider = GeminiProvider(config.get_settings())
        summarize_fn = lambda prompt: provider.generate_low_cost_text(
            TextGenerationRequest(prompt=prompt)
        )
    elif provider_name == "ollama":
        check_ollama_ready(
            ollama_url=args.ollama_url,
            timeout_sec=max(1, args.ollama_timeout_sec),
        )
        print("Ollama health check: OK")
        summarize_fn = make_ollama_summarize_fn(
            ollama_url=args.ollama_url,
            ollama_model=args.ollama_model,
            timeout_sec=max(1, args.ollama_timeout_sec),
            ollama_num_thread=max(0, args.ollama_num_thread),
        )
    if summarize_fn is not None:
        summarize_fn = make_retrying_summarize_fn(
            summarize_fn=summarize_fn,
            request_retries=max(1, args.request_retries),
            retry_backoff_sec=max(0.0, args.retry_backoff_sec),
        )

    benchmark_workers: List[int] = []
    if args.benchmark_workers:
        benchmark_workers = parse_workers(args.benchmark_workers)
        if summarize_fn is None:
            raise RuntimeError(
                "Benchmark requires a model provider (not --no-model/provider none)."
            )
        if pending_chunks <= 0:
            print("No chunks to benchmark.")
        else:
            chunks_per_trial = min(max(1, args.benchmark_chunks), pending_chunks)
            sample_messages = messages[
                processed : processed + chunks_per_trial * chunk_size
            ]
            print("Benchmark:")
            print(f"- chunks_per_trial: {chunks_per_trial}")
            print(f"- workers: {benchmark_workers}")
            for workers in benchmark_workers:
                bench_chat_id = f"{args.chat_id}-bench-w{workers}"
                start_ts = time.monotonic()
                created_bench = maybe_rollup_summary(
                    chat_id=bench_chat_id,
                    messages=sample_messages,
                    summarize_fn=summarize_fn,
                    max_chunks=chunks_per_trial,
                    force_rebuild=True,
                    parallel_workers=workers,
                    on_chunk_done=None,
                )
                elapsed = max(1e-6, time.monotonic() - start_ts)
                chunks_per_sec = created_bench / elapsed
                print(
                    f"- workers={workers}: chunks={created_bench}, "
                    f"elapsed_sec={elapsed:.2f}, chunks_per_sec={chunks_per_sec:.3f}"
                )
        if args.benchmark_only:
            return

    run_chunk_limit = (
        pending_chunks if args.max_chunks <= 0 else min(pending_chunks, args.max_chunks)
    )

    progress_done = 0
    total_chunks = run_chunk_limit
    progress_lock = threading.Lock()

    def on_chunk_done() -> None:
        nonlocal progress_done
        with progress_lock:
            progress_done += 1
            print_progress(progress_done, total_chunks)

    if total_chunks > 0:
        print_progress(0, total_chunks)

    created = maybe_rollup_summary(
        chat_id=args.chat_id,
        messages=messages,
        summarize_fn=summarize_fn,
        max_chunks=run_chunk_limit,
        force_rebuild=args.force_rebuild,
        parallel_workers=max(1, args.parallel_workers),
        on_chunk_done=on_chunk_done if total_chunks > 0 else None,
    )
    if total_chunks > 0:
        print()
    print(f"Created {created} summary chunks for chat_id={args.chat_id}.")


if __name__ == "__main__":
    main()
