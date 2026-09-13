#!/usr/bin/env python3
"""Print the reference rows assigned to one lab part, grouped by name.

    python3 scripts/slice.py 5          # human-readable
    python3 scripts/slice.py 5 --json   # raw rows
"""
import json
import os
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cat = json.load(open(os.path.join(ROOT, "scripts", "catalog.json")))
part = int(sys.argv[1])
rows = [e for e in cat if e["part"] == part]
if "--json" in sys.argv:
    json.dump(rows, sys.stdout, indent=1)
    sys.exit()
groups = OrderedDict()
for e in rows:
    groups.setdefault(e["name"], []).append(e)
print(f"# Part {part}: {len(rows)} rows, {len(groups)} names\n")
for name, es in groups.items():
    rets = ", ".join(e["ret"] for e in es)
    flag = "" if es[0]["in_clang_query_22"] else "   [NOT IN clang-query 22]"
    print(f"## {name}({es[0]['params']}) — {rets}  [{es[0]['section']}]{flag}")
    seen = set()
    for e in es:
        if e["doc"] in seen:
            continue
        seen.add(e["doc"])
        print(e["doc"].strip())
        print()
