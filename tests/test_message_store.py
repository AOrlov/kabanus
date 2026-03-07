from types import SimpleNamespace

from src import message_store
from src.memory import context_builder, history_store, summary_store


def _settings(**overrides):
    base = {
        "token_limit": 200,
        "chat_messages_store_path": "messages",
        "memory_enabled": True,
        "memory_recent_turns": 3,
        "memory_recent_budget_ratio": 0.85,
        "memory_summary_enabled": False,
        "memory_summary_budget_ratio": 0.15,
        "memory_summary_chunk_size": 16,
        "memory_summary_max_items": 4,
        "memory_summary_max_chunks_per_run": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_context_uses_recent_window(monkeypatch) -> None:
    monkeypatch.setattr(message_store.config, "get_settings", lambda: _settings(memory_recent_turns=2))
    messages = [
        {"sender": "Alice", "text": "one"},
        {"sender": "Bob", "text": "two"},
        {"sender": "Alice", "text": "three"},
    ]

    context = message_store.build_context(chat_id="c1", latest_user_text="three", messages=messages, token_limit=200)

    assert "[RECENT_DIALOGUE]" in context
    assert "Bob: two" in context
    assert "Alice: three" in context
    assert "Alice: one" not in context


def test_build_context_respects_token_budget(monkeypatch) -> None:
    monkeypatch.setattr(message_store.config, "get_settings", lambda: _settings(memory_recent_turns=10))
    messages = [
        {"sender": "Alice", "text": "a" * 60},
        {"sender": "Bob", "text": "b" * 60},
        {"sender": "Alice", "text": "c" * 60},
    ]

    context = message_store.build_context(chat_id="c2", latest_user_text="c", messages=messages, token_limit=30)

    assert "Alice: ccccc" in context
    assert "Bob: bbbbb" not in context
    assert "Alice: aaaaa" not in context


def test_build_context_falls_back_when_memory_disabled(monkeypatch) -> None:
    monkeypatch.setattr(message_store.config, "get_settings", lambda: _settings(memory_enabled=False))
    messages = [
        {"sender": "Alice", "text": "hello"},
        {"sender": "Bob", "text": "world"},
    ]

    context = message_store.build_context(chat_id="c3", latest_user_text="world", messages=messages, token_limit=200)

    assert context == "Alice: hello\nBob: world"


def test_add_message_stores_telegram_message_ids(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        message_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_path)),
    )
    message_store._message_store_by_chat.clear()

    message_store.add_message(
        "Alice",
        "hello",
        chat_id="chat1",
        telegram_message_id=1001,
        reply_to_telegram_message_id=999,
    )
    last_message = message_store.get_last_message("chat1")

    assert last_message is not None
    assert last_message["telegram_message_id"] == 1001
    assert last_message["reply_to_telegram_message_id"] == 999


def test_get_message_by_telegram_message_id(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        message_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_path)),
    )
    message_store._message_store_by_chat.clear()

    message_store.add_message("Alice", "first", chat_id="chat2", telegram_message_id=10)
    message_store.add_message("Bob", "second", chat_id="chat2", telegram_message_id=11)

    found = message_store.get_message_by_telegram_message_id("chat2", 10)
    missing = message_store.get_message_by_telegram_message_id("chat2", 999)

    assert found is not None
    assert found["sender"] == "Alice"
    assert found["text"] == "first"
    assert missing is None


def test_get_all_messages_returns_copy_for_legacy_callers(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        message_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_path)),
    )
    message_store._message_store_by_chat.clear()

    message_store.add_message("Alice", "first", chat_id="chat3")

    snapshot = message_store.get_all_messages("chat3")
    snapshot.append({"sender": "Injected", "text": "tampered"})

    fresh = message_store.get_all_messages("chat3")
    assert len(snapshot) == 2
    assert len(fresh) == 1
    assert fresh[0]["sender"] == "Alice"


def test_add_message_normalizes_legacy_string_ids(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        message_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_path)),
    )
    message_store._message_store_by_chat.clear()

    message_store.add_message(
        "Alice",
        "hello",
        chat_id="chat4",
        telegram_message_id="100",
        reply_to_telegram_message_id="90",
    )
    added = message_store.get_last_message("chat4")

    assert added is not None
    assert added["telegram_message_id"] == 100
    assert added["reply_to_telegram_message_id"] == 90


def test_facade_calls_target_same_store_behavior(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        message_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_path)),
    )
    message_store._message_store_by_chat.clear()
    history_store._message_store_by_chat.clear()

    message_store.add_message("Alice", "from facade", chat_id="chat_shared")
    last_message = history_store.get_last_message("chat_shared")
    assert last_message is not None
    assert last_message["sender"] == "Alice"
    assert last_message["text"] == "from facade"
    assert last_message["kind"] == "user"

    history_store.add_message("Bob", "from history", chat_id="chat_shared")
    assert len(message_store.get_all_messages("chat_shared")) == 2


def test_facade_get_summary_view_text_matches_summary_store(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        message_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_path)),
    )
    message_store._summary_store_by_chat.clear()
    message_store._summary_store_by_chat["chat5"] = {
        "version": 1,
        "last_message_count": 2,
        "chunks": [
            {
                "id": "chunk-0-1",
                "source_message_ids": ["a", "b"],
                "summary": "Planning update",
                "facts": ["prefers async updates"],
                "decisions": [],
                "open_items": [],
            }
        ],
    }

    facade_text = message_store.get_summary_view_text("chat5", head=1)
    module_text = summary_store.get_summary_view_text("chat5", head=1)

    assert facade_text == module_text


def test_facade_assemble_context_matches_context_builder() -> None:
    messages = [
        {"sender": "Alice", "text": "hello"},
        {"sender": "Bob", "text": "world"},
    ]

    facade_output = message_store.assemble_context(messages, token_limit=200)
    module_output = context_builder.assemble_context(messages, token_limit=200)

    assert facade_output == module_output
