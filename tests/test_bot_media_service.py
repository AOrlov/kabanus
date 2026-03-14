import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.bot.services import media_service
from src.providers.contracts import AudioTranscriptionRequest, ImageToTextRequest


class _Provider:
    def __init__(self) -> None:
        self.transcribe_paths = []
        self.image_calls = []

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        self.transcribe_paths.append(request.audio_path)
        return "voice transcript"

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        self.image_calls.append(
            {"bytes": request.image_bytes, "mime_type": request.mime_type}
        )
        return "ocr result"


_FILE_SIZE_SENTINEL = object()


class _TelegramFile:
    def __init__(self, payload: bytes, file_size=_FILE_SIZE_SENTINEL) -> None:
        self.payload = payload
        self.file_size = len(payload) if file_size is _FILE_SIZE_SENTINEL else file_size
        self.drive_paths = []

    async def download_to_drive(self, path: str) -> None:
        self.drive_paths.append(path)
        Path(path).write_bytes(self.payload)

    async def download_to_memory(self, bio) -> None:
        bio.write(self.payload)


def _context_for_file(payload: bytes):
    telegram_file = _TelegramFile(payload)

    class _Bot:
        async def get_file(self, _file_id: str):
            return telegram_file

    return SimpleNamespace(bot=_Bot()), telegram_file


def _service(provider, **kwargs):
    return media_service.MediaService(
        audio_transcription_provider=provider,
        ocr_provider=provider,
        **kwargs,
    )


def test_guess_mime_from_name_and_is_image_document() -> None:
    assert media_service.guess_mime_from_name("poster.JPG") == "image/jpeg"
    assert media_service.guess_mime_from_name("diagram.png") == "image/png"
    assert media_service.guess_mime_from_name("notes.txt") == ""

    document = SimpleNamespace(
        mime_type="application/octet-stream", file_name="scan.webp"
    )
    image_doc, mime = media_service.is_image_document(document)
    assert image_doc is True
    assert mime == "image/webp"

    regular_document = SimpleNamespace(mime_type="application/pdf", file_name="a.pdf")
    image_doc, mime = media_service.is_image_document(regular_document)
    assert image_doc is False
    assert mime == ""


def test_combine_caption_and_sender_name_helpers() -> None:
    assert (
        media_service.combine_caption_and_extracted("caption", "ocr") == "caption\nocr"
    )
    assert media_service.combine_caption_and_extracted("caption", "") == "caption"
    assert media_service.combine_caption_and_extracted("", "ocr") == "ocr"

    assert (
        media_service.message_sender_name(SimpleNamespace(from_user=None)) == "Unknown"
    )
    assert (
        media_service.message_sender_name(
            SimpleNamespace(from_user=SimpleNamespace(first_name="Alice"))
        )
        == "Alice"
    )
    assert (
        media_service.message_sender_name(
            SimpleNamespace(from_user=SimpleNamespace(name="Bob"))
        )
        == "Bob"
    )
    assert (
        media_service.message_sender_name(
            SimpleNamespace(from_user=SimpleNamespace(id=123))
        )
        == "123"
    )


def test_transcribe_voice_message_downloads_and_cleans_temp_file() -> None:
    provider = _Provider()
    service = _service(provider)
    context, telegram_file = _context_for_file(b"voice-bytes")
    voice = SimpleNamespace(file_id="voice-1")

    transcript = asyncio.run(service.transcribe_voice_message(voice, context))

    assert transcript == "voice transcript"
    assert len(provider.transcribe_paths) == 1
    temp_path = provider.transcribe_paths[0]
    assert len(telegram_file.drive_paths) == 1
    assert telegram_file.drive_paths[0] == temp_path
    assert not Path(temp_path).exists()


def test_extract_text_from_photo_message_combines_caption_and_ocr() -> None:
    provider = _Provider()
    service = _service(provider)
    context, _ = _context_for_file(b"img-bytes")
    message = SimpleNamespace(
        photo=[
            SimpleNamespace(file_id="photo-small"),
            SimpleNamespace(file_id="photo-large"),
        ],
        caption="Poster",
    )

    extracted = asyncio.run(service.extract_text_from_photo_message(message, context))

    assert extracted == "Poster\nocr result"
    assert provider.image_calls == [{"bytes": b"img-bytes", "mime_type": "image/jpeg"}]


def test_extract_text_from_photo_message_skips_oversized_photo() -> None:
    provider = _Provider()
    service = _service(provider)
    bot_calls = {"get_file": 0}

    class _Bot:
        async def get_file(self, _file_id: str):
            bot_calls["get_file"] += 1
            raise AssertionError("oversized photo should not be downloaded")

    context = SimpleNamespace(bot=_Bot())
    message = SimpleNamespace(
        photo=[
            SimpleNamespace(
                file_id="photo-too-large",
                file_size=media_service.IMAGE_MAX_BYTES + 1,
            )
        ],
        caption="Large poster",
    )

    extracted = asyncio.run(service.extract_text_from_photo_message(message, context))

    assert extracted == "Large poster"
    assert bot_calls["get_file"] == 0
    assert provider.image_calls == []


def test_extract_text_from_photo_message_handles_unknown_size_from_file_metadata() -> (
    None
):
    provider = _Provider()
    service = _service(provider)

    telegram_file = _TelegramFile(b"img-bytes", file_size=None)

    class _Bot:
        async def get_file(self, _file_id: str):
            return telegram_file

    context = SimpleNamespace(bot=_Bot())
    message = SimpleNamespace(
        photo=[SimpleNamespace(file_id="photo-unknown", file_size=None)],
        caption="Poster",
    )

    extracted = asyncio.run(service.extract_text_from_photo_message(message, context))

    assert extracted == "Poster\nocr result"
    assert provider.image_calls == [{"bytes": b"img-bytes", "mime_type": "image/jpeg"}]


def test_extract_text_from_photo_message_skips_oversized_file_metadata() -> None:
    provider = _Provider()
    service = _service(provider)

    telegram_file = _TelegramFile(
        b"img-bytes",
        file_size=media_service.IMAGE_MAX_BYTES + 1,
    )

    class _Bot:
        async def get_file(self, _file_id: str):
            return telegram_file

    context = SimpleNamespace(bot=_Bot())
    message = SimpleNamespace(
        photo=[SimpleNamespace(file_id="photo-big", file_size=None)],
        caption="Poster",
    )

    extracted = asyncio.run(service.extract_text_from_photo_message(message, context))

    assert extracted == "Poster"
    assert provider.image_calls == []


def test_extract_text_from_image_document_handles_non_image_and_image() -> None:
    provider = _Provider()
    service = _service(provider)
    context, _ = _context_for_file(b"png-bytes")

    non_image_message = SimpleNamespace(
        document=SimpleNamespace(
            file_id="doc-1", mime_type="application/pdf", file_name="doc.pdf"
        ),
        caption="ignored",
    )
    assert (
        asyncio.run(
            service.extract_text_from_image_document(non_image_message, context)
        )
        is None
    )
    assert provider.image_calls == []

    image_message = SimpleNamespace(
        document=SimpleNamespace(
            file_id="doc-2", mime_type="application/octet-stream", file_name="photo.png"
        ),
        caption="Document caption",
    )
    extracted = asyncio.run(
        service.extract_text_from_image_document(image_message, context)
    )
    assert extracted == "Document caption\nocr result"
    assert provider.image_calls[-1] == {"bytes": b"png-bytes", "mime_type": "image/png"}


def test_extract_text_from_image_document_handles_unknown_size_from_file_metadata() -> (
    None
):
    provider = _Provider()
    service = _service(provider)
    telegram_file = _TelegramFile(b"png-bytes", file_size=None)

    class _Bot:
        async def get_file(self, _file_id: str):
            return telegram_file

    context = SimpleNamespace(bot=_Bot())
    image_message = SimpleNamespace(
        document=SimpleNamespace(
            file_id="doc-unknown",
            mime_type="image/png",
            file_name="photo.png",
            file_size=None,
        ),
        caption="Document caption",
    )

    extracted = asyncio.run(
        service.extract_text_from_image_document(image_message, context)
    )

    assert extracted == "Document caption\nocr result"
    assert provider.image_calls == [{"bytes": b"png-bytes", "mime_type": "image/png"}]


def test_extract_text_from_photo_message_rejects_oversized_download_with_unknown_size(
    monkeypatch,
) -> None:
    provider = _Provider()
    service = _service(provider)
    monkeypatch.setattr(media_service, "IMAGE_MAX_BYTES", 4)
    telegram_file = _TelegramFile(b"12345", file_size=None)

    class _Bot:
        async def get_file(self, _file_id: str):
            return telegram_file

    context = SimpleNamespace(bot=_Bot())
    message = SimpleNamespace(
        photo=[SimpleNamespace(file_id="photo-unknown", file_size=None)],
        caption="Poster",
    )

    extracted = asyncio.run(service.extract_text_from_photo_message(message, context))

    assert extracted == "Poster"
    assert provider.image_calls == []


def test_extract_text_from_image_document_rejects_oversized_download_with_unknown_size(
    monkeypatch,
) -> None:
    provider = _Provider()
    service = _service(provider)
    monkeypatch.setattr(media_service, "IMAGE_MAX_BYTES", 4)
    telegram_file = _TelegramFile(b"12345", file_size=None)

    class _Bot:
        async def get_file(self, _file_id: str):
            return telegram_file

    context = SimpleNamespace(bot=_Bot())
    image_message = SimpleNamespace(
        document=SimpleNamespace(
            file_id="doc-unknown",
            mime_type="image/png",
            file_name="photo.png",
            file_size=None,
        ),
        caption="Document caption",
    )

    extracted = asyncio.run(
        service.extract_text_from_image_document(image_message, context)
    )

    assert extracted == "Document caption"
    assert provider.image_calls == []


def test_extract_reply_target_text_branches() -> None:
    provider = _Provider()
    warnings = []
    service = _service(
        provider,
        logger_override=SimpleNamespace(
            warning=lambda *args, **kwargs: warnings.append((args, kwargs))
        ),
    )
    context, _ = _context_for_file(b"img")

    text_reply = SimpleNamespace(text="direct text")
    resolved, source = asyncio.run(
        service.extract_reply_target_text(text_reply, context)
    )
    assert (resolved, source) == ("direct text", "message_text")

    caption_reply = SimpleNamespace(
        text="", caption="caption only", photo=None, document=None
    )
    resolved, source = asyncio.run(
        service.extract_reply_target_text(caption_reply, context)
    )
    assert (resolved, source) == ("caption only", "message_caption")

    photo_reply = SimpleNamespace(
        text="",
        caption="photo caption",
        photo=[SimpleNamespace(file_id="p")],
        document=None,
    )

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("ocr failed")

    service.extract_text_from_photo_message = _boom  # type: ignore[method-assign]
    resolved, source = asyncio.run(
        service.extract_reply_target_text(photo_reply, context)
    )
    assert (resolved, source) == ("photo caption", "message_caption")
    assert len(warnings) == 1

    oversized_image_reply = SimpleNamespace(
        text="",
        caption="",
        photo=None,
        document=SimpleNamespace(file_size=media_service.IMAGE_MAX_BYTES + 1),
    )
    resolved, source = asyncio.run(
        service.extract_reply_target_text(oversized_image_reply, context)
    )
    assert (resolved, source) == (
        media_service.NON_TEXT_REPLY_PLACEHOLDER,
        "image_too_large",
    )


def test_resolve_reply_target_context_prefers_history_and_falls_back() -> None:
    provider = _Provider()
    service = _service(provider)
    context, _ = _context_for_file(b"img")

    message = SimpleNamespace(
        reply_to_message=SimpleNamespace(
            from_user=SimpleNamespace(first_name="Alice"),
            message_id=42,
            text="ignored",
        )
    )

    resolved = asyncio.run(
        service.resolve_reply_target_context(
            message,
            chat_id="chat-1",
            context=context,
            get_message_by_telegram_message_id_fn=lambda _chat_id, _message_id: {
                "sender": "Stored Alice",
                "text": "Stored text",
            },
        )
    )
    assert resolved == {
        "sender": "Stored Alice",
        "text": "Stored text",
        "source": "history_lookup",
    }

    async def _fallback_extract(_reply_message, _context):
        return "fallback text", "fallback_ocr"

    service.extract_reply_target_text = _fallback_extract  # type: ignore[method-assign]
    fallback = asyncio.run(
        service.resolve_reply_target_context(
            message,
            chat_id="chat-1",
            context=context,
            get_message_by_telegram_message_id_fn=lambda _chat_id, _message_id: None,
        )
    )
    assert fallback == {
        "sender": "Alice",
        "text": "fallback text",
        "source": "fallback_ocr",
    }
