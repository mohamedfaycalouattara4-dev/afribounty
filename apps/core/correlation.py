from contextvars import ContextVar
from uuid import uuid4

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def current_correlation_id() -> str:
    return correlation_id.get()


def new_correlation_id() -> str:
    return uuid4().hex
