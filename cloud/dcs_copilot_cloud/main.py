"""MARA backend command line for source and standalone deployments."""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import logging
import secrets
from collections.abc import Sequence
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import uvicorn

from .config import LOCAL_DEVELOPMENT_SIGNING_KEY, CloudSettings
from .credentials import KeyringCredentialStore
from .runtime_paths import RuntimePaths


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="MaraBackend")
    commands = root.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="run the MARA HTTP/WebSocket backend")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--config", type=Path, default=None)
    serve.add_argument("--log-level", default=None)
    credential = commands.add_parser(
        "credentials", help="manage local secrets in the OS credential vault"
    )
    credential.add_argument("action", choices=("status", "set-openai", "delete-openai"))
    return root


def _load_non_secret_config(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("backend config must be a JSON object")
    forbidden = {"openai_api_key", "api_key", "token", "auth_token"}
    if forbidden.intersection(key.lower() for key in document):
        raise ValueError("secrets must be stored with `MaraBackend credentials`")
    return document


def _settings(args: argparse.Namespace) -> CloudSettings:
    document = _load_non_secret_config(args.config)
    settings = CloudSettings.from_env()
    allowed: dict[str, type] = {
        "host": str,
        "port": int,
        "database_url": str,
        "log_level": str,
        "deployment": str,
        "stt_provider": str,
        "stt_model": str,
        "llm_provider": str,
        "llm_model": str,
        "llm_max_output_tokens": int,
        "tts_provider": str,
        "tts_model": str,
        "tts_voice": str,
    }
    updates: dict[str, Any] = {}
    for name, value in document.items():
        expected = allowed.get(name)
        if expected is None:
            continue
        if not isinstance(value, expected) or (
            expected is int and isinstance(value, bool)
        ):
            raise ValueError(f"backend config field {name!r} has the wrong type")
        updates[name] = value
    if args.host is not None:
        updates["host"] = args.host
    if args.port is not None:
        updates["port"] = args.port
    if args.log_level is not None:
        updates["log_level"] = args.log_level.lower()
    configured = replace(settings, **updates)
    if configured.deployment not in {"local", "remote", "hosted"}:
        raise ValueError("deployment must be local, remote, or hosted")
    return configured


def _configure_file_logging(paths: RuntimePaths, level: str) -> None:
    handler = RotatingFileHandler(
        paths.backend_log,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.setLevel(level.upper())
    logging.getLogger().addHandler(handler)


def _secure_non_loopback(settings: CloudSettings, paths: RuntimePaths) -> CloudSettings:
    try:
        loopback = (
            settings.host.lower() == "localhost"
            or ipaddress.ip_address(settings.host).is_loopback
        )
    except ValueError:
        loopback = False
    if loopback:
        return settings
    signing_key = settings.auth_signing_key
    if signing_key == LOCAL_DEVELOPMENT_SIGNING_KEY:
        key_file = paths.config / "auth-signing.key"
        if key_file.is_file():
            signing_key = key_file.read_text(encoding="utf-8").strip()
        else:
            signing_key = secrets.token_urlsafe(48)
            key_file.write_text(signing_key, encoding="utf-8")
            try:
                key_file.chmod(0o600)
            except OSError:
                pass
    return replace(settings, dev_access_token="", auth_signing_key=signing_key)


def _credentials(action: str) -> int:
    store = KeyringCredentialStore()
    if action == "status":
        print(
            "OpenAI credential configured"
            if store.get_openai_key()
            else "OpenAI credential missing"
        )
    elif action == "delete-openai":
        store.delete_openai_key()
        print("OpenAI credential deleted")
    else:
        value = getpass.getpass("OpenAI API key: ").strip()
        if not value:
            raise ValueError("OpenAI API key cannot be empty")
        store.set_openai_key(value)
        print("OpenAI credential saved in the OS credential vault")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "credentials":
        return _credentials(args.action)
    if args.command is None:
        args = parser().parse_args(["serve"])
    paths = RuntimePaths.discover().ensure()
    settings = _secure_non_loopback(_settings(args), paths)
    _configure_file_logging(paths, settings.log_level)
    from .app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
        ws_max_size=2 * 1024 * 1024,
        ws_max_queue=16,
        ws_per_message_deflate=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
