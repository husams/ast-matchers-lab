"""Type-checks a parsed clang-query script the way clang-query's registry does.

The messages mirror the real ones on purpose ("Matcher not found: x",
"Incorrect type for arg 1. (Expected = ...) != (Actual = ...)") so that what an
editor shows and what the tool prints are the same sentence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import (LENIENT_MATCHERS, SAME_NODE_COMBINATORS, Catalog, Matcher,
                      Overload)
from .lexer import STRING
from .parser import Bind, Call, Command, Document, Expr, Literal, bound_ids

ERROR, WARNING, INFORMATION, HINT = 1, 2, 3, 4


@dataclass
class Diagnostic:
    start: int
    end: int
    message: str
    severity: int = ERROR
    code: str = ""


@dataclass
class LetType:
    """What a `let` name denotes, for checking its later uses."""
    name: str
    ret_kinds: list[str]          # empty == Matcher<*>
    is_node_matcher: bool
    signature: str


@dataclass
class Resolution:
    matcher: Matcher | None = None
    overload: Overload | None = None
    candidates: list[Overload] = field(default_factory=list)
    let: LetType | None = None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def arity_text(matcher: Matcher) -> str:
    lows = {o.min_args for o in matcher.overloads}
    if any(o.max_args is None for o in matcher.overloads):
        return f"({min(lows)}, )"
    highs = {o.max_args for o in matcher.overloads if o.max_args is not None}
    if lows == highs:
        return str(min(lows))
    return f"({min(lows)}, {max(highs)})"


class Analyzer:
    def __init__(self, catalog: Catalog, doc: Document) -> None:
        self.cat = catalog
        self.doc = doc
        self.lets: dict[str, LetType] = {}
        self.diags: list[Diagnostic] = []
        self._resolutions: dict[int, Resolution] = {}
        self._quiet = 0          # >0 while trying an overload on scratch diagnostics
        self._bound_cache: dict[int, list[str]] = {}
        # (id(call), expected) -> chosen overload. Without it every trial re-tries
        # the overloads of every nested call: exponential in nesting depth.
        self._overload_cache: dict[tuple[int, str | None], Overload | None] = {}

    # ------------------------------------------------------------------ API
    def run(self) -> list[Diagnostic]:
        self.diags = []
        self._overload_cache = {}
        self._lex_diagnostics()
        for cmd in self.doc.commands:
            self._command(cmd)
        for tok in self.doc.stray:
            self._err(tok.start, tok.end, f"unexpected input: {tok.text!r}", code="stray")
        self.diags.sort(key=lambda d: (d.start, d.end))
        return self.diags

    def resolution_for(self, call: Call) -> Resolution:
        """Overload picked for `call` during the last run() (for hover/help)."""
        return self._resolutions.get(id(call)) or self._resolve(call, None, record=False)

    # ------------------------------------------------------------- internals
    def _err(self, start: int, end: int, message: str, severity: int = ERROR,
             code: str = "") -> None:
        self.diags.append(Diagnostic(start, max(end, start + 1), message, severity, code))

    def _lex_diagnostics(self) -> None:
        for tok in self.doc.tokens:
            if tok.kind == STRING and not tok.terminated:
                self._err(tok.start, tok.end, "unterminated string literal",
                          code="unterminated-string")

    def _command(self, cmd: Command) -> None:
        if cmd.name in ("quit", "help"):
            return
        if cmd.name in ("set", "enable", "disable"):
            self._setting(cmd)
            return
        if cmd.name == "let" and cmd.let_name is None:
            self._err(cmd.keyword.start, cmd.keyword.end,
                      "`let` needs a name: let NAME MATCHER", code="let-name")
        if cmd.expr is None:
            self._err(cmd.keyword.start, cmd.keyword.end,
                      f"`{cmd.keyword.text}` needs a matcher expression", code="missing-matcher")
            return

        self._expr(cmd.expr, expected=None, cmd=cmd, top_level=cmd.name == "match")

        if cmd.name == "let" and cmd.let_name:
            name = cmd.let_name.text
            if name in self.cat.matchers:
                self._err(cmd.let_name.start, cmd.let_name.end,
                          f"`{name}` shadows the built-in matcher of the same name",
                          WARNING, code="shadow")
            self.lets[name] = self._let_type(name, cmd.expr)

    def _let_type(self, name: str, expr: Expr) -> LetType:
        if isinstance(expr, Call):
            res = self._resolve(expr, None, record=False)
            if res.matcher:
                return LetType(name, list(res.matcher.ret_kinds),
                               res.matcher.is_node_matcher,
                               res.matcher.signatures[0])
            if res.let:
                return LetType(name, res.let.ret_kinds, res.let.is_node_matcher, res.let.signature)
        return LetType(name, [], False, name)

    def _setting(self, cmd: Command) -> None:
        words = cmd.words
        if cmd.name in ("enable", "disable"):
            if not words or words[0].text != "output":
                where = words[0] if words else cmd.keyword
                self._err(where.start, where.end,
                          f"`{cmd.name}` takes only `output <feature>`", code="set-option")
                return
            self._enum_word(words[1] if len(words) > 1 else None, "OutputFeature", cmd)
            return

        if not words:
            self._err(cmd.keyword.start, cmd.keyword.end,
                      "`set` needs an option: " + ", ".join(sorted(self.cat.set_options)),
                      code="set-option")
            return
        option = words[0]
        spec = self.cat.set_options.get(option.text)
        if spec is None:
            hint = ", ".join(sorted(self.cat.set_options))
            self._err(option.start, option.end,
                      f"unknown setting `{option.text}`; expected one of: {hint}",
                      code="set-option")
            return
        value = words[1] if len(words) > 1 else None
        if spec["type"] == "bool":
            if value is None:
                self._err(option.start, option.end,
                          f"`set {option.text}` needs true or false", code="set-value")
            elif value.text not in ("true", "false"):
                self._err(value.start, value.end,
                          f"expected true or false, got `{value.text}`", code="set-value")
        else:
            self._enum_word(value, spec["type"], cmd, option=option.text)

    def _enum_word(self, value, enum: str, cmd: Command, option: str | None = None) -> None:
        allowed = self.cat.enum_values(enum)
        if value is None:
            where = cmd.words[-1] if cmd.words else cmd.keyword
            self._err(where.start, where.end,
                      f"expected one of: {', '.join(sorted(allowed))}", code="set-value")
            return
        if value.text not in allowed:
            self._err(value.start, value.end,
                      f"unknown {'value' if option else 'feature'} `{value.text}`; "
                      f"expected one of: {', '.join(sorted(allowed))}", code="set-value")

    # -- expressions -------------------------------------------------------
    def _expr(self, expr: Expr, expected: str | None, cmd: Command,
              top_level: bool = False, slot: dict | None = None,
              owner: Matcher | None = None, index: int = 0) -> None:
        if isinstance(expr, Literal):
            self._literal(expr, slot, owner, index, cmd)
            return
        if not isinstance(expr, Call):
            return

        res = self._resolve(expr, expected)
        if res.let is not None:
            if not expr.is_reference:
                self._err(expr.name_token.start, expr.name_token.end,
                          f"`{expr.name}` is a named matcher; use it without parentheses",
                          code="let-call")
            elif expected is not None and res.let.ret_kinds and not any(
                    self.cat.related(k, expected) for k in res.let.ret_kinds):
                self._err(expr.start, expr.end,
                          f"Incorrect type for arg {index + 1}. "
                          f"(Expected = Matcher<{expected}>) != "
                          f"(Actual = Matcher<{'|'.join(res.let.ret_kinds)}>)",
                          code="arg-type")
            if top_level and not res.let.is_node_matcher:
                self._err(expr.start, expr.end,
                          f"Not a valid top-level matcher: `{expr.name}` does not name a node",
                          code="top-level")
            return

        matcher = res.matcher
        if matcher is None:
            if slot and slot["kind"] == "matcher-name":
                return                      # already reported by _matcher_name
            hint = self.cat.suggest(expr.name)
            extra = f"; did you mean {' or '.join('`%s`' % h for h in hint)}" if hint else ""
            self._err(expr.name_token.start, expr.name_token.end,
                      f"Matcher not found: {expr.name}{extra}", code="unknown-matcher")
            return

        if not matcher.in_clang_query:
            self._err(expr.name_token.start, expr.name_token.end,
                      f"`{matcher.name}` is in the AST Matcher Reference but is not registered "
                      f"in clang-query 22 — see docs/part_12_capstone.md for the alternative",
                      WARNING, code="not-registered")

        if expr.is_reference:
            self._err(expr.name_token.start, expr.name_token.end,
                      f"`{expr.name}` is a matcher; it needs parentheses: {expr.name}()",
                      code="missing-parens")
            return
        if expr.rparen is None:
            self._err(expr.end, expr.end + 1, f"expected `)` to close {expr.name}(",
                      code="unclosed")

        if top_level:
            if not matcher.is_node_matcher:
                if matcher.polymorphic and not matcher.ret_kinds:
                    self._err(expr.start, expr.end,
                              f"`{matcher.name}` has an unresolved overloaded type here; wrap it "
                              f"in the node matcher you are looking for",
                              code="top-level")
                else:
                    self._err(expr.start, expr.end,
                              f"Not a valid top-level matcher: `{matcher.name}` narrows a node "
                              f"instead of naming one", code="top-level")

        count = len(expr.args)
        if not any(o.accepts_count(count) for o in matcher.overloads):
            self._err(expr.name_token.start, expr.rparen.end if expr.rparen else expr.end,
                      f"Incorrect argument count. (Expected = {arity_text(matcher)}) != "
                      f"(Actual = {count})", code="arity")
        elif not res.candidates:
            self._err(expr.start, expr.end,
                      f"Incorrect type for arg {index + 1}. "
                      f"(Expected = Matcher<{expected}>) != (Actual = {matcher.ret_display()})",
                      code="arg-type")

        overload = self._best_overload(expr, matcher, res, expected, cmd)
        if overload is not None:
            res.overload = overload
            self._arguments(expr, matcher, overload, expected, cmd)
        self._members(expr, matcher, cmd)

    def _best_overload(self, call: Call, matcher: Matcher, res: Resolution,
                       expected: str | None, cmd: Command) -> Overload | None:
        """Pick the overload whose parameters the given arguments actually fit.

        `hasType` takes either a Matcher<Decl> or a Matcher<QualType>; checking
        only the first-ranked overload would reject half of the legal uses.  So
        each distinct parameter shape is tried and the cleanest wins.
        """
        key = (id(call), expected)
        if key in self._overload_cache:
            return self._overload_cache[key]
        chosen = self._pick_overload(call, matcher, res, expected, cmd)
        self._overload_cache[key] = chosen
        return chosen

    def _pick_overload(self, call: Call, matcher: Matcher, res: Resolution,
                       expected: str | None, cmd: Command) -> Overload | None:
        pool = res.candidates or matcher.overloads
        if not pool:
            return None
        shapes: dict[str, Overload] = {}
        for o in pool:
            shapes.setdefault(o.signature, o)
        if len(shapes) == 1 or not call.args:
            return next(iter(shapes.values()))

        best: tuple[int, int, Overload] | None = None
        for overload in shapes.values():
            produced = self._trial(call, matcher, overload, expected, cmd)
            errors = sum(1 for d in produced if d.severity == ERROR)
            score = (errors, len(produced), overload)
            if best is None or score[:2] < best[:2]:
                best = score
            if errors == 0 and not produced:
                break
        return best[2] if best else None

    def _trial(self, call: Call, matcher: Matcher, overload: Overload,
               expected: str | None, cmd: Command) -> list[Diagnostic]:
        saved, self.diags = self.diags, []
        self._quiet += 1
        try:
            self._arguments(call, matcher, overload, expected, cmd)
            return self.diags
        finally:
            self._quiet -= 1
            self.diags = saved

    def _arguments(self, call: Call, matcher: Matcher, overload: Overload,
                   expected: str | None, cmd: Command) -> None:
        for index, arg in enumerate(call.args):
            slot = overload.slot(index)
            if slot is None:
                continue
            if slot["kind"] == "matcher":
                inner = slot["node"]
                if inner is None:
                    # Matcher<*>: same-node combinators keep the caller's expectation.
                    inner = expected if matcher.name in SAME_NODE_COMBINATORS else None
                if isinstance(arg, Literal):
                    self._err(arg.start, arg.end,
                              f"Incorrect type for arg {index + 1}. "
                              f"(Expected = Matcher<{inner or '*'}>) != "
                              f"(Actual = {arg.kind.capitalize()})", code="arg-type")
                else:
                    self._expr(arg, inner, cmd, slot=slot, owner=matcher, index=index)
                    self._dead_restriction(arg, inner)
            elif slot["kind"] == "matcher-name":
                self._matcher_name(arg, index)
            elif slot["kind"] == "enum" and not isinstance(arg, Literal):
                self._enum_bareword(arg, slot, index)
            elif slot["kind"] == "node-pointer":
                self._err(arg.start, arg.end,
                          f"`{matcher.name}` takes a `const {slot['node']}*`, which cannot be "
                          f"written in clang-query", code="unsupported-param")
            elif isinstance(arg, Literal):
                self._literal(arg, slot, matcher, index, cmd)
            else:
                self._expr(arg, None, cmd, slot=slot, owner=matcher, index=index)

    def _dead_restriction(self, arg: Expr, inner: str | None) -> None:
        """`functionDecl(varDecl())` builds but can never match: sibling kinds."""
        if inner is None or not isinstance(arg, Call) or arg.is_reference:
            return
        matcher = self.cat.get(arg.name)
        if matcher is None or not matcher.node_kinds or matcher.name in LENIENT_MATCHERS:
            return
        if not any(self.cat.related(ret, inner) for ret in matcher.ret_kinds):
            return                          # already reported as a type error
        if any(self.cat.related(node, inner) for node in matcher.node_kinds):
            return
        self._err(arg.start, arg.end,
                  f"`{arg.name}` matches {'/'.join(matcher.node_kinds)}, which is never a "
                  f"{inner}: this can never match", WARNING, code="dead-restriction")

    def _enum_bareword(self, arg: Expr, slot: dict, index: int) -> None:
        allowed = self.cat.enum_values(slot.get("enum", ""))
        spelled = arg.name if isinstance(arg, Call) and arg.is_reference else None
        if spelled in allowed:
            return
        self._err(arg.start, arg.end,
                  f"Unknown value for arg {index + 1}; expected one of: "
                  f"{', '.join(sorted(allowed))}", code="enum-value")

    def _matcher_name(self, arg: Expr, index: int) -> None:
        if not isinstance(arg, Call) or not arg.is_reference:
            self._err(arg.start, arg.end,
                      f"arg {index + 1} of mapAnyOf must be a bare node-matcher name, "
                      f"like `ifStmt`", code="arg-type")
            return
        matcher = self.cat.get(arg.name)
        if matcher is None or not matcher.is_node_matcher:
            self._err(arg.start, arg.end,
                      f"`{arg.name}` is not a node matcher name", code="arg-type")

    def _literal(self, lit: Literal, slot: dict | None, owner: Matcher | None,
                 index: int, cmd: Command) -> None:
        if slot is None:
            return
        want, got = slot["kind"], lit.kind
        pretty = {"string": "String", "unsigned": "Unsigned", "bool": "Boolean",
                  "double": "Double", "negative": "Negative", "unknown": "Unknown"}
        if got == "negative":
            self._err(lit.start, lit.end,
                      "clang-query cannot parse a negative literal; use "
                      "unaryOperator(hasOperatorName(\"-\"), hasUnaryOperand(...)) instead",
                      code="negative-literal")
            return
        if want == "value":
            return
        if want == "enum" or (want == "string" and owner is not None and owner.value_set):
            if got != "string":
                self._err(lit.start, lit.end,
                          f"Incorrect type for arg {index + 1}. (Expected = string) != "
                          f"(Actual = {pretty.get(got, got)})", code="arg-type")
                return
            self._enum_literal(lit, slot, owner, index)
            return
        if want == "double" and got == "unsigned":
            return                          # 4 is a fine double
        if want == "regex-flags" and got == "string":
            return
        if want != got:
            self._err(lit.start, lit.end,
                      f"Incorrect type for arg {index + 1}. (Expected = {want}) != "
                      f"(Actual = {pretty.get(got, got)})", code="arg-type")
            return
        if owner is not None and owner.bound_id_arg and got == "string":
            ids = self.visible_bound_ids(cmd)
            if lit.token.value not in ids:
                known = ", ".join(f"`{i}`" for i in ids) if ids else "none in this match"
                self._err(lit.start, lit.end,
                          f"`{lit.token.value}` is not bound in this match (bound ids: {known})",
                          WARNING, code="unbound-id")

    def visible_bound_ids(self, cmd: Command) -> list[str]:
        """Ids this match can refer to: its own, plus every `let` in the file.

        A `let` body may bind an id that a later `match` reads back
        (`let heavyParam parmVarDecl(...).bind("p")`), so the ids of all named
        matchers count as visible rather than only the current command's.
        """
        key = id(cmd)
        cached = self._bound_cache.get(key)
        if cached is not None:
            return cached
        ids = list(bound_ids(cmd))
        for let in self.doc.lets.values():
            for name in bound_ids(let):
                if name not in ids:
                    ids.append(name)
        self._bound_cache[key] = ids
        return ids

    def _enum_literal(self, lit: Literal, slot: dict, owner: Matcher | None,
                      index: int) -> None:
        enum = slot.get("enum") or (owner.value_set if owner else None)
        if not enum:
            return
        allowed = self.cat.enum_values(enum)
        if not allowed or lit.token.value in allowed:
            return
        import difflib
        near = difflib.get_close_matches(lit.token.value, list(allowed), n=1, cutoff=0.6)
        extra = f"; did you mean '{near[0]}'" if near else ""
        self._err(lit.start, lit.end,
                  f"Unknown value '{lit.token.value}' for arg {index + 1}{extra}",
                  code="enum-value")

    def _members(self, call: Call, matcher: Matcher, cmd: Command) -> None:
        for bind in call.binds:
            member = bind.name_token.text
            if member == "with":
                self._with(call, bind, matcher, cmd)
                continue
            if member != "bind":
                self._err(bind.name_token.start, bind.name_token.end,
                          f"unknown member `{member}`; a matcher can be followed only by "
                          f"`.bind(\"id\")` (or `.with(...)` after mapAnyOf)",
                          code="unknown-member")
                continue
            if bind.lparen is None:
                self._err(bind.start, bind.end, "`bind` needs an id: .bind(\"name\")",
                          code="bind-arity")
                continue
            if len(bind.args) != 1:
                self._err(bind.start, bind.end,
                          f"Incorrect argument count. (Expected = 1) != (Actual = "
                          f"{len(bind.args)})", code="bind-arity")
                continue
            arg = bind.args[0]
            if not isinstance(arg, Literal) or arg.token.kind != STRING:
                self._err(arg.start, arg.end, "bind id must be a string literal",
                          code="bind-arity")

    def _with(self, call: Call, bind: Bind, matcher: Matcher, cmd: Command) -> None:
        """`mapAnyOf(ifStmt, forStmt).with(hasCondition(...))`."""
        if matcher.name != "mapAnyOf":
            self._err(bind.name_token.start, bind.name_token.end,
                      "`.with(...)` applies only to mapAnyOf", code="with-owner")
            return
        if bind.lparen is None:
            self._err(bind.start, bind.end, "`.with` needs at least one matcher",
                      code="with-arity")
            return
        for index, arg in enumerate(bind.args):
            if isinstance(arg, Literal):
                self._err(arg.start, arg.end,
                          f"Incorrect type for arg {index + 1}. (Expected = Matcher<*>) != "
                          f"(Actual = {arg.kind.capitalize()})", code="arg-type")
            else:
                self._expr(arg, None, cmd, index=index)

    # -- overload resolution ----------------------------------------------
    def _resolve(self, call: Call, expected: str | None, record: bool = True) -> Resolution:
        res = Resolution()
        let = self.lets.get(call.name)
        matcher = self.cat.get(call.name)
        # A bare name is looked up among `let` names first, as clang-query does.
        if let is not None and (matcher is None or call.is_reference):
            res.let = let
        elif matcher is None:
            pass
        else:
            res.matcher = matcher
            count = len(call.args)
            by_count = [o for o in matcher.overloads if o.accepts_count(count)]
            pool = by_count or matcher.overloads
            lenient = matcher.name in LENIENT_MATCHERS
            fits = [o for o in pool
                    if expected is None or lenient or self.cat.related(o.ret, expected)]
            res.candidates = fits
            ranked = sorted(
                fits or pool,
                key=lambda o: (self.cat.distance(expected, o.ret), -len(o.params)),
            )
            res.overload = ranked[0] if ranked else None
        if record and not self._quiet:
            self._resolutions[id(call)] = res
        return res


def analyze(catalog: Catalog, doc: Document) -> tuple[list[Diagnostic], Analyzer]:
    an = Analyzer(catalog, doc)
    return an.run(), an
