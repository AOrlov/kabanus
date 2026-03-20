import io
import json
import os
import stat
import time
import urllib.error
import urllib.parse

import pytest

from src.providers.errors import ProviderAuthError, ProviderConfigurationError
from src.providers.openai import OpenAIAuthManager


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


def _write_auth_file(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def test_auth_manager_uses_existing_access_token(tmp_path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(
        auth_file,
        {
            "access_token": "a1",
            "refresh_token": "r1",
            "expires_at": int(time.time()) + 3600,
        },
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
    _write_auth_file(auth_file, {"refresh_token": "r1"})

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


def test_auth_manager_refresh_writes_private_file_permissions(
    tmp_path, monkeypatch
) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, {"refresh_token": "r1"})

    def _fake_urlopen(req, timeout):
        _ = req
        _ = timeout
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
    mode = stat.S_IMODE(os.stat(auth_file).st_mode)
    if os.name != "nt":
        assert mode == 0o600


def test_auth_manager_reads_codex_style_nested_tokens(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(
        auth_file,
        {
            "tokens": {
                "access_token": "a-old",
                "refresh_token": "r-nested",
                "client_id": "cid-nested",
            }
        },
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


def test_auth_manager_reads_root_tokens_when_openai_block_exists(
    tmp_path, monkeypatch
) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(
        auth_file,
        {
            "openai": {"model": "gpt-5.3-codex"},
            "tokens": {
                "refresh_token": "r-mixed",
                "client_id": "cid-mixed",
                "token_url": "https://example.com/token",
            },
            "OPENAI_API_KEY": "",
        },
    )

    def _fake_urlopen(req, timeout):
        _ = timeout
        parsed = urllib.parse.parse_qs(req.data.decode("utf-8"))
        assert parsed.get("refresh_token") == ["r-mixed"]
        assert parsed.get("client_id") == ["cid-mixed"]
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

    assert manager.has_refresh_token() is True
    token = manager.get_access_token(force_refresh=True)

    assert token == "a-new"
    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["openai"]["access_token"] == "a-new"
    assert payload["openai"]["refresh_token"] == "r-new"


def test_auth_manager_handles_millisecond_expiry(tmp_path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(
        auth_file,
        {
            "tokens": {
                "access_token": "a1",
                "refresh_token": "r1",
                "expires": int((time.time() + 3600) * 1000),
            }
        },
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


def test_auth_manager_rejects_directory_path(tmp_path) -> None:
    with pytest.raises(ProviderConfigurationError, match="point to a file"):
        OpenAIAuthManager(
            str(tmp_path),
            refresh_url_default="https://example.com/token",
            client_id_default="",
            grant_type_default="refresh_token",
            leeway_secs=60,
            timeout_secs=5,
        )


def test_auth_manager_rejects_insecure_permissions(tmp_path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX file permissions are not enforced on Windows")
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"refresh_token": "r1"}), encoding="utf-8")
    auth_file.chmod(0o644)

    with pytest.raises(ProviderConfigurationError, match="permissions are too broad"):
        OpenAIAuthManager(
            str(auth_file),
            refresh_url_default="https://example.com/token",
            client_id_default="",
            grant_type_default="refresh_token",
            leeway_secs=60,
            timeout_secs=5,
        )


def test_auth_manager_redacts_http_error_details(tmp_path, monkeypatch) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, {"refresh_token": "r1"})

    def _fake_urlopen(req, timeout):
        _ = timeout
        raise urllib.error.HTTPError(
            req.full_url,
            401,
            "unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"refresh_token":"secret-token"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    manager = OpenAIAuthManager(
        str(auth_file),
        refresh_url_default="https://example.com/token",
        client_id_default="",
        grant_type_default="refresh_token",
        leeway_secs=60,
        timeout_secs=5,
    )

    with pytest.raises(ProviderAuthError) as exc_info:
        manager.get_access_token(force_refresh=True)

    assert "HTTP 401" in str(exc_info.value)
    assert "secret-token" not in str(exc_info.value)
