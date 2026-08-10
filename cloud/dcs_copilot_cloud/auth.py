"""User authentication with short-lived access and rotating refresh tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import Database, RefreshCredential, User, utc_now

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1


class AuthenticationError(ValueError):
    pass


class AccountAlreadyExists(AuthenticationError):
    pass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str | None
    device_id: str
    development: bool = False


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class AuthService:
    def __init__(
        self,
        database: Database,
        *,
        signing_key: str,
        issuer: str = "dcs-copilot",
        audience: str = "dcs-copilot-client",
        access_token_seconds: int = 900,
        refresh_token_days: int = 30,
        dev_access_token: str = "",
    ) -> None:
        if len(signing_key.encode()) < 32:
            raise ValueError("DCS_COPILOT_AUTH_SIGNING_KEY must be at least 32 bytes")
        if access_token_seconds <= 0:
            raise ValueError("AUTH_ACCESS_TOKEN_SECONDS must be positive")
        if refresh_token_days <= 0:
            raise ValueError("AUTH_REFRESH_TOKEN_DAYS must be positive")
        self.database = database
        self._signing_key = signing_key.encode()
        self._issuer = issuer
        self._audience = audience
        self._access_token_seconds = access_token_seconds
        self._refresh_token_days = refresh_token_days
        self._dev_access_token = dev_access_token

    async def register(
        self, email: str, password: str, device_id: str
    ) -> tuple[str, TokenPair]:
        normalized_email = normalize_email(email)
        validate_password(password)
        normalized_device = validate_device_id(device_id)
        user_id = str(uuid4())
        user = User(
            id=user_id,
            email=normalized_email,
            password_hash=hash_password(password),
        )
        async with self.database.session() as session:
            session.add(user)
            try:
                await session.flush()
                pair = self._issue_pair(session, user_id, normalized_device)
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise AccountAlreadyExists("account already exists") from exc
        return user_id, pair

    async def login(
        self, email: str, password: str, device_id: str
    ) -> tuple[str, TokenPair]:
        normalized_email = normalize_email(email)
        normalized_device = validate_device_id(device_id)
        async with self.database.session() as session:
            user = await session.scalar(
                select(User).where(User.email == normalized_email)
            )
            if user is None or not verify_password(password, user.password_hash):
                raise AuthenticationError("invalid email or password")
            pair = self._issue_pair(session, user.id, normalized_device)
            await session.commit()
            return user.id, pair

    async def refresh(self, refresh_token: str, device_id: str) -> TokenPair:
        token_id, secret = split_refresh_token(refresh_token)
        normalized_device = validate_device_id(device_id)
        async with self.database.session() as session:
            credential = await session.scalar(
                select(RefreshCredential)
                .where(RefreshCredential.id == token_id)
                .with_for_update()
            )
            if (
                credential is None
                or credential.device_id != normalized_device
                or credential.revoked_at is not None
                or as_utc(credential.expires_at) <= utc_now()
                or not hmac.compare_digest(
                    credential.secret_hash, hash_refresh_secret(secret)
                )
            ):
                raise AuthenticationError("invalid refresh token")
            credential.revoked_at = utc_now()
            pair = self._issue_pair(session, credential.user_id, normalized_device)
            await session.commit()
            return pair

    async def revoke_refresh(self, refresh_token: str, user_id: str) -> None:
        token_id, secret = split_refresh_token(refresh_token)
        async with self.database.session() as session:
            credential = await session.scalar(
                select(RefreshCredential)
                .where(RefreshCredential.id == token_id)
                .with_for_update()
            )
            if (
                credential is None
                or credential.user_id != user_id
                or not hmac.compare_digest(
                    credential.secret_hash, hash_refresh_secret(secret)
                )
            ):
                raise AuthenticationError("invalid refresh token")
            if credential.revoked_at is None:
                credential.revoked_at = utc_now()
            await session.commit()

    def verify_access_token(
        self, token: str, expected_device_id: str | None = None
    ) -> AuthenticatedPrincipal:
        if not token or len(token) > 4_096:
            raise AuthenticationError("access token is malformed")
        if self._dev_access_token and hmac.compare_digest(
            token, self._dev_access_token
        ):
            if expected_device_id is None:
                raise AuthenticationError("device ID is required")
            return AuthenticatedPrincipal(
                None, validate_device_id(expected_device_id), True
            )
        payload = decode_jwt(token, self._signing_key)
        now = int(datetime.now(UTC).timestamp())
        required = {"sub", "device_id", "exp", "iat", "iss", "aud", "type"}
        if not required.issubset(payload):
            raise AuthenticationError("access token is missing required claims")
        if payload["iss"] != self._issuer or payload["aud"] != self._audience:
            raise AuthenticationError("access token issuer or audience is invalid")
        if payload["type"] != "access":
            raise AuthenticationError("token is not an access token")
        if (
            not isinstance(payload["exp"], int)
            or isinstance(payload["exp"], bool)
            or payload["exp"] <= now
        ):
            raise AuthenticationError("access token has expired")
        if (
            not isinstance(payload["iat"], int)
            or isinstance(payload["iat"], bool)
            or payload["iat"] > now + 30
        ):
            raise AuthenticationError("access token issued-at claim is invalid")
        user_id = payload["sub"]
        device_id = payload["device_id"]
        if not isinstance(user_id, str) or not user_id:
            raise AuthenticationError("access token subject is invalid")
        if not isinstance(device_id, str):
            raise AuthenticationError("access token device is invalid")
        device_id = validate_device_id(device_id)
        if expected_device_id is not None and not hmac.compare_digest(
            device_id, validate_device_id(expected_device_id)
        ):
            raise AuthenticationError("access token is bound to another device")
        return AuthenticatedPrincipal(user_id, device_id)

    def _issue_pair(self, session: Any, user_id: str, device_id: str) -> TokenPair:
        now = utc_now()
        expires_in = self._access_token_seconds
        payload = {
            "sub": user_id,
            "device_id": device_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
            "iss": self._issuer,
            "aud": self._audience,
            "type": "access",
            "jti": str(uuid4()),
        }
        access_token = encode_jwt(payload, self._signing_key)
        refresh_id = str(uuid4())
        refresh_secret = secrets.token_urlsafe(32)
        session.add(
            RefreshCredential(
                id=refresh_id,
                user_id=user_id,
                device_id=device_id,
                secret_hash=hash_refresh_secret(refresh_secret),
                expires_at=now + timedelta(days=self._refresh_token_days),
            )
        )
        return TokenPair(
            access_token,
            f"{refresh_id}.{refresh_secret}",
            "bearer",
            expires_in,
        )


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 320 or not EMAIL_PATTERN.fullmatch(value):
        raise AuthenticationError("invalid email address")
    return value


def validate_password(password: str) -> None:
    if len(password) < 10 or len(password) > 256:
        raise AuthenticationError("password must contain 10 to 256 characters")


def validate_device_id(device_id: str) -> str:
    value = device_id.strip()
    if not value or len(value) > 128:
        raise AuthenticationError("device ID must contain 1 to 128 characters")
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=32,
    )
    return "$".join(
        (
            "scrypt",
            str(PASSWORD_SCRYPT_N),
            str(PASSWORD_SCRYPT_R),
            str(PASSWORD_SCRYPT_P),
            _base64url(salt),
            _base64url(digest),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    if len(password) > 256:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=_base64url_decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_base64url(digest), expected)


def hash_refresh_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def split_refresh_token(token: str) -> tuple[str, str]:
    try:
        token_id, secret = token.split(".", 1)
    except ValueError as exc:
        raise AuthenticationError("invalid refresh token") from exc
    if not token_id or not secret or len(token) > 256:
        raise AuthenticationError("invalid refresh token")
    return token_id, secret


def encode_jwt(payload: dict[str, Any], key: bytes) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _base64url(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    )
    encoded_payload = _base64url(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = _base64url(hmac.digest(key, signing_input, "sha256"))
    return f"{encoded_header}.{encoded_payload}.{signature}"


def decode_jwt(token: str, key: bytes) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}".encode()
        expected = _base64url(hmac.digest(key, signing_input, "sha256"))
        if not hmac.compare_digest(signature, expected):
            raise AuthenticationError("access token signature is invalid")
        header = json.loads(_base64url_decode(encoded_header))
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthenticationError("access token is malformed") from exc
    if header != {"alg": "HS256", "typ": "JWT"} or not isinstance(payload, dict):
        raise AuthenticationError("access token header or payload is invalid")
    return payload


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
