import argparse
import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Tuple

DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_AUTH_URL = "https://auth.openai.com/oauth/authorize"
DEFAULT_TOKEN_URL = "https://auth.openai.com/oauth/token"
DEFAULT_SCOPE = "openid profile email offline_access"
DEFAULT_REDIRECT_PORT = 1455
DEFAULT_REDIRECT_HOST = "localhost"
DEFAULT_REDIRECT_PATH = "/auth/callback"
DEFAULT_ORIGINATOR = "pi"
DEFAULT_MODEL = "gpt-5.3-codex"
DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _generate_pkce() -> Tuple[str, str]:
    verifier = _b64url_no_pad(secrets.token_bytes(64))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _extract_query_value(url: str, name: str) -> str:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if not qs and parsed.fragment:
        qs = urllib.parse.parse_qs(parsed.fragment)
    values = qs.get(name, [])
    return values[0] if values else ""


class _CallbackHandler(BaseHTTPRequestHandler):
    result = {"url": "", "error": ""}
    event = threading.Event()
    expected_state = ""
    expected_path = DEFAULT_REDIRECT_PATH
    success_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Authentication successful</title></head><body>"
        "<p>Authentication successful. Return to your terminal to continue.</p>"
        "</body></html>"
    )

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != _CallbackHandler.expected_path:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        code = _extract_query_value(self.path, "code")
        err = _extract_query_value(self.path, "error")
        returned_state = _extract_query_value(self.path, "state")
        _CallbackHandler.result["url"] = self.path
        if (
            returned_state
            and _CallbackHandler.expected_state
            and returned_state != _CallbackHandler.expected_state
        ):
            _CallbackHandler.result["error"] = "State mismatch"
            _CallbackHandler.event.set()
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"State mismatch")
            return
        if code or err:
            _CallbackHandler.event.set()
            self.send_response(200)
            if code:
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_CallbackHandler.success_html.encode("utf-8"))
                return
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"OAuth callback returned an error. Check terminal output."
            )
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"Callback received without code yet. Return to OpenAI login tab to continue."
            )

    def log_message(self, _format: str, *_args) -> None:
        return


def _run_local_callback_server(
    host: str, port: int, path: str, state: str, timeout_sec: int
) -> str:
    _CallbackHandler.event.clear()
    _CallbackHandler.result = {"url": "", "error": ""}
    _CallbackHandler.expected_path = path
    _CallbackHandler.expected_state = state
    server = HTTPServer((host, port), _CallbackHandler)
    server.timeout = 1
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        server.handle_request()
        if _CallbackHandler.event.is_set():
            break
    server.server_close()
    if not _CallbackHandler.event.is_set():
        raise RuntimeError("Timed out waiting for OAuth callback")
    if _CallbackHandler.result.get("error"):
        raise RuntimeError(_CallbackHandler.result["error"])
    return _CallbackHandler.result["url"]


def _exchange_code_for_tokens(
    *,
    token_url: str,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict:
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }
    req = urllib.request.Request(
        token_url,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = ""
        try:
            details = exc.read().decode("utf-8").strip()
        except Exception:
            details = ""
        msg = f"OAuth token exchange failed with HTTP {exc.code}"
        if details:
            msg += f": {details[:500]}"
        raise RuntimeError(msg) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OAuth token exchange request failed: {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OAuth token response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("OAuth token response must be a JSON object")
    return parsed


def _extract_account_id(access_token: str) -> str:
    parts = access_token.split(".")
    if len(parts) < 2:
        return ""
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return ""
    auth_claim = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        value = auth_claim.get("chatgpt_account_id")
        if isinstance(value, str):
            return value
    return ""


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def print_runtime_exports(auth_path: Path) -> None:
    print("export MODEL_PROVIDER=openai")
    print(f"export OPENAI_AUTH_JSON_PATH='{auth_path}'")
    print(f"export OPENAI_MODEL='{DEFAULT_MODEL}'")
    print(f"export OPENAI_LOW_COST_MODEL='{DEFAULT_MODEL}'")
    print(f"export OPENAI_REACTION_MODEL='{DEFAULT_MODEL}'")
    print(f"export OPENAI_TRANSCRIPTION_MODEL='{DEFAULT_TRANSCRIPTION_MODEL}'")


def _save_auth_json(
    *,
    path: Path,
    client_id: str,
    token_url: str,
    token_payload: dict,
) -> None:
    root = _load_json(path)
    tokens = (
        dict(root.get("tokens", {})) if isinstance(root.get("tokens"), dict) else {}
    )

    access_token = str(token_payload.get("access_token", "")).strip()
    refresh_token = str(token_payload.get("refresh_token", "")).strip()
    if not access_token or not refresh_token:
        raise RuntimeError("OAuth token response missing access_token or refresh_token")
    id_token = str(token_payload.get("id_token", "")).strip()
    expires_in = token_payload.get("expires_in")
    expires_at = None
    try:
        if expires_in is not None:
            expires_at = int(time.time() + float(expires_in))
    except (TypeError, ValueError):
        expires_at = None

    tokens.update(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "account_id": _extract_account_id(access_token)
            or tokens.get("account_id", ""),
            "token_url": token_url,
            "client_id": client_id,
            "grant_type": "refresh_token",
            "expires_at": expires_at,
        }
    )
    root["tokens"] = tokens
    root["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if "OPENAI_API_KEY" not in root:
        root["OPENAI_API_KEY"] = ""

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_path = tempfile.mkstemp(
        prefix=".openai-codex-",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        try:
            os.fchmod(file_descriptor, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_obj:
            json.dump(root, file_obj, ensure_ascii=False, indent=2)
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


def _build_auth_url(
    *,
    auth_url: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    originator: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": originator,
        }
    )
    return f"{auth_url}?{query}"


def _parse_authorization_input(value: str) -> Tuple[str, str]:
    stripped = value.strip()
    if not stripped:
        return "", ""
    parsed = urllib.parse.urlparse(stripped)
    if parsed.scheme and parsed.netloc:
        code = _extract_query_value(stripped, "code")
        state = _extract_query_value(stripped, "state")
        return code, state
    if "#" in stripped:
        left, right = stripped.split("#", 1)
        return left.strip(), right.strip()
    if "code=" in stripped:
        qs = urllib.parse.parse_qs(stripped)
        code_values = qs.get("code", [])
        state_values = qs.get("state", [])
        code = code_values[0] if code_values else ""
        state = state_values[0] if state_values else ""
        return code, state
    return stripped, ""


def run_oauth(args: argparse.Namespace) -> int:
    auth_path = Path(args.auth_file).expanduser().resolve()
    redirect_path = (
        args.redirect_path
        if args.redirect_path.startswith("/")
        else f"/{args.redirect_path}"
    )
    redirect_uri = f"http://{args.redirect_host}:{args.redirect_port}{redirect_path}"
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(24)
    login_url = _build_auth_url(
        auth_url=args.auth_url,
        client_id=args.client_id,
        redirect_uri=redirect_uri,
        scope=args.scope,
        state=state,
        code_challenge=code_challenge,
        originator=args.originator,
    )

    if args.remote:
        print("Remote/VPS mode: open this URL in your LOCAL browser:\n")
        print(login_url)
        print("\nAfter login, paste full redirect URL:")
        callback_url = input("> ").strip()
    else:
        print("Opening browser for OpenAI Codex OAuth...")
        webbrowser.open(login_url)
        print(
            f"If callback does not auto-complete, paste redirect URL manually. Callback: {redirect_uri}"
        )
        try:
            callback_path = _run_local_callback_server(
                host=args.redirect_host,
                port=args.redirect_port,
                path=redirect_path,
                state=state,
                timeout_sec=args.timeout_sec,
            )
            callback_url = (
                f"http://{args.redirect_host}:{args.redirect_port}{callback_path}"
            )
        except Exception:
            print("Auto-callback not received. Paste redirect URL:")
            callback_url = input("> ").strip()

    error = _extract_query_value(callback_url, "error")
    if error:
        raise RuntimeError(f"OAuth authorization failed: {error}")
    code, returned_state = _parse_authorization_input(callback_url)
    if not code:
        code = _extract_query_value(callback_url, "code")
    if not returned_state:
        returned_state = _extract_query_value(callback_url, "state")
    if returned_state and returned_state != state:
        raise RuntimeError("OAuth state mismatch")
    if not code:
        raise RuntimeError(f"OAuth callback missing code. Callback was: {callback_url}")

    token_payload = _exchange_code_for_tokens(
        token_url=args.token_url,
        client_id=args.client_id,
        code=code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )
    _save_auth_json(
        path=auth_path,
        client_id=args.client_id,
        token_url=args.token_url,
        token_payload=token_payload,
    )
    print(f"OAuth credentials saved to: {auth_path}")
    print("\nSet env for bot runtime:")
    print_runtime_exports(auth_path)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenAI Codex OAuth login for bot auth.json"
    )
    parser.add_argument(
        "--auth-file",
        default=".secrets/auth.json",
        help="Path to auth.json to write/update.",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Remote/VPS mode: manual redirect URL paste.",
    )
    parser.add_argument(
        "--client-id", default=DEFAULT_CLIENT_ID, help="OAuth client_id."
    )
    parser.add_argument(
        "--auth-url", default=DEFAULT_AUTH_URL, help="OAuth authorize endpoint."
    )
    parser.add_argument(
        "--token-url", default=DEFAULT_TOKEN_URL, help="OAuth token endpoint."
    )
    parser.add_argument("--scope", default=DEFAULT_SCOPE, help="OAuth scope.")
    parser.add_argument(
        "--redirect-host", default=DEFAULT_REDIRECT_HOST, help="OAuth callback host."
    )
    parser.add_argument(
        "--redirect-port",
        type=int,
        default=DEFAULT_REDIRECT_PORT,
        help="OAuth callback port.",
    )
    parser.add_argument(
        "--redirect-path", default=DEFAULT_REDIRECT_PATH, help="OAuth callback path."
    )
    parser.add_argument(
        "--originator", default=DEFAULT_ORIGINATOR, help="OAuth originator."
    )
    parser.add_argument(
        "--timeout-sec", type=int, default=180, help="Local callback wait timeout."
    )
    args = parser.parse_args()

    code = run_oauth(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
