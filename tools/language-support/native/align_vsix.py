#!/usr/bin/env python3
"""Replace generated matcher assets in a VSIX with the host Clang catalog."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile


GENERATED = {
    "extension/snippets/astmatcher.json": "vscode/snippets/astmatcher.json",
    "extension/syntaxes/astmatcher.tmLanguage.json":
        "vscode/syntaxes/astmatcher.tmLanguage.json",
}


def align(source: Path, generated: Path, output: Path) -> None:
    if source.resolve() == output.resolve():
        raise ValueError("output VSIX must differ from the input")
    replacements = {name: (generated / path).read_bytes()
                    for name, path in GENERATED.items()}
    seen: set[str] = set()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(source) as original, ZipFile(output, "w") as updated:
        for info in original.infolist():
            content = replacements.get(info.filename)
            if content is not None:
                seen.add(info.filename)
            else:
                content = original.read(info.filename)
            updated.writestr(info, content)
    missing = set(replacements) - seen
    if missing:
        output.unlink(missing_ok=True)
        raise ValueError("VSIX is missing generated assets: " + ", ".join(sorted(missing)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("generated", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    align(args.source, args.generated, args.output)


if __name__ == "__main__":
    main()
