"""Executor adapter implementations and interfaces."""

from .executor_adapter import (
    ExecutorAdapter,
    ExecutorAdapterInputError,
    ExecutorDispatchInput,
    ExecutorDispatchOutput,
    StubExecutorAdapter,
)

__all__ = [
    "ExecutorAdapter",
    "ExecutorAdapterInputError",
    "ExecutorDispatchInput",
    "ExecutorDispatchOutput",
    "StubExecutorAdapter",
]
