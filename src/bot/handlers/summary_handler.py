import re
from typing import Any, Callable, Dict, Optional, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.contracts import GetSummaryViewTextFn, IsAllowedFn, StorageIdFn
from src.bot.services.reply_service import chunk_string


def parse_summary_command_args(
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
        raw: str,
        name: str,
        allow_zero: bool = False,
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
        value, err = parse_int(args[1], lowered[0], allow_zero=(lowered[0] == "index"))
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
            value, err = parse_int(args[idx + 1], key, allow_zero=(key == "index"))
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


class SummaryHandler:
    def __init__(
        self,
        *,
        is_allowed_fn: IsAllowedFn,
        storage_id_fn: StorageIdFn,
        get_summary_view_text_fn: GetSummaryViewTextFn,
        parse_summary_args_fn: Callable[[list[str]], Tuple[Optional[Dict], Optional[str]]] = parse_summary_command_args,
        summary_usage_fn: Callable[[], str] = summary_command_usage,
        command_args_from_text_fn: Callable[[str], list[str]] = command_args_from_message_text,
        chunk_string_fn: Callable[[str, int], list[str]] = chunk_string,
    ) -> None:
        self._is_allowed = is_allowed_fn
        self._storage_id = storage_id_fn
        self._get_summary_view_text = get_summary_view_text_fn
        self._parse_summary_args = parse_summary_args_fn
        self._summary_usage = summary_usage_fn
        self._command_args_from_text = command_args_from_text_fn
        self._chunk_string = chunk_string_fn

    async def view_summary(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not self._is_allowed(update):
            return
        if (
            update.message is None
            or update.effective_chat is None
            or update.effective_user is None
        ):
            return

        args = self._command_args_from_text(update.message.text or "")
        if not args:
            args = context.args or []
        parsed, err = self._parse_summary_args(args)
        if err:
            await update.message.reply_text(f"{err}\n\n{self._summary_usage()}")
            return
        if parsed is None:
            return

        if parsed.get("show_help"):
            await update.message.reply_text(self._summary_usage())
            return

        chat_storage_id = self._storage_id(update)
        if chat_storage_id is None:
            return

        try:
            output = self._get_summary_view_text(
                chat_id=chat_storage_id,
                head=int(parsed["head"]),
                tail=int(parsed["tail"]),
                index=parsed["index"],
                grep=str(parsed["grep"]),
            )
        except RuntimeError as exc:
            await update.message.reply_text(f"Failed to read summary: {exc}")
            return

        for chunk in self._chunk_string(output, 4000):
            if chunk.strip():
                await update.message.reply_text(chunk)
