from __future__ import annotations

import hashlib
from pathlib import Path

from dcs_copilot_cloud.models import ModelAsset, provision_asset


class Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size: int) -> bytes:
        payload, self.payload = self.payload, b""
        return payload


def test_model_download_is_verified_cached_and_reports_progress(tmp_path: Path) -> None:
    payload = b"verified-model"
    asset = ModelAsset(
        "model.bin",
        "https://example.invalid/model.bin",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
    )
    calls = 0
    progress = []

    def opener(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response(payload)

    path = provision_asset(
        asset,
        tmp_path,
        opener=opener,
        progress=lambda *values: progress.append(values),
    )
    assert path.read_bytes() == payload
    assert progress == [("model.bin", len(payload), len(payload))]
    assert provision_asset(asset, tmp_path, opener=opener) == path
    assert calls == 1
