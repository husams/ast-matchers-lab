#!/usr/bin/env python3
"""Generate docs/matcher_index.md and docs/PROGRESS.md from the part docs.

* matcher_index.md — every reference matcher name → part, section, return
  types, and whether it is registered in clang-query 22.
* PROGRESS.md — one checkbox per `## N.M — Title` section of every part.
  Existing `[x]` marks in PROGRESS.md are preserved for sections whose
  title is unchanged.
"""
import glob
import json
import os
import re
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
TITLE_RE = re.compile(r"^# Part (\d+) — (.*)$")
SEC_RE = re.compile(r"^## (\d+)\.(\d+) — (.*)$")
HEAD_RE = re.compile(r"^###\s+`(\w+)\(.*`.*?—\s*(.*)$")
RET_RE = re.compile(r"Matcher<([^>]+)>")


def part_docs():
    docs = {}
    for p in glob.glob(os.path.join(DOCS, "part_*_*.md")):
        n = int(re.search(r"part_(\d+)_", os.path.basename(p)).group(1))
        docs[n] = p
    return OrderedDict(sorted(docs.items()))


def scan(path):
    title, sections, entries = None, [], []
    cur_sec = None
    for ln in open(path, encoding="utf-8"):
        ln = ln.rstrip("\n")
        m = TITLE_RE.match(ln)
        if m:
            title = m.group(2)
            continue
        m = SEC_RE.match(ln)
        if m:
            cur_sec = (f"{m.group(1)}.{m.group(2)}", m.group(3))
            sections.append(cur_sec)
            continue
        m = HEAD_RE.match(ln)
        if m and cur_sec:
            entries.append((m.group(1), RET_RE.findall(m.group(2)), cur_sec[0]))
    return title, sections, entries


def main():
    cat = json.load(open(os.path.join(ROOT, "scripts", "catalog.json")))
    avail = {e["name"]: e["in_clang_query_22"] for e in cat}
    section_of = {e["name"]: e["section"] for e in cat}
    docs = part_docs()
    parts = {n: scan(p) for n, p in docs.items()}

    # ---- matcher_index.md
    index = {}  # name -> list of (part, section, rets)
    for n, (title, sections, entries) in parts.items():
        for name, rets, sec in entries:
            index.setdefault(name, []).append((n, sec, rets, os.path.basename(docs[n])))
    out = ["# Matcher Index", "",
           "Every name in the AST Matcher Reference, and the lab section that covers it.",
           "Names are grouped as the reference groups them. `✗` marks names not",
           "registered in clang-query 22 (their entries explain the alternative).", ""]
    for sec_name, label in (("node", "Node matchers"), ("narrowing", "Narrowing matchers"),
                            ("traversal", "Traversal matchers")):
        names = sorted({e["name"] for e in cat if e["section"] == sec_name})
        out += [f"## {label} ({len(names)})", "", "| Matcher | Returns | Where | |", "|---|---|---|---|"]
        for name in names:
            hits = index.get(name, [])
            rets = sorted({r for h in hits for r in h[2]})
            where = ", ".join(f"[§{h[1]}]({h[3]})" for h in hits) or "**MISSING**"
            flag = "" if avail.get(name, True) else "✗"
            out.append(f"| `{name}` | {', '.join(f'`{r}`' for r in rets)} | {where} | {flag} |")
        out.append("")
    open(os.path.join(DOCS, "matcher_index.md"), "w", encoding="utf-8").write("\n".join(out))

    # ---- PROGRESS.md
    prog_path = os.path.join(DOCS, "PROGRESS.md")
    done = set()
    if os.path.exists(prog_path):
        for ln in open(prog_path, encoding="utf-8"):
            m = re.match(r"- \[x\] (\d+\.\d+) — (.*)", ln)
            if m:
                done.add((m.group(1), m.group(2).strip()))
    out = ["# Lab Progress", "", "Mark each section `[x]` as you complete it.", ""]
    for n, (title, sections, entries) in parts.items():
        out.append(f"## Part {n} — {title}")
        for num, name in sections:
            box = "x" if (num, name) in done else " "
            out.append(f"- [{box}] {num} — {name}")
        out.append("")
    open(prog_path, "w", encoding="utf-8").write("\n".join(out))
    missing = [n for n in avail if n not in index]
    print(f"parts: {len(parts)}  sections: {sum(len(s) for _, s, _ in parts.values())}  "
          f"indexed names: {len(index)}/{len(avail)}  missing: {missing}")


if __name__ == "__main__":
    main()
