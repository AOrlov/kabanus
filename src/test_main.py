import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import main
import io


class TestBotStartup(unittest.IsolatedAsyncioTestCase):
    async def test_start_command(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        await main.start(update, context)
        update.message.reply_text.assert_awaited_with(
            "Hello! I am your speech-to-text bot."
        )

    async def test_voice_handler(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        await main.handle_voice(update, context)
        update.message.reply_text.assert_awaited_with("Voice received!")


class TestTranscription(unittest.IsolatedAsyncioTestCase):
    @patch("main.transcribe_audio")
    async def test_voice_handler_success(self, mock_transcribe):
        mock_transcribe.return_value = "Пример текста"
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.chat.send_action = AsyncMock()
        update.message.voice = MagicMock()
        update.message.voice.file_id = "file_id"
        context = MagicMock()
        file_mock = AsyncMock()
        file_mock.download_to_drive = AsyncMock()
        context.bot.get_file = AsyncMock(return_value=file_mock)
        await main.handle_voice(update, context)
        update.message.reply_text.assert_awaited_with("Пример текста")

    @patch("main.transcribe_audio", side_effect=Exception("fail"))
    async def test_voice_handler_failure(self, mock_transcribe):
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.chat.send_action = AsyncMock()
        update.message.voice = MagicMock()
        update.message.voice.file_id = "file_id"
        context = MagicMock()
        file_mock = AsyncMock()
        file_mock.download_to_drive = AsyncMock()
        context.bot.get_file = AsyncMock(return_value=file_mock)
        await main.handle_voice(update, context)
        update.message.reply_text.assert_awaited_with(
            "Извините, не удалось распознать речь."
        )

    @patch("main.notify_admin")
    @patch("main.transcribe_audio", side_effect=Exception("fail"))
    async def test_voice_handler_critical_error_notifies_admin(
        self, mock_transcribe, mock_notify_admin
    ):
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.chat.send_action = AsyncMock()
        update.message.voice = MagicMock()
        update.message.voice.file_id = "file_id"
        context = MagicMock()
        file_mock = AsyncMock()
        file_mock.download_to_drive = AsyncMock()
        context.bot.get_file = AsyncMock(return_value=file_mock)
        await main.handle_voice(update, context)
        mock_notify_admin.assert_awaited()


class TestEndToEnd(unittest.IsolatedAsyncioTestCase):
    @patch("main.transcribe_audio")
    async def test_successful_voice_message(self, mock_transcribe):
        mock_transcribe.return_value = "Тестовая расшифровка"
        update = MagicMock()
        update.effective_user.id = 1
        update.message.reply_text = AsyncMock()
        update.message.chat.send_action = AsyncMock()
        update.message.voice = MagicMock()
        update.message.voice.file_id = "file_id"
        context = MagicMock()
        file_mock = AsyncMock()
        file_mock.download_to_drive = AsyncMock()
        context.bot.get_file = AsyncMock(return_value=file_mock)
        await main.handle_voice(update, context)
        update.message.reply_text.assert_awaited_with("Тестовая расшифровка")

    @patch("main.transcribe_audio", side_effect=Exception("fail"))
    @patch("main.notify_admin")
    async def test_critical_error_triggers_admin_notification(
        self, mock_notify_admin, mock_transcribe
    ):
        update = MagicMock()
        update.effective_user.id = 2
        update.message.reply_text = AsyncMock()
        update.message.chat.send_action = AsyncMock()
        update.message.voice = MagicMock()
        update.message.voice.file_id = "file_id"
        context = MagicMock()
        file_mock = AsyncMock()
        file_mock.download_to_drive = AsyncMock()
        context.bot.get_file = AsyncMock(return_value=file_mock)
        await main.handle_voice(update, context)
        update.message.reply_text.assert_awaited_with(
            "Извините, не удалось распознать речь."
        )
        mock_notify_admin.assert_awaited()


if __name__ == "__main__":
    unittest.main()
