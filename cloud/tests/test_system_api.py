from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.credentials import MemoryCredentialStore
from dcs_copilot_cloud.main import _load_non_secret_config
from dcs_copilot_cloud.provider_diagnostics import ProviderDiagnostic
from dcs_copilot_cloud.runtime_paths import RuntimePaths
from fastapi.testclient import TestClient


def test_health_readiness_and_compatibility_handshake() -> None:
    app = create_app(
        CloudSettings(
            deployment="local",
            tts_provider="kokoro",
            openai_api_key="test-key",
        )
    )
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "version": "0.1.0"}
        ready = client.get("/ready").json()
        assert ready["status"] == "ready"
        assert ready["components"] == {
            "database": True,
            "kokoro": True,
            "coach": True,
            "openai": True,
        }
        info = client.get("/api/system/info").json()
        assert info["api_version"] == "1"
        assert info["deployment"] == "local"
        assert info["capabilities"]["kokoro"] is True
        assert info["openai_configured"] is True
        assert info["operational"] is True
        assert info["services"]["kokoro"]["status"] == "ready"
        assert info["services"]["openai"]["status"] == "configured"


def test_missing_openai_key_is_an_explicit_operational_blocker() -> None:
    app = create_app(CloudSettings(deployment="local", tts_provider="kokoro"))

    with TestClient(app) as client:
        ready = client.get("/ready").json()
        info = client.get("/api/system/info").json()

    assert ready["status"] == "ready"
    assert ready["operational"] is False
    assert info["services"]["openai"]["status"] == "missing"
    assert info["blocking_reasons"] == ["Add an OpenAI API key in MARA settings."]


def test_local_startup_checks_real_openai_access_without_inference() -> None:
    checked_keys: list[str] = []

    def check(key: str) -> ProviderDiagnostic:
        checked_keys.append(key)
        return ProviderDiagnostic("available", "Authenticated.", "now")

    app = create_app(
        CloudSettings(
            deployment="local",
            tts_provider="kokoro",
            openai_api_key="stored-key",
            verify_openai_access=True,
        ),
        openai_checker=check,
    )
    with TestClient(app) as client:
        for _ in range(50):
            info = client.get("/api/system/info").json()
            if info["services"]["openai"]["status"] == "available":
                break
            time.sleep(0.01)
        else:
            pytest.fail("OpenAI diagnostic did not complete")

    assert checked_keys == ["stored-key"]
    assert info["operational"] is True


def test_kokoro_provisioning_reports_progress_before_ready(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def provision(_directory, *, progress):
        progress("kokoro-v1.0.onnx", 50, 100)
        started.set()
        release.wait(timeout=2)
        return Path("model.onnx"), Path("voices.bin")

    monkeypatch.setattr("dcs_copilot_cloud.app.provision_kokoro", provision)
    validated: list[tuple[Path, Path, str]] = []
    app = create_app(
        CloudSettings(
            deployment="local",
            tts_provider="kokoro",
            provision_models=True,
        ),
        kokoro_validator=lambda model, voices, voice: validated.append(
            (model, voices, voice)
        ),
    )
    with TestClient(app) as client:
        assert started.wait(timeout=1)
        readiness = client.get("/ready").json()
        assert readiness["status"] == "starting"
        assert readiness["model_progress"]["percent"] == 50
        release.set()
        for _ in range(50):
            if client.get("/ready").json()["status"] == "ready":
                break
            time.sleep(0.01)
        else:
            pytest.fail("backend did not become ready after model provisioning")
    assert validated == [(Path("model.onnx"), Path("voices.bin"), "marin")]


def test_kokoro_runtime_load_failure_is_reported_before_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        "dcs_copilot_cloud.app.provision_kokoro",
        lambda *_args, **_kwargs: (Path("model.onnx"), Path("voices.bin")),
    )
    app = create_app(
        CloudSettings(
            deployment="local",
            tts_provider="kokoro",
            provision_models=True,
        ),
        kokoro_validator=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("ONNX runtime unavailable")
        ),
    )

    with TestClient(app) as client:
        for _ in range(50):
            ready = client.get("/ready").json()
            if ready["status"] == "error":
                break
            time.sleep(0.01)
        else:
            pytest.fail("Kokoro runtime failure was not reported")

    assert "ONNX runtime unavailable" in ready["error"]
    assert ready["components"]["kokoro"] is False


def test_fake_credential_store_supplies_key_without_config_serialization(
    tmp_path: Path,
) -> None:
    store = MemoryCredentialStore()
    store.set_openai_key("secret-value")
    settings = CloudSettings.from_env(tmp_path / "missing.env", credential_store=store)
    assert settings.openai_api_key == "secret-value"
    store.delete_openai_key()
    assert store.get_openai_key() is None


def test_runtime_paths_keep_mutable_data_outside_assets(tmp_path: Path) -> None:
    paths = RuntimePaths.discover(tmp_path / "MARA").ensure()
    assert paths.database_url.endswith("/MARA/data/mara.db")
    assert paths.backend_log == tmp_path / "MARA" / "logs" / "backend.log"
    assert paths.runtime.is_dir()
    assert paths.assets not in {paths.data, paths.logs, paths.runtime}


def test_backend_json_config_rejects_secrets(tmp_path: Path) -> None:
    path = tmp_path / "backend.json"
    path.write_text('{"openai_api_key": "secret"}')
    with pytest.raises(ValueError, match="secrets"):
        _load_non_secret_config(path)
