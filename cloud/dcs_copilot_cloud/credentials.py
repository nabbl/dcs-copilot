"""Secret providers used by source, hosted, and packaged backend deployments."""

from __future__ import annotations

import os
from typing import Protocol

OPENAI_CREDENTIAL_SERVICE = "MARA Backend"
OPENAI_CREDENTIAL_ACCOUNT = "openai-api-key"


class CredentialStore(Protocol):
    def get_openai_key(self) -> str | None: ...

    def set_openai_key(self, value: str) -> None: ...

    def delete_openai_key(self) -> None: ...


class EnvironmentCredentialStore:
    """Hosted/development adapter; environment access stays at this boundary."""

    def get_openai_key(self) -> str | None:
        return os.getenv("OPENAI_API_KEY", "").strip() or None

    def set_openai_key(self, value: str) -> None:
        raise RuntimeError("environment credentials are read-only")

    def delete_openai_key(self) -> None:
        raise RuntimeError("environment credentials are read-only")


class KeyringCredentialStore:
    """Use Windows Credential Manager (or the platform keyring in development)."""

    def get_openai_key(self) -> str | None:
        import keyring

        try:
            return keyring.get_password(
                OPENAI_CREDENTIAL_SERVICE, OPENAI_CREDENTIAL_ACCOUNT
            )
        except keyring.errors.KeyringError:
            return None

    def set_openai_key(self, value: str) -> None:
        import keyring

        keyring.set_password(
            OPENAI_CREDENTIAL_SERVICE, OPENAI_CREDENTIAL_ACCOUNT, value
        )

    def delete_openai_key(self) -> None:
        import keyring

        try:
            keyring.delete_password(
                OPENAI_CREDENTIAL_SERVICE, OPENAI_CREDENTIAL_ACCOUNT
            )
        except keyring.errors.PasswordDeleteError:
            pass


class ChainedCredentialStore:
    """Prefer the OS vault for local installs and retain hosted env support."""

    def __init__(self, *stores: CredentialStore) -> None:
        self.stores = stores

    def get_openai_key(self) -> str | None:
        for store in self.stores:
            value = store.get_openai_key()
            if value:
                return value
        return None

    def set_openai_key(self, value: str) -> None:
        if not self.stores:
            raise RuntimeError("no writable credential store configured")
        self.stores[0].set_openai_key(value)

    def delete_openai_key(self) -> None:
        if self.stores:
            self.stores[0].delete_openai_key()


class MemoryCredentialStore:
    """Deterministic secret store for automated tests."""

    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def get_openai_key(self) -> str | None:
        return self.value

    def set_openai_key(self, value: str) -> None:
        self.value = value

    def delete_openai_key(self) -> None:
        self.value = None
