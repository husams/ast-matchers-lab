# Authoring Guide — AST Matchers Lab

Rules every part doc in this lab follows. `scripts/check.py` and
`scripts/coverage.py` enforce them mechanically; run both before calling a
part done.

## Scope

* The lab teaches the **matcher DSL as used in `clang-query`** — never the
  C++ `MatchFinder` API. No C++ tool code, no CMake, no callbacks.
* **Every row** of the reference (`scripts/catalog.json`, 726 rows, 516
  unique names) gets its own entry in the part it is assigned to
  (`python3 scripts/slice.py <part>` prints a part's rows). Overloads of one
  name share a single entry that lists every return type.
* Source: https://clang.llvm.org/docs/LibASTMatchersReference.html. The
  catalog carries each row's original doc text — paraphrase it, keep the
  meaning, and reuse its example code in the sample when it is good.

## Toolchain

Homebrew LLVM 22.1.8 on macOS:

```bash
export LLVM=$(brew --prefix llvm)
$LLVM/bin/clang-query manifests/decls.cpp -- -std=c++23
```

Sample files use **no `#include`** (no SDK is needed then). Write any needed
`std::` stubs by hand (e.g. a minimal `std::coroutine_traits`,
`std::initializer_list`, `std::strong_ordering`). Samples must parse with
**zero diagnostics** at the flags declared in the doc — `check.py` fails an
example if `error:` appears in the output, and warnings are noise the
learner should not see.

## Doc layout

```markdown
# Part N — <Title>

[← Part N-1 — <Title>](part_N-1_<slug>.md) | [Part N+1 — <Title> →](part_N+1_<slug>.md)

**Sample:** `manifests/<file>` · flags: `-std=c++23`

## What You'll Learn
- …

## The Big Picture
<concepts first: what this family of matchers is, how it reads, a compact
 ASCII diagram if it helps. Never open with commands.>

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/<file> -- -std=c++23
```

---

## N.1 — <Group title>

<one paragraph introducing the group>

### `hasName(StringRef Name)` — Matcher<NamedDecl>

<1–3 sentences: what it matches, in plain English, with the sample in mind.>

```clang-query
match namedDecl(hasName("Circle"))
```

**Expected:** 1 match — `Circle` at `decls.cpp:12`.

### `isImplicit()` — Matcher<Attr>, Matcher<Decl>

…

## N.K — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| … | … |

**Quiz.** <one question that needs 2–3 matchers combined>

> [!hint]- Hint
> …

> [!success]- Answer
> `…` — N matches.

---

[← Part N-1 — <Title>](part_N-1_<slug>.md) | [Part N+1 — <Title> →](part_N+1_<slug>.md)
```

### Entry heading — exact form

```
### `<name>(<params>)` — Matcher<Ret>[, Matcher<Ret2>, …]
```

* `<params>` as in the reference, lightly simplified is fine
  (`hasParameter(unsigned N, Matcher<ParmVarDecl>)`).
* `Matcher<*>` for polymorphic rows; `mapAnyOf` uses `Matcher<*>` too.
* One heading per name; list **all** return types of that name that are
  assigned to this part (`slice.py` shows them). `coverage.py` matches
  `(name, ret)` pairs against these headings, so a missing return type is a
  failure.

### Example block — exact form

* Fenced block opened with ```` ```clang-query ```` — never ```` ```text ````,
  which is for diagrams and output. No `clang-query> ` prompt: the block
  must paste straight into the REPL.
* One `match` per block. `set …` / `let …` lines may precede it in the same
  block (state does **not** carry across blocks in validation).
* Every line at column 0 is one command. Multi-line matchers continue on
  the next line **indented** (two or more spaces); `#` lines are comments.
* Immediately after the block:
  `**Expected:** N match(es) — <what/where, e.g. names + line numbers>.`
  `check.py` compares N with clang-query's count. N is normally ≥ 1; a
  deliberately negative example (`0 matches`) is allowed as an *extra*
  block, never as the entry's only one.
* To use a different sample for one block, make its first line
  `# sample: manifests/other.cpp -std=c++23 -fblocks` (clang-query treats
  `#` lines as comments, so the learner can paste it as-is).
* Prefer `.bind("x")` only when it teaches something; the default `root`
  binding is fine.

### Entries for names not registered in clang-query 22

Fourteen reference names are absent from this clang-query build (the
catalog marks them `"in_clang_query_22": false`). Their entries keep the
heading, explain what the matcher does, and replace the example block with a
line starting exactly with:

```
**Not in clang-query 22** — <why: trunk-only / C++-API-only> … then show the nearest working alternative as a normal example block if one exists.
```

## Style

* Explain before commanding; one concept per entry; plain English.
* Break long commands across lines; keep ASCII diagrams compact.
* Obsidian callouts for quizzes (`> [!hint]-`, `> [!success]-`), never raw
  HTML.
* Line references (`decls.cpp:12`) must be right — re-check after editing
  a sample.
* Never use `cat <<EOF` in docs; sample files are written to `manifests/`.

## Validate

```bash
python3 scripts/check.py docs/part_2_*.md -v     # every example runs & counts match
python3 scripts/coverage.py 2                    # every assigned row present with example
```
