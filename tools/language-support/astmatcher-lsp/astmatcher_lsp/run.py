"""Run AST matcher scripts through the native C++ gRPC server.

The Python LSP discovers translation units and compile flags, sends typed
commands to the native server, and preserves the existing runQuery JSON shape:

    {"ok", "command", "cwd", "sample", "exitCode", "durationMs", "truncated",
     "files", "target", "cache", "errors", "stderr", "cancelled"?,
     "queries": [{"matcher", "range"?, "count", "translationUnit",
                  "matches": [{"index", "bindings": [{"id", "node", "kind",
                  "semanticKind", "translationUnit", "summary", "file", "uri",
                  "location", "text", "range"?}]}]}],
     "bindings": {"<id>": [{"node", "kind", ..., "matches": [...]}]}}

All ranges are zero-based LSP ranges; source ends are exclusive.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .lexer import COMMENT, EOF, IDENT, LineIndex
from .native_client import NativeClient, NativeClientError, get_client
from .parser import Command, Document, parse
from .targets import compile_flags, discover_target, translation_unit_dependencies


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



# ----------------------------------------------------------------- running

def native_commands(doc: Document) -> tuple[list[dict], list[Command], dict | None]:
    """Validate script tokens in order, then keep commands the native server handles."""
    commands: list[dict] = []
    originals: list[Command] = []
    index = LineIndex(doc.text)
    output_features = {"print", "diag", "dump", "detailed-ast"}
    outside = [token for token in doc.tokens if token.kind not in (COMMENT, EOF)
               and not any(cmd.start <= token.start and token.end <= cmd.end
                           for cmd in doc.commands)]
    events = sorted([(cmd.start, "command", cmd) for cmd in doc.commands] +
                    [(token.start, "stray", token) for token in outside],
                    key=lambda event: event[0])

    def issue(message: str, start: int, end: int) -> dict:
        return {"message": message, "range": _lsp_range(index, start, end)}

    previous: Command | None = None
    previous_emitted = False
    for _, kind, item in events:
        if previous is not None and index.position(previous.end)[0] == index.position(item.start)[0]:
            if previous_emitted:
                commands.pop()
                originals.pop()
            token = item if kind == "stray" else item.keyword
            return commands, originals, issue(f"Unexpected token: {token.text}",
                                              token.start, token.end)
        if kind == "stray":
            return commands, originals, issue(f"Unexpected token: {item.text}",
                                              item.start, item.end)
        cmd = item
        if cmd.name == "quit":
            break
        command = None
        if cmd.name == "match":
            command = {"kind": "MATCH", "expression":
                       doc.text[cmd.expr.start:cmd.expr.end] if cmd.expr else ""}
        elif cmd.name == "let":
            command = {"kind": "LET", "name": cmd.let_name.text if cmd.let_name else "",
                       "expression": doc.text[cmd.expr.start:cmd.expr.end] if cmd.expr else ""}
        elif cmd.name == "set":
            if len(cmd.words) > 2:
                extra = cmd.words[2]
                return commands, originals, issue(f"Unexpected token: {extra.text}",
                                                  extra.start, extra.end)
            if not cmd.words:
                return commands, originals, issue("Missing setting name",
                                                  cmd.start, cmd.end)
            option = cmd.words[0]
            setting = option.text
            value_token = cmd.words[1] if len(cmd.words) >= 2 else None
            if option.kind != IDENT:
                return commands, originals, issue(f"Unexpected setting: {setting}",
                                                  option.start, option.end)
            if value_token is not None and value_token.kind != IDENT:
                return commands, originals, issue(f"Unexpected value: {value_token.text}",
                                                  value_token.start, value_token.end)
            value = value_token.text if value_token else ""
            if setting == "traversal":
                command = {"kind": "SET_TRAVERSAL", "value": value}
            elif setting == "bind-root":
                command = {"kind": "SET_BIND_ROOT", "value": value}
            elif setting == "output":
                if value not in output_features:
                    token = value_token or option
                    return commands, originals, issue("Invalid output mode",
                                                      token.start, token.end)
            elif setting == "print-matcher":
                if value not in ("true", "false"):
                    token = value_token or option
                    return commands, originals, issue("Invalid print-matcher value",
                                                      token.start, token.end)
            else:
                return commands, originals, issue(f"Unsupported setting: {setting}",
                                                  option.start, option.end)
        elif cmd.name in ("enable", "disable"):
            if len(cmd.words) != 2:
                token = cmd.words[2] if len(cmd.words) > 2 else (
                    cmd.words[-1] if cmd.words else cmd.keyword)
                return commands, originals, issue(f"Invalid {cmd.name} output command",
                                                  token.start, token.end)
            option, feature = cmd.words
            if option.kind != IDENT or option.text != "output" or \
                    feature.kind != IDENT or feature.text not in output_features:
                return commands, originals, issue(f"Invalid {cmd.name} output command",
                                                  feature.start, feature.end)
        else:
            return commands, originals, issue(f"Unsupported command: {cmd.name}",
                                              cmd.start, cmd.end)
        if command is not None:
            commands.append(command)
            originals.append(cmd)
        previous = cmd
        previous_emitted = command is not None
    return commands, originals, None


def _native_binding(binding: dict, working_directory: str) -> dict:
    source_range = binding.get("range")
    path = None
    uri = None
    location = ""
    lsp_range = None
    if isinstance(source_range, dict) and source_range.get("file"):
        raw = Path(source_range["file"])
        path = str((raw if raw.is_absolute() else Path(working_directory) / raw).resolve())
        start = source_range.get("start") or {}
        end = source_range.get("end") or {}
        lsp_range = {"start": {"line": int(start.get("line", 0)),
                               "character": int(start.get("character", 0))},
                     "end": {"line": int(end.get("line", 0)),
                             "character": int(end.get("character", 0))}}
        uri = Path(path).as_uri()
        location = (f"{Path(path).name}:{lsp_range['start']['line'] + 1}:"
                    f"{lsp_range['start']['character'] + 1}")
    return {"id": binding.get("id", ""), "node": binding.get("node") or None,
            "kind": binding.get("kind", ""),
            "semanticKind": binding.get("semanticKind", ""),
            "summary": binding.get("summary", ""), "text": binding.get("text", ""),
            "file": path, "uri": uri, "location": location, "range": lsp_range}


def _native_diagnostic(diagnostic: dict, originals: list[Command],
                       doc: Document) -> dict:
    error = {"message": diagnostic.get("message", "native matcher error")}
    command_index = int(diagnostic.get("commandIndex", 0))
    if not 0 <= command_index < len(originals):
        return error
    cmd = originals[command_index]
    index = LineIndex(doc.text)
    if cmd.expr is not None:
        base = cmd.expr.start
    elif cmd.words:
        base = cmd.words[1].start if len(cmd.words) >= 2 else cmd.words[0].start
    else:
        base = cmd.keyword.end
    base_line, base_column = index.position(base)
    relative_line = max(0, int(diagnostic.get("line", 0)))
    relative_column = max(0, int(diagnostic.get("column", 0)))
    line = base_line + relative_line
    column = (base_column if relative_line == 0 else 0) + relative_column
    start = index.offset(line, column)
    token = next((tok for tok in doc.tokens if tok.start <= start < tok.end), None)
    error["range"] = _lsp_range(index, start, token.end if token else start + 1)
    return error


def _native_queries(reply: dict, originals: list[Command], doc: Document,
                    working_directory: str, source_file: str) -> list[dict]:
    index = LineIndex(doc.text)
    main_file = str(Path(source_file).resolve())
    output = []
    for raw_query in reply.get("queries", []):
        command_index = int(raw_query.get("commandIndex", 0))
        cmd = originals[command_index] if 0 <= command_index < len(originals) else None
        query = {"matcher": raw_query.get("matcher", ""), "count": int(raw_query.get("count", 0)),
                 "matches": []}
        if cmd is not None:
            query["range"] = _lsp_range(index, cmd.start, cmd.end)
        for raw_match in raw_query.get("matches", []):
            bindings = [_native_binding(b, working_directory)
                        for b in raw_match.get("bindings", [])]
            # clang visits declarations in included headers too. Keep only
            # matches whose matched node is spelled in this translation unit,
            # then omit any auxiliary bindings that point into included files.
            root = next((binding for binding in bindings if binding["id"] == "root"), None)
            main_bindings = [binding for binding in bindings
                             if binding["file"] == main_file or
                             (binding["file"] is None and binding["kind"] == "TranslationUnitDecl")]
            if (bindings and root is not None and root["file"] != main_file and
                    not (root["file"] is None and root["kind"] == "TranslationUnitDecl")):
                continue
            if bindings and root is None and not main_bindings:
                continue
            bindings = main_bindings
            bindings.sort(key=lambda b: b["id"] != "root")
            query["matches"].append({"index": int(raw_match.get("index", 0)),
                                     "bindings": bindings})
        query["count"] = len(query["matches"])
        output.append(query)
    return output


def _valid_cached_queries(queries: object) -> bool:
    """Reject damaged cache data before it reaches result grouping."""
    if not isinstance(queries, list):
        return False
    for query in queries:
        if (not isinstance(query, dict) or
                not isinstance(query.get("matcher"), str) or
                type(query.get("count")) is not int or
                not isinstance(query.get("matches"), list)):
            return False
        for match in query["matches"]:
            if (not isinstance(match, dict) or
                    type(match.get("index")) is not int or
                    not isinstance(match.get("bindings"), list)):
                return False
            for binding in match["bindings"]:
                if not isinstance(binding, dict) or not isinstance(binding.get("id"), str):
                    return False
                if not all(key in binding for key in
                           ("node", "kind", "semanticKind", "summary", "text",
                            "file", "uri", "location", "range")):
                    return False
                source_range = binding["range"]
                if source_range is not None:
                    if not isinstance(source_range, dict):
                        return False
                    for position in ("start", "end"):
                        point = source_range.get(position)
                        if (not isinstance(point, dict) or
                                type(point.get("line")) is not int or
                                type(point.get("character")) is not int):
                            return False
    return True


def run_query(text: str, sample: str, flags: list[str] | None = None, *,
              cwd: str | None = None,
              timeout: float = 120.0, max_matches: int = 5000,
              on_start: Callable[[subprocess.Popen], None] | None = None,
              target: dict | None = None, exclusions: list[str] | None = None,
              compile_commands: str | None = None, traversal: str | None = None,
              cache: dict | None = None, cancelled: threading.Event | None = None,
              on_progress: Callable[[dict], None] | None = None,
              native_server: str | None = None,
              client: NativeClient | None = None) -> dict:
    """Run a query script against a file, directory, or workspace."""
    flags = list(flags or [])
    cwd = cwd or os.getcwd()
    try:
        normalized_target, files = discover_target(target, sample, cwd, exclusions)
    except (OSError, ValueError, TypeError) as exc:
        return {"ok": False, "command": [], "cwd": cwd, "sample": sample,
                "flags": flags, "exitCode": None, "durationMs": 0, "truncated": False,
                "errors": [{"message": str(exc)}], "stderr": "", "queries": [],
                "bindings": {}, "files": [], "target": target or
                {"scope": "file", "path": sample, "roots": []},
                "cache": {"enabled": bool((cache or {}).get("enabled", False)),
                          "hits": 0, "misses": 0, "location": None}}
    sample_path = normalized_target["path"]
    doc = parse(text)
    commands, originals, script_error = native_commands(doc)
    result: dict = {"ok": False, "command": [], "cwd": cwd, "sample": sample_path,
                    "flags": flags, "exitCode": None, "durationMs": 0,
                    "truncated": False, "errors": [], "stderr": "", "queries": [],
                    "bindings": {}, "files": files, "target": normalized_target,
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
    if not commands:
        result["exitCode"] = 0
        if script_error is not None:
            result["errors"].append(dict(script_error, file=files[0]))
        else:
            result["ok"] = True
        return result
    try:
        client = client or get_client(native_server)
    except NativeClientError as exc:
        result["errors"].append({"message": str(exc)})
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

    started = time.monotonic()
    stderr_chunks: list[str] = []
    total_matches = 0
    for file_index, source in enumerate(files, 1):
        if cancelled is not None and cancelled.is_set():
            result["cancelled"] = True
            break
        if total_matches >= max_matches:
            result["truncated"] = True
            break
        query_start = len(result["queries"])
        error_start = len(result["errors"])
        hits_before = result["cache"]["hits"]
        misses_before = result["cache"]["misses"]

        if on_progress:
            on_progress({"kind": "file-start", "file": source,
                         "completedFiles": file_index - 1, "totalFiles": len(files),
                         "durationMs": int((time.monotonic() - started) * 1000)})

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
            try:
                compiler_path = getattr(client, "compiler_path", None)
            except NativeClientError:
                compiler_path = None
            compiler_identity = None
            if (isinstance(compiler_path, str) and os.path.isabs(compiler_path) and
                    os.path.isfile(compiler_path) and os.access(compiler_path, os.X_OK)):
                try:
                    compiler_stat = os.stat(compiler_path)
                    compiler_identity = (compiler_path, compiler_stat.st_size,
                                         compiler_stat.st_mtime_ns)
                except OSError:
                    pass
            deps = (translation_unit_dependencies(source, tu_flags, effective_cwd,
                                                  compiler_path)
                    if compiler_identity is not None else None)
            if deps is not None:
                import hashlib
                h = hashlib.sha256()
                h.update(b"astmatcher-native-result-cache-v6\0")
                h.update(text.encode())
                h.update(json.dumps([source, tu_flags, effective_cwd, traversal],
                                    sort_keys=True).encode())
                h.update(json.dumps(compiler_identity).encode())
                try:
                    executable = Path(client.binary).resolve()
                    stat = executable.stat()
                    h.update(f"{executable}:{stat.st_size}:{stat.st_mtime_ns}".encode())
                except OSError:
                    h.update(client.binary.encode())
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
                if not isinstance(cached, dict) or cached.get("schema") != 6:
                    raise ValueError("unsupported cache schema")
                parsed, tu_stderr, exit_code = (
                    cached["queries"], cached["stderr"], cached["exitCode"])
                if (not _valid_cached_queries(parsed) or
                        not isinstance(tu_stderr, str) or
                        not isinstance(exit_code, int) or isinstance(exit_code, bool)):
                    raise ValueError("invalid cache entry")
                cached_matches = sum(len(q.get("matches", [])) for q in parsed)
                if total_matches + cached_matches > max_matches:
                    parsed = None
                else:
                    result["cache"]["hits"] += 1
                    total_matches += cached_matches
            except (OSError, ValueError, KeyError):
                parsed = None
        native_failed = False
        if parsed is None:
            if cancelled is not None and cancelled.is_set():
                result["cancelled"] = True
                break
            result["cache"]["misses"] += int(cache_enabled)
            request = {"sourcePath": source, "workingDirectory": effective_cwd,
                       "flags": tu_flags, "traversal": traversal or "AsIs",
                       "maxMatches": max_matches - total_matches,
                       "commands": commands}
            try:
                def native_progress(event: dict) -> None:
                    if on_progress and (cancelled is None or not cancelled.is_set()):
                        on_progress({"kind": "heartbeat", "file": source,
                                     "completedFiles": file_index - 1,
                                     "totalFiles": len(files),
                                     "fileDurationMs": int(event.get("elapsedMs", 0)),
                                     "durationMs": int((time.monotonic() - started) * 1000)})

                reply, command, exit_code, client_stderr = client.run(
                    request, cwd=effective_cwd, timeout=timeout, on_start=on_start,
                    on_progress=native_progress)
                result["command"] = command
            except NativeClientError as exc:
                if cancelled is not None and cancelled.is_set():
                    result["cancelled"] = True
                    break
                if "timed out" in str(exc):
                    result["truncated"] = True
                result["errors"].append({"message": str(exc), "file": source})
                emit_file()
                continue
            if cancelled is not None and cancelled.is_set():
                result["cancelled"] = True
            parsed = _native_queries(reply, originals, doc, effective_cwd, source)
            result["truncated"] = bool(reply.get("truncated", False))
            tu_stderr = (reply.get("stderr") or "") + client_stderr
            diagnostics = [_native_diagnostic(d, originals, doc)
                           for d in reply.get("diagnostics", [])]
            native_failed = bool(diagnostics)
            if any("Clang failed to parse the source file" in error["message"]
                   for error in diagnostics):
                parsed = []
            total_matches += sum(len(q["matches"]) for q in parsed)
            result["errors"].extend(dict(e, file=source) for e in diagnostics)
            if (cache_file and exit_code == 0 and not diagnostics and
                    script_error is None and not result["truncated"]):
                try:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile("w", dir=cache_dir, suffix=".tmp",
                                                     delete=False, encoding="utf-8") as tmp:
                        tmp.write(json.dumps({"schema": 6, "queries": parsed,
                                              "stderr": tu_stderr, "exitCode": exit_code}))
                        tmp_name = tmp.name
                    os.replace(tmp_name, cache_file)
                except OSError as exc:
                    result["cache"].setdefault("warnings", []).append(
                        f"could not write cache entry: {exc}")
        if script_error is not None and not native_failed:
            result["errors"].append(dict(script_error, file=source))
        result["exitCode"] = (exit_code if result["exitCode"] is None
                              else max(result["exitCode"], exit_code))
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
        if result["truncated"] or result.get("cancelled"):
            break

    result["durationMs"] = int((time.monotonic() - started) * 1000)
    result["stderr"] = "".join(stderr_chunks)
    result["bindings"] = group_bindings(result["queries"])
    if cancelled is not None and cancelled.is_set():
        result["cancelled"] = True
    result["ok"] = (not result["errors"] and result["exitCode"] == 0 and
                    not result.get("cancelled", False))
    return result
