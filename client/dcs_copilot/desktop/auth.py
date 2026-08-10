"""Desktop account API and OS credential-vault integration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import keyring

from dcs_copilot.network.connection import validate_cloud_url

SERVICE_NAME = "DCS Copilot"


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: str | None = None


class CredentialStore(Protocol):
    def get(self, device_id: str) -> str | None: ...

    def set(self, device_id: str, refresh_token: str) -> None: ...

    def delete(self, device_id: str) -> None: ...


class KeyringCredentialStore:
    """Keep refresh credentials in Windows Credential Manager (or OS equivalent)."""

    def __init__(self, namespace: str = "") -> None:
        self.service_name = (
            f"{SERVICE_NAME} ({namespace})" if namespace else SERVICE_NAME
        )

    def get(self, device_id: str) -> str | None:
        return keyring.get_password(self.service_name, device_id)

    def set(self, device_id: str, refresh_token: str) -> None:
        keyring.set_password(self.service_name, device_id, refresh_token)

    def delete(self, device_id: str) -> None:
        try:
            keyring.delete_password(self.service_name, device_id)
        except keyring.errors.PasswordDeleteError:
            pass


def auth_base_url(realtime_url: str) -> str:
    try:
        validate_cloud_url(realtime_url)
    except ValueError as exc:
        raise AuthError(str(exc)) from exc
    parsed = urlparse(realtime_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme)
    if scheme is None or not parsed.netloc:
        raise AuthError("Cloud URL must start with ws:// or wss://")
    return urlunparse((scheme, parsed.netloc, "/v1/auth", "", "", ""))


class AuthClient:
    def __init__(self, realtime_url: str, *, timeout: float = 10.0) -> None:
        self.base_url = auth_base_url(realtime_url)
        self.timeout = timeout

    def login(self, email: str, password: str, device_id: str) -> TokenPair:
        return self._pair(
            self._request(
                "/token",
                {"email": email, "password": password, "device_id": device_id},
            )
        )

    def register(self, email: str, password: str, device_id: str) -> TokenPair:
        return self._pair(
            self._request(
                "/register",
                {"email": email, "password": password, "device_id": device_id},
            )
        )

    def refresh(self, refresh_token: str, device_id: str) -> TokenPair:
        return self._pair(
            self._request(
                "/refresh",
                {"refresh_token": refresh_token, "device_id": device_id},
            )
        )

    def logout(self, pair: TokenPair) -> None:
        self._request(
            "/logout",
            {"refresh_token": pair.refresh_token},
            access_token=pair.access_token,
            expect_json=False,
        )

    def _request(
        self,
        path: str,
        body: dict[str, str],
        *,
        access_token: str | None = None,
        expect_json: bool = True,
    ) -> dict[str, object]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = Request(
            self.base_url + path,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except HTTPError as exc:
            detail = "Authentication request failed"
            try:
                document = json.loads(exc.read())
                if isinstance(document, dict) and isinstance(
                    document.get("detail"), str
                ):
                    detail = document["detail"]
            except (ValueError, json.JSONDecodeError):
                pass
            raise AuthError(detail) from exc
        except (OSError, URLError) as exc:
            raise AuthError(f"Cannot reach the DCS Copilot service: {exc}") from exc
        if not expect_json:
            return {}
        try:
            document = json.loads(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError(
                "Service returned an invalid authentication response"
            ) from exc
        if not isinstance(document, dict):
            raise AuthError("Service returned an invalid authentication response")
        return document

    @staticmethod
    def _pair(document: dict[str, object]) -> TokenPair:
        access = document.get("access_token")
        refresh = document.get("refresh_token")
        expires = document.get("expires_in")
        user_id = document.get("user_id")
        if (
            not isinstance(access, str)
            or not isinstance(refresh, str)
            or not isinstance(expires, int)
            or isinstance(expires, bool)
        ):
            raise AuthError("Service returned an incomplete authentication response")
        return TokenPair(
            access,
            refresh,
            expires,
            user_id if isinstance(user_id, str) else None,
        )


class StoredAuthSession:
    def __init__(
        self,
        realtime_url: str,
        device_id: str,
        store: CredentialStore | None = None,
    ) -> None:
        self.client = AuthClient(realtime_url)
        self.device_id = device_id
        self.store = store or KeyringCredentialStore(self.client.base_url)
        self.current: TokenPair | None = None

    def login(self, email: str, password: str, *, register: bool = False) -> TokenPair:
        pair = (
            self.client.register(email, password, self.device_id)
            if register
            else self.client.login(email, password, self.device_id)
        )
        self._save(pair)
        return pair

    def restore(self) -> TokenPair | None:
        refresh_token = self.store.get(self.device_id)
        if not refresh_token:
            return None
        try:
            pair = self.client.refresh(refresh_token, self.device_id)
        except AuthError:
            self.store.delete(self.device_id)
            raise
        self._save(pair)
        return pair

    def refresh(self) -> str:
        pair = self.restore()
        if pair is None:
            raise AuthError("Sign in is required")
        return pair.access_token

    def logout(self) -> None:
        if self.current is not None:
            try:
                self.client.logout(self.current)
            finally:
                self.store.delete(self.device_id)
                self.current = None
        else:
            self.store.delete(self.device_id)

    def _save(self, pair: TokenPair) -> None:
        self.store.set(self.device_id, pair.refresh_token)
        self.current = pair
