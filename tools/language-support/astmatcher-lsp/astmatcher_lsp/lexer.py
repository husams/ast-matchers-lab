"""Tokenizer for clang-query input.

clang-query reads a whole `-f` script at once: `#` runs to end of line and a
matcher expression may span as many lines as its parentheses need.  The lexer
therefore works on offsets into the whole document, not on lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COMMENT = "comment"
IDENT = "ident"
STRING = "string"
NUMBER = "number"
LPAREN = "lparen"
RPAREN = "rparen"
COMMA = "comma"
DOT = "dot"
OTHER = "other"
EOF = "eof"

# `-` is part of a word so that settings like `print-matcher` and features like
# `detailed-ast` are single tokens; the DSL itself has no arithmetic operators.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:(?:::|-)[A-Za-z_][A-Za-z0-9_]*)*")
# A leading `-` is lexed as part of the number so that `equals(-1)` can be
# reported precisely (clang-query rejects it); `314e-2` is legal.
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_SIMPLE = {"(": LPAREN, ")": RPAREN, ",": COMMA, ".": DOT}


@dataclass
class Token:
    kind: str
    text: str
    start: int
    end: int
    value: str = ""          # STRING: the decoded contents
    terminated: bool = True  # STRING: closing quote seen

    def covers(self, offset: int) -> bool:
        return self.start <= offset <= self.end


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            tokens.append(Token(COMMENT, text[i:j], i, j))
            i = j
            continue
        if ch == '"':
            j, buf, terminated = i + 1, [], False
            while j < n:
                c = text[j]
                if c == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                if c == '"':
                    terminated = True
                    j += 1
                    break
                if c == "\n":       # clang-query does not allow a raw newline
                    break
                buf.append(c)
                j += 1
            tokens.append(Token(STRING, text[i:j], i, j,
                                value="".join(buf), terminated=terminated))
            i = j
            continue
        if ch in _SIMPLE:
            tokens.append(Token(_SIMPLE[ch], ch, i, i + 1))
            i += 1
            continue
        m = _IDENT_RE.match(text, i)
        if m:
            tokens.append(Token(IDENT, m.group(), i, m.end()))
            i = m.end()
            continue
        m = _NUMBER_RE.match(text, i)
        if m:
            tokens.append(Token(NUMBER, m.group(), i, m.end()))
            i = m.end()
            continue
        tokens.append(Token(OTHER, ch, i, i + 1))
        i += 1
    tokens.append(Token(EOF, "", n, n))
    return tokens


class LineIndex:
    """Offset <-> (line, character) conversion, 0-based, as LSP wants it."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self.starts.append(i + 1)

    def position(self, offset: int) -> tuple[int, int]:
        offset = max(0, min(offset, len(self.text)))
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo, offset - self.starts[lo]

    def offset(self, line: int, character: int) -> int:
        if line < 0:
            return 0
        if line >= len(self.starts):
            return len(self.text)
        start = self.starts[line]
        end = self.starts[line + 1] - 1 if line + 1 < len(self.starts) else len(self.text)
        return min(start + character, end)
