"""Safe, repeatable DCS-BIOS installation for the selected Saved Games tree."""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath
from urllib.error import URLError
from urllib.request import Request, urlopen

DCS_BIOS_VERSION = "0.11.5"
DCS_BIOS_URL = (
    "https://github.com/DCS-Skunkworks/dcs-bios/releases/download/"
    f"v{DCS_BIOS_VERSION}/DCS-BIOS_v{DCS_BIOS_VERSION}.zip"
)
DCS_BIOS_SHA256 = "96091c9321773b5c2d4be088e28bb596f341bc2f560f71aba8868db348a1921d"
EXPORT_LINE = r"dofile(lfs.writedir()..[[Scripts\DCS-BIOS\BIOS.lua]])"
SPATIAL_EXPORT_LINE = r"dofile(lfs.writedir()..[[Scripts\MARA\MARASpatial.lua]])"
INDICATION_EXPORT_LINE = r"dofile(lfs.writedir()..[[Scripts\MARA\MARAIndications.lua]])"


class DcsSetupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DcsSetupResult:
    dcs_path: Path
    bios_path: Path
    export_path: Path
    backup_paths: tuple[Path, ...]
    version: str
    spatial_export_path: Path


@dataclass(frozen=True, slots=True)
class IndicationProbeSetupResult:
    dcs_path: Path
    probe_path: Path
    export_path: Path
    backup_paths: tuple[Path, ...]


def inspect_installation(dcs_path: Path) -> tuple[bool, str]:
    bios = dcs_path / "Scripts" / "DCS-BIOS"
    export = dcs_path / "Scripts" / "Export.lua"
    if not (bios / "BIOS.lua").is_file():
        return False, "DCS-BIOS is not installed"
    if not (bios / "doc" / "json" / "MetadataStart.json").is_file():
        return False, "DCS-BIOS control metadata is missing"
    if not (dcs_path / "Scripts" / "MARA" / "MARASpatial.lua").is_file():
        return False, "MARA spatial export is not installed"
    if not export.is_file():
        return False, "Export.lua is missing"
    try:
        export_text = export.read_text(encoding="utf-8-sig")
        configured = EXPORT_LINE in export_text and SPATIAL_EXPORT_LINE in export_text
    except OSError as exc:
        return False, f"Export.lua cannot be read: {exc}"
    return (
        (True, f"DCS-BIOS {DCS_BIOS_VERSION} is ready")
        if configured
        else (
            False,
            "DCS-BIOS or MARA spatial export is not enabled in Export.lua",
        )
    )


def inspect_indication_probe(dcs_path: Path) -> tuple[bool, str]:
    probe = dcs_path / "Scripts" / "MARA" / "MARAIndications.lua"
    export = dcs_path / "Scripts" / "Export.lua"
    if not probe.is_file():
        return False, "MARA indication probe is not installed"
    if not export.is_file():
        return False, "Export.lua is missing"
    try:
        configured = INDICATION_EXPORT_LINE in export.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return False, f"Export.lua cannot be read: {exc}"
    return (
        (True, "MARA indication probe is ready")
        if configured
        else (False, "MARA indication probe is not enabled in Export.lua")
    )


def install_indication_probe(dcs_path: Path) -> IndicationProbeSetupResult:
    """Explicitly install the development-only loopback indication probe."""

    dcs_path = dcs_path.expanduser().resolve()
    if not dcs_path.is_dir():
        raise DcsSetupError(f"DCS Saved Games folder does not exist: {dcs_path}")
    if not dcs_path.name.lower().startswith("dcs"):
        raise DcsSetupError("Select a DCS, DCS.openbeta, or DCS.openalpha folder")

    scripts = dcs_path / "Scripts"
    probe_dir = scripts / "MARA"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_path = probe_dir / "MARAIndications.lua"
    packaged = (
        files("dcs_copilot.resources").joinpath("MARAIndications.lua").read_bytes()
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backups: list[Path] = []
    if probe_path.is_file() and probe_path.read_bytes() != packaged:
        backup = _available_backup(
            probe_dir / f"MARAIndications.lua.backup-{timestamp}"
        )
        shutil.copy2(probe_path, backup)
        backups.append(backup)
    if not probe_path.is_file() or probe_path.read_bytes() != packaged:
        temporary_probe = probe_path.with_suffix(".lua.tmp")
        temporary_probe.write_bytes(packaged)
        temporary_probe.replace(probe_path)

    export_path = scripts / "Export.lua"
    existing = ""
    if export_path.is_file():
        existing = export_path.read_text(encoding="utf-8-sig")
        if INDICATION_EXPORT_LINE not in existing:
            backup = _available_backup(scripts / f"Export.lua.backup-{timestamp}")
            shutil.copy2(export_path, backup)
            backups.append(backup)
    if INDICATION_EXPORT_LINE not in existing:
        separator = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
        updated = existing + separator + INDICATION_EXPORT_LINE + "\n"
        temporary_export = export_path.with_suffix(".lua.tmp")
        temporary_export.write_text(updated, encoding="utf-8", newline="\n")
        temporary_export.replace(export_path)

    ready, detail = inspect_indication_probe(dcs_path)
    if not ready:
        raise DcsSetupError(detail)
    return IndicationProbeSetupResult(
        dcs_path=dcs_path,
        probe_path=probe_path,
        export_path=export_path,
        backup_paths=tuple(backups),
    )


def download_dcs_bios() -> bytes:
    request = Request(DCS_BIOS_URL, headers={"User-Agent": "DCS-Copilot-Installer"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read(128 * 1024 * 1024 + 1)
    except (OSError, URLError) as exc:
        raise DcsSetupError(f"DCS-BIOS download failed: {exc}") from exc
    if len(payload) > 128 * 1024 * 1024:
        raise DcsSetupError("DCS-BIOS archive is unexpectedly large")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != DCS_BIOS_SHA256:
        raise DcsSetupError(
            "DCS-BIOS archive checksum does not match the pinned release"
        )
    return payload


def install_dcs_bios(dcs_path: Path, archive: bytes | None = None) -> DcsSetupResult:
    dcs_path = dcs_path.expanduser().resolve()
    if not dcs_path.is_dir():
        raise DcsSetupError(f"DCS Saved Games folder does not exist: {dcs_path}")
    if not dcs_path.name.lower().startswith("dcs"):
        raise DcsSetupError("Select a DCS, DCS.openbeta, or DCS.openalpha folder")
    payload = archive if archive is not None else download_dcs_bios()
    if hashlib.sha256(payload).hexdigest() != DCS_BIOS_SHA256:
        raise DcsSetupError(
            "DCS-BIOS archive checksum does not match the pinned release"
        )

    scripts = dcs_path / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backups: list[Path] = []
    mara_dir = scripts / "MARA"
    mara_dir.mkdir(parents=True, exist_ok=True)
    spatial_export_path = mara_dir / "MARASpatial.lua"
    spatial_payload = (
        files("dcs_copilot.resources").joinpath("MARASpatial.lua").read_bytes()
    )
    if (
        not spatial_export_path.is_file()
        or spatial_export_path.read_bytes() != spatial_payload
    ):
        if spatial_export_path.is_file():
            backup = _available_backup(mara_dir / f"MARASpatial.lua.backup-{timestamp}")
            shutil.copy2(spatial_export_path, backup)
            backups.append(backup)
        temporary_spatial = spatial_export_path.with_suffix(".lua.tmp")
        temporary_spatial.write_bytes(spatial_payload)
        temporary_spatial.replace(spatial_export_path)
    bios_path = scripts / "DCS-BIOS"

    with tempfile.TemporaryDirectory(prefix="dcs-copilot-bios-") as temporary:
        staging = Path(temporary)
        _safe_extract(payload, staging)
        source = staging / "DCS-BIOS"
        if not (source / "BIOS.lua").is_file():
            raise DcsSetupError("DCS-BIOS archive has an unexpected layout")
        if bios_path.exists():
            backup = _available_backup(scripts / f"DCS-BIOS.backup-{timestamp}")
            bios_path.replace(backup)
            backups.append(backup)
        try:
            shutil.copytree(source, bios_path)
        except Exception:
            if backups and not bios_path.exists():
                backups[-1].replace(bios_path)
                backups.pop()
            raise

    export_path = scripts / "Export.lua"
    existing = ""
    if export_path.is_file():
        existing = export_path.read_text(encoding="utf-8-sig")
        if EXPORT_LINE not in existing or SPATIAL_EXPORT_LINE not in existing:
            backup = _available_backup(scripts / f"Export.lua.backup-{timestamp}")
            shutil.copy2(export_path, backup)
            backups.append(backup)
    missing_lines = [
        line for line in (EXPORT_LINE, SPATIAL_EXPORT_LINE) if line not in existing
    ]
    if missing_lines:
        separator = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
        updated = existing + separator + "\n".join(missing_lines) + "\n"
        temporary_export = export_path.with_suffix(".lua.tmp")
        temporary_export.write_text(updated, encoding="utf-8", newline="\n")
        temporary_export.replace(export_path)

    ready, detail = inspect_installation(dcs_path)
    if not ready:
        raise DcsSetupError(detail)
    return DcsSetupResult(
        dcs_path,
        bios_path,
        export_path,
        tuple(backups),
        DCS_BIOS_VERSION,
        spatial_export_path,
    )


def _safe_extract(payload: bytes, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise DcsSetupError("DCS-BIOS download is not a valid ZIP archive") from exc
    total = 0
    with archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise DcsSetupError("DCS-BIOS archive contains an unsafe path")
            total += info.file_size
            if total > 512 * 1024 * 1024:
                raise DcsSetupError("DCS-BIOS archive expands beyond the safety limit")
        archive.extractall(destination)


def _available_backup(candidate: Path) -> Path:
    if not candidate.exists():
        return candidate
    for number in range(2, 1_000):
        numbered = candidate.with_name(f"{candidate.name}-{number}")
        if not numbered.exists():
            return numbered
    raise DcsSetupError(f"Cannot allocate a backup name below {candidate.parent}")
