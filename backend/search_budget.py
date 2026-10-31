"""A per-job budget shared by planning, native tools, retries and review."""
from contextvars import ContextVar
from contextlib import contextmanager
import time

_active = ContextVar("search_call_budget", default=None)


class CallBudgetExceeded(ValueError):
    pass


class CallBudget:
    def __init__(self, limit=5, seconds=180):
        self.limit, self.used = limit, 0
        self.deadline = time.monotonic() + seconds

    def take(self, timeout):
        remaining = self.deadline - time.monotonic()
        if self.used >= self.limit or remaining <= 0:
            raise CallBudgetExceeded("KI-Aufruf- oder Zeitlimit erreicht / AI call or time limit reached")
        self.used += 1
        return min(timeout, remaining)


def take_call(timeout):
    budget = _active.get()
    return budget.take(timeout) if budget else timeout


@contextmanager
def call_budget(limit=5, seconds=180):
    budget = CallBudget(limit, seconds)
    token = _active.set(budget)
    try:
        yield budget
    finally:
        _active.reset(token)
