import argparse
import getpass
import json
import os
import tempfile
import webbrowser
from pathlib import Path
from typing import Callable, Dict


OPENAI_KEYS_URL = "https://platform.openai.com/api-keys"
DEFAULT_MODEL = "gpt-5.3-codex"


def verify_openai(api_key: str, model: str) -> None:
    """Run a minimal live request to validate key + model."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "input_text", "text": "ping"}]}],
        max_output_tokens=1,
    )


def maybe_open_openai_keys_page(
    *,
    auto_open_browser: bool = False,
    prompt_open_browser: Callable[[], bool] | None = None,
) -> None:
    should_open = auto_open_browser
    if not should_open and prompt_open_browser is not None:
        should_open = bool(prompt_open_browser())
    if not should_open:
        return
    opened = webbrowser.open(OPENAI_KEYS_URL)
    if opened:
        print(f"Opened: {OPENAI_KEYS_URL}")
    else:
        print(f"Please open manually: {OPENAI_KEYS_URL}")


def print_runtime_exports(
    payload: Dict[str, Dict[str, str]], *, auth_file: str
) -> None:
    openai = payload.get("openai", {})
    print("export MODEL_PROVIDER=openai")
    print(f"export OPENAI_AUTH_JSON_PATH='{auth_file}'")
    print(f"export OPENAI_MODEL='{openai.get('model', DEFAULT_MODEL)}'")
    print(
        f"export OPENAI_LOW_COST_MODEL='{openai.get('low_cost_model', openai.get('model', DEFAULT_MODEL))}'"
    )
    print(
        f"export OPENAI_REACTION_MODEL='{openai.get('reaction_model', openai.get('low_cost_model', openai.get('model', DEFAULT_MODEL)))}'"
    )


def _default_prompt_secret(label: str) -> str:
    return getpass.getpass(f"{label}: ").strip()


def _default_prompt_input(name: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{name}{suffix}: ").strip()
    return value or default


def _default_prompt_overwrite(path: str) -> bool:
    answer = input(f"{path} exists. Overwrite? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _default_prompt_open_browser() -> bool:
    answer = input("Open OpenAI API keys page in browser now? [Y/n]: ").strip().lower()
    return answer in {"", "y", "yes"}


def _resolve_auth_file_path(auth_file: str) -> Path:
    path = Path(auth_file).expanduser().resolve()
    if path.exists() and not path.is_file():
        raise ValueError(f"Auth file path must point to a file: {path}")
    return path


def _write_private_json(path: Path, payload: Dict[str, Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_path = tempfile.mkstemp(
        prefix=".openai-onboard-",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        try:
            os.fchmod(file_descriptor, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)
            file_obj.write("\n")
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def onboard(
    auth_file: str,
    *,
    no_verify: bool = False,
    prompt_secret: Callable[[str], str] | None = None,
    prompt_input: Callable[[str, str], str] | None = None,
    prompt_overwrite: Callable[[str], bool] | None = None,
) -> int:
    prompt_secret = prompt_secret or _default_prompt_secret
    prompt_input = prompt_input or _default_prompt_input
    prompt_overwrite = prompt_overwrite or _default_prompt_overwrite

    try:
        path = _resolve_auth_file_path(auth_file)
    except ValueError as exc:
        print(str(exc))
        return 2
    if path.exists() and not prompt_overwrite(str(path)):
        print("Aborted: auth file already exists and overwrite was declined.")
        return 1

    api_key = (prompt_secret("OpenAI API key") or "").strip()
    if not api_key:
        print("OpenAI API key is required.")
        return 2

    model = (prompt_input("OPENAI_MODEL", DEFAULT_MODEL) or "").strip() or DEFAULT_MODEL
    low_cost_model = (
        prompt_input("OPENAI_LOW_COST_MODEL", model) or ""
    ).strip() or model
    reaction_model = (
        prompt_input("OPENAI_REACTION_MODEL", low_cost_model) or ""
    ).strip() or low_cost_model

    if not no_verify:
        try:
            verify_openai(api_key, model)
        except Exception as exc:
            print(f"OpenAI verification failed: {exc}")
            return 2

    payload = {
        "openai": {
            "api_key": api_key,
            "model": model,
            "low_cost_model": low_cost_model,
            "reaction_model": reaction_model,
        }
    }

    _write_private_json(path, payload)
    print(f"Saved OpenAI auth settings to: {path}")
    print_runtime_exports(payload, auth_file=str(path))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive OpenAI API key onboarding"
    )
    parser.add_argument(
        "--auth-file",
        default="scripts/openai.auth.json",
        help="Path to write auth JSON.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip live OpenAI verification request.",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open OpenAI API keys page automatically.",
    )
    args = parser.parse_args()

    maybe_open_openai_keys_page(
        auto_open_browser=args.open_browser,
        prompt_open_browser=_default_prompt_open_browser,
    )
    raise SystemExit(
        onboard(
            args.auth_file,
            no_verify=args.no_verify,
        )
    )


if __name__ == "__main__":
    main()
