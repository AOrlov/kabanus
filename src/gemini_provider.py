# gemini_provider.py
import google.generativeai as genai

from src.config import LANGUAGE

from .model_provider import ModelProvider


class GeminiProvider(ModelProvider):
    def __init__(self, gemini_api_key: str, gemini_model: str):
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel(model_name=gemini_model)

    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        response = self.model.generate_content(
            [
                {"mime_type": "audio/ogg", "data": audio_bytes},
                f"Transcribe this audio to {LANGUAGE} text.",
            ]
        )
        return response.text.strip()

    def generate(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text.strip()
