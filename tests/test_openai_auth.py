import json
import time
import urllib.parse

from src.openai_auth import OpenAIAuthManager


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_auth_manager_uses_existing_access_token(tmp_path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "a1",
                "refresh_token": "r1",
                "expires_at": int(time.time()) + 3600,
            }
        ),
        encoding="utf-8",
    )
    manager = OpenAIAuthManager(
        str(auth_file),
        refresh_url_default="https://example.com/token",
        client_id_default="",
        grant_type_default="refresh_token",
        leeway_secs=60,
        timeout_secs=5,
    )
    assert manager.get_access_token() == "a1"


def test_auth_manager_refreshes_and_writes_file(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"refresh_token": "r1"}), encoding="utf-8")

    def _fake_urlopen(req, timeout):
        assert timeout == 5
        assert req.full_url == "https://example.com/token"
        assert req.headers.get("Content-type") == "application/x-www-form-urlencoded"
        parsed = urllib.parse.parse_qs(req.data.decode("utf-8"))
        assert parsed.get("grant_type") == ["refresh_token"]
        assert parsed.get("refresh_token") == ["r1"]
        assert parsed.get("client_id") == ["cid"]
        return _FakeResponse(
            {
                "access_token": "a2",
                "refresh_token": "r2",
                "expires_in": 1200,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    manager = OpenAIAuthManager(
        str(auth_file),
        refresh_url_default="https://example.com/token",
        client_id_default="cid",
        grant_type_default="refresh_token",
        leeway_secs=60,
        timeout_secs=5,
    )
    token = manager.get_access_token()
    assert token == "a2"
    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["access_token"] == "a2"
    assert payload["refresh_token"] == "r2"


def test_auth_manager_reads_codex_style_nested_tokens(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "a-old",
                    "refresh_token": "r-nested",
                    "client_id": "cid-nested",
                }
            }
        ),
        encoding="utf-8",
    )

    def _fake_urlopen(req, timeout):
        _ = timeout
        parsed = urllib.parse.parse_qs(req.data.decode("utf-8"))
        assert parsed.get("refresh_token") == ["r-nested"]
        assert parsed.get("client_id") == ["cid-nested"]
        return _FakeResponse(
            {
                "access_token": "a-new",
                "refresh_token": "r-new",
                "expires_in": 1200,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    manager = OpenAIAuthManager(
        str(auth_file),
        refresh_url_default="https://example.com/token",
        client_id_default="cid-default",
        grant_type_default="refresh_token",
        leeway_secs=999999,
        timeout_secs=5,
    )
    token = manager.get_access_token(force_refresh=True)
    assert token == "a-new"
    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["tokens"]["access_token"] == "a-new"
    assert payload["tokens"]["refresh_token"] == "r-new"


def test_auth_manager_handles_millisecond_expiry(tmp_path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "a1",
                    "refresh_token": "r1",
                    "expires": int((time.time() + 3600) * 1000),
                }
            }
        ),
        encoding="utf-8",
    )
    manager = OpenAIAuthManager(
        str(auth_file),
        refresh_url_default="https://example.com/token",
        client_id_default="",
        grant_type_default="refresh_token",
        leeway_secs=60,
        timeout_secs=5,
    )
    assert manager.get_access_token() == "a1"
