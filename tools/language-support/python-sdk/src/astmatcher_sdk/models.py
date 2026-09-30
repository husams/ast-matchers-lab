"""Immutable request and response values for the native matcher protocol."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class Definition:
    name: str
    expression: str

    def __post_init__(self) -> None:
        if not self.name.isidentifier() or not self.expression.strip():
            raise ValueError("definition needs an identifier and a matcher expression")


@dataclass(frozen=True, slots=True)
class MatcherQuery:
    """A source file, named matchers, and expressions to run in declaration order."""

    source: str | Path
    matches: tuple[str, ...]
    definitions: tuple[Definition, ...] = ()
    flags: tuple[str, ...] = ()
    traversal: Literal["AsIs", "IgnoreUnlessSpelledInSource"] = "AsIs"
    max_matches: int = 1000
    working_directory: str | Path | None = None

    def __post_init__(self) -> None:
        if isinstance(self.matches, str):
            raise TypeError("matches must be a sequence of expressions")
        if isinstance(self.flags, str):
            raise TypeError("flags must be a sequence of compiler flags")
        object.__setattr__(self, "matches", tuple(self.matches))
        object.__setattr__(self, "definitions", tuple(self.definitions))
        object.__setattr__(self, "flags", tuple(self.flags))
        if not self.matches or any(not item.strip() for item in self.matches):
            raise ValueError("matches must contain at least one matcher expression")
        if self.traversal not in ("AsIs", "IgnoreUnlessSpelledInSource"):
            raise ValueError("unsupported traversal mode")
        if not 0 <= self.max_matches <= 10000:
            raise ValueError("max_matches must be between 0 and 10000")

    def request(self) -> dict[str, object]:
        source = Path(self.source).expanduser().resolve()
        cwd = (Path(self.working_directory).expanduser().resolve()
               if self.working_directory else source.parent)
        return {
            "sourcePath": str(source),
            "workingDirectory": str(cwd),
            "flags": list(self.flags),
            "traversal": self.traversal,
            "maxMatches": self.max_matches,
            "commands": [
                *({"kind": "LET", "name": item.name, "expression": item.expression}
                  for item in self.definitions),
                *({"kind": "MATCH", "expression": item} for item in self.matches),
            ],
        }


@dataclass(frozen=True, slots=True)
class ServerStatus:
    state: Literal["stopped", "ready", "unavailable"]
    version: str | None = None
    compiler_path: str | None = None
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return self.state == "ready"


@dataclass(frozen=True, slots=True)
class SourcePosition:
    line: int
    character: int


@dataclass(frozen=True, slots=True)
class SourceRange:
    file: str
    start: SourcePosition
    end: SourcePosition


@dataclass(frozen=True, slots=True)
class Binding:
    id: str
    node: str
    kind: str
    semantic_kind: str
    summary: str
    text: str
    range: SourceRange | None = None
    qualified_name: str = ""
    type: str = ""
    signature: str = ""
    record_kind: str = ""
    record_identity: str = ""


@dataclass(frozen=True, slots=True)
class Match:
    index: int
    bindings: tuple[Binding, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryResult:
    command_index: int
    matcher: str
    count: int
    matches: tuple[Match, ...] = ()


@dataclass(frozen=True, slots=True)
class Diagnostic:
    command_index: int
    message: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class RunResult:
    queries: tuple[QueryResult, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    stderr: str = ""
    truncated: bool = False

    @classmethod
    def from_reply(cls, reply: dict[str, object]) -> "RunResult":
        def position(value: dict) -> SourcePosition:
            return SourcePosition(int(value.get("line", 0)),
                                  int(value.get("character", 0)))

        def binding(value: dict) -> Binding:
            source_range = value.get("range")
            span = None
            if isinstance(source_range, dict) and source_range.get("file"):
                span = SourceRange(
                    str(source_range["file"]),
                    position(source_range.get("start") or {}),
                    position(source_range.get("end") or {}),
                )
            return Binding(
                id=str(value.get("id", "")),
                node=str(value.get("node", "")),
                kind=str(value.get("kind", "")),
                semantic_kind=str(value.get("semanticKind", "")),
                summary=str(value.get("summary", "")),
                text=str(value.get("text", "")),
                range=span,
                qualified_name=str(value.get("qualifiedName", "")),
                type=str(value.get("type", "")),
                signature=str(value.get("signature", "")),
                record_kind=str(value.get("recordKind", "")),
                record_identity=str(value.get("recordIdentity", "")),
            )

        return cls(
            queries=tuple(
                QueryResult(
                    command_index=int(query.get("commandIndex", 0)),
                    matcher=str(query.get("matcher", "")),
                    count=int(query.get("count", 0)),
                    matches=tuple(
                        Match(int(match.get("index", 0)),
                              tuple(binding(item) for item in match.get("bindings", [])))
                        for match in query.get("matches", [])
                    ),
                )
                for query in reply.get("queries", [])
            ),
            diagnostics=tuple(
                Diagnostic(
                    int(item.get("commandIndex", 0)),
                    str(item.get("message", "")),
                    int(item.get("line", 0)),
                    int(item.get("column", 0)),
                )
                for item in reply.get("diagnostics", [])
            ),
            stderr=str(reply.get("stderr", "")),
            truncated=bool(reply.get("truncated", False)),
        )
