from types import SimpleNamespace

import pytest

from src.memory import history_store


def _settings(chat_messages_store_path: str) -> SimpleNamespace:
    return SimpleNamespace(chat_messages_store_path=chat_messages_store_path)


def test_get_store_path_creates_chat_file(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        history_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )

    path = history_store.get_store_path("c1")

    assert path.endswith("messages_c1.jsonl")
    assert (tmp_path / "messages_c1.jsonl").exists()


def test_add_message_persists_and_lookup_by_telegram_id(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        history_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    history_store.clear_cache()

    history_store.add_message("Alice", "hello", chat_id="c2", telegram_message_id="100")
    history_store.add_message("Bob", "world", chat_id="c2", telegram_message_id=101)

    found = history_store.get_message_by_telegram_message_id("c2", 100)

    assert found is not None
    assert found["sender"] == "Alice"
    assert found["text"] == "hello"
    assert found["telegram_message_id"] == 100

    lines = (
        (tmp_path / "messages_c2.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    assert len(lines) == 2


def test_get_all_messages_returns_copy(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        history_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    history_store.clear_cache()

    history_store.add_message("Alice", "first", chat_id="c3")
    snapshot = history_store.get_all_messages("c3")
    snapshot.append({"sender": "Injected", "text": "tampered"})

    fresh = history_store.get_all_messages("c3")

    assert len(snapshot) == 2
    assert len(fresh) == 1
    assert fresh[0]["sender"] == "Alice"


def test_get_all_messages_requires_chat_id() -> None:
    with pytest.raises(ValueError, match="chat_id is required"):
        history_store.get_all_messages("")


def test_get_store_path_sanitizes_chat_id_for_file_name(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        history_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )

    path = history_store.get_store_path("../escape")

    assert path.endswith("messages_..%2Fescape.jsonl")
    assert (tmp_path / "messages_..%2Fescape.jsonl").exists()


def test_add_message_does_not_cache_on_append_error(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        history_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    history_store.clear_cache()

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(history_store, "_append_message", _boom)

    with pytest.raises(OSError, match="disk full"):
        history_store.add_message("Alice", "hello", chat_id="c4")

    assert history_store.get_all_messages("c4") == []


def test_clear_cache_can_drop_single_chat(monkeypatch, tmp_path) -> None:
    store_base = tmp_path / "messages.jsonl"
    monkeypatch.setattr(
        history_store.config,
        "get_settings",
        lambda: _settings(chat_messages_store_path=str(store_base)),
    )
    history_store.clear_cache()

    history_store.add_message("Alice", "hello", chat_id="c5")
    history_store.add_message("Bob", "hello", chat_id="c6")
    history_store.get_all_messages("c5")
    history_store.get_all_messages("c6")
    history_store._message_store_by_chat["c5"].append(
        {"sender": "Injected", "text": "tampered"}
    )

    history_store.clear_cache("c5")

    assert "c5" not in history_store._message_store_by_chat
    assert "c6" in history_store._message_store_by_chat
    reloaded = history_store.get_all_messages("c5")
    assert len(reloaded) == 1
    assert reloaded[0]["sender"] == "Alice"
