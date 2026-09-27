"""Run a query script through clang-query and turn its output into JSON.

clang-query has no machine-readable output, so the script is run with a fixed
preamble that makes its text output parseable:

    set print-matcher true    ->  "  Matcher: <expr>" header per `match`
    set output dump           ->  "Binding for "id":" + AST dump line with the
    enable output diag            full source range, and a "binds here" note

The user's own output settings are blanked out (same length, so offsets in the
script do not move).  The result is what the editor shows as a table and tree:

    {"ok", "command", "cwd", "sample", "exitCode", "durationMs", "truncated",
     "files": ["<translation-unit path>"],
     "target": {"scope", "path", "roots": ["<workspace root>"]},
     "cache": {"enabled", "hits", "misses", "location", "warnings"?},
     "errors": [{"message", "range"?, "file"?}], "stderr", "cancelled"?,
     "queries": [{"matcher", "range"?, "count", "translationUnit",
                  "matches": [{"index", "bindings": [{"id", "node", "kind", "semanticKind",
                               "translationUnit", "summary",
                               "file", "uri", "location", "text",
                               "range"?}]}]}],
     "bindings": {"<id>": [{"node", "kind", ..., "matches": [{"query", "match",
                                                             "binding", "index"}]}]}}

`queries` is clang-query's view (match by match, per translation unit);
`bindings` groups the same data by bind id, with each AST address counted once
within its translation unit (see group_bindings). `semanticKind` is empty for
non-declarations. `sample` names the selected file or target directory.

Ranges are 0-based LSP ranges; binding ranges are in each binding's source file, query
and error ranges in the query document.
"""

from __future__ import annotations

import os
import json
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
from .targets import compile_flags, discover_target, translation_unit_dependencies

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
    return {"kind": kind, "semanticKind": _semantic_kind(kind, rest), "node": node,
            "begin": begin, "end": end, "summary": rest}


def _semantic_kind(kind: str, summary: str) -> str:
    """Map Clang dump classes and declaration tags to user-facing AST meaning."""
    if kind in {"CXXRecordDecl", "RecordDecl"}:
        tag = re.search(r"\b(class|struct|union)\b", summary)
        return tag.group(1) if tag else "record"
    if kind == "EnumDecl":
        return "enum"
    if kind == "EnumConstantDecl":
        return "enum constant"
    if kind in {"FunctionDecl", "CXXMethodDecl"}:
        return "function" if kind == "FunctionDecl" else "method"
    if kind in {"CXXConstructorDecl", "CXXDestructorDecl", "CXXConversionDecl"}:
        return {"CXXConstructorDecl": "constructor", "CXXDestructorDecl": "destructor",
                "CXXConversionDecl": "conversion function"}[kind]
    if kind in {"VarDecl", "ParmVarDecl", "FieldDecl", "BindingDecl"}:
        return {"VarDecl": "variable", "ParmVarDecl": "parameter", "FieldDecl": "field",
                "BindingDecl": "binding"}[kind]
    if kind in {"TypedefDecl", "TypeAliasDecl", "TypeAliasTemplateDecl"}:
        return "type alias"
    if kind in {"NamespaceDecl", "NamespaceAliasDecl"}:
        return "namespace"
    if kind.startswith("ClassTemplate") or kind.startswith("TemplateTypeParm"):
        return "template"
    if kind.endswith("Decl"):
        return "declaration"
    return ""


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
        self.path_base = os.getcwd()
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
        b = {"id": bind_id, "node": None, "kind": "", "semanticKind": "", "summary": "", "file": None, "uri": None,
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
        b["kind"], b["semanticKind"], b["summary"], b["node"] = (
            info["kind"], info["semanticKind"], info["summary"], info["node"])
        if info["begin"] and info["end"]:
            self._set_range(b, info["begin"], info["end"])
        b.pop("_open", None)

    def _set_range(self, b: dict, begin: tuple[str, int, int],
                   end: tuple[str, int, int]) -> None:
        path, line, col = begin
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(self.path_base, path))
        if not os.path.isabs(end[0]):
            end = (os.path.abspath(os.path.join(self.path_base, end[0])), end[1], end[2])
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
                tu = b.get("translationUnit") or b.get("file")
                key = (f"{tu}|" + (b.get("node") or
                       f"{b['kind']}@{b.get('file')}:{start.get('line')}:"
                       f"{start.get('character')}"))
                nodes = out.setdefault(b["id"], {})
                if key not in nodes:
                    nodes[key] = {k: b[k] for k in ("node", "kind", "semanticKind", "summary", "text", "file",
                                                    "uri", "location", "range")}
                    nodes[key]["translationUnit"] = tu
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
              on_start: Callable[[subprocess.Popen], None] | None = None,
              target: dict | None = None, exclusions: list[str] | None = None,
              compile_commands: str | None = None, traversal: str | None = None,
              cache: dict | None = None,
              cancelled: threading.Event | None = None,
              on_progress: Callable[[dict], None] | None = None) -> dict:
    """Run a query script against a file, directory, or workspace."""
    flags = list(flags or [])
    cwd = cwd or os.getcwd()
    try:
        normalized_target, files = discover_target(target, sample, cwd, exclusions)
    except (OSError, ValueError, TypeError) as exc:
        return {"ok": False, "command": [], "cwd": cwd, "sample": sample,
                "flags": flags, "exitCode": None, "durationMs": 0, "truncated": False,
                "errors": [{"message": str(exc)}], "stderr": "", "queries": [],
                "bindings": {}, "files": [], "target": target or {"scope": "file",
                "path": sample, "roots": []},
                "cache": {"enabled": bool((cache or {}).get("enabled", False)),
                          "hits": 0, "misses": 0, "location": None}}
    sample_path = normalized_target["path"]
    exe = clang_query or clang_query_path()
    doc = parse(text)
    result: dict = {"ok": False, "command": [], "cwd": cwd, "sample": sample_path,
                    "flags": flags, "exitCode": None, "durationMs": 0,
                    "truncated": False, "errors": [], "stderr": "", "queries": [],
                    "bindings": {},
                    "files": files, "target": normalized_target,
                    "cache": {"enabled": bool((cache or {}).get("enabled", False)),
                              "hits": 0, "misses": 0, "location": None}}
    if traversal not in (None, "AsIs", "IgnoreUnlessSpelledInSource"):
        result["errors"].append({"message": "traversal must be AsIs or IgnoreUnlessSpelledInSource"})
        return result
    if not files:
        if normalized_target["scope"] == "file" and not Path(sample_path).is_file():
            message = f"sample file not found: {sample_path}"
        else:
            message = f"no source files found for target: {sample_path}"
        result["errors"].append({"message": message})
        return result

    cache_cfg = cache or {}
    cache_enabled = bool(cache_cfg.get("enabled", False))
    cache_dir = Path(cache_cfg.get("location") or os.path.join(cwd, ".astmatcher-cache"))
    if not cache_dir.is_absolute():
        cache_dir = Path(cwd) / cache_dir
    if cache_enabled:
        result["cache"]["location"] = str(cache_dir.resolve())
    if on_progress:
        on_progress({"kind": "start", "sample": sample_path, "flags": flags,
                     "target": normalized_target, "totalFiles": len(files),
                     "cache": result["cache"].copy()})

    with tempfile.NamedTemporaryFile("w", suffix=".query", delete=False,
                                     encoding="utf-8") as fh:
        script_body = build_script(text, doc)
        if traversal:
            script_body = PREAMBLE + f"set traversal {traversal}\n" + script_body[len(PREAMBLE):]
        fh.write(script_body)
        script = fh.name
    started = time.monotonic()
    stderr_chunks: list[str] = []
    total_matches = 0
    try:
        for file_index, source in enumerate(files, 1):
            if cancelled is not None and cancelled.is_set():
                result["cancelled"] = True
                break
            query_start = len(result["queries"])
            error_start = len(result["errors"])
            hits_before = result["cache"]["hits"]
            misses_before = result["cache"]["misses"]

            def emit_file(queries: list[dict] | None = None, stderr: str = "") -> None:
                if not on_progress or (cancelled is not None and cancelled.is_set()):
                    return
                current = queries if queries is not None else result["queries"][query_start:]
                on_progress({"kind": "file", "file": source, "completedFiles": file_index,
                             "totalFiles": len(files), "queries": current,
                             "bindings": group_bindings(current),
                             "errors": result["errors"][error_start:], "stderr": stderr,
                             "cache": {"hits": result["cache"]["hits"] - hits_before,
                                       "misses": result["cache"]["misses"] - misses_before},
                             "durationMs": int((time.monotonic() - started) * 1000)})
            try:
                tu_flags, tu_cwd = compile_flags(compile_commands, source, flags, cwd)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                result["errors"].append({"message": str(exc), "file": source})
                emit_file()
                continue
            effective_cwd = tu_cwd or cwd
            key = None
            if cache_enabled:
                if cancelled is not None and cancelled.is_set():
                    result["cancelled"] = True
                    break
                import shutil
                resolved_exe = shutil.which(exe) or exe
                sibling_clang = str(Path(resolved_exe).resolve().with_name("clang"))
                deps = translation_unit_dependencies(source, tu_flags, effective_cwd,
                                                    sibling_clang if os.path.isfile(sibling_clang) else None)
                if deps is not None:
                    import hashlib
                    h = hashlib.sha256()
                    h.update(b"astmatcher-result-cache-v1\0")
                    h.update(text.encode())
                    h.update(json.dumps([source, tu_flags, traversal], sort_keys=True).encode())
                    try:
                        executable = Path(shutil.which(exe) or exe).resolve()
                        stat = executable.stat()
                        h.update(f"{executable}:{stat.st_size}:{stat.st_mtime_ns}".encode())
                    except OSError:
                        h.update(exe.encode())
                    for dep in sorted(set(deps + [source])):
                        try:
                            h.update(dep.encode())
                            h.update(Path(dep).read_bytes())
                        except OSError:
                            deps = None
                            break
                    if deps is not None:
                        key = h.hexdigest()
            cache_file = cache_dir / f"{key}.json" if key else None
            parsed: list[dict] | None = None
            tu_stderr = ""
            exit_code = 0
            if cache_file and cache_file.is_file():
                try:
                    cached = json.loads(cache_file.read_text(encoding="utf-8"))
                    if cached.get("schema") != 1:
                        raise ValueError("unsupported cache schema")
                    parsed, tu_stderr, exit_code = cached["queries"], cached["stderr"], cached["exitCode"]
                    cached_matches = sum(len(q.get("matches", [])) for q in parsed)
                    if total_matches + cached_matches > max_matches:
                        parsed = None
                    else:
                        result["cache"]["hits"] += 1
                        total_matches += cached_matches
                except (OSError, ValueError, KeyError):
                    parsed = None
            if parsed is None:
                if cancelled is not None and cancelled.is_set():
                    result["cancelled"] = True
                    break
                result["cache"]["misses"] += int(cache_enabled)
                parser = OutputParser()
                parser.path_base = effective_cwd
                cmd = [exe, "-f", script, source, "--", *tu_flags]
                result["command"] = cmd
                try:
                    proc = subprocess.Popen(cmd, cwd=effective_cwd, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True,
                                            encoding="utf-8", errors="replace")
                except OSError as exc:
                    result["errors"].append({"message": f"cannot run {exe}: {exc}", "file": source})
                    emit_file()
                    continue
                if on_start:
                    on_start(proc)
                assert proc.stdout is not None and proc.stderr is not None
                tu_stderr_chunks: list[str] = []
                def drain_stderr() -> None:
                    size = 0
                    for chunk in proc.stderr:
                        if size < 64_000:
                            tu_stderr_chunks.append(chunk)
                            size += len(chunk)
                err_thread = threading.Thread(target=drain_stderr, daemon=True)
                err_thread.start()
                timed_out = threading.Event()
                def kill_for_timeout() -> None:
                    timed_out.set()
                    proc.kill()
                timer = threading.Timer(timeout, kill_for_timeout)
                timer.start()
                try:
                    for line in proc.stdout:
                        parser.feed(line)
                        if total_matches + parser.matches > max_matches:
                            result["truncated"] = True
                            proc.kill()
                            break
                finally:
                    timer.cancel()
                proc.wait()
                err_thread.join(timeout=5)
                proc.stdout.close(); proc.stderr.close()
                exit_code = proc.returncode
                if cancelled is not None and cancelled.is_set():
                    result["cancelled"] = True
                if timed_out.is_set():
                    result["truncated"] = True
                    result["errors"].append({"message": f"clang-query timed out after {timeout:.0f}s",
                                             "file": source})
                state = parser.result()
                total_matches += state.matches
                attach_query_ranges(state, doc)
                parsed = state.queries
                tu_stderr = "".join(tu_stderr_chunks)
                if state.other:
                    tu_stderr = "\n".join(state.other) + ("\n" + tu_stderr if tu_stderr else "")
                result["errors"].extend(dict(e, file=source) for e in state.errors)
                if cache_file and exit_code == 0 and not state.errors and not result["truncated"]:
                    try:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        with tempfile.NamedTemporaryFile("w", dir=cache_dir, suffix=".tmp",
                                                         delete=False, encoding="utf-8") as tmp:
                            tmp.write(json.dumps({"schema": 1, "queries": parsed,
                                                  "stderr": tu_stderr, "exitCode": exit_code}))
                            tmp_name = tmp.name
                        os.replace(tmp_name, cache_file)
                    except OSError as exc:
                        result["cache"].setdefault("warnings", []).append(
                            f"could not write cache entry: {exc}")
            result["exitCode"] = exit_code if result["exitCode"] is None else max(result["exitCode"], exit_code)
            for query in parsed or []:
                query["translationUnit"] = source
                for match in query["matches"]:
                    for binding in match["bindings"]:
                        binding["translationUnit"] = source
                        binding["semanticKind"] = binding.get("semanticKind", "")
            result["queries"].extend(parsed or [])
            if tu_stderr:
                stderr_chunks.append(tu_stderr)
            emit_file(parsed or [], tu_stderr)
            if result["truncated"]:
                break
    finally:
        os.unlink(script)

    result["durationMs"] = int((time.monotonic() - started) * 1000)
    result["stderr"] = "".join(stderr_chunks)
    result["bindings"] = group_bindings(result["queries"])
    if cancelled is not None and cancelled.is_set():
        result["cancelled"] = True
    result["ok"] = (not result["errors"] and result["exitCode"] == 0 and
                     not result.get("cancelled", False))
    return result
