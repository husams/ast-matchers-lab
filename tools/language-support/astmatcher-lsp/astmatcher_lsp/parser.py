"""Error-tolerant parser for clang-query scripts.

The tree is deliberately loose: a half-typed document has to parse, because
completion asks it "what belongs at this offset?".  Missing parts are recorded
(`rparen is None`, `Error` nodes) instead of aborting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lexer import (COMMA, COMMENT, DOT, EOF, IDENT, LPAREN, NUMBER, OTHER,
                    RPAREN, STRING, Token, tokenize)

COMMAND_NAMES = {"match", "m", "let", "l", "set", "enable", "disable", "quit", "q", "help"}
BOOLEANS = {"true", "false"}
# The two members a matcher expression may carry.
MEMBERS = {"bind", "with"}


@dataclass
class Node:
    start: int = 0
    end: int = 0


@dataclass
class Literal(Node):
    token: Token = None                     # type: ignore[assignment]

    @property
    def kind(self) -> str:
        if self.token.kind == STRING:
            return "string"
        if self.token.kind == NUMBER:
            if self.token.text.startswith("-"):
                return "negative"
            if "." in self.token.text or "e" in self.token.text.lower():
                return "double"
            return "unsigned"
        if self.token.kind == IDENT and self.token.text in BOOLEANS:
            return "bool"
        return "unknown"


@dataclass
class Bind(Node):
    name_token: Token = None                # type: ignore[assignment]
    lparen: Token | None = None
    rparen: Token | None = None
    args: list["Expr"] = field(default_factory=list)
    commas: list[Token] = field(default_factory=list)


@dataclass
class Call(Node):
    name_token: Token = None                # type: ignore[assignment]
    lparen: Token | None = None
    rparen: Token | None = None
    args: list["Expr"] = field(default_factory=list)
    commas: list[Token] = field(default_factory=list)
    binds: list[Bind] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.name_token.text

    @property
    def is_reference(self) -> bool:
        """A bare name: a `let` reference, or a matcher name passed to mapAnyOf."""
        return self.lparen is None

    def arg_index_at(self, offset: int) -> int:
        return sum(1 for c in self.commas if c.end <= offset)

    def body_contains(self, offset: int) -> bool:
        if self.lparen is None:
            return False
        if offset < self.lparen.end:
            return False
        return self.rparen is None or offset <= self.rparen.start


Expr = Call | Literal


@dataclass
class Command(Node):
    keyword: Token = None                   # type: ignore[assignment]
    name: str = ""                          # normalized: match/let/set/...
    let_name: Token | None = None
    expr: Expr | None = None
    words: list[Token] = field(default_factory=list)   # set/enable/disable operands


@dataclass
class Document:
    text: str
    tokens: list[Token]
    commands: list[Command]
    lets: dict[str, Command]
    stray: list[Token]                      # tokens no command could absorb


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.toks = [t for t in tokens if t.kind != COMMENT]
        self.i = 0
        self.stray: list[Token] = []

    # -- token helpers -----------------------------------------------------
    def peek(self, ahead: int = 0) -> Token:
        j = min(self.i + ahead, len(self.toks) - 1)
        return self.toks[j]

    def next(self) -> Token:
        tok = self.peek()
        if tok.kind != EOF:
            self.i += 1
        return tok

    def at_command(self) -> bool:
        tok = self.peek()
        return tok.kind == IDENT and tok.text in COMMAND_NAMES

    # -- grammar -----------------------------------------------------------
    def parse(self) -> tuple[list[Command], list[Token]]:
        commands: list[Command] = []
        while self.peek().kind != EOF:
            if not self.at_command():
                self.stray.append(self.next())
                continue
            commands.append(self.command())
        return commands, self.stray

    def command(self) -> Command:
        kw = self.next()
        name = {"m": "match", "l": "let", "q": "quit"}.get(kw.text, kw.text)
        cmd = Command(start=kw.start, end=kw.end, keyword=kw, name=name)

        if name == "match":
            cmd.expr = self.expr()
        elif name == "let":
            if self.peek().kind == IDENT and self.peek().text not in COMMAND_NAMES:
                cmd.let_name = self.next()
            cmd.expr = self.expr()
        elif name in ("set", "enable", "disable"):
            while self.peek().kind in (IDENT, NUMBER, STRING, OTHER) and not self.at_command():
                cmd.words.append(self.next())
                if len(cmd.words) >= 3:
                    break
        cmd.end = max(cmd.end, self._last_end())
        return cmd

    def _last_end(self) -> int:
        return self.toks[self.i - 1].end if self.i else 0

    def expr(self) -> Expr | None:
        tok = self.peek()
        if tok.kind in (STRING, NUMBER):
            lit = Literal(start=tok.start, end=tok.end, token=self.next())
            return lit
        if tok.kind != IDENT:
            return None
        if tok.text in COMMAND_NAMES and self.peek(1).kind != LPAREN:
            return None                     # a new command, not an expression
        name = self.next()
        if name.text in BOOLEANS and self.peek().kind != LPAREN:
            return Literal(start=name.start, end=name.end, token=name)

        call = Call(start=name.start, end=name.end, name_token=name)
        if self.peek().kind == LPAREN:
            call.lparen = self.next()
            self._arguments(call)
        self._binds(call)
        return call

    def _arguments(self, call: Call | Bind) -> None:
        depth_guard = 0
        while True:
            tok = self.peek()
            if tok.kind == EOF:
                call.end = tok.start
                return
            if tok.kind == RPAREN:
                call.rparen = self.next()
                call.end = call.rparen.end
                return
            if tok.kind == COMMA:
                call.commas.append(self.next())
                continue
            if tok.kind == IDENT and tok.text in COMMAND_NAMES and self.peek(1).kind != LPAREN:
                call.end = tok.start        # unterminated: the next command starts here
                return
            arg = self.expr()
            if arg is None:
                self.stray.append(self.next())
            else:
                call.args.append(arg)
            depth_guard += 1
            if depth_guard > 4096:
                return

    def _binds(self, call: Call) -> None:
        while self.peek().kind == DOT and self.peek(1).kind == IDENT:
            dot = self.next()
            name = self.next()
            bind = Bind(start=dot.start, end=name.end, name_token=name)
            if self.peek().kind == LPAREN:
                bind.lparen = self.next()
                self._arguments(bind)
                bind.end = bind.rparen.end if bind.rparen else bind.end
            call.binds.append(bind)
            call.end = bind.end


def parse(text: str) -> Document:
    tokens = tokenize(text)
    parser = _Parser(tokens)
    commands, stray = parser.parse()
    lets: dict[str, Command] = {}
    for cmd in commands:
        if cmd.name == "let" and cmd.let_name:
            lets[cmd.let_name.text] = cmd
    return Document(text=text, tokens=tokens, commands=commands, lets=lets, stray=stray)


# -- position queries ------------------------------------------------------

def command_at(doc: Document, offset: int) -> Command | None:
    """The command the offset belongs to.

    Commands are sequential, so the answer is the last one that starts at or
    before the offset — which keeps working while the command is half typed
    and its expression has not been written yet.
    """
    best = None
    for cmd in doc.commands:
        if cmd.keyword.start > offset:
            break
        best = cmd
    if best is not None:
        for tok in doc.stray:
            # A stray word after the last command starts something new.
            if best.end <= tok.start <= offset and tok.kind == IDENT:
                return None
    return best


def calls_at(doc: Document, offset: int, expr: Expr | None = None) -> list[Call]:
    """Innermost-last chain of calls whose argument list contains `offset`."""
    chain: list[Call] = []
    if expr is None:
        cmd = command_at(doc, offset)
        expr = cmd.expr if cmd else None
    if not isinstance(expr, Call):
        return chain
    if expr.body_contains(offset):
        chain.append(expr)
        for arg in expr.args:
            deeper = calls_at(doc, offset, arg)
            if deeper:
                chain.extend(deeper)
                break
    for bind in expr.binds:
        if bind.lparen and (bind.rparen is None or offset <= bind.rparen.start) \
                and offset >= bind.lparen.end:
            chain.append(Call(start=bind.start, end=bind.end, name_token=bind.name_token,
                              lparen=bind.lparen, rparen=bind.rparen,
                              args=bind.args, commas=bind.commas))
    return chain


def token_at(doc: Document, offset: int, *, prefer_left: bool = True) -> Token | None:
    """The token the cursor sits in or immediately after."""
    for tok in doc.tokens:
        if tok.kind in (COMMENT, EOF):
            continue
        if tok.start <= offset <= tok.end:
            if offset == tok.end and not prefer_left:
                continue
            return tok
        if tok.start > offset:
            break
    return None


def walk(expr: Expr | None):
    if isinstance(expr, Call):
        yield expr
        for arg in expr.args:
            yield from walk(arg)
    elif isinstance(expr, Literal):
        yield expr


def bound_ids(cmd: Command) -> list[str]:
    """Every id `.bind("...")` introduces in this command."""
    out: list[str] = []
    for node in walk(cmd.expr):
        if isinstance(node, Call):
            for bind in node.binds:
                if bind.name_token.text != "bind":
                    continue
                for arg in bind.args:
                    if isinstance(arg, Literal) and arg.token.kind == STRING:
                        if arg.token.value not in out:
                            out.append(arg.token.value)
    return out
