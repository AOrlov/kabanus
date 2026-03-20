import importlib


def test_backfill_script_imports_memory_helpers() -> None:
    module = importlib.import_module("scripts.backfill_summaries")

    tokens = module.estimate_input_tokens(
        [{"sender": "Alice", "text": "hello"}],
        start=0,
        chunk_size=1,
    )

    assert tokens > 0
