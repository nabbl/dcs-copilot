"""OS-vault storage for local backend provider credentials."""

from __future__ import annotations

from typing import Protocol

import keyring

OPENAI_CREDENTIAL_SERVICE = "MARA Backend"
OPENAI_CREDENTIAL_ACCOUNT = "openai-api-key"


class BackendCredentialStore(Protocol):
    def get_openai_key(self) -> str | None: ...

    def set_openai_key(self, value: str) -> None: ...

    def delete_openai_key(self) -> None: ...


class KeyringBackendCredentialStore:
    def get_openai_key(self) -> str | None:
        try:
            return keyring.get_password(
                OPENAI_CREDENTIAL_SERVICE, OPENAI_CREDENTIAL_ACCOUNT
            )
        except keyring.errors.KeyringError:
            return None

    def set_openai_key(self, value: str) -> None:
        try:
            keyring.set_password(
                OPENAI_CREDENTIAL_SERVICE, OPENAI_CREDENTIAL_ACCOUNT, value
            )
        except keyring.errors.KeyringError as exc:
            raise OSError(
                "The operating-system credential vault is unavailable"
            ) from exc

    def delete_openai_key(self) -> None:
        try:
            keyring.delete_password(
                OPENAI_CREDENTIAL_SERVICE, OPENAI_CREDENTIAL_ACCOUNT
            )
        except keyring.errors.PasswordDeleteError:
            pass


class MemoryBackendCredentialStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def get_openai_key(self) -> str | None:
        return self.value

    def set_openai_key(self, value: str) -> None:
        self.value = value

    def delete_openai_key(self) -> None:
        self.value = None
