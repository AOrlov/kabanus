import json
import os
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


@dataclass
class OpenAIAuthSnapshot:
    access_token: str
    refresh_token: str
    expires_at: Optional[float]
    token_url: str
    client_id: str
    grant_type: str


class OpenAIAuthManager:
    def __init__(
        self,
        auth_json_path: str,
        *,
        refresh_url_default: str,
        client_id_default: str,
        grant_type_default: str,
        leeway_secs: int,
        timeout_secs: float,
    ) -> None:
        self._path = os.path.abspath(os.path.expanduser(auth_json_path))
        self._refresh_url_default = refresh_url_default
        self._client_id_default = client_id_default
        self._grant_type_default = grant_type_default
        self._leeway_secs = max(0, int(leeway_secs))
        self._timeout_secs = max(1.0, float(timeout_secs))
        self._lock = threading.Lock()

    def get_access_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            data, is_nested = self._read_auth_json()
            token = (
                self._extract_text(data, "access_token")
                or self._extract_text(data, "tokens.access_token")
                or self._extract_text(data, "api_key")
                or self._extract_text(data, "OPENAI_API_KEY")
            )
            refresh_token = self._extract_text(
                data, "refresh_token"
            ) or self._extract_text(data, "tokens.refresh_token")
            expires_at = self._parse_expires_at(data)
            token_url = (
                self._extract_text(data, "token_url")
                or self._extract_text(data, "tokens.token_url")
                or self._refresh_url_default
            )
            client_id = (
                self._extract_text(data, "client_id")
                or self._extract_text(data, "tokens.client_id")
                or self._client_id_default
            )
            grant_type = (
                self._extract_text(data, "grant_type")
                or self._extract_text(data, "tokens.grant_type")
                or self._grant_type_default
            )

            if token and not force_refresh and not self._is_expiring_soon(expires_at):
                return token
            if not refresh_token:
                raise RuntimeError("auth.json is missing refresh_token")

            snapshot = OpenAIAuthSnapshot(
                access_token=token or "",
                refresh_token=refresh_token,
                expires_at=expires_at,
                token_url=token_url,
                client_id=client_id,
                grant_type=grant_type,
            )
            new_access_token, new_refresh_token, new_expires_at = self._refresh(
                snapshot
            )
            self._write_auth_json(
                data=data,
                is_nested=is_nested,
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                expires_at=new_expires_at,
                token_url=token_url,
                client_id=client_id,
                grant_type=grant_type,
            )
            return new_access_token

    def _read_auth_json(self) -> Tuple[Dict[str, Any], bool]:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except OSError as exc:
            raise RuntimeError(f"Failed to read auth file {self._path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"auth.json is invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("auth.json must be a JSON object")
        if isinstance(payload.get("openai"), dict):
            return payload["openai"], True
        return payload, False

    def _write_auth_json(
        self,
        *,
        data: Dict[str, Any],
        is_nested: bool,
        access_token: str,
        refresh_token: str,
        expires_at: Optional[float],
        token_url: str,
        client_id: str,
        grant_type: str,
    ) -> None:
        target: Dict[str, Any]
        if is_nested:
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    root = json.load(f)
            except (OSError, json.JSONDecodeError):
                root = {}
            if not isinstance(root, dict):
                root = {}
            target = dict(root)
            openai_block = (
                dict(target.get("openai", {}))
                if isinstance(target.get("openai"), dict)
                else {}
            )
            openai_block.update(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": int(expires_at) if expires_at is not None else None,
                    "token_url": token_url,
                    "client_id": client_id,
                    "grant_type": grant_type,
                }
            )
            target["openai"] = openai_block
        else:
            target = dict(data)
            if isinstance(target.get("tokens"), dict):
                tokens_block = dict(target["tokens"])
                tokens_block.update(
                    {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_at": (
                            int(expires_at) if expires_at is not None else None
                        ),
                        "token_url": token_url,
                        "client_id": client_id,
                        "grant_type": grant_type,
                    }
                )
                target["tokens"] = tokens_block
            else:
                target.update(
                    {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_at": (
                            int(expires_at) if expires_at is not None else None
                        ),
                        "token_url": token_url,
                        "client_id": client_id,
                        "grant_type": grant_type,
                    }
                )
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(target, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def _refresh(
        self, snapshot: OpenAIAuthSnapshot
    ) -> Tuple[str, str, Optional[float]]:
        payload = {
            "grant_type": snapshot.grant_type,
            "refresh_token": snapshot.refresh_token,
        }
        if snapshot.client_id:
            payload["client_id"] = snapshot.client_id
        req = urllib.request.Request(
            snapshot.token_url,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_secs) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = ""
            try:
                details = exc.read().decode("utf-8").strip()
            except Exception:
                details = ""
            msg = f"Token refresh failed with HTTP {exc.code}"
            if details:
                msg += f": {details[:500]}"
            raise RuntimeError(msg) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Token refresh request failed: {exc}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Token refresh response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Token refresh response must be a JSON object")
        access_token = self._extract_text(data, "access_token")
        if not access_token:
            raise RuntimeError("Token refresh response missing access_token")
        refresh_token = (
            self._extract_text(data, "refresh_token") or snapshot.refresh_token
        )
        expires_at = self._parse_expires_at(data)
        if expires_at is None:
            expires_in = data.get("expires_in")
            if expires_in is not None:
                try:
                    expires_at = time.time() + float(expires_in)
                except (TypeError, ValueError):
                    expires_at = None
        return access_token, refresh_token, expires_at

    def _extract_text(self, data: Dict[str, Any], key: str) -> str:
        value = self._get_path(data, key)
        if value is None:
            return ""
        return str(value).strip()

    def _get_path(self, data: Dict[str, Any], path: str) -> Any:
        current: Any = data
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _parse_expires_at(self, data: Dict[str, Any]) -> Optional[float]:
        raw = self._get_path(data, "expires_at")
        if raw is None:
            raw = self._get_path(data, "tokens.expires_at")
        if raw is None:
            raw = self._get_path(data, "expires")
        if raw is None:
            raw = self._get_path(data, "tokens.expires")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            value = float(raw)
            return value / 1000.0 if value > 10_000_000_000 else value
        if isinstance(raw, str):
            text_value = raw.strip()
            if not text_value:
                return None
            try:
                numeric = float(text_value)
                return numeric / 1000.0 if numeric > 10_000_000_000 else numeric
            except ValueError:
                pass
            try:
                # Accept RFC3339-ish timestamps.
                return datetime.fromisoformat(
                    text_value.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                return None
        return None

    def _is_expiring_soon(self, expires_at: Optional[float]) -> bool:
        if expires_at is None:
            return False
        return expires_at <= (time.time() + self._leeway_secs)
