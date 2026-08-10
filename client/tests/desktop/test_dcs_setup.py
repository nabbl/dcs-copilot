from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import dcs_copilot.desktop.dcs_setup as setup


def archive() -> bytes:
    value = io.BytesIO()
    with zipfile.ZipFile(value, "w") as output:
        output.writestr("DCS-BIOS/BIOS.lua", "-- bios")
        output.writestr("DCS-BIOS/doc/json/MetadataStart.json", "{}")
    return value.getvalue()


def test_install_preserves_export_and_is_repeatable(
    tmp_path: Path, monkeypatch
) -> None:
    payload = archive()
    monkeypatch.setattr(setup, "DCS_BIOS_SHA256", hashlib.sha256(payload).hexdigest())
    dcs = tmp_path / "DCS.openbeta"
    scripts = dcs / "Scripts"
    scripts.mkdir(parents=True)
    export = scripts / "Export.lua"
    export.write_text("dofile('Tacview.lua')\n", encoding="utf-8")

    first = setup.install_dcs_bios(dcs, payload)
    assert (first.bios_path / "BIOS.lua").is_file()
    text = export.read_text(encoding="utf-8")
    assert "Tacview.lua" in text
    assert text.count(setup.EXPORT_LINE) == 1
    assert any(
        path.name.startswith("Export.lua.backup-") for path in first.backup_paths
    )

    second = setup.install_dcs_bios(dcs, payload)
    assert export.read_text(encoding="utf-8").count(setup.EXPORT_LINE) == 1
    assert any(path.name.startswith("DCS-BIOS.backup-") for path in second.backup_paths)


def test_rejects_non_dcs_target(tmp_path: Path, monkeypatch) -> None:
    payload = archive()
    monkeypatch.setattr(setup, "DCS_BIOS_SHA256", hashlib.sha256(payload).hexdigest())
    target = tmp_path / "Documents"
    target.mkdir()
    try:
        setup.install_dcs_bios(target, payload)
    except setup.DcsSetupError as exc:
        assert "Select a DCS" in str(exc)
    else:
        raise AssertionError("unsafe target was accepted")
