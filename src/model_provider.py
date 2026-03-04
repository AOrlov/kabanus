# model_provider.py
class ModelProvider:
    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError

    def generate_stream(self, prompt: str):
        text = self.generate(prompt)
        if text:
            yield text

    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    def generate_low_cost(self, prompt: str) -> str:
        raise NotImplementedError

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        raise NotImplementedError

    def parse_image_to_event(self, image_path: str) -> dict:
        raise NotImplementedError

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        raise NotImplementedError
