from types import SimpleNamespace

from src.memory import context_builder


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "token_limit": 200,
        "memory_enabled": True,
        "memory_recent_turns": 3,
        "memory_summary_enabled": False,
        "memory_summary_budget_ratio": 0.15,
        "memory_summary_max_items": 4,
        "memory_summary_max_chunks_per_run": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_collect_recent_lines_respects_turn_and_budget_limits() -> None:
    messages = [
        {"sender": "Alice", "text": "one"},
        {"sender": "Bob", "text": "two"},
        {"sender": "Alice", "text": "three"},
    ]

    lines, _ = context_builder._collect_recent_lines(messages, max_turns=2, token_limit=200)

    assert lines == ["Bob: two", "Alice: three"]


def test_assemble_context_uses_token_limit() -> None:
    messages = [
        {"sender": "Alice", "text": "a" * 60},
        {"sender": "Bob", "text": "b" * 60},
    ]

    context = context_builder.assemble_context(messages, token_limit=20)

    assert "Bob: bbbbb" in context
    assert "Alice: aaaaa" not in context


def test_build_context_uses_legacy_assemble_when_memory_disabled(monkeypatch) -> None:
    monkeypatch.setattr(context_builder.config, "get_settings", lambda: _settings(memory_enabled=False))
    messages = [
        {"sender": "Alice", "text": "hello"},
        {"sender": "Bob", "text": "world"},
    ]

    context = context_builder.build_context(chat_id="c1", messages=messages, token_limit=200)

    assert context == "Alice: hello\nBob: world"


def test_build_context_merges_recent_and_summary_sections(monkeypatch) -> None:
    monkeypatch.setattr(
        context_builder.config,
        "get_settings",
        lambda: _settings(
            memory_enabled=True,
            memory_recent_turns=2,
            memory_summary_enabled=True,
            memory_summary_budget_ratio=0.5,
            memory_summary_max_items=2,
            memory_summary_max_chunks_per_run=3,
        ),
    )

    calls = []

    def _fake_rollup(chat_id, messages=None, summarize_fn=None, max_chunks=None):
        calls.append({"chat_id": chat_id, "max_chunks": max_chunks, "messages": list(messages or [])})
        return 0

    monkeypatch.setattr(context_builder.summary_store, "maybe_rollup_summary", _fake_rollup)
    monkeypatch.setattr(
        context_builder.summary_store,
        "_build_summary_lines",
        lambda chat_id, latest_user_text, token_limit, max_items: (["- summary line"], 3),
    )

    messages = [
        {"sender": "Alice", "text": "one"},
        {"sender": "Bob", "text": "two"},
        {"sender": "Alice", "text": "three"},
    ]

    context = context_builder.build_context(
        chat_id="c2",
        latest_user_text="three",
        messages=messages,
        token_limit=200,
    )

    assert "[RECENT_DIALOGUE]" in context
    assert "[LONG_TERM_SUMMARY]" in context
    assert "- summary line" in context
    assert calls
    assert calls[0]["chat_id"] == "c2"
    assert calls[0]["max_chunks"] == 3


def test_build_context_returns_empty_on_non_positive_token_limit(monkeypatch) -> None:
    monkeypatch.setattr(context_builder.config, "get_settings", lambda: _settings(token_limit=0))

    context = context_builder.build_context(chat_id="c3", token_limit=0, messages=[])

    assert context == ""
