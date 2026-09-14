#!/usr/bin/env python3
"""Validate every clang-query example in the lab docs.

Conventions the docs follow (see AUTHORING.md):

* A doc declares its default sample with a line such as
      **Sample:** `manifests/decls.cpp` · flags: `-std=c++23`
  It may be re-declared later in the same doc; each declaration applies to the
  blocks that follow it.
* An example is a fenced block opened with ```clang-query. Every line that
  starts at column 0 is one command; a line that starts with whitespace
  continues the previous command (multi-line matchers). `#` lines are
  comments. A first line `# sample: <path> [flags…]` overrides the sample
  for that block only.
* The first non-blank line after the block must be
      **Expected:** N match(es) …
  when the block contains a `match` (or `m`) command. The number is compared
  with the count printed for the last `match` in the block.

Exit status is non-zero when any example fails.
"""
import argparse
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLVM = os.environ.get("LLVM") or subprocess.run(
    ["brew", "--prefix", "llvm"], capture_output=True, text=True).stdout.strip()
CLANG_QUERY = os.path.join(LLVM, "bin", "clang-query")

SAMPLE_RE = re.compile(r"^\*\*Sample:\*\*\s*`([^`]+)`(?:.*?flags:\s*`([^`]*)`)?")
EXPECT_RE = re.compile(r"^\*\*Expected:\*\*\s*(\d+)\s+match")
FENCE_RE = re.compile(r"^```(\S*)")
COUNT_RE = re.compile(r"^(\d+) match(?:es)?\.$", re.M)


def parse_doc(path):
    """Yield (line_no, sample, flags, commands, expected) for each example."""
    lines = open(path, encoding="utf-8").read().split("\n")
    sample, flags = None, ""
    i = 0
    while i < len(lines):
        m = SAMPLE_RE.match(lines[i])
        if m:
            sample, flags = m.group(1), m.group(2) or ""
            i += 1
            continue
        fm = FENCE_RE.match(lines[i])
        if fm:
            start = i
            i += 1
            block = []
            while i < len(lines) and not FENCE_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            i += 1  # closing fence
            if fm.group(1) != "clang-query":
                continue
            cmds, ovr_sample, ovr_flags = [], None, None
            for ln in block:
                if not cmds and ln.startswith("# sample:"):
                    parts = ln[len("# sample:"):].strip().split(None, 1)
                    ovr_sample = parts[0]
                    ovr_flags = parts[1] if len(parts) > 1 else ""
                    continue
                if not ln.strip() or ln.startswith("#"):
                    continue
                if ln[0].isspace():
                    if cmds:
                        cmds[-1] += "\n" + ln
                else:
                    cmds.append(ln)
            if not cmds:
                continue
            has_match = any(re.match(r"^(match|m)\b", c) for c in cmds)
            expected = None
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                em = EXPECT_RE.match(lines[j])
                if em:
                    expected = int(em.group(1))
            yield dict(line=start + 1, sample=ovr_sample or sample,
                       flags=ovr_flags if ovr_flags is not None else flags,
                       cmds=cmds, expected=expected, has_match=has_match)
            continue
        i += 1


def run_example(ex):
    if not ex["sample"]:
        return None, "no **Sample:** declared before this block"
    sample = os.path.join(ROOT, ex["sample"])
    if not os.path.exists(sample):
        return None, f"sample file missing: {ex['sample']}"
    argv = [CLANG_QUERY]
    for c in ex["cmds"]:
        argv += ["-c", c]
    argv += [sample, "--"] + shlex.split(ex["flags"])
    r = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = r.stdout + r.stderr
    problems = []
    for bad in ("Matcher not found", "Error parsing", "error:", "Invalid token"):
        if bad in out:
            problems.append(bad)
    counts = COUNT_RE.findall(out)
    count = int(counts[-1]) if counts else None
    return count, ("; ".join(problems) + ("\n" + out[:1500] if problems else "")) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docs", nargs="*", help="part docs to check (default: all)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--grep", help="only run examples whose command contains this text")
    args = ap.parse_args()
    docs = args.docs or sorted(
        os.path.join(ROOT, "docs", f) for f in os.listdir(os.path.join(ROOT, "docs"))
        if re.match(r"part_\d+_.*\.md$", f))
    total = failed = 0
    for doc in docs:
        rel = os.path.relpath(doc, ROOT)
        n_doc = f_doc = 0
        for ex in parse_doc(doc):
            if args.grep and not any(args.grep in c for c in ex["cmds"]):
                continue
            if not ex["has_match"]:
                continue
            total += 1
            n_doc += 1
            count, err = run_example(ex)
            ok = err is None and ex["expected"] is not None and count == ex["expected"]
            if not ok:
                failed += 1
                f_doc += 1
                print(f"FAIL {rel}:{ex['line']}  expected={ex['expected']} got={count}")
                print("     " + " | ".join(c.replace("\n", " ") for c in ex["cmds"]))
                if err:
                    print("     " + err.replace("\n", "\n     "))
            elif args.verbose:
                print(f"ok   {rel}:{ex['line']}  {count} match(es)")
        print(f"{rel}: {n_doc - f_doc}/{n_doc} examples pass")
    print(f"\nTOTAL: {total - failed}/{total} examples pass")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
