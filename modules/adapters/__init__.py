"""Executor adapter implementations and interfaces."""

from .executor_adapter import (
    ExecutorAdapter,
    ExecutorAdapterInputError,
    ExecutorDispatchInput,
    ExecutorDispatchOutput,
    StubExecutorAdapter,
)
from .openclaw import OpenClawAdapterError, OpenClawExecutorAdapter, OpenClawRuntimeClient

__all__ = [
    "ExecutorAdapter",
    "ExecutorAdapterInputError",
    "ExecutorDispatchInput",
    "ExecutorDispatchOutput",
    "StubExecutorAdapter",
    "OpenClawAdapterError",
    "OpenClawExecutorAdapter",
    "OpenClawRuntimeClient",
]
