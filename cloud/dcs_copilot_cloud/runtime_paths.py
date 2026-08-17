"""Stable backend paths for source, hosted, and frozen application layouts."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path
    config: Path
    data: Path
    models: Path
    logs: Path
    runtime: Path
    assets: Path

    @classmethod
    def discover(cls, root: Path | None = None) -> RuntimePaths:
        if root is None:
            configured = os.getenv("MARA_DATA_DIR", "").strip()
            if configured:
                root = Path(configured).expanduser()
            elif sys.platform == "win32":
                root = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "MARA"
            else:
                root = Path.home() / ".local" / "share" / "mara"
        asset_root = (
            Path(sys._MEIPASS) / "assets"
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
            else Path(__file__).resolve().parent / "assets"
        )
        return cls(
            root=root,
            config=root / "config",
            data=root / "data",
            models=root / "models",
            logs=root / "logs",
            runtime=root / "runtime",
            assets=asset_root,
        )

    def ensure(self) -> RuntimePaths:
        for directory in (
            self.config,
            self.data,
            self.models,
            self.logs,
            self.runtime,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data / 'mara.db'}"

    @property
    def backend_log(self) -> Path:
        return self.logs / "backend.log"
