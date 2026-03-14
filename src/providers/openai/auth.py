"""OpenAI auth.json loading and refresh helpers."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.providers.errors import (
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderQuotaError,
)


@dataclass(frozen=True)
class OpenAIAuthSnapshot:
    access_token: str
    refresh_token: str
    expires_at: Optional[float]
    token_url: str
    client_id: str
    grant_type: str


@dataclass(frozen=True)
class _AuthDocument:
    root: Dict[str, Any]
    target: Dict[str, Any]
    section_name: Optional[str]


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
        self._path = self._validate_path(auth_json_path)
        self._refresh_url_default = refresh_url_default
        self._client_id_default = client_id_default
        self._grant_type_default = grant_type_default
        self._leeway_secs = max(0, int(leeway_secs))
        self._timeout_secs = max(1.0, float(timeout_secs))
        self._lock = threading.Lock()

    def has_refresh_token(self) -> bool:
        document = self._read_auth_json()
        data = document.target
        return bool(
            self._extract_text(data, "refresh_token")
            or self._extract_text(data, "tokens.refresh_token")
        )

    def get_access_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            document = self._read_auth_json()
            data = document.target
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
                raise ProviderConfigurationError(
                    "OpenAI auth.json is missing refresh_token",
                    provider="openai",
                )

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
                document=document,
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                expires_at=new_expires_at,
                token_url=token_url,
                client_id=client_id,
                grant_type=grant_type,
            )
            return new_access_token

    def _validate_path(self, auth_json_path: str) -> Path:
        raw_path = auth_json_path.strip()
        if not raw_path:
            raise ProviderConfigurationError(
                "OpenAI auth.json path is empty",
                provider="openai",
            )
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise ProviderConfigurationError(
                f"OpenAI auth.json does not exist: {path}",
                provider="openai",
            )
        if not path.is_file():
            raise ProviderConfigurationError(
                f"OpenAI auth.json path must point to a file: {path}",
                provider="openai",
            )
        self._assert_private_permissions(path)
        return path

    def _assert_private_permissions(self, path: Path) -> None:
        if os.name == "nt":
            return
        try:
            file_mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            raise ProviderConfigurationError(
                f"Failed to stat OpenAI auth.json: {path}",
                provider="openai",
            ) from exc
        if file_mode & 0o077:
            raise ProviderConfigurationError(
                "OpenAI auth.json permissions are too broad; expected 0600",
                provider="openai",
            )

    def _read_auth_json(self) -> _AuthDocument:
        try:
            with self._path.open("r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
        except OSError as exc:
            raise ProviderConfigurationError(
                f"Failed to read OpenAI auth.json: {self._path}",
                provider="openai",
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderConfigurationError(
                "OpenAI auth.json is not valid JSON",
                provider="openai",
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderConfigurationError(
                "OpenAI auth.json must contain a JSON object",
                provider="openai",
            )
        if isinstance(payload.get("openai"), dict):
            return _AuthDocument(
                root=payload,
                target=dict(payload["openai"]),
                section_name="openai",
            )
        return _AuthDocument(root=payload, target=dict(payload), section_name=None)

    def _write_auth_json(
        self,
        *,
        document: _AuthDocument,
        access_token: str,
        refresh_token: str,
        expires_at: Optional[float],
        token_url: str,
        client_id: str,
        grant_type: str,
    ) -> None:
        target = dict(document.root)
        payload_fields = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": int(expires_at) if expires_at is not None else None,
            "token_url": token_url,
            "client_id": client_id,
            "grant_type": grant_type,
        }
        if document.section_name == "openai":
            openai_block = dict(document.root.get("openai", {}))
            openai_block.update(payload_fields)
            target["openai"] = openai_block
        elif isinstance(document.root.get("tokens"), dict):
            tokens_block = dict(document.root["tokens"])
            tokens_block.update(payload_fields)
            target["tokens"] = tokens_block
        else:
            target.update(payload_fields)
        self._atomic_write_auth_json(target)

    def _atomic_write_auth_json(self, payload: Dict[str, Any]) -> None:
        parent_dir = self._path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        file_descriptor, temp_path = tempfile.mkstemp(
            prefix=".openai-auth-",
            suffix=".tmp",
            dir=parent_dir,
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
            os.replace(temp_path, self._path)
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass
            self._assert_private_permissions(self._path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _refresh(
        self, snapshot: OpenAIAuthSnapshot
    ) -> Tuple[str, str, Optional[float]]:
        payload = {
            "grant_type": snapshot.grant_type,
            "refresh_token": snapshot.refresh_token,
        }
        if snapshot.client_id:
            payload["client_id"] = snapshot.client_id
        request = urllib.request.Request(
            snapshot.token_url,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout_secs
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise ProviderQuotaError(
                    f"OpenAI token refresh failed with HTTP {exc.code}",
                    provider="openai",
                ) from exc
            raise ProviderAuthError(
                f"OpenAI token refresh failed with HTTP {exc.code}",
                provider="openai",
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderAuthError(
                "OpenAI token refresh request failed",
                provider="openai",
            ) from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderAuthError(
                "OpenAI token refresh response is not valid JSON",
                provider="openai",
            ) from exc
        if not isinstance(data, dict):
            raise ProviderAuthError(
                "OpenAI token refresh response must be a JSON object",
                provider="openai",
            )
        access_token = self._extract_text(data, "access_token")
        if not access_token:
            raise ProviderAuthError(
                "OpenAI token refresh response missing access_token",
                provider="openai",
            )
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
