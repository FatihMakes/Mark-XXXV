from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class ActionResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None
    error_code: str | None = None
    retryable: bool = False

    def to_response_payload(self) -> dict[str, Any]:
        return asdict(self)


def success(message: str, data: dict[str, Any] | None = None) -> ActionResult:
    return ActionResult(ok=True, message=message, data=data, error_code=None, retryable=False)


def failure(
    message: str,
    *,
    error_code: str = "action_failed",
    retryable: bool = False,
    data: dict[str, Any] | None = None,
) -> ActionResult:
    return ActionResult(
        ok=False,
        message=message,
        data=data,
        error_code=error_code,
        retryable=retryable,
    )
