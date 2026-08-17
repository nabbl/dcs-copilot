"""Verified, cached provisioning for large local backend model assets."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int, int], None]


class DownloadResponse(Protocol):
    status: int

    def __enter__(self) -> Self: ...

    def __exit__(self, *args: object) -> object: ...

    def read(self, size: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ModelAsset:
    name: str
    url: str
    size: int
    sha256: str


KOKORO_MODEL = ModelAsset(
    "kokoro-v1.0.onnx",
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx",
    325_532_387,
    "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
)
KOKORO_VOICES = ModelAsset(
    "voices-v1.0.bin",
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin",
    28_214_398,
    "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
)


class ModelProvisionError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def provision_asset(
    asset: ModelAsset,
    directory: Path,
    *,
    progress: ProgressCallback | None = None,
    retries: int = 3,
    opener: Callable[..., DownloadResponse] = urlopen,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / asset.name
    if (
        destination.is_file()
        and destination.stat().st_size == asset.size
        and _digest(destination) == asset.sha256
    ):
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            offset = partial.stat().st_size if partial.is_file() else 0
            if offset > asset.size:
                partial.unlink()
                offset = 0
            headers = {"User-Agent": "MARA-model-provisioner/1"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            response = opener(Request(asset.url, headers=headers), timeout=300)
            status = int(getattr(response, "status", 200))
            append = bool(offset and status == 206)
            if not append:
                offset = 0
            with response, partial.open("ab" if append else "wb") as output:
                downloaded = offset
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(asset.name, downloaded, asset.size)
            if partial.stat().st_size != asset.size:
                raise ModelProvisionError(
                    f"{asset.name} has size {partial.stat().st_size}, expected {asset.size}"
                )
            if _digest(partial) != asset.sha256:
                partial.unlink(missing_ok=True)
                raise ModelProvisionError(f"{asset.name} failed SHA-256 verification")
            partial.replace(destination)
            return destination
        except Exception as exc:  # noqa: BLE001 - retry isolates network/filesystem errors
            last_error = exc
            LOGGER.warning(
                "model provisioning attempt %d/%d failed for %s: %s",
                attempt,
                retries,
                asset.name,
                exc,
            )
            if attempt < retries:
                time.sleep(min(attempt, 2))
    raise ModelProvisionError(f"Could not provision {asset.name}: {last_error}")


def provision_kokoro(
    directory: Path, *, progress: ProgressCallback | None = None
) -> tuple[Path, Path]:
    return (
        provision_asset(KOKORO_MODEL, directory, progress=progress),
        provision_asset(KOKORO_VOICES, directory, progress=progress),
    )
