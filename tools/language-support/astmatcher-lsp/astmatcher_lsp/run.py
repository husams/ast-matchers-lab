"""Run a query script through clang-query and turn its output into JSON.

clang-query has no machine-readable output, so the script is run with a fixed
preamble that makes its text output parseable:

    set print-matcher true    ->  "  Matcher: <expr>" header per `match`
    set output dump           ->  "Binding for "id":" + AST dump line with the
    enable output diag            full source range, and a "binds here" note

The user's own output settings are blanked out (same length, so offsets in the
script do not move).  The result is what the editor shows as a table and tree:

    {"ok", "command", "cwd", "sample", "exitCode", "durationMs", "truncated",
     "errors": [{"message", "range"?}], "stderr",
     "queries": [{"matcher", "range"?, "count",
                  "matches": [{"index", "bindings": [{"id", "node", "kind", "summary",
                               "file", "uri", "location", "text",
                               "range"?}]}]}],
     "bindings": {"<id>": [{"node", "kind", ..., "matches": [{"query", "match",
                                                             "binding", "index"}]}]}}

`queries` is clang-query's view (match by match); `bindings` the same data by
bind id with every AST node once (see group_bindings).

Ranges are 0-based LSP ranges; binding ranges are in the sample file, query
and error ranges in the query document.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .lexer import LineIndex
from .parser import Command, Document, parse

PREAMBLE = "set print-matcher true\nset output dump\nenable output diag\n"
PREAMBLE_LINES = PREAMBLE.count("\n")

_MATCHER_RE = re.compile(r"^\s*Matcher: (.*)$")
_RULE_RE = re.compile(r"^\s*=+\s*$")
_MATCH_RE = re.compile(r"^Match #(\d+):$")
_NOTE_RE = re.compile(r'^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): note: "(?P<id>[^"]*)" binds here$')
_BINDING_RE = re.compile(r'^Binding for "(?P<id>[^"]*)":$')
_COUNT_RE = re.compile(r"^(\d+) match(?:es)?\.$")
_ERROR_RE = re.compile(r"^(\d+):(\d+): (.*)$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\S")


def clang_query_path() -> str:
    """$LLVM/bin/clang-query, else PATH, else the Homebrew LLVM prefixes."""
    llvm = os.environ.get("LLVM")
    candidates = [os.path.join(llvm, "bin", "clang-query")] if llvm else []
    found = shutil.which("clang-query")
    if found:
        candidates.append(found)
    candidates += ["/opt/homebrew/opt/llvm/bin/clang-query",
                   "/usr/local/opt/llvm/bin/clang-query"]
    for path in candidates:
        if os.access(path, os.X_OK):
            return path
    return "clang-query"


# ----------------------------------------------------------------- script

def _silenced(cmd: Command) -> bool:
    """Commands that would change the output format the parser relies on."""
    if cmd.name == "set":
        return bool(cmd.words) and cmd.words[0].text in ("output", "print-matcher")
    return cmd.name in ("enable", "disable")


def build_script(text: str, doc: Document | None = None) -> str:
    doc = doc or parse(text)
    chars = list(text)
    for cmd in doc.commands:
        if _silenced(cmd):
            for i in range(cmd.start, cmd.end):
                if chars[i] != "\n":
                    chars[i] = " "
    return PREAMBLE + "".join(chars)


# ----------------------------------------------------------------- source

class _Sources:
    """Reads sample files once, to turn clang's byte columns into ranges."""

    def __init__(self) -> None:
        self._lines: dict[str, list[bytes] | None] = {}

    def line(self, path: str, line: int) -> bytes | None:
        if path not in self._lines:
            try:
                self._lines[path] = Path(path).read_bytes().split(b"\n")
            except OSError:
                self._lines[path] = None
        lines = self._lines[path]
        if lines is None or not 1 <= line <= len(lines):
            return None
        return lines[line - 1]

    def char(self, path: str, line: int, col: int) -> int:
        """1-based byte column -> 0-based character index."""
        raw = self.line(path, line)
        if raw is None:
            return max(col - 1, 0)
        return len(raw[:max(col - 1, 0)].decode("utf-8", "replace"))

    def token_end(self, path: str, line: int, col: int) -> int:
        """clang ranges end at the *start* of the last token; find its end."""
        raw = self.line(path, line)
        start = self.char(path, line, col)
        if raw is None:
            return start + 1
        text = raw.decode("utf-8", "replace")
        m = _TOKEN_RE.match(text, start)
        return m.end() if m else start + 1

    def text(self, path: str, line: int, start: int, end_line: int, end: int) -> str:
        raw = self.line(path, line)
        if raw is None:
            return ""
        first = raw.decode("utf-8", "replace")
        if end_line == line:
            return first[start:end].strip()
        return first[start:].strip() + " …"


# ----------------------------------------------------------------- dump

def _first_range(header: str) -> tuple[str, int]:
    """The `<...>` source range right after the node address, and where it ends."""
    start = header.find("<")
    if start < 0:
        return "", 0
    depth = 0
    for i in range(start, len(header)):
        if header[i] == "<":
            depth += 1
        elif header[i] == ">":
            depth -= 1
            if depth == 0:
                return header[start + 1:i], i + 1
    return "", 0


def _split_locations(inner: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in inner:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    # `file.cpp:3:5 <Spelling=...>` -> `file.cpp:3:5`
    return [re.sub(r"\s*<Spelling=.*$", "", loc) for loc in out]


_FULL_LOC = re.compile(r"^(?P<path>.+):(?P<line>\d+):(?P<col>\d+)$")
_LINE_LOC = re.compile(r"^line:(?P<line>\d+):(?P<col>\d+)$")
_COL_LOC = re.compile(r"^col:(?P<col>\d+)$")


def _resolve(loc: str, base: tuple[str, int, int] | None) -> tuple[str, int, int] | None:
    m = _COL_LOC.match(loc)
    if m:
        return (base[0], base[1], int(m["col"])) if base else None
    m = _LINE_LOC.match(loc)
    if m:
        return (base[0], int(m["line"]), int(m["col"])) if base else None
    m = _FULL_LOC.match(loc)
    if m and not m["path"].startswith("<"):
        return m["path"], int(m["line"]), int(m["col"])
    return None


def parse_dump_header(header: str) -> dict:
    """`CXXRecordDecl 0x... </a.cpp:47:1, col:38> col:8 struct Pair definition`.

    The address is the node's identity: the same address in two matches is the
    same AST node, bound twice.
    """
    m = re.match(r"^(\S+)(?:\s+(0x[0-9a-f]+))?\s*", header)
    kind, node = m.group(1), m.group(2)
    rest = header[m.end():]
    begin = end = None
    if rest.startswith("<"):                # a type has no range: 'vector<int>' is not one
        inner, after = _first_range(rest)
        locs = _split_locations(inner)
        begin = _resolve(locs[0], None)
        end = _resolve(locs[-1], begin) if len(locs) > 1 else begin
        rest = rest[after:]
    # drop the node's own location (`col:8`, `line:3:5`, `file:3:5`)
    rest = re.sub(r"^\s*(?:col:\d+|line:\d+:\d+|\S+:\d+:\d+)(?:\s+<Spelling=[^>]*>)?", "",
                  rest).strip()
    return {"kind": kind, "node": node, "begin": begin, "end": end, "summary": rest}


# ----------------------------------------------------------------- output

@dataclass
class _State:
    queries: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    matches: int = 0


class OutputParser:
    """Line-at-a-time parser of clang-query's text output (see module doc)."""

    def __init__(self, sources: _Sources | None = None) -> None:
        self.src = sources or _Sources()
        self.s = _State()
        self._query: dict | None = None
        self._match: dict | None = None
        self._pending_binding: str | None = None    # after `Binding for "id":`
        self._in_matcher_header = False
        self._in_snippet = False

    @property
    def matches(self) -> int:
        return self.s.matches

    def feed(self, line: str) -> None:
        line = line.rstrip("\r\n")
        if self._pending_binding is not None:
            self._dump(self._pending_binding, line)
            self._pending_binding = None
            return
        if self._in_matcher_header:
            if _RULE_RE.match(line):
                self._in_matcher_header = False
            elif self._query is not None:
                self._query["matcher"] += "\n" + line.strip()
            return
        m = _MATCHER_RE.match(line)
        if m:
            self._query = {"matcher": m.group(1).strip(), "count": 0, "matches": []}
            self.s.queries.append(self._query)
            self._match = None
            self._in_matcher_header = True
            return
        m = _MATCH_RE.match(line)
        if m and self._query is not None:
            self._match = {"index": int(m.group(1)), "bindings": []}
            self._query["matches"].append(self._match)
            self.s.matches += 1
            return
        m = _NOTE_RE.match(line)
        if m and self._match is not None:
            self._note(m)
            return
        m = _BINDING_RE.match(line)
        if m and self._match is not None:
            self._pending_binding = m.group("id")
            return
        m = _COUNT_RE.match(line)
        if m and self._query is not None:
            self._query["count"] = int(m.group(1))
            self._query, self._match = None, None
            return
        m = _ERROR_RE.match(line)
        if m and self._query is None:
            self.s.errors.append({"line": int(m.group(1)), "column": int(m.group(2)),
                                  "message": m.group(3)})
            return
        if self._match is not None:
            return                          # source snippet / AST dump body
        if line.strip():
            self.s.other.append(line)

    # -- bindings ----------------------------------------------------------
    def _binding(self, bind_id: str) -> dict:
        assert self._match is not None
        for b in self._match["bindings"]:
            if b["id"] == bind_id and b.get("_open"):
                return b
        b = {"id": bind_id, "node": None, "kind": "", "summary": "", "file": None, "uri": None,
             "location": "", "text": "", "range": None, "_open": True}
        self._match["bindings"].append(b)
        return b

    def _note(self, m: re.Match) -> None:
        b = self._binding(m["id"])
        path, line, col = m["path"], int(m["line"]), int(m["col"])
        self._set_range(b, (path, line, col), (path, line, col))

    def _dump(self, bind_id: str, header: str) -> None:
        b = self._binding(bind_id)
        info = parse_dump_header(header)
        b["kind"], b["summary"], b["node"] = info["kind"], info["summary"], info["node"]
        if info["begin"] and info["end"]:
            self._set_range(b, info["begin"], info["end"])
        b.pop("_open", None)

    def _set_range(self, b: dict, begin: tuple[str, int, int],
                   end: tuple[str, int, int]) -> None:
        path, line, col = begin
        if end[0] != path:
            end = begin
        start_char = self.src.char(path, line, col)
        end_char = self.src.token_end(path, end[1], end[2])
        b["file"] = path
        b["uri"] = Path(path).resolve().as_uri() if os.path.isabs(path) else None
        b["location"] = f"{os.path.basename(path)}:{line}:{col}"
        b["range"] = {"start": {"line": line - 1, "character": start_char},
                      "end": {"line": end[1] - 1, "character": end_char}}
        b["text"] = self.src.text(path, line, start_char, end[1], end_char)[:200]

    def result(self) -> _State:
        for q in self.s.queries:
            for m in q["matches"]:
                for b in m["bindings"]:
                    b.pop("_open", None)
                # clang-query prints ids alphabetically; `root` reads best first.
                m["bindings"].sort(key=lambda b: b["id"] != "root")
        return self.s


# ----------------------------------------------------------------- grouping

def group_bindings(queries: list[dict]) -> dict[str, list[dict]]:
    """{bind id: [distinct node, ...]}, each node listing the matches that bound it.

    Nodes are told apart by their AST address, so `d` in

        cxxRecordDecl(eachOf(has(...).bind("v"), has(...).bind("v"))).bind("d")

    is one record found by two matches, while `v` is two different fields:

        {"d": [{..., "matches": [{"query": 0, "match": 0, "binding": 1, "index": 1},
                                 {"query": 0, "match": 1, "binding": 1, "index": 2}]}],
         "v": [{... "first" ..., "matches": [#1]}, {... "second" ..., "matches": [#2]}]}

    `root` comes first; the other ids in order of first appearance.
    """
    out: dict[str, dict[str, dict]] = {}
    for qi, q in enumerate(queries):
        for mi, m in enumerate(q["matches"]):
            for bi, b in enumerate(m["bindings"]):
                r = b.get("range") or {}
                start = r.get("start") or {}
                key = b.get("node") or f"{b['kind']}@{b.get('file')}:{start.get('line')}:" \
                                       f"{start.get('character')}"
                nodes = out.setdefault(b["id"], {})
                if key not in nodes:
                    nodes[key] = {k: b[k] for k in ("node", "kind", "summary", "text", "file",
                                                    "uri", "location", "range")}
                    nodes[key]["matches"] = []
                nodes[key]["matches"].append({"query": qi, "match": mi, "binding": bi,
                                              "index": m["index"]})
    ids = sorted(out, key=lambda i: i != "root")
    return {i: list(out[i].values()) for i in ids}


# ----------------------------------------------------------------- mapping

def _lsp_range(index: LineIndex, start: int, end: int) -> dict:
    sl, sc = index.position(start)
    el, ec = index.position(end)
    return {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}


def attach_query_ranges(state: _State, doc: Document) -> None:
    """Point each result and error back at the command in the query file.

    clang-query runs the commands in order and stops at the first one it cannot
    parse; every `match` it ran printed a "Matcher:" header.  So the n-th header
    is the n-th `match`, and an error belongs to the first command after the
    last `match` that ran.
    """
    index = LineIndex(doc.text)
    matches = [c for c in doc.commands if c.name == "match"]
    for q, cmd in zip(state.queries, matches):
        q["range"] = _lsp_range(index, cmd.start, cmd.end)
    if not state.errors:
        return
    ran = len(state.queries)
    after = matches[ran - 1].end if ran else 0
    failed = next((c for c in doc.commands
                   if c.start >= after and c.name in ("match", "let", "set", "enable",
                                                      "disable")), None)
    for err in state.errors:
        if failed is None:
            continue
        if failed.name == "let" and failed.let_name is not None:
            base = failed.let_name.end          # clang-query counts from after the name
        elif failed.expr is not None:
            base = failed.expr.start            # ... and from the expression of a match
        else:
            base = failed.keyword.end
        bl, bc = index.position(base)
        line = bl + err["line"] - 1
        col = (bc if err["line"] == 1 else 0) + err["column"] - 1
        start = index.offset(line, col)
        tok = next((t for t in doc.tokens if t.start <= start < t.end), None)
        err["range"] = _lsp_range(index, start, tok.end if tok else start + 1)


# ----------------------------------------------------------------- running

def run_query(text: str, sample: str, flags: list[str] | None = None, *,
              clang_query: str | None = None, cwd: str | None = None,
              timeout: float = 120.0, max_matches: int = 5000,
              on_start: Callable[[subprocess.Popen], None] | None = None) -> dict:
    """Run `text` (a whole query script) against `sample`; return the JSON result."""
    flags = list(flags or [])
    cwd = cwd or os.getcwd()
    sample_path = sample if os.path.isabs(sample) else os.path.join(cwd, sample)
    exe = clang_query or clang_query_path()
    doc = parse(text)
    result: dict = {"ok": False, "command": [], "cwd": cwd, "sample": sample_path,
                    "flags": flags, "exitCode": None, "durationMs": 0,
                    "truncated": False, "errors": [], "stderr": "", "queries": []}
    if not os.path.isfile(sample_path):
        result["errors"].append({"message": f"sample file not found: {sample_path}"})
        return result

    with tempfile.NamedTemporaryFile("w", suffix=".query", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(build_script(text, doc))
        script = fh.name
    cmd = [exe, "-f", script, sample_path, "--", *flags]
    result["command"] = cmd
    started = time.monotonic()
    parser = OutputParser()
    stderr_chunks: list[str] = []
    try:
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace")
        except OSError as exc:
            result["errors"].append({"message": f"cannot run {exe}: {exc}"})
            return result
        if on_start:
            on_start(proc)

        assert proc.stdout is not None and proc.stderr is not None

        def drain_stderr() -> None:
            assert proc.stderr is not None
            size = 0
            for chunk in proc.stderr:
                if size < 64_000:
                    stderr_chunks.append(chunk)
                    size += len(chunk)

        err_thread = threading.Thread(target=drain_stderr, daemon=True)
        err_thread.start()
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            for line in proc.stdout:
                parser.feed(line)
                if parser.matches > max_matches:
                    result["truncated"] = True
                    proc.kill()
                    break
        finally:
            timer.cancel()
        proc.wait()
        err_thread.join(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
        timed_out = time.monotonic() - started >= timeout
        result["exitCode"] = proc.returncode
        if timed_out:
            result["truncated"] = True
            result["errors"].append({"message": f"clang-query timed out after {timeout:.0f}s"})
    finally:
        os.unlink(script)

    state = parser.result()
    attach_query_ranges(state, doc)
    result["durationMs"] = int((time.monotonic() - started) * 1000)
    result["queries"] = state.queries
    result["bindings"] = group_bindings(state.queries)
    result["errors"].extend(state.errors)
    result["stderr"] = "".join(stderr_chunks)
    if state.other:
        result["stderr"] = "\n".join(state.other) + ("\n" + result["stderr"]
                                                    if result["stderr"] else "")
    result["ok"] = not result["errors"] and proc.returncode == 0
    return result
