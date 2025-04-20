# whisper_provider.py
import whisper
from .model_provider import ModelProvider


class WhisperProvider(ModelProvider):
    def __init__(self):
        self.model = whisper.load_model("small")

    def transcribe(self, audio_path: str) -> str:
        result = self.model.transcribe(audio_path, language="ru")
        return result["text"].strip()

    def generate(self, prompt: str) -> str:
        raise NotImplementedError("Whisper does not support text generation.")
