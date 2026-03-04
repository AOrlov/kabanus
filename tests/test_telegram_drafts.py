import asyncio
import json

import pytest

from src import telegram_drafts


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_send_message_draft_sync_success(monkeypatch) -> None:
    captured = {}

    def _fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["data"] = request.data
        return _FakeResponse('{"ok": true, "result": true}')

    monkeypatch.setattr(telegram_drafts.urllib.request, "urlopen", _fake_urlopen)

    result = telegram_drafts._send_message_draft_sync(
        bot_token="test-token",
        chat_id=123,
        draft_id=987654321,
        text="hello",
    )

    payload = json.loads(captured["data"].decode("utf-8"))
    assert result is True
    assert captured["url"].endswith("/sendMessageDraft")
    assert captured["timeout"] == 10.0
    assert payload["chat_id"] == "123"
    assert payload["draft_id"] == 987654321
    assert payload["text"] == "hello"


def test_send_message_draft_sync_raises_on_api_error(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_drafts.urllib.request,
        "urlopen",
        lambda request, timeout=0: _FakeResponse('{"ok": false, "description": "bad request"}'),
    )

    with pytest.raises(RuntimeError, match="sendMessageDraft failed: bad request"):
        telegram_drafts._send_message_draft_sync(
            bot_token="test-token",
            chat_id=123,
            draft_id=987654321,
            text="hello",
        )


def test_send_message_draft_async_wrapper(monkeypatch) -> None:
    captured = {}

    def _fake_send_sync(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(telegram_drafts, "_send_message_draft_sync", _fake_send_sync)

    result = asyncio.run(
        telegram_drafts.send_message_draft(
            bot_token="token",
            chat_id=1,
            draft_id=123,
            text="x",
            timeout_secs=5.0,
        )
    )

    assert result is True
    assert captured["bot_token"] == "token"
    assert captured["chat_id"] == 1
    assert captured["draft_id"] == 123
    assert captured["text"] == "x"
    assert captured["timeout_secs"] == 5.0


def test_send_message_draft_sync_rejects_non_integer_draft_id() -> None:
    with pytest.raises(ValueError, match="draft_id must be an integer"):
        telegram_drafts._send_message_draft_sync(
            bot_token="token",
            chat_id=1,
            draft_id="ai_1_1",
            text="x",
        )
