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
    hooks = scripts / "Hooks"
    hooks.mkdir()
    (hooks / "MARAText.lua").write_text("-- local modification\n", encoding="utf-8")

    first = setup.install_dcs_bios(dcs, payload)
    assert (first.bios_path / "BIOS.lua").is_file()
    text = export.read_text(encoding="utf-8")
    assert "Tacview.lua" in text
    assert text.count(setup.EXPORT_LINE) == 1
    assert text.count(setup.SPATIAL_EXPORT_LINE) == 1
    assert first.spatial_export_path.is_file()
    assert "LoIsObjectExportAllowed" in first.spatial_export_path.read_text()
    assert first.text_output_path.is_file()
    assert "trigger.action.outText" in first.text_output_path.read_text()
    assert "DCS.setUserCallbacks" in first.text_output_path.read_text()
    assert any(
        path.name.startswith("Export.lua.backup-") for path in first.backup_paths
    )
    assert any(
        path.name.startswith("MARAText.lua.backup-") for path in first.backup_paths
    )

    second = setup.install_dcs_bios(dcs, payload)
    assert export.read_text(encoding="utf-8").count(setup.EXPORT_LINE) == 1
    assert export.read_text(encoding="utf-8").count(setup.SPATIAL_EXPORT_LINE) == 1
    assert second.text_output_path.read_bytes() == first.text_output_path.read_bytes()
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


def test_indication_probe_install_is_explicit_repeatable_and_backed_up(
    tmp_path: Path,
) -> None:
    dcs = tmp_path / "DCS.openbeta"
    scripts = dcs / "Scripts"
    mara = scripts / "MARA"
    mara.mkdir(parents=True)
    export = scripts / "Export.lua"
    export.write_text("-- another export\n", encoding="utf-8")
    probe = mara / "MARAIndications.lua"
    probe.write_text("-- local modification\n", encoding="utf-8")

    first = setup.install_indication_probe(dcs)
    second = setup.install_indication_probe(dcs)

    assert setup.INDICATION_EXPORT_LINE in export.read_text(encoding="utf-8")
    assert "list_indication" in probe.read_text(encoding="utf-8")
    assert any(path.name.startswith("Export.lua.backup-") for path in first.backup_paths)
    assert any(
        path.name.startswith("MARAIndications.lua.backup-")
        for path in first.backup_paths
    )
    assert second.backup_paths == ()
    assert setup.inspect_indication_probe(dcs)[0] is True
