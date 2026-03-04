import asyncio
import json
import urllib.error
import urllib.request
from typing import Optional, Union

_MAX_DRAFT_TEXT_LENGTH = 4096


def _prepare_draft_text(text: str) -> str:
    prepared = str(text or "")[:_MAX_DRAFT_TEXT_LENGTH]
    return prepared if prepared else " "


def _send_message_draft_sync(
    *,
    bot_token: str,
    chat_id: Union[str, int],
    draft_id: Union[str, int],
    text: str,
    parse_mode: Optional[str] = None,
    timeout_secs: float = 10.0,
) -> bool:
    token = str(bot_token or "").strip()
    try:
        draft = int(draft_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("draft_id must be an integer") from exc
    if not token:
        raise ValueError("bot_token is required")
    if draft == 0:
        raise ValueError("draft_id must be non-zero")

    payload = {
        "chat_id": str(chat_id),
        "draft_id": draft,
        "text": _prepare_draft_text(text),
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    request = urllib.request.Request(
        url=f"https://api.telegram.org/bot{token}/sendMessageDraft",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_secs) as response:
            raw_response = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"sendMessageDraft HTTP {exc.code}: {body[:256]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"sendMessageDraft request failed: {exc}") from exc

    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise RuntimeError("sendMessageDraft returned non-JSON response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("sendMessageDraft returned invalid payload")
    if payload.get("ok") is True:
        return bool(payload.get("result"))
    description = str(payload.get("description") or "unknown error")
    raise RuntimeError(f"sendMessageDraft failed: {description}")


async def send_message_draft(
    *,
    bot_token: str,
    chat_id: Union[str, int],
    draft_id: Union[str, int],
    text: str,
    parse_mode: Optional[str] = None,
    timeout_secs: float = 10.0,
) -> bool:
    return await asyncio.to_thread(
        _send_message_draft_sync,
        bot_token=bot_token,
        chat_id=chat_id,
        draft_id=draft_id,
        text=text,
        parse_mode=parse_mode,
        timeout_secs=timeout_secs,
    )
