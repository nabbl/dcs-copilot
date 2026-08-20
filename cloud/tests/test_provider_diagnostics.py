from __future__ import annotations

from urllib.error import HTTPError, URLError

from dcs_copilot_cloud.provider_diagnostics import check_openai_access


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_openai_connectivity_check_authenticates_without_inference() -> None:
    requests = []

    def open_request(request, **_kwargs):
        requests.append(request)
        return Response()

    result = check_openai_access("sk-test-secret", opener=open_request)

    assert result.status == "available"
    assert result.usable
    assert requests[0].full_url == "https://api.openai.com/v1/models"
    assert requests[0].get_header("Authorization") == "Bearer sk-test-secret"
    assert "sk-test-secret" not in result.detail


def test_openai_connectivity_check_explains_missing_invalid_and_offline() -> None:
    missing = check_openai_access("")
    invalid = check_openai_access(
        "bad-key",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError("https://api.openai.com/v1/models", 401, "", {}, None)
        ),
    )
    offline = check_openai_access(
        "key",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            URLError("network offline")
        ),
    )

    assert missing.status == "missing"
    assert invalid.status == "invalid"
    assert offline.status == "unreachable"
