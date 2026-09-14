# AST Matchers Lab — Agent Guide

This is a hands-on lab teaching the **Clang AST Matcher DSL** purely through
`clang-query`. It is *not* about the C++ MatchFinder API (that is the sibling
`libtooling-lab`, Part 33) and not about libclang (`libclang-lab`). Every one
of the 726 rows of the official AST Matcher Reference has its own entry with
a verified `clang-query` example.

The lab runs **entirely locally on macOS** against Homebrew LLVM 22. No VM,
no build step — samples have no `#include`, so no SDK plumbing is needed.

## Response Style (strict)

Default to a **single short sentence** per response. Only expand into
detail, lists, or code when the user explicitly asks — or when presenting a
lab section, which follows the flow below.

## How to Present This Lab

Present the lab **interactively, section by section**. Do NOT dump entire
parts at once (Parts 3, 9 and 10 have ~100 entries each).

### Flow
1. Check `docs/PROGRESS.md` to see where the user left off.
2. Present ONE section at a time (a section is a group of related matcher
   entries, e.g. "9.3 — Control flow"). Within a section, walk the entries
   in order: explain the matcher, show the clang-query command, let the
   user run it, then discuss the result. Never run the examples for the
   user unless asked — the learning is in typing the matcher and reading
   the output.
3. Explain concepts before commands. Each part opens with "What You'll
   Learn" and "The Big Picture" — present those first, always.
4. **Quizzes:** each part ends with a quiz (`**Quiz.**` followed by
   collapsed Obsidian callouts `> [!hint]- Hint` / `> [!success]- Answer`).
   Ask the question and let the user answer before revealing anything.
   Offer the hint if they're stuck; only then the answer. Never skip a
   quiz. Never use raw HTML (`<details>` etc.) in lab docs — Obsidian
   callouts only.
5. When the user's result differs from `**Expected:**`, first check the
   flags and sample file named in the doc's `**Sample:**` line (or the
   block's `# sample:` override), then run `python3 scripts/check.py
   docs/part_N_*.md --grep <matcher>` to see whether the doc or the user's
   invocation is off.
6. After completing a part, update `docs/PROGRESS.md` (mark sections `[x]`)
   and ask whether to continue.

### Editing docs or samples
Any change to a sample file can shift line numbers quoted in `**Expected:**`
lines and change counts. After editing, run `scripts/check.sh` (all
examples + coverage) and fix every failure before finishing. Read
`AUTHORING.md` for the exact entry/example conventions the scripts enforce.

## Lab Structure

```
ast-matchers-lab/
├── CLAUDE.md                 ← this file
├── AUTHORING.md              ← doc conventions enforced by the scripts
├── README.md                 ← root pointer to docs/
├── docs/
│   ├── README.md             ← TOC + environment
│   ├── PROGRESS.md           ← section-by-section checklist
│   ├── matcher_index.md      ← every matcher name → part/section
│   ├── part_1_clang_query_and_the_dsl.md
│   ├── part_2 … part_4       ← node matchers (decls, stmts/exprs, types)
│   ├── part_5 … part_7       ← narrowing matchers
│   ├── part_8 … part_10      ← traversal matchers
│   ├── part_11_objc_openmp_cuda_blocks.md
│   └── part_12_capstone.md   ← real checks as -f scripts + appendix
├── manifests/                ← sample sources, one (or a few) per part
│   ├── intro.cpp, decls.cpp, stmts.cpp, types.cpp,
│   ├── narrow_*.cpp, trav_*.cpp, include/ (fake system headers)
│   ├── objc.m, openmp.cpp, cuda.cu, blocks.cpp
│   ├── capstone.cpp, queries/*.query
│   └── *.query               ← clang-query -f script files
└── scripts/
    ├── catalog.json          ← all 726 reference rows + part assignment
    ├── slice.py              ← print one part's rows
    ├── check.py              ← run every example, compare counts
    ├── coverage.py           ← every row present with an example
    └── check.sh              ← both of the above
```

## Environment

| Item | Value |
|------|-------|
| Toolchain | Homebrew LLVM 22.1.8 — `export LLVM=$(brew --prefix llvm)` |
| clang-query | `$LLVM/bin/clang-query` |
| Default flags | `-std=c++23` (C++ samples); per-part flags are on each doc's `**Sample:**` line |
| ObjC / OpenMP / CUDA / Blocks | `objc.m` (`-fobjc-exceptions`, no ARC), `openmp.cpp` (`-std=c++23 -fopenmp`), `cuda.cu` (`-x cuda --cuda-host-only -nocudainc -nocudalib`), `blocks.cpp` (`-std=c++23 -fblocks`) — see Part 11 |

### Common commands
```bash
export LLVM=$(brew --prefix llvm)
cd ast-matchers-lab

# Interactive session for a part
$LLVM/bin/clang-query manifests/decls.cpp -- -std=c++23

# One-shot command
$LLVM/bin/clang-query -c 'match functionDecl(hasName("main"))' manifests/intro.cpp -- -std=c++23

# Run a query script
$LLVM/bin/clang-query -f manifests/queries/use-nullptr.query manifests/capstone.cpp -- -std=c++23

# Validate the whole lab (every example + coverage)
scripts/check.sh
python3 scripts/check.py docs/part_9_traversal_stmts.md -v --grep hasCondition
```

### Known limits
- 14 reference names are not registered in this clang-query build
  (`traverse`, `findAll`, `equalsNode`, `cxxNamedCastExpr`, `functionTypeLoc`,
  `isInheritingConstructor`, `requiresExpr`, `requiresExprBodyDecl`,
  `templateArgumentLocCountIs`, and five `omp*` names). Their entries say
  `**Not in clang-query 22**` and give the nearest alternative; Part 12 has
  the full table.
- `traverse()` is C++-API-only; in clang-query use
  `set traversal IgnoreUnlessSpelledInSource`.
- After a brew LLVM major bump, re-run `scripts/check.sh` — matcher
  registration and match counts can drift.
