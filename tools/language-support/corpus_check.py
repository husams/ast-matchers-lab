#!/usr/bin/env python3
"""Run the analyzer over every verified example in the lab and report surprises.

Every ```clang-query block in docs/ and every manifests/**/*.query file is known
to work with clang-query 22 (scripts/check.sh proves it).  So any *error* the
language server reports on them is a false positive in the server, and that is
what this script fails on.  Warnings are listed but tolerated.
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent.parent
sys.path.insert(0, str(HERE / "astmatcher-lsp"))

from astmatcher_lsp.analyze import ERROR, analyze          # noqa: E402
from astmatcher_lsp.catalog import load                    # noqa: E402
from astmatcher_lsp.lexer import LineIndex                 # noqa: E402
from astmatcher_lsp.parser import parse                    # noqa: E402

FENCE = re.compile(r"^```(\S*)")


def blocks() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for doc in sorted((LAB / "docs").glob("*.md")):
        lines = doc.read_text(encoding="utf-8").split("\n")
        i = 0
        while i < len(lines):
            fence = FENCE.match(lines[i])
            if not fence:
                i += 1
                continue
            start, i, body = i, i + 1, []
            while i < len(lines) and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            if fence.group(1) == "clang-query":
                out.append((f"docs/{doc.name}:{start + 1}", "\n".join(body)))
    for query in sorted((LAB / "manifests").rglob("*.query")):
        out.append((str(query.relative_to(LAB)), query.read_text(encoding="utf-8")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true", help="list warnings too")
    args = ap.parse_args()

    catalog = load()
    corpus = blocks()
    errors, warnings = [], collections.Counter()
    for where, source in corpus:
        index = LineIndex(source)
        for diag in analyze(catalog, parse(source))[0]:
            line, char = index.position(diag.start)
            if diag.severity == ERROR:
                errors.append((where, line + 1, char + 1, diag))
            else:
                warnings[diag.code] += 1
                if args.verbose:
                    print(f"{where} (+{line + 1}:{char + 1}): warning: {diag.message}")

    print(f"{len(corpus)} verified examples, {len(errors)} false positives, "
          f"{sum(warnings.values())} warnings {dict(warnings)}")
    for where, line, char, diag in errors:
        print(f"  {where} (+{line}:{char}): {diag.message} [{diag.code}]")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
