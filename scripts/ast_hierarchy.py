#!/usr/bin/env python3
"""Extract Clang's AST class hierarchies from the installed LLVM headers.

Reads DeclNodes.inc, StmtNodes.inc and TypeNodes.inc (TypeLocs mirror the
Type hierarchy, see TypeLocNodes.def) and writes scripts/ast_hierarchy.json,
which scripts/build_web.py embeds for the web UI's "AST explorer" appendix.
Re-run after a brew LLVM major bump:

    python3 scripts/ast_hierarchy.py
"""
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLVM = os.environ.get("LLVM") or subprocess.run(
    ["brew", "--prefix", "llvm"], capture_output=True, text=True).stdout.strip()
AST = os.path.join(LLVM, "include", "clang", "AST")
ENTRY = re.compile(r"^(?:(ABSTRACT_\w+)\()?[A-Z_]+\((\w+), (\w+)\)\)?\s*$")


def entries(name):
    for line in open(os.path.join(AST, name)):
        m = ENTRY.match(line.strip())
        if m:
            yield m.group(2), m.group(3), bool(m.group(1))


def main():
    groups = {}

    decl = {"root": "Decl", "parent": {}, "abstract": []}
    for cls, base, abstract in entries("DeclNodes.inc"):
        cls += "Decl"
        decl["parent"][cls] = base
        if abstract:
            decl["abstract"].append(cls)
    groups["Decl"] = decl

    stmt = {"root": "Stmt", "parent": {}, "abstract": []}
    for cls, base, abstract in entries("StmtNodes.inc"):
        stmt["parent"][cls] = base
        if abstract:
            stmt["abstract"].append(cls)
    groups["Stmt"] = stmt

    typ = {"root": "Type", "parent": {}, "abstract": []}
    loc = {"root": "TypeLoc", "parent": {"QualifiedTypeLoc": "TypeLoc"}, "abstract": []}
    for cls, base, abstract in entries("TypeNodes.inc"):
        typ["parent"][cls + "Type"] = base
        loc["parent"][cls + "TypeLoc"] = base + "Loc"
        if abstract:
            typ["abstract"].append(cls + "Type")
            loc["abstract"].append(cls + "TypeLoc")
    groups["Type"] = typ
    groups["TypeLoc"] = loc

    out = os.path.join(ROOT, "scripts", "ast_hierarchy.json")
    with open(out, "w") as f:
        json.dump({"llvm": os.path.basename(os.path.realpath(LLVM)), "groups": groups}, f, indent=1)
    print(f"wrote scripts/ast_hierarchy.json — " +
          ", ".join(f"{k}: {len(v['parent']) + 1}" for k, v in groups.items()))


if __name__ == "__main__":
    main()
