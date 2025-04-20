# model_provider.py
class ModelProvider:
    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError

    def generate(self, prompt: str) -> str:
        raise NotImplementedError
