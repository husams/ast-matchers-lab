#!/usr/bin/env python3
"""Bundle docs/*.md, manifests/* and the matcher catalog into web/index.html.

The page is fully self-contained (no network, no build tooling): markdown is
rendered client-side by web/template.html. Re-run after editing any doc or
sample:

    python3 scripts/build_web.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MANIFESTS = ROOT / "manifests"
TEMPLATE = ROOT / "web" / "template.html"
OUT = ROOT / "web" / "index.html"

SAMPLE_EXTS = {".cpp", ".cppm", ".c", ".m", ".cu", ".h", ".query"}


def part_key(p: Path) -> int:
    return int(re.match(r"part_(\d+)_", p.name).group(1))


def load_docs():
    docs = [{"file": "README.md", "slug": "home", "md": (DOCS / "README.md").read_text()}]
    for p in sorted(DOCS.glob("part_*.md"), key=part_key):
        docs.append({"file": p.name, "slug": f"part-{part_key(p)}", "md": p.read_text()})
    docs.append({"file": "matcher_index.md", "slug": "index", "md": (DOCS / "matcher_index.md").read_text()})
    for d in docs:
        m = re.search(r"^# (.+)$", d["md"], re.M)
        d["title"] = m.group(1).strip() if m else d["file"]
    return docs


def load_samples():
    return {
        str(p.relative_to(ROOT)): p.read_text()
        for p in sorted(MANIFESTS.rglob("*"))
        if p.is_file() and p.suffix in SAMPLE_EXTS
    }


def load_catalog():
    cat = {}
    for row in json.loads((ROOT / "scripts" / "catalog.json").read_text()):
        doc = row["doc"].strip()
        if len(doc) > 700:
            doc = doc[:700].rsplit("\n", 1)[0] + "\n…"
        cat.setdefault(row["name"], []).append({
            "s": row["section"], "r": row["ret"], "p": row["params"], "d": doc,
            "ok": row.get("in_clang_query_22", True),
        })
    return cat


def load_progress():
    text = (DOCS / "PROGRESS.md").read_text()
    return re.findall(r"^- \[[xX]\] (\d+\.\d+)", text, re.M)


def load_steps():
    """Per-example step counts from scripts/explain_steps.py (optional)."""
    path = ROOT / "web" / "steps.json"
    if not path.exists():
        print("note: web/steps.json missing — run scripts/explain_steps.py for 'How it works' panels")
        return {}
    return json.loads(path.read_text())


def main():
    data = {
        "docs": load_docs(),
        "samples": load_samples(),
        "catalog": load_catalog(),
        "progress": load_progress(),
        "steps": load_steps(),
        "hier": json.loads((ROOT / "scripts" / "ast_hierarchy.json").read_text()),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__LAB_DATA__*/null", payload)
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KiB, "
          f"{len(data['docs'])} docs, {len(data['samples'])} samples)")


if __name__ == "__main__":
    main()
