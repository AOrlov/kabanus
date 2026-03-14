import json
import os
import stat

from scripts import onboard_openai


def _prompt_input_factory(values):
    items = iter(values)

    def _prompt(_name: str, default: str = "") -> str:
        try:
            return next(items)
        except StopIteration:
            return default

    return _prompt


def test_onboard_writes_json_on_success(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "openai.auth.json"
    monkeypatch.setattr(onboard_openai, "verify_openai", lambda api_key, model: None)
    rc = onboard_openai.onboard(
        str(auth_file),
        prompt_secret=lambda _: "sk-test",
        prompt_input=_prompt_input_factory(
            ["gpt-5.3-codex", "gpt-5.3-codex", "gpt-5.3-codex"]
        ),
        prompt_overwrite=lambda _: True,
    )
    assert rc == 0
    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["openai"]["api_key"] == "sk-test"
    assert payload["openai"]["model"] == "gpt-5.3-codex"
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(auth_file).st_mode)
        assert mode == 0o600


def test_onboard_respects_overwrite_rejection(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "openai.auth.json"
    auth_file.write_text('{"openai":{"api_key":"old"}}', encoding="utf-8")
    monkeypatch.setattr(onboard_openai, "verify_openai", lambda api_key, model: None)
    rc = onboard_openai.onboard(
        str(auth_file),
        prompt_secret=lambda _: "sk-new",
        prompt_input=_prompt_input_factory(
            ["gpt-5.3-codex", "gpt-5.3-codex", "gpt-5.3-codex"]
        ),
        prompt_overwrite=lambda _: False,
    )
    assert rc == 1
    assert "old" in auth_file.read_text(encoding="utf-8")


def test_onboard_verify_failure_blocks_write(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "openai.auth.json"

    def _fail_verify(api_key: str, model: str) -> None:
        raise RuntimeError("bad key")

    monkeypatch.setattr(onboard_openai, "verify_openai", _fail_verify)
    rc = onboard_openai.onboard(
        str(auth_file),
        prompt_secret=lambda _: "sk-test",
        prompt_input=_prompt_input_factory(
            ["gpt-5.3-codex", "gpt-5.3-codex", "gpt-5.3-codex"]
        ),
        prompt_overwrite=lambda _: True,
    )
    assert rc == 2
    assert not auth_file.exists()


def test_onboard_no_verify_writes(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "openai.auth.json"
    called = {"verify": 0}

    def _verify(api_key: str, model: str) -> None:
        called["verify"] += 1

    monkeypatch.setattr(onboard_openai, "verify_openai", _verify)
    rc = onboard_openai.onboard(
        str(auth_file),
        no_verify=True,
        prompt_secret=lambda _: "sk-test",
        prompt_input=_prompt_input_factory(
            ["gpt-5.3-codex", "gpt-5.3-codex", "gpt-5.3-codex"]
        ),
        prompt_overwrite=lambda _: True,
    )
    assert rc == 0
    assert called["verify"] == 0
    assert auth_file.exists()


def test_onboard_model_fallback_chain(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "openai.auth.json"
    monkeypatch.setattr(onboard_openai, "verify_openai", lambda api_key, model: None)
    rc = onboard_openai.onboard(
        str(auth_file),
        prompt_secret=lambda _: "sk-test",
        prompt_input=_prompt_input_factory(["", "", ""]),
        prompt_overwrite=lambda _: True,
    )
    assert rc == 0
    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["openai"]["model"] == "gpt-5.3-codex"
    assert payload["openai"]["low_cost_model"] == "gpt-5.3-codex"
    assert payload["openai"]["reaction_model"] == "gpt-5.3-codex"


def test_onboard_rejects_directory_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(onboard_openai, "verify_openai", lambda api_key, model: None)
    rc = onboard_openai.onboard(
        str(tmp_path),
        prompt_secret=lambda _: "sk-test",
        prompt_input=_prompt_input_factory(
            ["gpt-5.3-codex", "gpt-5.3-codex", "gpt-5.3-codex"]
        ),
        prompt_overwrite=lambda _: True,
    )
    assert rc == 2


def test_print_runtime_exports_contains_expected_keys(capsys) -> None:
    onboard_openai.print_runtime_exports(
        {
            "openai": {
                "api_key": "sk-test",
                "model": "gpt-5.3-codex",
                "low_cost_model": "gpt-5.3-codex",
                "reaction_model": "gpt-5.3-codex",
            }
        },
        auth_file="/tmp/openai.auth.json",
    )
    captured = capsys.readouterr()
    assert "MODEL_PROVIDER=openai" in captured.out
    assert "OPENAI_AUTH_JSON_PATH='/tmp/openai.auth.json'" in captured.out
    assert "OPENAI_API_KEY" not in captured.out
    assert "sk-test" not in captured.out


def test_maybe_open_openai_keys_page_auto(monkeypatch, capsys) -> None:
    opened = {"url": ""}

    def _fake_open(url: str) -> bool:
        opened["url"] = url
        return True

    monkeypatch.setattr(onboard_openai.webbrowser, "open", _fake_open)
    onboard_openai.maybe_open_openai_keys_page(auto_open_browser=True)
    assert opened["url"] == onboard_openai.OPENAI_KEYS_URL
    assert "Opened:" in capsys.readouterr().out


def test_maybe_open_openai_keys_page_prompt_decline(monkeypatch) -> None:
    opened = {"called": False}

    def _fake_open(_url: str) -> bool:
        opened["called"] = True
        return True

    monkeypatch.setattr(onboard_openai.webbrowser, "open", _fake_open)
    onboard_openai.maybe_open_openai_keys_page(
        auto_open_browser=False,
        prompt_open_browser=lambda: False,
    )
    assert opened["called"] is False
