"""Safe provider connectivity checks used by local first-run diagnostics."""

from __future__ import annotations

import ssl
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol, Self
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


class HttpResponse(Protocol):
    status: int

    def __enter__(self) -> Self: ...

    def __exit__(self, *args: object) -> object: ...


def _open_url(request: Request, *, timeout: float) -> HttpResponse:
    context = ssl.create_default_context(cafile=certifi.where())
    return urlopen(request, timeout=timeout, context=context)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ProviderDiagnostic:
    status: str
    detail: str
    checked_at: str

    @property
    def usable(self) -> bool:
        return self.status in {"available", "configured"}

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _result(status: str, detail: str) -> ProviderDiagnostic:
    return ProviderDiagnostic(
        status=status,
        detail=detail,
        checked_at=datetime.now(UTC).isoformat(),
    )


def check_openai_access(
    api_key: str,
    *,
    timeout: float = 10.0,
    opener: Callable[..., HttpResponse] = _open_url,
) -> ProviderDiagnostic:
    """Authenticate against the model-list endpoint without running inference."""

    if not api_key.strip():
        return _result("missing", "Add an OpenAI API key in MARA settings.")
    request = Request(
        "https://api.openai.com/v1/models",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "MARA-provider-diagnostics/1",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
        if status == 200:
            return _result("available", "Authenticated with the OpenAI API.")
        return _result("error", f"OpenAI returned unexpected HTTP status {status}.")
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return _result(
                "invalid", "The stored OpenAI API key was rejected. Replace it."
            )
        if exc.code == 429:
            return _result(
                "limited",
                "OpenAI rate or quota limits currently prevent API access.",
            )
        return _result("error", f"OpenAI returned HTTP {exc.code}.")
    except (OSError, TimeoutError, URLError) as exc:
        reason = getattr(exc, "reason", exc)
        return _result("unreachable", f"Cannot reach the OpenAI API: {reason}")
