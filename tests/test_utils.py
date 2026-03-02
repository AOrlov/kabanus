import re

from src import utils


def test_sanitize_telegram_html_escapes_disallowed_tags() -> None:
    raw = 'hello <script>alert(1)</script> <a href="javascript:alert(1)">bad</a>'
    safe = utils.sanitize_telegram_html(raw)
    assert "&lt;script&gt;" in safe
    assert "&lt;/script&gt;" in safe
    assert '&lt;a href="javascript:alert(1)"&gt;' in safe
    assert "&lt;/a&gt;" in safe
    assert "<script>" not in safe


def test_sanitize_telegram_html_closes_unbalanced_tags() -> None:
    safe = utils.sanitize_telegram_html("<b>Hello")
    assert safe == "<b>Hello</b>"


def test_chunk_telegram_html_keeps_chunks_balanced() -> None:
    safe = utils.sanitize_telegram_html("<b>" + ("a" * 4500) + "</b>")
    chunks = utils.chunk_telegram_html(safe, 4000)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert all(chunk.count("<b>") == chunk.count("</b>") for chunk in chunks)
    assert "".join(utils.telegram_html_to_plain_text(chunk) for chunk in chunks) == "a" * 4500


def test_build_telegram_html_chunks_avoids_partial_entity() -> None:
    raw = ("x" * 3998) + "&" + ("y" * 10)
    chunks = utils.build_telegram_html_chunks(raw, 4000)
    assert len(chunks) == 2
    assert re.search(r"&(?:#[0-9]{0,8}|#x[0-9a-fA-F]{0,8}|[a-zA-Z0-9]{0,32})$", chunks[0]) is None
    assert not chunks[1].startswith("amp;")


def test_telegram_html_to_plain_text_unescapes_entities() -> None:
    assert utils.telegram_html_to_plain_text("<b>A &amp; B</b>") == "A & B"


def test_markdownish_to_html_converts_common_patterns() -> None:
    raw = (
        "**Bold** _italic_ ~~strike~~\n"
        "[site](https://example.com) and `print('x')`\n"
        "```python\nx = 1\n```"
    )
    html_text = utils.prepare_telegram_html(raw)
    assert "<b>Bold</b>" in html_text
    assert "<i>italic</i>" in html_text
    assert "<s>strike</s>" in html_text
    assert '<a href="https://example.com">site</a>' in html_text
    assert "<code>print('x')</code>" in html_text
    assert "<pre>x = 1\n</pre>" in html_text


def test_prepare_telegram_html_keeps_html_and_markdown() -> None:
    raw = "Hello <b>there</b> and **friend**"
    html_text = utils.prepare_telegram_html(raw)
    assert "<b>there</b>" in html_text
    assert "<b>friend</b>" in html_text
