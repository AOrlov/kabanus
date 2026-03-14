import json
import os
import stat
from pathlib import Path

from scripts import openai_codex_oauth


def test_build_auth_url_contains_pkce_and_state() -> None:
    url = openai_codex_oauth._build_auth_url(
        auth_url="https://auth.openai.com/oauth/authorize",
        client_id="cid",
        redirect_uri="http://localhost:1455/auth/callback",
        scope="openid profile email offline_access",
        state="st",
        code_challenge="cc",
        originator="pi",
    )
    assert "client_id=cid" in url
    assert "state=st" in url
    assert "code_challenge=cc" in url
    assert "code_challenge_method=S256" in url
    assert "codex_cli_simplified_flow=true" in url
    assert "id_token_add_organizations=true" in url
    assert "originator=pi" in url


def test_save_auth_json_updates_tokens_block(tmp_path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text("{}", encoding="utf-8")
    openai_codex_oauth._save_auth_json(
        path=auth_file,
        client_id="cid",
        token_url="https://auth.openai.com/oauth/token",
        token_payload={
            "access_token": "a.b.c",
            "refresh_token": "rt",
            "id_token": "id",
            "expires_in": 1000,
        },
    )
    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["tokens"]["refresh_token"] == "rt"
    assert payload["tokens"]["client_id"] == "cid"
    assert payload["tokens"]["token_url"] == "https://auth.openai.com/oauth/token"
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(auth_file).st_mode)
        assert mode == 0o600


def test_extract_query_value_reads_fragment() -> None:
    url = "http://localhost:1455/#code=abc123&state=st1"
    assert openai_codex_oauth._extract_query_value(url, "code") == "abc123"
