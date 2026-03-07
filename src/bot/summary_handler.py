import re
from typing import Any, Dict, Optional, Tuple

from telegram import Message, Update
from telegram.ext import ContextTypes

from src.message_store import get_summary_view_text

from src.bot.access import is_allowed, storage_id
from src.bot.response_service import chunk_string
from src.bot.runtime import BotRuntime


def parse_summary_command_args(  # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
    args: list[str],
) -> Tuple[Optional[Dict], Optional[str]]:
    parsed: Dict = {"head": 0, "tail": 0, "index": None, "grep": "", "show_help": False}
    if not args:
        parsed["tail"] = 1
        return parsed, None

    lowered = [arg.lower() for arg in args]
    if len(args) == 1 and lowered[0] in {"help", "--help", "-help", "?"}:
        parsed["show_help"] = True
        return parsed, None

    def parse_int(
        raw: str, name: str, allow_zero: bool = False
    ) -> Tuple[Optional[int], Optional[str]]:
        try:
            value = int(raw)
        except ValueError:
            return None, f"Invalid integer for {name}: {raw}"
        min_allowed = 0 if allow_zero else 1
        if value < min_allowed:
            return None, f"{name} must be >= {min_allowed}"
        return value, None

    if args[0].lstrip("-").isdigit():
        value, err = parse_int(args[0], "tail")
        if err:
            return None, err
        parsed["tail"] = value
        if len(args) > 1:
            parsed["grep"] = " ".join(args[1:]).strip()
        return parsed, None

    if lowered[0] in {"head", "index"}:
        if len(args) < 2:
            return None, f"Missing value for {args[0]}"
        value, err = parse_int(args[1], lowered[0], allow_zero=lowered[0] == "index")
        if err:
            return None, err
        parsed[lowered[0]] = value
        if len(args) > 2:
            parsed["grep"] = " ".join(args[2:]).strip()
        return parsed, None

    if not args[0].startswith("--"):
        parsed["grep"] = " ".join(args).strip()
        parsed["head"] = 5
        return parsed, None

    flags = {"--head", "--index", "--grep"}
    idx = 0
    while idx < len(args):
        token = args[idx]
        if token not in flags:
            return None, f"Unknown argument: {token}"
        if token in {"--head", "--index"}:
            if idx + 1 >= len(args):
                return None, f"Missing value for {token}"
            key = token[2:]
            value, err = parse_int(args[idx + 1], key, allow_zero=key == "index")
            if err:
                return None, err
            parsed[key] = value
            idx += 2
            continue
        if idx + 1 >= len(args):
            return None, "Missing value for --grep"
        grep_tokens = []
        idx += 1
        while idx < len(args):
            if args[idx].startswith("--") and args[idx] in flags:
                break
            grep_tokens.append(args[idx])
            idx += 1
        if not grep_tokens:
            return None, "Missing value for --grep"
        parsed["grep"] = " ".join(grep_tokens)

    if parsed["head"] == 0 and parsed["tail"] == 0 and parsed["index"] is None:
        parsed["head"] = 5
    return parsed, None


def summary_command_usage() -> str:
    return (
        "Summary command examples:\n"
        "/summary               -> last chunk\n"
        "/summary 5             -> last 5 chunks\n"
        "/summary index 12      -> chunk #12\n"
        "/summary budget api    -> search text in summary/facts/decisions/open_items\n"
        "/summary --head 10 --grep budget\n"
        "Alias: /tldr"
    )


def command_args_from_message_text(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return []
    payload = parts[1].strip()
    if not payload:
        return []
    return [token for token in re.split(r"\s+", payload) if token]


def _resolve_summary_args(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    assert update.message is not None
    args = command_args_from_message_text(update.message.text or "")
    if not args:
        args = context.args or []
    parsed, err = parse_summary_command_args(args)
    if err:
        return None, err
    if parsed is None:
        return None, "Unable to parse summary command"
    return parsed, None


def _build_summary_output(
    chat_storage_id: str,
    parsed: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    try:
        output = get_summary_view_text(
            chat_id=chat_storage_id,
            head=int(parsed["head"]),
            tail=int(parsed["tail"]),
            index=parsed["index"],
            grep=str(parsed["grep"]),
        )
    except RuntimeError as exc:
        return None, f"Failed to read summary: {exc}"
    return output, None


async def _reply_summary_chunks(message: Message, output: str) -> None:
    for chunk in chunk_string(output, 4000):
        if chunk.strip():
            await message.reply_text(chunk)


def build_view_summary_handler(runtime: BotRuntime):
    async def view_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed(
            update,
            settings_getter=runtime.get_settings,
            logger=runtime.logger,
        ):
            return
        if (
            update.message is None
            or update.effective_chat is None
            or update.effective_user is None
        ):
            return

        parsed, err = _resolve_summary_args(update, context)
        if err:
            await update.message.reply_text(f"{err}\n\n{summary_command_usage()}")
            return
        assert parsed is not None
        if parsed.get("show_help"):
            await update.message.reply_text(summary_command_usage())
            return

        chat_storage_id = storage_id(update)
        if chat_storage_id is None:
            return

        output, output_err = _build_summary_output(chat_storage_id, parsed)
        if output_err:
            await update.message.reply_text(output_err)
            return
        assert output is not None
        await _reply_summary_chunks(update.message, output)

    return view_summary
