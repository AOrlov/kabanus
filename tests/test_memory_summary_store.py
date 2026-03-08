import json
from types import SimpleNamespace

from src.memory import summary_store


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "chat_messages_store_path": "messages",
        "memory_summary_enabled": True,
        "memory_summary_chunk_size": 2,
        "memory_summary_max_chunks_per_run": 2,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _seed_chunks() -> list:
    return [
        {
            "id": "chunk-0-1",
            "source_message_ids": ["m1", "m2"],
            "summary": "Budget was discussed and tracked",
            "facts": ["prefers weekly budget review"],
            "decisions": ["review on Mondays"],
            "open_items": ["share spreadsheet"],
        },
        {
            "id": "chunk-2-3",
            "source_message_ids": ["m3", "m4"],
            "summary": "Travel planning notes",
            "facts": ["likes trains"],
            "decisions": [],
            "open_items": [],
        },
        {
            "id": "chunk-4-5",
            "source_message_ids": ["m5", "m6"],
            "summary": "Sprint retrospective completed",
            "facts": [],
            "decisions": ["keep standup at 10"],
            "open_items": ["track blockers"],
        },
    ]


def test_summary_state_save_and_load_roundtrip(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        summary_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    summary_store.clear_cache()

    state = {"version": 1, "last_message_count": 2, "chunks": _seed_chunks()[:1]}
    summary_store.save_summary_state("chat1", state)
    summary_store.clear_cache()

    loaded = summary_store.load_summary_state("chat1")

    assert loaded == state
    assert (tmp_path / "messages_chat1.summary.json").exists()


def test_load_summary_state_quarantines_corrupt_json(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        summary_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    summary_store.clear_cache()
    corrupt_path = tmp_path / "messages_chat-corrupt.summary.json"
    corrupt_path.write_text("{not json", encoding="utf-8")

    loaded = summary_store.load_summary_state("chat-corrupt")

    assert loaded == {"version": 1, "last_message_count": 0, "chunks": []}
    quarantined = list(tmp_path.glob("messages_chat-corrupt.summary.json.corrupt*"))
    assert quarantined
    assert not corrupt_path.exists()


def test_maybe_rollup_summary_creates_fallback_chunks(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        summary_store.config,
        "get_settings",
        lambda: _settings(
            chat_messages_store_path=str(store_base), memory_summary_chunk_size=2
        ),
    )
    summary_store.clear_cache()

    messages = [
        {"id": "a", "sender": "Alice", "text": "one"},
        {"id": "b", "sender": "Bob", "text": "two"},
        {"id": "c", "sender": "Alice", "text": "three"},
        {"id": "d", "sender": "Bob", "text": "four"},
        {"id": "e", "sender": "Alice", "text": "five"},
    ]

    created = summary_store.maybe_rollup_summary(
        "chat2", messages=messages, summarize_fn=None, max_chunks=2
    )
    state = summary_store.load_summary_state("chat2")

    assert created == 2
    assert state["last_message_count"] == 4
    assert len(state["chunks"]) == 2
    assert state["chunks"][0]["source_message_ids"] == ["a", "b"]
    assert state["chunks"][1]["source_message_ids"] == ["c", "d"]


def test_maybe_rollup_summary_resets_if_processed_exceeds_message_count(
    monkeypatch, tmp_path
) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        summary_store.config,
        "get_settings",
        lambda: _settings(
            chat_messages_store_path=str(store_base), memory_summary_chunk_size=2
        ),
    )
    summary_store.clear_cache()
    summary_store.save_summary_state(
        "chat3",
        {
            "version": 1,
            "last_message_count": 100,
            "chunks": [{"id": "old"}],
        },
    )

    messages = [
        {"id": "a", "sender": "Alice", "text": "one"},
        {"id": "b", "sender": "Bob", "text": "two"},
    ]
    created = summary_store.maybe_rollup_summary(
        "chat3", messages=messages, summarize_fn=None
    )
    state = summary_store.load_summary_state("chat3")

    assert created == 1
    assert state["last_message_count"] == 2
    assert len(state["chunks"]) == 1
    assert state["chunks"][0]["id"] == "chunk-0-1"


def test_get_summary_view_text_and_summary_lines(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        summary_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    summary_store.clear_cache()
    summary_store.save_summary_state(
        "chat4",
        {
            "version": 1,
            "last_message_count": 6,
            "chunks": _seed_chunks(),
        },
    )

    head_tail = summary_store.get_summary_view_text("chat4", head=1, tail=1)
    by_index = summary_store.get_summary_view_text("chat4", index=1)
    with_grep = summary_store.get_summary_view_text("chat4", grep="budget", head=2)
    lines, _ = summary_store.build_summary_lines(
        chat_id="chat4",
        latest_user_text="budget monday",
        token_limit=200,
        max_items=2,
    )

    assert "Chunk #0" in head_tail
    assert "Chunk #2" in head_tail
    assert "Chunk #1" in by_index
    assert "Matches for 'budget': 1" in with_grep
    assert lines
    assert lines[0].startswith("- Budget was discussed")


def test_summarize_chunk_retries_when_language_mismatch() -> None:
    prompts = []

    def _summarize(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) == 1:
            return json.dumps(
                {
                    "summary": "Привет мир",
                    "facts": [],
                    "decisions": [],
                    "open_items": [],
                }
            )
        return json.dumps(
            {
                "summary": "Hello world",
                "facts": ["prefers concise updates"],
                "decisions": [],
                "open_items": [],
            }
        )

    chunk = [
        {"id": "m1", "sender": "Alice", "text": "Need weekly status updates"},
        {"id": "m2", "sender": "Bob", "text": "Okay, every Monday"},
    ]

    summary = summary_store._summarize_chunk(
        chat_id="chat5",
        chunk=chunk,
        start=0,
        end=1,
        summarize_fn=_summarize,
    )

    assert len(prompts) == 2
    assert "IMPORTANT: Your previous answer used the wrong language" in prompts[1]
    assert summary["summary"] == "Hello world"
    assert summary["facts"] == ["prefers concise updates"]


def test_clear_cache_drops_single_chat(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        summary_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    summary_store.clear_cache()

    summary_store.load_summary_state("chat6")
    summary_store.load_summary_state("chat7")

    summary_store.clear_cache("chat6")

    assert "chat6" not in summary_store._summary_store_by_chat
    assert "chat7" in summary_store._summary_store_by_chat
