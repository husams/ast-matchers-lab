# Python API reference

## Contents

- [Environment](#environment)
- [Async SDK](#async-sdk)
- [Workspace and directory bridge](#workspace-and-directory-bridge)
- [Record graphs](#record-graphs)
- [Static matcher checking](#static-matcher-checking)
- [Recovery](#recovery)

## Environment

Assume `astmatcher_sdk` is already installed in the deployed uv project and
that deployment configures the native backend. Run all examples from that uv
project with `uv run python`; use the default `MatcherClient()` and normal
imports. Do not install packages, build a backend, activate a virtual environment,
add module search paths, or set executable/catalog locations yourself.

The optional `astmatcher_lsp` bridge must also be supplied by the project's
deployment before using its examples. It is separate from the SDK wheel. If an
import or backend status fails, report the deployment error; do not find a source
checkout or alter the environment to bypass it.

Check the deployed SDK without any target-source access:

```bash
uv run python - <<'PY'
import asyncio
from astmatcher_sdk import MatcherClient

async def probe():
    client = MatcherClient()
    try:
        status = await client.status()
        print(status.state, status.version, status.compiler_path, status.detail)
    finally:
        await client.close()

asyncio.run(probe())
PY
```

`stopped` is normal before the first query; `unavailable` indicates a deployment
problem. Let `run()` or the async context start the configured backend when needed.

For examples that accept arguments, set `analysis_workspace` and
`analysis_source` from the user's request or API discovery. Set `record_name`
from the requested qualified symbol. These are analysis inputs, not installation
paths; no example assumes a particular checkout or deployment directory.

## Async SDK

Use `async with MatcherClient() as client` to start a private server and close
it automatically. Reuse the client for related queries. `run()` also starts it
on first use without a context manager; explicitly `await client.close()` then.

| API | Contract |
| --- | --- |
| `MatcherClient()` | Use the executable and socket configuration provided by deployment |
| `await client.start()` | Start or reuse the private server; return `ServerStatus` |
| `await client.status()` | `stopped`, `ready`, or `unavailable`; version, compiler path, detail; does not start it |
| `client.watch_status(interval=1.0)` | Async iterator of changed statuses |
| `await client.run(query, timeout=120.0)` | Return `RunResult`; positive finite timeout up to 3,600 seconds |
| `await client.close()` | Stop the owned service; use a new client after closing |
| `Definition(name, expression)` | Identifier plus nonempty matcher expression |

Construct `MatcherQuery` with these fields:

| Field | Default and behavior |
| --- | --- |
| `source` | Required file path, resolved from `workspace` |
| `matches` | Required sequence of expressions, not one string |
| `definitions` | Empty sequence; evaluated before matches in declaration order |
| `workspace` | Process current directory; root for paths and database discovery |
| `compile_commands` | `"auto"`; known file/build directory, or `None` to disable discovery |
| `flags` | Empty sequence; supplement database flags or provide flags without a database |
| `working_directory` | Workspace unless a selected database entry supplies its directory |
| `traversal` | `"AsIs"`; optionally `"IgnoreUnlessSpelledInSource"` |
| `max_matches` | 1,000; cap shared across this request; accepted range 0–10,000 |

Automatic SDK database discovery checks the workspace itself, then `build`,
`out`, `cmake-build-debug`, and `cmake-build-release`. It does not search arbitrary
ancestors. A database's existing `-std=` takes precedence over an explicit
`-std=` supplement. Without a database, flags may be empty and Clang uses its
defaults; provide the actual project flags instead of assuming a language standard.
Prefer an exact source entry: related-TU selection is heuristic even for an
unlisted source. Use `query.request()` to inspect resolved paths, flags, and
command order without reading C++ contents yourself.

Run function discovery with the source workspace and selected file as runtime arguments:

```bash
uv run python - "$analysis_workspace" "$analysis_source" <<'PY'
import asyncio
import sys
from astmatcher_sdk import Definition, MatcherClient, MatcherQuery

async def find_functions(workspace: str, source: str):
    query = MatcherQuery(
        workspace=workspace,
        source=source,
        compile_commands="auto",
        definitions=(Definition(
            "authored_function",
            'functionDecl(isDefinition(), unless(isImplicit())).bind("function")',
        ),),
        matches=("authored_function",),
        traversal="IgnoreUnlessSpelledInSource",
        max_matches=1000,
    )
    context = query.request()
    print(context["sourcePath"], context["workingDirectory"], context["flags"])
    async with MatcherClient() as client:
        status = await client.status()
        print(status.state, status.version, status.compiler_path)
        result = await client.run(query)
    if result.diagnostics:
        raise RuntimeError([(d.command_index, d.message) for d in result.diagnostics])
    if result.stderr:
        print("Compiler diagnostics:", result.stderr)
    print("Incomplete:", result.truncated)
    for found in result.queries:
        print(found.matcher, found.count, len(found.matches))
        for match in found.matches:
            bindings = {binding.id: binding for binding in match.bindings}
            function = bindings["function"]
            span = function.range
            location = (f"{span.file}:{span.start.line + 1}"
                        if span else "no source location")
            print(location, function.signature or function.summary, function.text)
    return result

asyncio.run(find_functions(sys.argv[1], sys.argv[2]))
PY
```

Handle `MatcherError` for native service failures, `ValueError`/`TypeError` for
request or compilation-database errors, and `TimeoutError` for query timeouts.
Inspect returned diagnostics even if `run()` did not raise.

`RunResult.queries` contains `QueryResult(command_index, matcher, count, matches)`;
each `Match(index, bindings)` has a one-based index. `command_index` is zero-based
and includes preceding definitions. `Diagnostic` has `command_index`, `message`,
and expression `line`/`column`. `RunResult` also has `stderr` and `truncated`.

`Binding` exposes `id`, opaque `node`, `kind`, `semantic_kind`, `summary`, `text`,
optional `range`, `qualified_name`, `type`, `signature`, `record_kind`, and
`record_identity`. A range contains `file`, `start`, and `end`; positions contain
`line` and `character`. Optional string metadata defaults to an empty string.
There is no full AST, persistent node handle, CFG, or data-flow response.

## Workspace and directory bridge

Use synchronous `run_query(text, sample, flags=None, *, cwd=None, timeout=120.0,
max_matches=5000, target=None, exclusions=None, compile_commands=None,
traversal=None, cache=None, native_server=None, client=None, ...)`.
Pass `compile_commands="auto"` explicitly for bridge database discovery.
The bridge searches at or above each source, unlike SDK workspace-only discovery.
Use `asyncio.to_thread()` when invoking it inside an async application.

```bash
uv run python - "$analysis_workspace" <<'PY'
import sys
from astmatcher_lsp.native_client import close_global
from astmatcher_lsp.run import run_query
from astmatcher_lsp.targets import discover_target

def scan_calls(workspace: str):
    target, files = discover_target(
        {"scope": "workspace", "path": workspace, "roots": [workspace]},
        sample=workspace,
        cwd=workspace,
        exclusions=[],
    )
    try:
        result = run_query(
            'match callExpr(callee(functionDecl(hasName("::app::Service::start"))), '
            'forFunction(functionDecl().bind("caller"))).bind("call")',
            sample=workspace,
            cwd=workspace,
            target=target,
            exclusions=[],
            compile_commands="auto",
            traversal="IgnoreUnlessSpelledInSource",
            max_matches=5000,
            cache={"enabled": False},
        )
    finally:
        close_global()
    print(result["ok"], result["errors"], result["stderr"])
    print(result.get("completedFiles", 0), len(files), result["truncated"])
    print(result["queries"])
    return result

scan_calls(sys.argv[1])
PY
```

Use `scope="directory"` with one `path`, or `scope="file"` for a selected TU
including its headers. Discovery respects `.gitignore` and exclusions and
normally enumerates source TUs, not all headers. Choose exclusions deliberately
and report them if they limit the claim.

The bridge returns camel-case dictionaries, not SDK dataclasses: `queries`,
`bindings`, `files`, `target`, `completedFiles`, `errors`, `stderr`, `ok`,
`truncated`, and optional `cancelled`. Each query and binding carries
`translationUnit`; binding metadata includes `qualifiedName`, `recordIdentity`,
`semanticKind`, `signature`, `file`, and optional `range`. Keep endpoint pairs
in `queries[*].matches[*].bindings`; grouped `bindings` is convenient for
distinct-node inspection but loses the immediate relationship row.

Directory/workspace scans filter header nodes, including callees declared in
headers. The example deliberately binds only the main-file caller and call site;
use a file-scope request with a `callee` binding to recover its declaration.
Bridge query `count` is the retained match-list length, not the native full
count. Check truncation and completed-file coverage separately.

Reuse optional `cache={"enabled": True}` for repeated scans with the default
location managed by the API; it uses compiler dependency information. Do not
supply a hard-coded cache directory. SDK queries have no cache field. A threading
`Event` can be passed as `cancelled`; `on_progress` accepts start, file-start,
heartbeat, and completed-file records.

## Record graphs

The SDK has no record-inspection method. Use the bridge
`inspect_record(translation_unit, file, source_range, flags=None, *, cwd=None,
compile_commands=None, native_server=None, timeout=120.0, client=None,
record_identity=None)`.

Query the requested record through the SDK, then pass its returned locator and
resolved compilation context to the bridge. Supply all analysis paths and the
qualified record name as runtime arguments:

```bash
uv run python - "$analysis_workspace" "$analysis_source" "$record_name" <<'PY'
import asyncio
import json
import sys
from astmatcher_sdk import MatcherClient, MatcherQuery
from astmatcher_lsp.native_client import close_global
from astmatcher_lsp.run import inspect_record

async def record_graph(workspace: str, source: str, qualified_name: str):
    query = MatcherQuery(
        workspace=workspace,
        source=source,
        matches=(
            'cxxRecordDecl(isDefinition(), unless(isImplicit()), '
            f'hasName({json.dumps(qualified_name)})).bind("record")',
        ),
        compile_commands="auto",
        traversal="IgnoreUnlessSpelledInSource",
    )
    context = query.request()
    async with MatcherClient() as client:
        result = await client.run(query)
    if result.diagnostics or result.truncated:
        raise RuntimeError((result.diagnostics, result.truncated, result.stderr))
    if result.stderr:
        print("Compiler diagnostics:", result.stderr)
    try:
        for found in result.queries:
            for match in found.matches:
                record = next(b for b in match.bindings if b.id == "record")
                if record.range is None:
                    print("Record binding has no source locator", record.summary)
                    continue
                span = record.range
                graph = await asyncio.to_thread(
                    inspect_record,
                    context["sourcePath"], span.file,
                    {"start": {"line": span.start.line,
                               "character": span.start.character}},
                    flags=context["flags"],
                    cwd=context["workingDirectory"],
                    compile_commands=None,
                    record_identity=record.record_identity or None,
                )
                print(graph)
    finally:
        close_global()

asyncio.run(record_graph(sys.argv[1], sys.argv[2], sys.argv[3]))
PY
```

The example reuses the SDK-resolved source, flags, and working directory, with
bridge database rediscovery disabled to preserve that compilation context.
Check graph `ok`, `diagnostics`, `stderr`, and `truncated` before interpreting it.
IDs are local to this graph reply; `recordIdentity` selects specializations
sharing a source anchor.

| Edge kind | Direction and interpretation |
| --- | --- |
| `inherits` | Derived record to base; access and virtual inheritance metadata |
| `field`, `method` | Record to explicit member |
| `fieldType` | Field to record type; `ownership` is `value` or `indirect` |
| `calls` | Caller method to directly called method |
| `instantiates` | Class instantiation to primary/partial pattern |
| `specializes` | Explicit/partial specialization to primary template |

Record nodes carry `definitionStatus="defined"` or `"unresolved"`. Graphs are
bounded to 256 nodes, 512 edges, and 32 inheritance levels. They are not complete
whole-program graphs; virtual calls and indirect field types require care.

## Static matcher checking

Validate only generated matcher text with the Python language APIs:

```bash
uv run python - <<'PY'
from astmatcher_lsp.analyze import analyze
from astmatcher_lsp.catalog import load
from astmatcher_lsp.parser import parse

diagnostics, analyzer = analyze(load(), parse('match functionDecl().bind("f")'))
print(diagnostics)
PY
```

Inspect `load().matchers[name].signatures` to discover overloads rather than
guessing them. Static acceptance does not prove native registration or C++
behavior; treat native diagnostics as authoritative. Use the catalog supplied
by deployment and report version mismatches without changing catalog paths.

## Recovery

For missing modules/backends, report the failed import/status in the selected
uv project. Leave dependency installation and backend configuration to deployment;
do not add source checkout paths or create a replacement environment.
For compilation errors, inspect API-returned flags, working directory,
and diagnostics, then correct the context and retry. For matcher errors,
simplify the expression, inspect catalog signatures, and rebuild incrementally.
For capped evidence, narrow the symbol, request fewer MATCH commands, or divide
known TUs into separate API requests. Never read the target file to recover.
