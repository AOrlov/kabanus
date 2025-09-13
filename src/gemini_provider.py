# gemini_provider.py
import json
import logging
import os
from datetime import datetime

from google import genai
from google.genai import types

from src import config, utils

from .model_provider import ModelProvider

logger = logging.getLogger(__name__)


class GeminiProvider(ModelProvider):

    def __init__(self, gemini_api_key: str, gemini_model: str):
        self.client = genai.Client()
        self.system_instructions = self._load_system_instructions()

    def _load_system_instructions(self):
        path = os.path.join(os.path.dirname(__file__), config.AI_SYSTEM_INSTRUCTIONS_PATH)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        response = self.client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[f"Transcribe this audio to {config.LANGUAGE} text.",
                      types.Part.from_bytes(
                          data=audio_bytes,
                          mime_type="audio/ogg",
            )],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=config.THINKING_BUDGET)
            )
        )

        return response.text.strip() if response.text else ""

    def generate(self, prompt: str) -> str:
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        response = self.client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instructions,
                thinking_config=types.ThinkingConfig(thinking_budget=config.THINKING_BUDGET),
                tools=[grounding_tool] if config.USE_GOOGLE_SEARCH else None,
            ),
        )
        return response.text.strip() if response.text else ""

    def parse_image_to_event(self, image_path: str) -> dict:
        with open(image_path, "rb") as f:
            image_data = f.read()

        response = self.client.models.generate_content(
            model='gemini-pro-vision',
            contents=[
                "Analyze this image and extract event information. " +
                "Provide a JSON response with the following fields: " +
                "title (string), date (YYYY-MM-DD), time (HH:MM), " +
                "location (string), description (string), " +
                "confidence (float between 0 and 1). " +
                "If any field is unclear, set it to null." +
                f"If there is no year, set it to current year ({datetime.now().year})",
                {"mime_type": "image/jpeg", "data": image_data}
            ],
            config=types.GenerateContentConfig(
                system_instruction=self.system_instructions,
                thinking_config=types.ThinkingConfig(thinking_budget=config.THINKING_BUDGET),
            ),
        )
        event_data = json.loads(utils.strip_markdown_to_json(response.text or ""))
        logger.info(f"Event data from model: {event_data}")

        return event_data

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        """Extracts readable content from image bytes and returns plain text."""
        response = self.client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[
                (
                    f"Extract all visible text from the image and, if helpful, "
                    f"briefly describe important visual content. Respond in {config.LANGUAGE}. "
                    f"Return plain text only without any markdown or JSON."
                ),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                system_instruction=self.system_instructions,
                thinking_config=types.ThinkingConfig(thinking_budget=config.THINKING_BUDGET),
            ),
        )
        return (response.text or "").strip()
