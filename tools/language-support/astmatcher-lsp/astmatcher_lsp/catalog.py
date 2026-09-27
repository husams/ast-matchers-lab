"""Loads the generated matcher data and answers type questions about it."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# Combinators that keep the node the enclosing matcher is looking at, so an
# expected node kind propagates through them (`functionDecl(unless(isPublic()))`
# checks isPublic against FunctionDecl).  Everything else that takes a
# `Matcher<*>` moves to a different node and imposes no expectation.
SAME_NODE_COMBINATORS = frozenset({
    "allOf", "anyOf", "eachOf", "unless", "optionally", "anything", "traverse",
})

# `match` accepts only node matchers; a narrowing matcher on its own is rejected
# by clang-query with "Not a valid top-level matcher".  (A `let` body has no such
# restriction: `let fixable allOf(...)` is fine.)
TOP_LEVEL_SECTION = "node"

# Matcher<*> helpers that still produce a node and so may stand at top level.
TOP_LEVEL_POLYMORPHIC = frozenset({"binaryOperation", "invocation", "mapAnyOf"})


# `hasDeclaration` is implemented for every node that has a getDecl(), which is
# more than the reference's type list names (ObjCIvarRefExpr, for one), so its
# argument type is not checked.
LENIENT_MATCHERS = frozenset({"hasDeclaration"})

# clang's dynamic registry converts freely between these two kinds, so
# `hasType(pointerType())` and `pointee(isConstQualified())` both build.
KIND_ALIASES = {"QualType": "Type"}


def data_dir() -> Path:
    env = os.environ.get("ASTMATCHER_DATA")
    if env:
        return Path(env)
    # tools/language-support/astmatcher-lsp/astmatcher_lsp/ -> tools/language-support/data
    return Path(__file__).resolve().parent.parent.parent / "data"


@dataclass
class Overload:
    ret: str | None                 # node kind clang converts through (None: Matcher<*>)
    node: str | None                # node kind the matcher actually restricts to
    section: str
    params: list[dict]
    variadic: bool
    min_args: int
    max_args: int | None
    signature: str
    doc: str

    def slot(self, index: int) -> dict | None:
        """The parameter slot for argument `index`, honouring variadics."""
        if index < len(self.params):
            return self.params[index]
        if self.variadic and self.params:
            return self.params[-1]
        if self.variadic:
            return {"kind": "matcher", "node": None, "name": "InnerMatcher"}
        return None

    def accepts_count(self, count: int) -> bool:
        if count < self.min_args:
            return False
        return self.max_args is None or count <= self.max_args


@dataclass
class Matcher:
    name: str
    kind: str                       # node | narrowing | traversal
    sections: list[str]
    parts: list[int]
    in_clang_query: bool
    polymorphic: bool
    ret_kinds: list[str]
    node_kinds: list[str]
    doc: str
    overloads: list[Overload]
    top_level: bool = False
    value_set: str | None = None
    bound_id_arg: bool = False

    @property
    def is_node_matcher(self) -> bool:
        """Accepted by `match` — see generate.py:is_node_shaped."""
        return self.top_level

    @property
    def signatures(self) -> list[str]:
        out: list[str] = []
        for o in self.overloads:
            if o.signature not in out:
                out.append(o.signature)
        return out

    def ret_display(self) -> str:
        if self.polymorphic and not self.ret_kinds:
            return "Matcher<*>"
        return "Matcher<" + "|".join(self.ret_kinds) + ">"


@dataclass
class Catalog:
    matchers: dict[str, Matcher]
    bases: dict[str, str | None]
    roots: frozenset[str]
    enums: dict[str, dict[str, str]]
    commands: dict[str, str]
    set_options: dict[str, dict]
    part_docs: dict[str, str] = field(default_factory=dict)
    rows: int = 0
    _ancestors: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # -- hierarchy ---------------------------------------------------------
    @staticmethod
    def canonical(kind: str | None) -> str | None:
        return KIND_ALIASES.get(kind, kind) if kind else kind

    def ancestors(self, kind: str) -> tuple[str, ...]:
        """(kind, base, base-of-base, ...) — empty when the kind is unknown."""
        cached = self._ancestors.get(kind)
        if cached is not None:
            return cached
        if kind not in self.bases:
            return ()
        chain, cur = [], kind
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = self.bases.get(cur)
        result = tuple(chain)
        self._ancestors[kind] = result
        return result

    def is_base_of(self, base: str, derived: str) -> bool:
        return base in self.ancestors(derived)

    def related(self, a: str | None, b: str | None) -> bool:
        """clang's dynamic-matcher conversion rule: related in either direction."""
        if a is None or b is None:          # Matcher<*> converts to anything
            return True
        a, b = self.canonical(a), self.canonical(b)
        if a == b:
            return True
        return self.is_base_of(a, b) or self.is_base_of(b, a)

    def distance(self, expected: str | None, actual: str | None) -> int:
        """How specific `actual` is for a slot expecting `expected` (lower = better)."""
        if expected is None or actual is None:
            return 50
        expected, actual = self.canonical(expected), self.canonical(actual)
        if expected == actual:
            return 0
        chain = self.ancestors(expected)
        if actual in chain:                 # actual is a base of expected
            return chain.index(actual)
        chain = self.ancestors(actual)
        if expected in chain:                # actual is more derived than expected
            return chain.index(expected)
        return 99

    def root_of(self, kind: str | None) -> str | None:
        chain = self.ancestors(kind) if kind else ()
        return chain[-1] if chain else None

    def is_root(self, kind: str | None) -> bool:
        return kind in self.roots

    # -- matchers ----------------------------------------------------------
    def get(self, name: str) -> Matcher | None:
        return self.matchers.get(name)

    def applies_to(self, matcher: Matcher, expected: str | None) -> bool:
        if expected is None or matcher.name in LENIENT_MATCHERS:
            return True
        if matcher.polymorphic and not matcher.ret_kinds:
            return True
        return any(self.related(ret, expected) for ret in matcher.ret_kinds)

    def enum_values(self, name: str) -> dict[str, str]:
        return self.enums.get(name, {})

    def suggest(self, word: str, limit: int = 3) -> list[str]:
        import difflib
        return difflib.get_close_matches(word, list(self.matchers), n=limit, cutoff=0.7)


@lru_cache(maxsize=4)
def load(directory: str | None = None) -> Catalog:
    root = Path(directory) if directory else data_dir()
    matchers_raw = json.loads((root / "matchers.json").read_text())
    hierarchy = json.loads((root / "hierarchy.json").read_text())
    enums = json.loads((root / "enums.json").read_text())

    matchers: dict[str, Matcher] = {}
    for name, entry in matchers_raw["matchers"].items():
        matchers[name] = Matcher(
            name=name,
            kind=entry["kind"],
            sections=entry["sections"],
            parts=entry["parts"],
            in_clang_query=entry["in_clang_query"],
            polymorphic=entry["polymorphic"],
            ret_kinds=entry["ret_kinds"],
            node_kinds=entry["node_kinds"],
            top_level=entry["top_level"],
            doc=entry["doc"],
            value_set=entry.get("value_set"),
            bound_id_arg=entry.get("bound_id_arg", False),
            overloads=[Overload(**{k: o[k] for k in (
                "ret", "node", "section", "params", "variadic",
                "min_args", "max_args", "signature", "doc")})
                for o in entry["overloads"]],
        )
    return Catalog(
        matchers=matchers,
        bases=hierarchy["bases"],
        roots=frozenset(hierarchy["roots"]),
        enums=enums["values"],
        commands=enums["commands"],
        set_options=enums["set_options"],
        part_docs=enums.get("part_docs", {}),
        rows=matchers_raw.get("rows", 0),
    )
