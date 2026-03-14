from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_documents_capability_routing_contract() -> None:
    readme = _read("README.md")

    for required in (
        "AI_PROVIDER_TEXT_GENERATION",
        "AI_PROVIDER_STREAMING_TEXT_GENERATION",
        "AI_PROVIDER_AUDIO_TRANSCRIPTION",
        "AI_PROVIDER_EVENT_PARSING",
        "GEMINI_LOW_COST_MODEL",
        "src/providers/capabilities.py",
        "src/providers/errors.py",
    ):
        assert required in readme

    assert "Provider fallback:" not in readme
    assert "were removed in favor of provider packages" in readme


def test_architecture_doc_references_new_provider_boundaries() -> None:
    overview = _read("docs/architecture/refactor-overview.md")

    for required in (
        "src/providers/capabilities.py",
        "src/providers/errors.py",
        "src/providers/openai/*",
        "src/providers/gemini/*",
        "ProviderCapabilityError",
        "ProviderConfigurationError",
    ):
        assert required in overview

    assert "were removed." in overview


def test_claude_notes_match_provider_contracts() -> None:
    claude = _read("CLAUDE.md")

    assert "src/providers/capabilities.py" in claude
    assert "src/providers/errors.py" in claude
    assert "fail fast on unsupported combinations" in claude
    assert "src/model_provider.py" not in claude
    assert "Preserve provider fallback semantics" not in claude
