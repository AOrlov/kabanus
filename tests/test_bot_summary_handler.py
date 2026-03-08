import asyncio
from types import SimpleNamespace

from src.bot.handlers.summary_handler import (
    SummaryHandler,
    command_args_from_message_text,
    parse_summary_command_args,
)


def test_command_args_from_message_text() -> None:
    assert command_args_from_message_text("/summary") == []
    assert command_args_from_message_text("/summary 5") == ["5"]
    assert command_args_from_message_text("/summary@kaban index 3") == ["index", "3"]


def test_parse_summary_command_args_keyword_form() -> None:
    parsed, err = parse_summary_command_args(["incident", "report"])

    assert err is None
    assert parsed == {
        "head": 5,
        "tail": 0,
        "index": None,
        "grep": "incident report",
        "show_help": False,
    }


def test_view_summary_prefers_message_text_args() -> None:
    calls = {}

    def _fake_get_summary_view_text(**kwargs):
        calls.update(kwargs)
        return "summary text"

    async def _reply_text(text: str):
        replies.append(text)

    replies = []
    handler = SummaryHandler(
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "42",
        get_summary_view_text_fn=_fake_get_summary_view_text,
    )

    update = SimpleNamespace(
        message=SimpleNamespace(text="/summary 2", reply_text=_reply_text),
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=99),
    )
    context = SimpleNamespace(args=["9"])

    asyncio.run(handler.view_summary(update, context))

    assert calls["chat_id"] == "42"
    assert calls["tail"] == 2
    assert replies == ["summary text"]


def test_view_summary_reports_parse_error_with_usage() -> None:
    replies = []

    async def _reply_text(text: str):
        replies.append(text)

    handler = SummaryHandler(
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "42",
        get_summary_view_text_fn=lambda **kwargs: "unused",
    )

    update = SimpleNamespace(
        message=SimpleNamespace(text="/summary index", reply_text=_reply_text),
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=99),
    )
    context = SimpleNamespace(args=[])

    asyncio.run(handler.view_summary(update, context))

    assert len(replies) == 1
    assert "Missing value for index" in replies[0]
    assert "Summary command examples:" in replies[0]


def test_view_summary_chunks_non_empty_outputs() -> None:
    replies = []

    async def _reply_text(text: str):
        replies.append(text)

    handler = SummaryHandler(
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "42",
        get_summary_view_text_fn=lambda **kwargs: "summary output",
        chunk_string_fn=lambda _text, _max_len: ["first chunk", "   ", "second chunk"],
    )

    update = SimpleNamespace(
        message=SimpleNamespace(text="/summary 1", reply_text=_reply_text),
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=99),
    )
    context = SimpleNamespace(args=[])

    asyncio.run(handler.view_summary(update, context))

    assert replies == ["first chunk", "second chunk"]
