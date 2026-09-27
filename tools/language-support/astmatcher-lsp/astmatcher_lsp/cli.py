"""Command line entry point: `--stdio` for editors, `--check` for everyone else."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyze import ERROR, analyze
from .catalog import load
from .features import completions, context_at, hover, signature_help
from .lexer import LineIndex
from .parser import parse
from .run import run_query

SEVERITY = {1: "error", 2: "warning", 3: "note", 4: "hint"}


def check(paths: list[str], data_dir: str | None, as_json: bool = False) -> int:
    cat = load(data_dir)
    failures = 0
    payload = []
    for path in paths:
        text = sys.stdin.read() if path == "-" else Path(path).read_text()
        doc = parse(text)
        index = LineIndex(text)
        diags, _ = analyze(cat, doc)
        for diag in diags:
            line, char = index.position(diag.start)
            if as_json:
                payload.append({"file": path, "line": line + 1, "column": char + 1,
                                "severity": SEVERITY[diag.severity],
                                "code": diag.code, "message": diag.message})
            else:
                print(f"{path}:{line + 1}:{char + 1}: {SEVERITY[diag.severity]}: "
                      f"{diag.message}" + (f" [{diag.code}]" if diag.code else ""))
            if diag.severity == ERROR:
                failures += 1
    if as_json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    return 1 if failures else 0


def _position(text: str, spec: str) -> int:
    """LINE:COL (1-based, as editors report) or a bare byte offset."""
    if ":" in spec:
        line, _, col = spec.partition(":")
        return LineIndex(text).offset(int(line) - 1, int(col) - 1)
    return int(spec)


def inspect(path: str, spec: str, what: str, data_dir: str | None) -> int:
    cat = load(data_dir)
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    doc = parse(text)
    offset = _position(text, spec)
    if what == "complete":
        items = completions(cat, doc, offset)
        items.sort(key=lambda i: (i.get("sortText", ""), i["label"]))
        json.dump({"context": context_at(cat, doc, offset).kind,
                   "items": [{k: v for k, v in i.items() if k != "documentation"}
                             for i in items]}, sys.stdout, indent=2)
    elif what == "hover":
        json.dump(hover(cat, doc, offset), sys.stdout, indent=2)
    else:
        json.dump(signature_help(cat, doc, offset), sys.stdout, indent=2)
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="astmatcher-lsp",
        description="Language support for the Clang AST Matcher DSL (clang-query).")
    ap.add_argument("--version", action="version", version=f"astmatcher-lsp {__version__}")
    ap.add_argument("--stdio", action="store_true",
                    help="run as an LSP server over stdin/stdout (default with no files)")
    ap.add_argument("--check", nargs="*", metavar="FILE",
                    help="type-check .query files and print diagnostics ('-' for stdin)")
    ap.add_argument("--json", action="store_true", help="machine-readable --check output")
    ap.add_argument("--at", metavar="LINE:COL",
                    help="with --complete/--hover/--signature: where to look")
    ap.add_argument("--complete", metavar="FILE", help="print completions at --at")
    ap.add_argument("--hover", metavar="FILE", help="print hover text at --at")
    ap.add_argument("--signature", metavar="FILE", help="print signature help at --at")
    ap.add_argument("--data", metavar="DIR", help="override the generated data directory")
    ap.add_argument("--run", metavar="FILE",
                    help="run FILE through clang-query against --sample and print JSON; "
                         "compiler flags go after `--`")
    ap.add_argument("--sample", metavar="SOURCE", help="with --run: the translation unit")
    ap.add_argument("--clang-query", metavar="PATH", help="with --run: clang-query binary")
    ap.add_argument("--target-scope", choices=("file", "directory", "workspace"),
                    default="file", help="with --run: target scope")
    ap.add_argument("--target-path", metavar="PATH", help="with --run: file/directory path")
    ap.add_argument("--root", action="append", default=[],
                    help="with --run: workspace root; may be repeated")
    ap.add_argument("--exclude", action="append", default=[],
                    help="with --run: exclude glob; may be repeated")
    ap.add_argument("--compile-commands", metavar="PATH",
                    help="with --run: compile_commands.json")
    ap.add_argument("--traversal", choices=("AsIs", "IgnoreUnlessSpelledInSource"),
                    help="with --run: clang-query traversal mode")
    ap.add_argument("--cache", action="store_true", help="with --run: enable result cache")
    ap.add_argument("--cache-location", metavar="DIR", help="with --run: cache directory")
    argv = list(sys.argv[1:] if argv is None else argv)
    flags: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, flags = argv[:cut], argv[cut + 1:]
    args = ap.parse_args(argv)

    if args.run:
        if not args.sample:
            ap.error("--run needs --sample SOURCE")
        text = sys.stdin.read() if args.run == "-" else Path(args.run).read_text()
        target = {"scope": args.target_scope,
                  "path": args.target_path or args.sample,
                  "roots": args.root}
        result = run_query(text, args.sample, flags, clang_query=args.clang_query,
                           target=target, exclusions=args.exclude,
                           compile_commands=args.compile_commands, traversal=args.traversal,
                           cache={"enabled": args.cache, "location": args.cache_location})
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0 if result["ok"] else 1

    for what in ("complete", "hover", "signature"):
        path = getattr(args, what)
        if path:
            if not args.at:
                ap.error(f"--{what} needs --at LINE:COL")
            return inspect(path, args.at, what, args.data)

    if args.check is not None:
        return check(args.check or ["-"], args.data, args.json)

    from .server import serve
    return serve(args.data)


if __name__ == "__main__":
    sys.exit(main())
