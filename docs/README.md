# AST Matchers Lab — Hands-on Clang AST Matcher DSL with clang-query

A hands-on lab for learning the **Clang AST Matcher DSL** — the declarative
pattern language behind clang-tidy — entirely inside `clang-query`. No C++
tool code, no CMake: you type matchers, Clang finds the nodes.

The lab walks **every entry** of the official
[AST Matcher Reference](https://clang.llvm.org/docs/LibASTMatchersReference.html)
— all 726 rows (516 unique names: 226 node matchers, 239 narrowing matchers,
261 traversal matchers) — each with a plain-English explanation, a
`clang-query` example against a small sample file, and the exact expected
result. Every example is machine-checked (`scripts/check.sh`).

> Sibling labs: `libtooling-lab` covers the C++ `MatchFinder` API that *runs*
> these matchers inside a tool (its Part 33); `libclang-lab` covers the Python
> bindings. This lab is only about the language of the matchers themselves.

## Environment — fully local

| Component | Details |
|-----------|---------|
| OS | macOS (Apple Silicon or Intel) |
| Toolchain | `brew install llvm` — LLVM 22.1.8 at `$(brew --prefix llvm)` |
| Tool | `$(brew --prefix llvm)/bin/clang-query` |
| Samples | `manifests/*.cpp`, `*.m`, `*.cu` — no `#include`, so no SDK setup |
| Validation | `python3 scripts/check.py` + `python3 scripts/coverage.py` |

```bash
export LLVM=$(brew --prefix llvm)
cd ast-matchers-lab
$LLVM/bin/clang-query manifests/intro.cpp -- -std=c++23
```

## Lab Parts

**Foundations**

| # | Part | Topics |
|---|------|--------|
| 1 | [clang-query & the DSL Grammar](part_1_clang_query_and_the_dsl.md) | starting clang-query · `match`/`set`/`let`/`-f` · the three matcher categories · `.bind` · traversal modes · reading a reference entry |

**Node matchers — 226 rows** (the only matchers that can be outermost)

| # | Part | Topics |
|---|------|--------|
| 2 | [Node Matchers I — Declarations](part_2_node_matchers_decls.md) | every `*Decl` node matcher · attr · base specifiers · ctor initializers · lambda captures · nested-name specifiers · template arguments/names |
| 3 | [Node Matchers II — Statements & Expressions](part_3_node_matchers_stmts.md) | every `Stmt`/`Expr` node matcher: control flow · literals · operators · calls · casts · C++ objects · implicit nodes · dependent nodes · coroutines · GNU/C extensions |
| 4 | [Node Matchers III — Types & TypeLocs](part_4_node_matchers_types.md) | `Type` vs `QualType` vs `TypeLoc` · every `*Type` and `*TypeLoc` node matcher |

**Narrowing matchers — 239 rows** (predicates on the current node)

| # | Part | Topics |
|---|------|--------|
| 5 | [Narrowing I — Logic & Declarations](part_5_narrowing_logic_decls.md) | allOf/anyOf/unless/anything/mapAnyOf · names · access · functions · methods · constructors · records · variables |
| 6 | [Narrowing II — Statements & Expressions](part_6_narrowing_stmts.md) | operator names · literal values · argument counts · cast kinds · member access · fold expressions · statement counts |
| 7 | [Narrowing III — Types, Templates & Source Locations](part_7_narrowing_types_templates_locations.md) | QualType predicates · template instantiation & dependence · `isExpansionIn*` · `isExpandedFromMacro` · `equalsBoundNode` |

**Traversal matchers — 261 rows** (jump to a related node)

| # | Part | Topics |
|---|------|--------|
| 8 | [Traversal I — Tree Navigation & Declarations](part_8_traversal_tree_decls.md) | has/hasDescendant/forEachDescendant · hasParent/hasAncestor · eachOf/optionally · parameters · bases · ctor initializers · initializers · decl contexts |
| 9 | [Traversal II — Statements & Expressions](part_9_traversal_stmts.md) | callee/arguments · operands · conditions & bodies · `ignoring*` · casts · new/init lists · lambdas · sizeof |
| 10 | [Traversal III — Types, TypeLocs & Templates](part_10_traversal_types_templates.md) | `hasType` · `hasDeclaration` · pointee/pointsTo/references · TypeLocs · nested-name specifiers · template arguments |

**Beyond C++, and putting it together**

| # | Part | Topics |
|---|------|--------|
| 11 | [Objective-C, OpenMP, CUDA & Blocks](part_11_objc_openmp_cuda_blocks.md) | every `objc*`, `omp*`, `cuda*`, `block*` matcher and their narrowing/traversal companions |
| 12 | [Capstone — Real Checks in Pure clang-query](part_12_capstone.md) | clang-tidy-style checks as `-f` query scripts · appendix of the 14 reference names absent from clang-query 22 |

[`matcher_index.md`](matcher_index.md) maps every matcher name to the part
and section that covers it.

## Known quirks of clang-query 22.1.8 (found while validating)

Everything below is explained again where it bites; this is the short list.

- **Match count = distinct bound-node sets.** `forEachDescendant(x())` without a
  `.bind()` reports one match per *parent*; bind the inner node to get one per
  element. Same for `forEach`, `eachOf`, `forEachSwitchCase`,
  `forEachArgumentWithParam`, `forEachTemplateArgument`.
- **Injected class names.** In `AsIs` mode every class matches twice on
  `cxxRecordDecl(hasName("X"))`; use `unless(isImplicit())`, `isDefinition()`,
  or `set traversal IgnoreUnlessSpelledInSource`.
- **Target builtins leak in.** Bare `typedefDecl()`, `builtinType()`,
  `typeLoc()` count ~90 implicit SVE/NEON typedefs on Apple Silicon — never
  trust an unnarrowed count for those.
- **Not valid at top level:** `cxxBaseSpecifier`, `lambdaCapture`,
  `templateArgument`, `templateName`, `ompDefaultClause` — reach them through
  `hasAnyBase`, `hasAnyCapture`, `hasAnyTemplateArgument`, `refersToTemplate`,
  `hasAnyClause`. `labelDecl()` bare finds nothing (use
  `labelStmt(hasDeclaration(...))`). Outermost `qualType(<narrower>)` crashes
  clang-query — keep it under `hasType(...)`.
- **Not registered at all** (14 reference names, table in Part 12): `traverse`
  (use `set traversal`), `findAll` (use `eachOf(m, forEachDescendant(m))`),
  `equalsNode`, `cxxNamedCastExpr`, `functionTypeLoc`,
  `isInheritingConstructor`, `requiresExpr`, `requiresExprBodyDecl`,
  `templateArgumentLocCountIs`, five `omp*` names. Also missing as node
  matchers: `varTemplateSpecializationDecl`, `overloadExpr`,
  `unresolvedUsingType`, `ompClause` — so a few overloads of `hasTemplateArgument*`
  and `isImplicit` (`InitListExpr`) are unreachable from the DSL.
- **Enum arguments are quoted strings:** `hasCastKind("CK_NullToPointer")`,
  `ofKind("UETT_SizeOf")`, `hasAttr("attr::Override")` (Clang's internal attr
  class names — `[[noreturn]]` is `attr::CXX11NoReturn`).
- **Implicit nodes inflate counts:** defaulted `operator<=>` synthesises
  `ifStmt`/casts/rewritten operators; coroutines add implicit `co_await`s and a
  fall-through `co_return`; `hasArgument` peels implicit casts but
  `hasAnyArgument` does not; several reference examples (`return 42`,
  `hasCaseConstant(integerLiteral())`, `hasArraySize(integerLiteral())`) need
  `ignoringImplicit`/`IgnoreUnlessSpelledInSource` on clang 22.
- **Objective-C / CUDA samples need no SDK:** `objc.m` parses with
  `-fobjc-exceptions` and a hand-declared `objc_root_class`; `cuda.cu` needs a
  hand-declared `cudaConfigureCall` + `dim3` under `-nocudainc -nocudalib`.

## Prerequisites

- Comfortable reading C++; some idea of what an AST is (Part 1 recaps).
- Homebrew LLVM installed (`brew install llvm`).

## Conventions

- `clang-query> …` — a command to type at the clang-query prompt
- `**Expected:** N matches` — the exact result you should see (verified by `scripts/check.py`)
- `### \`name(params)\` — Matcher<Ret>` — one entry per reference matcher; `Ret` is the node matcher it plugs into
- `**Not in clang-query 22**` — reference names this build does not register (see Part 12 appendix)
- **bold** — key concepts on first mention
- `> [!hint]-` / `> [!success]-` — collapsed quiz callouts (Obsidian)
