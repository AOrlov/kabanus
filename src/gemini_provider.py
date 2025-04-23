# gemini_provider.py
import os
import google.generativeai as genai
from .model_provider import ModelProvider
from src.config import CALENDAR_AI_PROVIDER

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


class GeminiProvider(ModelProvider):
    def __init__(self):
        self.model = genai.GenerativeModel(CALENDAR_AI_PROVIDER)

    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        response = self.model.generate_content(
            [
                {"mime_type": "audio/ogg", "data": audio_bytes},
                "Transcribe this audio to Russian text.",
            ]
        )
        return response.text.strip()

    def generate(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text.strip()
