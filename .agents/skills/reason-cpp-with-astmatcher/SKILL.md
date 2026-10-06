---
name: reason-cpp-with-astmatcher
description: Reason about C++ source using ast-matchers-lab's native Clang matcher Python APIs. Use for finding declarations and definitions, inspecting classes and inheritance, tracing callers and local variable references, comparing signatures, and investigating code relationships in a file or workspace. Obtain all target-source evidence through API responses; never read or search C++ source files directly.
---

# Reason about C++ through native matcher APIs

## Use the deployed uv project

Assume the SDK and native backend are already installed and configured by the
project's deployment. Run every Python invocation with `uv run python` from that
uv project's execution directory, including scripts and stdin snippets. Import
installed APIs normally and use `MatcherClient()` with its deployment defaults.

Do not hard-code SDK, executable, checkout, catalog, or cache installation paths;
do not modify module search paths, create or activate a virtual environment, or
install/build dependencies. Take source-workspace and source-file paths from the
request or API discovery and pass them as runtime inputs. The uv project and the
C++ workspace may be different directories; do not confuse their roles.

Use the separate `astmatcher_lsp` APIs only when provided by the deployed uv
project; they are not bundled in the SDK wheel. If a deployed API/backend is
missing, report the import/status failure and stop that operation instead of
locating a checkout or changing deployment settings.

## Enforce the source-access boundary

- Use `astmatcher_sdk` and the documented `astmatcher_lsp` Python APIs for all
  target C++ discovery, inspection, and analysis. Let their native Clang backend
  read and parse source files and included headers.
- Inspect source only through returned `Binding.text` or bridge `text` fields.
  Do not open, read, search, or fetch target source through `open()`,
  `Path.read_text()`, shell commands such as `cat`/`sed`/`rg`/`grep`, editor or
  GitHub file tools, web browsing, or a separate parser. Do not read an entire
  file as a fallback when a query fails or a snippet is incomplete.
- Read this skill, its references, API documentation, and environment metadata
  as needed. Use runtime analysis inputs without changing the deployed uv
  environment. Use the target-discovery API for source inventories.
- Use `uv run python` to call these APIs and post-process their structured results.
  Do not invoke `clang-query`, native CLI commands, or raw gRPC yourself; the
  Python clients manage the native bridge, sockets, and server lifecycle.
- If an API or backend is unavailable, report the concrete missing prerequisite
  and the analysis that could not run. Provide a prepared query if useful;
  never manufacture results or fall back to direct source access.

## Choose the API

Read [API reference](references/api-reference.md) for uv execution, exact signatures,
response fields, and executable patterns. Read
[reasoning recipes](references/reasoning-recipes.md) for matcher expressions
and follow-up strategies.

| Need | Python API | Evidence |
| --- | --- | --- |
| Query one translation unit with reusable matcher definitions | `MatcherClient.run(MatcherQuery(...))` | Immutable query results and bound nodes |
| Discover files without reading their contents yourself | `astmatcher_lsp.targets.discover_target(...)` | Normalized target and source-path inventory |
| Scan a directory or multiple workspace roots | `astmatcher_lsp.run.run_query(...)` | Per-TU matches, coverage, errors, and optional cache metadata |
| Inspect a record's members, bases, and method relationships | `astmatcher_lsp.run.inspect_record(...)` | Bounded nodes and edges anchored by an API-returned source range |
| Check a proposed matcher script's shape | `catalog.load()`, `parser.parse()`, `analyze.analyze()` | Static matcher diagnostics; no source-code evidence |

Treat the SDK and bridge as separate interfaces. Do not invent SDK methods for
workspace queries, record graphs, CFGs, data flow, or AST-node sessions.

## Follow an evidence-driven query loop

1. State the question and scope: workspace, TU, symbol, overload, configuration,
   and whether the claim concerns direct calls, declarations, or runtime behavior.
   Use known paths or `discover_target()`; never search source text for a name.
2. Establish the compilation context. Prefer the project's compilation database.
   Set SDK `workspace` explicitly; use `compile_commands="auto"` or a known
   database path. Reuse the same context for follow-up queries. A header borrowing
   another TU's flags is a heuristic; prefer its actual including TU when known.
3. Probe narrowly for the target definition and bind it. Inspect returned
   `qualified_name`, `signature`, `type`, `record_identity`, and source range to
   distinguish overloads, templates, forward declarations, and definitions.
4. Express the relationship in a matcher. Bind each endpoint and the evidence
   site: for example `caller`, `callee`, and `call`; or `variable` and `reference`.
   Preserve bindings from the **same match** as a relationship row.
5. Execute through the selected Python API. Check matcher diagnostics, compiler
   diagnostics, completion, and truncation **before** drawing a conclusion.
6. Refine or decompose the matcher if evidence is too broad or truncated. Bind
   smaller statements, expressions, or declarations when returned text is cut
   off. Follow definitions or record anchors with another API request.
7. Answer with the relationship, supporting locations and signatures, checked
   scope/configuration, and any specific coverage limitation. Separate observed
   AST facts from inferred consequences.

For authored-code questions, start with
`traversal="IgnoreUnlessSpelledInSource"` and explicit declarations such as
`unless(isImplicit())`. Use `AsIs` deliberately for implicit conversions,
generated methods, or template instantiations. Treat traversal as part of the
evidence scope. Apply `isExpansionInMainFile()` only when intentionally excluding
included headers; it concerns expansion locations, including macros.

## Compose matchers and preserve identity

- Use `Definition("name", expression)` to build reusable matcher expressions;
  refer to them by plain `name` in later definitions and `matches`. Do not use
  JavaScript `let`, `$name`, `match ...` prefixes, or semicolons in SDK expressions.
- Put definitions in dependency order. Each request starts a fresh named-matcher
  map; include its definitions again in a later request.
- Treat `.bind("id")` as a result label, not an enduring variable or AST handle.
  Use `equalsBoundNode("id")` for identity joins inside one composed matcher,
  after the matching declaration has been bound. Separate `MATCH` commands do
  not share captured nodes.
- Use `has`/`hasDescendant` for existence and `forEach`/`forEachDescendant` to
  enumerate witnesses. Beware duplicate rows and Cartesian products when
  combining enumerating traversals. Preserve witnesses before deduplicating.
- Deduplicate a node by its opaque `node` only inside one native response. In a
  bridge scan include `translationUnit` in that key. Never persist an opaque ID,
  send it to a later request, or use it as a cross-TU symbol identity.
- Across requests, reselect using qualified name, signature/type constraints,
  record identity, and location with the same compilation context. These are
  evidence keys, not guaranteed universal symbol IDs; report ambiguous joins.

## Validate coverage and limits

- The SDK returns `RunResult`, with no `ok` flag. Inspect `diagnostics`, `stderr`,
  and `truncated`; service failures raise `MatcherError`. A parse failure can
  coexist with earlier query results. Never interpret that as complete coverage.
- The bridge returns dictionaries. Check `ok`, `errors` (or record-graph
  `diagnostics`), `stderr`, `cancelled`, `completedFiles`, and `truncated`. Compare
  completed files against the returned inventory and retain per-file errors.
- SDK `QueryResult.count` is the full native match count; returned `matches`
  share a storage cap across all MATCH commands. Bridge counts reflect retained,
  filtered matches. Do not mix these two counting contracts.
- Narrow or split capped requests. SDK `max_matches=0` means the native default
  of 1,000, not unlimited; the SDK accepts at most 10,000. Large counts do not
  prove all witnesses were returned.
- Directory/workspace bridge runs retain main-file results and can remove
  header-bound endpoints. Rerun relevant TUs with file scope to inspect headers
  and complete those relationship rows. Do not claim repository-wide absence
  from a main-file scan alone.
- Source ranges use zero-based lines and UTF-16 columns with exclusive ends.
  Add one for human-facing line numbers; do not slice a file using those columns.
  Accept absent ranges/text for types, implicit nodes, or macro-spanning nodes.
  Native text is capped at 4,096 bytes independently of match truncation.
- Treat a call match or graph `calls` edge as a direct AST relationship. It does
  not enumerate possible virtual dispatch targets, indirect calls, or runtime
  paths. Local reference matches are syntactic uses, not interprocedural data flow.
- Treat record `fieldType` ownership `indirect` as pointer/reference structure,
  not proof of lifetime ownership. Check unresolved records and graph truncation.
- State when CFG, alias/points-to, reachability, lifetime, or formal proof needs
  evidence these APIs do not expose. Return the supported observations and the
  precise remaining question; do not claim to have run an unavailable analysis.

## Report the result

Lead with the supported conclusion. Cite API-returned files and line numbers,
qualified symbols, and the matcher or graph edges that support it. State checked
TUs, traversal, build configuration, and material diagnostics or truncation when
they affect the answer. Phrase a negative result as “no matches in the checked
scope” unless complete coverage for the requested claim has been established.
