"""Request-wide timeout budget (Block A.3).

One deadline for the whole request path (HTTP intake -> preprocessing ->
LLM call(s) -> persistence -> notifications) instead of isolated timeouts per
hop. The deadline is propagated through asyncio contextvars, so every awaited
component can consult the remaining budget.
"""

import contextvars
import time
from contextvars import ContextVar
from typing import Optional


class DeadlineExceeded(Exception):
    """Raised when the total request budget is exhausted."""


class Deadline:
    __slots__ = ("_expires_at",)

    def __init__(self, budget_seconds: float):
        if budget_seconds <= 0:
            raise ValueError("budget_seconds must be positive")
        self._expires_at = time.monotonic() + budget_seconds

    def remaining(self) -> float:
        return max(0.0, self._expires_at - time.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def check(self) -> None:
        if self.expired():
            raise DeadlineExceeded("Общий таймаут обработки запроса исчерпан")


_current_deadline: ContextVar[Optional[Deadline]] = ContextVar(
    "current_deadline", default=None
)


def set_deadline(deadline: Optional[Deadline]) -> contextvars.Token:
    return _current_deadline.set(deadline)


def reset_deadline(token: contextvars.Token) -> None:
    _current_deadline.reset(token)


def current_deadline() -> Optional[Deadline]:
    return _current_deadline.get()
