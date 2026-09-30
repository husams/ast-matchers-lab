"""Async declarative access to the native AST matcher service."""

from .client import MatcherClient, MatcherError
from .models import (
    Binding,
    Definition,
    Diagnostic,
    Match,
    MatcherQuery,
    QueryResult,
    RunResult,
    ServerStatus,
    SourcePosition,
    SourceRange,
)

__all__ = [
    "Binding",
    "Definition",
    "Diagnostic",
    "Match",
    "MatcherClient",
    "MatcherError",
    "MatcherQuery",
    "QueryResult",
    "RunResult",
    "ServerStatus",
    "SourcePosition",
    "SourceRange",
]
