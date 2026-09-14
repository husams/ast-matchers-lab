#!/usr/bin/env python3
"""Check that every row of the AST Matcher Reference has an entry in the lab.

`scripts/catalog.json` holds all 726 rows of
https://clang.llvm.org/docs/LibASTMatchersReference.html (section, return
type, name, parameters, doc) plus the lab part each row is assigned to.

An entry is a heading of the form

    ### `name(params)` — Matcher<Ret>[, Matcher<Ret2>…]

Every row must appear, with its return type, in the doc of its assigned part
(`docs/part_<N>_*.md`), and every entry heading must contain at least one
example block (a fenced block opened with ```clang-query) before the next
heading — or, for names not registered in clang-query 22, a line starting
with `**Not in clang-query 22**`.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAD_RE = re.compile(r"^###\s+`(\w+)\(.*`.*?—\s*(.*)$")
RET_RE = re.compile(r"Matcher<([^>]+)>")


def part_doc(n):
    hits = glob.glob(os.path.join(ROOT, "docs", f"part_{n}_*.md"))
    return hits[0] if hits else None


def entries(path):
    """Return {(name, ret): has_example} for a doc."""
    text = open(path, encoding="utf-8").read().split("\n")
    result, cur = {}, None
    body_has_example = False
    def close():
        if cur:
            for r in cur[1]:
                result[(cur[0], r)] = body_has_example
    for ln in text:
        m = HEAD_RE.match(ln)
        if m:
            close()
            rets = RET_RE.findall(m.group(2))
            cur = (m.group(1), rets)
            body_has_example = False
            continue
        if cur and (ln.startswith("```clang-query") or ln.startswith("**Not in clang-query 22**")):
            body_has_example = True
    close()
    return result


def main():
    cat = json.load(open(os.path.join(ROOT, "scripts", "catalog.json")))
    parts = sorted({e["part"] for e in cat})
    docs = {p: part_doc(p) for p in parts}
    ents = {p: entries(d) if d else {} for p, d in docs.items()}
    missing, no_example = [], []
    for e in cat:
        ret = e["ret"].replace("Matcher<", "").rstrip(">")
        key = (e["name"], ret)
        have = ents[e["part"]]
        if key not in have:
            missing.append((e["part"], e["name"], e["ret"]))
        elif not have[key]:
            no_example.append((e["part"], e["name"], e["ret"]))
    only = sys.argv[1:]  # optional list of part numbers to report
    for p in parts:
        if only and str(p) not in only:
            continue
        rows = [e for e in cat if e["part"] == p]
        miss = [m for m in missing if m[0] == p]
        noex = [m for m in no_example if m[0] == p]
        print(f"part {p:2d}: {len(rows) - len(miss):3d}/{len(rows):3d} rows present, "
              f"{len(noex)} without example  ({os.path.basename(docs[p] or '') or 'NO DOC'})")
        for m in miss:
            print(f"   MISSING  {m[1]}  {m[2]}")
        for m in noex:
            print(f"   NO EXAMPLE  {m[1]}  {m[2]}")
    print(f"\nTOTAL rows: {len(cat)}  missing: {len(missing)}  without example: {len(no_example)}")
    sys.exit(1 if (missing or no_example) else 0)


if __name__ == "__main__":
    main()
