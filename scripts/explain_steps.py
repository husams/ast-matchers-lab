#!/usr/bin/env python3
"""Precompute step-by-step match counts for every clang-query example.

For each example's final `match` command the matcher is parsed into a tree and
rebuilt one argument at a time (outermost node matcher first, then each
narrowing/traversal argument in source order).  Every intermediate matcher is
run through clang-query against the example's sample, recording the count and
the location of each match.  The web UI (web/index.html) shows this as the
"How it works" panel under each **Expected:** line, so the reader can see what
every component of the matcher contributed to the final result.

Output: web/steps.json (embedded by scripts/build_web.py).

    python3 scripts/explain_steps.py          # all parts
    python3 scripts/explain_steps.py -j 4     # limit parallelism
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check import CLANG_QUERY, COUNT_RE, ROOT, parse_doc  # noqa: E402

CATALOG = {}
for row in json.load(open(os.path.join(ROOT, "scripts", "catalog.json"))):
    CATALOG.setdefault(row["name"], row["section"])
LOGIC = {"allOf", "anyOf", "eachOf", "unless", "optionally", "mapAnyOf", "not"}
MAX_STEPS = 7
MAX_LOCS = 40  # locations kept per step (the count is always exact)
BIND_RE = re.compile(r'^(.*?):(\d+):(\d+): note: "([^"]+)" binds here', re.M)


# ---------- tiny matcher-expression parser ----------
class ParseError(Exception):
    pass


def parse(s):
    node, i = _expr(s, 0)
    if s[i:].strip():
        raise ParseError(f"trailing text: {s[i:]!r}")
    return node


def _ws(s, i):
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def _expr(s, i):
    i = _ws(s, i)
    if i >= len(s):
        raise ParseError("unexpected end")
    if s[i] == '"':
        j = i + 1
        while j < len(s) and s[j] != '"':
            j += 2 if s[j] == "\\" else 1
        return {"lit": s[i:j + 1]}, j + 1
    m = re.compile(r"-?\d+(?:\.\d+)?").match(s, i)
    if m:
        return {"lit": m.group(0)}, m.end()
    m = re.compile(r"[A-Za-z_]\w*").match(s, i)
    if not m:
        raise ParseError(f"unexpected {s[i]!r}")
    node = {"name": m.group(0)}
    i = _ws(s, m.end())
    if i < len(s) and s[i] == "(":
        node["args"] = []
        i = _ws(s, i + 1)
        if s[i] == ")":
            i += 1
        else:
            while True:
                a, i = _expr(s, i)
                node["args"].append(a)
                i = _ws(s, i)
                if s[i] == ",":
                    i += 1
                    continue
                if s[i] == ")":
                    i += 1
                    break
                raise ParseError(f"expected , or ) at {s[i:i + 10]!r}")
    else:
        node["var"] = True
    i = _ws(s, i)
    m = re.compile(r'\.bind\(\s*("(?:[^"\\]|\\.)*")\s*\)').match(s, i)
    if m:
        node["bind"] = m.group(1)
        i = m.end()
    return node, i


def ser(n, revealed=None):
    if "lit" in n:
        return n["lit"]
    if n.get("var"):
        out = n["name"]
    else:
        args = [ser(a, revealed) for a in n["args"]
                if "lit" in a or revealed is None or id(a) in revealed]
        out = f"{n['name']}({', '.join(args)})"
    return out + (f'.bind({n["bind"]})' if "bind" in n else "")


def matcher_args(n):
    return [a for a in n.get("args", []) if "lit" not in a]


def needs_inner(n):
    return (CATALOG.get(n["name"]) == "traversal" or n["name"] in LOGIC) and matcher_args(n)


def steps_for(root):
    """Return [(expr, added_expr_or_None)] revealing one argument at a time."""
    order = []

    def pre(n):
        for a in matcher_args(n):
            order.append(a)
            pre(a)
    pre(root)
    revealed = set()

    def reveal(n):
        revealed.add(id(n))
        if needs_inner(n):
            reveal(matcher_args(n)[0])

    if needs_inner(root):
        reveal(matcher_args(root)[0])
    steps = [(ser(root, revealed), None)]
    for a in order:
        if id(a) in revealed:
            continue
        reveal(a)
        steps.append((ser(root, revealed), ser(a, revealed)))
    full = ser(root)
    if steps[-1][0] != full:
        steps.append((full, None))
    if len(steps) > MAX_STEPS:  # keep the first, the last and an even spread
        idx = sorted({round(k * (len(steps) - 1) / (MAX_STEPS - 1)) for k in range(MAX_STEPS)})
        steps = [steps[k] for k in idx]
    return steps


# ---------- running ----------
def run(prefix, expr, sample, flags):
    argv = [CLANG_QUERY]
    for c in prefix + ["set output diag", "match " + expr]:
        argv += ["-c", c]
    argv += [os.path.join(ROOT, sample), "--"] + shlex.split(flags)
    r = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = r.stdout + r.stderr
    counts = COUNT_RE.findall(out)
    if not counts or "Error" in out or "Matcher not found" in out or "Not a valid" in out:
        return None
    locs = []
    for block in re.split(r"^Match #\d+:\s*$", out, flags=re.M)[1:]:
        b = BIND_RE.search(block)
        if b:
            f = os.path.relpath(b.group(1), ROOT)
            loc = f"{b.group(2)}:{b.group(3)}"
            locs.append(loc if f == sample else f"{f}:{loc}")
    return {"count": int(counts[-1]), "locs": locs[:MAX_LOCS]}


def explain(ex):
    matches = [k for k, c in enumerate(ex["cmds"]) if re.match(r"^(match|m)\s", c)]
    if not matches or not ex["sample"]:
        return None
    last = matches[-1]
    prefix = [c for k, c in enumerate(ex["cmds"][:last])
              if not re.match(r"^(match|m)\s", c) and not re.match(r"^set\s+output\b", c)]
    expr = re.sub(r"^(match|m)\s+", "", ex["cmds"][last]).strip()
    try:
        tree = parse(expr)
    except (ParseError, IndexError):
        return None
    steps = [] if tree.get("var") else steps_for(tree)
    if not steps:
        steps = [(expr, None)]
    out = []
    for e, added in steps:
        res = run(prefix, e, ex["sample"], ex["flags"])
        if res is None:
            continue
        out.append({"expr": e, "added": added, **res})
    return {"tree": tree, "steps": out} if out else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=os.cpu_count() or 4)
    args = ap.parse_args()
    docs = sorted(f for f in os.listdir(os.path.join(ROOT, "docs")) if re.match(r"part_\d+_.*\.md$", f))
    jobs = []
    for d in docs:
        path = os.path.join(ROOT, "docs", d)
        lines = open(path, encoding="utf-8").read().split("\n")
        for ex in parse_doc(path):
            if not ex["has_match"]:
                continue
            start = ex["line"]  # 1-based line of the opening fence
            end = start
            while not lines[end].startswith("```"):
                end += 1
            key = d + "\n" + "\n".join(lines[start:end])
            jobs.append((key, ex))
    result = {}
    with ThreadPoolExecutor(args.j) as pool:
        for n, (key, res) in enumerate(pool.map(lambda kj: (kj[0], explain(kj[1])), jobs), 1):
            if res:
                result[key] = res
            if n % 100 == 0:
                print(f"  {n}/{len(jobs)}", file=sys.stderr)
    out = os.path.join(ROOT, "web", "steps.json")
    with open(out, "w") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote web/steps.json ({len(result)}/{len(jobs)} examples explained)")


if __name__ == "__main__":
    main()
