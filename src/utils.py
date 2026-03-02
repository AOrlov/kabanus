import html
import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urlparse

_ALLOWED_HTML_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "code",
    "pre",
    "a",
    "tg-spoiler",
    "blockquote",
}
_ALLOWED_LINK_SCHEMES = {"http", "https", "tg", "mailto"}
_TAG_OR_TEXT_RE = re.compile(r"<[^>]+>|[^<]+")
_START_TAG_RE = re.compile(r"<\s*([a-z0-9-]+)(?:\s+[^>]*)?>", re.IGNORECASE)
_END_TAG_RE = re.compile(r"</\s*([a-z0-9-]+)\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_PARTIAL_ENTITY_RE = re.compile(r"&(?:#[0-9]{0,8}|#x[0-9a-fA-F]{0,8}|[a-zA-Z0-9]{0,32})$")
_FENCED_CODE_RE = re.compile(r"```(?:[^\n`]*)\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+|tg://[^\s)]+|mailto:[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", re.DOTALL)
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", re.DOTALL)
_HEADING_RE = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.+?)\s*$")
_PLACEHOLDER_RE = re.compile(r"@@TGBLOCK\d+@@")


def strip_markdown_to_json(text: str) -> str:
    text = text.strip()
    # remove markdown code block markers if present
    if text.startswith('```json'):
        text = text[7:]
    if text.endswith('```'):
        text = text[:-3]
    return text.strip()


def sanitize_telegram_html(text: str) -> str:
    """Keep a safe Telegram HTML subset and escape everything else."""
    if not text:
        return ""

    parser = _TelegramHTMLSanitizer()
    parser.feed(text)
    return parser.render()


def chunk_telegram_html(text: str, chunk_size: int) -> List[str]:
    """Split sanitized Telegram HTML into balanced chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    tokens = _TAG_OR_TEXT_RE.findall(text)
    chunks: List[str] = []
    current_parts: List[str] = []
    current_len = 0
    open_tags: List[Tuple[str, str]] = []

    def closing_tags() -> str:
        return "".join(f"</{tag}>" for tag, _ in reversed(open_tags))

    def reopening_tags() -> str:
        return "".join(start_tag for _, start_tag in open_tags)

    def flush(start_new_chunk: bool) -> None:
        nonlocal current_parts, current_len
        if not current_parts:
            return
        chunk_text = "".join(current_parts) + closing_tags()
        if chunk_text.strip():
            chunks.append(chunk_text)
        if start_new_chunk and open_tags:
            reopen = reopening_tags()
            current_parts = [reopen]
            current_len = len(reopen)
        else:
            current_parts = []
            current_len = 0

    for token in tokens:
        if token.startswith("<"):
            suffix_len = len(closing_tags())
            if current_parts and current_len + len(token) + suffix_len > chunk_size:
                flush(start_new_chunk=True)
            current_parts.append(token)
            current_len += len(token)
            tag_name, is_end_tag = _parse_tag_token(token)
            if tag_name:
                if is_end_tag:
                    if open_tags and open_tags[-1][0] == tag_name:
                        open_tags.pop()
                else:
                    open_tags.append((tag_name, token))
            continue

        remaining = token
        while remaining:
            suffix_len = len(closing_tags())
            available = chunk_size - current_len - suffix_len
            if available <= 0:
                flush(start_new_chunk=True)
                continue
            if len(remaining) <= available:
                current_parts.append(remaining)
                current_len += len(remaining)
                remaining = ""
                continue
            split_at = _find_text_split(remaining, available)
            part = remaining[:split_at]
            current_parts.append(part)
            current_len += len(part)
            flush(start_new_chunk=True)
            remaining = remaining[split_at:]

    flush(start_new_chunk=False)
    return chunks


def build_telegram_html_chunks(text: str, chunk_size: int) -> List[str]:
    """Convert markdown-like text to Telegram-safe HTML and chunk it."""
    return chunk_telegram_html(prepare_telegram_html(text), chunk_size)


def prepare_telegram_html(text: str) -> str:
    return sanitize_telegram_html(markdownish_to_html(text))


def telegram_html_to_plain_text(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text))


def markdownish_to_html(text: str) -> str:
    """Convert common LLM markdown patterns to HTML before Telegram sanitizing."""
    if not text:
        return ""

    blocks: List[str] = []

    def stash(value: str) -> str:
        key = f"@@TGBLOCK{len(blocks)}@@"
        blocks.append(value)
        return key

    def replace_fenced_code(match: re.Match[str]) -> str:
        return stash(f"<pre>{match.group(1)}</pre>")

    def replace_inline_code(match: re.Match[str]) -> str:
        return stash(f"<code>{match.group(1)}</code>")

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = match.group(2)
        return f'<a href="{url}">{label}</a>'

    converted = _FENCED_CODE_RE.sub(replace_fenced_code, text)
    converted = _INLINE_CODE_RE.sub(replace_inline_code, converted)
    converted = _LINK_RE.sub(replace_link, converted)
    converted = _HEADING_RE.sub(r"<b>\1</b>", converted)
    converted = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2) or ''}</b>", converted)
    converted = _STRIKE_RE.sub(r"<s>\1</s>", converted)
    converted = _ITALIC_STAR_RE.sub(r"<i>\1</i>", converted)
    converted = _ITALIC_UNDERSCORE_RE.sub(r"<i>\1</i>", converted)

    def restore(match: re.Match[str]) -> str:
        key = match.group(0)
        idx = int(key[len("@@TGBLOCK"):-2])
        return blocks[idx]

    return _PLACEHOLDER_RE.sub(restore, converted)


class _TelegramHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: List[str] = []
        self._open_tags: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        normalized_tag = tag.lower()
        raw_tag = self.get_starttag_text() or f"<{tag}>"
        if normalized_tag not in _ALLOWED_HTML_TAGS:
            self._parts.append(html.escape(raw_tag, quote=False))
            return

        if normalized_tag == "a":
            href = None
            for key, value in attrs:
                if key and key.lower() == "href":
                    href = (value or "").strip()
                    break
            if not href or not _is_safe_link(href):
                self._parts.append(html.escape(raw_tag, quote=False))
                return
            safe_href = html.escape(href, quote=True)
            start_tag = f'<a href="{safe_href}">'
        else:
            start_tag = f"<{normalized_tag}>"

        self._parts.append(start_tag)
        self._open_tags.append(normalized_tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag not in _ALLOWED_HTML_TAGS:
            self._parts.append(html.escape(f"</{tag}>", quote=False))
            return
        if self._open_tags and self._open_tags[-1] == normalized_tag:
            self._parts.append(f"</{normalized_tag}>")
            self._open_tags.pop()
        else:
            self._parts.append(html.escape(f"</{tag}>", quote=False))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        before = len(self._open_tags)
        self.handle_starttag(tag, attrs)
        if len(self._open_tags) > before and self._open_tags[-1] == tag.lower():
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        self._parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._parts.append(html.escape(f"<!--{data}-->", quote=False))

    def render(self) -> str:
        self.close()
        while self._open_tags:
            self._parts.append(f"</{self._open_tags.pop()}>")
        return "".join(self._parts)


def _is_safe_link(href: str) -> bool:
    parsed = urlparse(href)
    if not parsed.scheme:
        return False
    return parsed.scheme.lower() in _ALLOWED_LINK_SCHEMES


def _parse_tag_token(token: str) -> Tuple[str, bool]:
    end_match = _END_TAG_RE.fullmatch(token)
    if end_match:
        return end_match.group(1).lower(), True
    start_match = _START_TAG_RE.fullmatch(token)
    if start_match:
        return start_match.group(1).lower(), False
    return "", False


def _find_text_split(text: str, max_len: int) -> int:
    if len(text) <= max_len:
        return len(text)

    preferred = max(
        text.rfind("\n", 0, max_len + 1),
        text.rfind(" ", 0, max_len + 1),
    )
    split_at = preferred + 1 if preferred > 0 else max_len

    entity_start = text.rfind("&", 0, split_at)
    if entity_start != -1:
        entity_end = text.find(";", entity_start)
        if entity_end != -1 and entity_start < split_at <= entity_end:
            split_at = entity_start

    if split_at <= 0:
        split_at = max_len
    if _PARTIAL_ENTITY_RE.search(text[:split_at]):
        amp = text[:split_at].rfind("&")
        if amp > 0:
            split_at = amp
    return max(1, split_at)
