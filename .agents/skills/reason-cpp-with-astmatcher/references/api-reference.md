# Python API reference

## Contents

- [Environment](#environment)
- [Async SDK](#async-sdk)
- [Workspace and directory bridge](#workspace-and-directory-bridge)
- [Record graphs](#record-graphs)
- [Static matcher checking](#static-matcher-checking)
- [Recovery](#recovery)

## Environment

Use the installed `astmatcher-sdk` package (import `astmatcher_sdk`), Python
3.14 or newer, and a separately installed native `astmatcher-native` executable.
Use `MatcherClient(binary="/absolute/path/to/astmatcher-native")` or the
`ASTMATCHER_NATIVE` environment variable when it is not on PATH. The SDK can
also find the repository's local native build. Native Clang/LLVM 22+, protobuf,
and gRPC are build dependencies; see the existing
[native setup](../../../../tools/language-support/native/README.md) and
[SDK setup](../../../../tools/language-support/python-sdk/README.md).

The LSP bridge is a separate stdlib-only Python 3.10+ module tree. Put
`tools/language-support/astmatcher-lsp` on `PYTHONPATH`, or use the installed
module tree from the deployment. Set `ASTMATCHER_DATA` to the accompanying
`tools/language-support/data` directory if generated catalog data is elsewhere.
Import the module; do not run its CLI for source analysis. See the existing
[bridge contract](../../../../tools/language-support/astmatcher-lsp/README.md).

## Async SDK

Use `async with MatcherClient() as client` to start a private server and close
it automatically. Reuse the client for related queries. `run()` also starts it
on first use without a context manager; explicitly `await client.close()` then.

| API | Contract |
| --- | --- |
| `MatcherClient(*, binary=None)` | Optional executable path; no socket configuration |
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

Executable function-discovery pattern (supply the actual paths):

```python
import asyncio
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

# In a script: asyncio.run(find_functions("/absolute/project", "src/unit.cpp"))
# In an existing event loop: await find_functions(workspace, source)
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

```python
from astmatcher_lsp.native_client import NativeClient, native_binary_path
from astmatcher_lsp.run import run_query
from astmatcher_lsp.targets import discover_target

def scan_calls(workspace: str):
    target, files = discover_target(
        {"scope": "workspace", "path": workspace, "roots": [workspace]},
        sample=workspace,
        cwd=workspace,
        exclusions=["build/**", "vendor/**"],
    )
    client = NativeClient(native_binary_path())
    try:
        result = run_query(
            'match callExpr(callee(functionDecl(hasName("::app::Service::start"))), '
            'forFunction(functionDecl().bind("caller"))).bind("call")',
            sample=workspace,
            cwd=workspace,
            target=target,
            exclusions=["build/**", "vendor/**"],
            compile_commands="auto",
            traversal="IgnoreUnlessSpelledInSource",
            max_matches=5000,
            cache={"enabled": False},
            client=client,
        )
    finally:
        client.close()
    print(result["ok"], result["errors"], result["stderr"])
    print(result.get("completedFiles", 0), len(files), result["truncated"])
    return result
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

Reuse optional `cache={"enabled": True, "location": "/absolute/cache"}` for
repeated scans; it uses compiler dependency information. SDK queries have no
cache field. A threading `Event` can be passed as `cancelled`; `on_progress`
accepts start, file-start, heartbeat, and completed-file records.

## Record graphs

The SDK has no record-inspection method. Use the bridge
`inspect_record(translation_unit, file, source_range, flags=None, *, cwd=None,
compile_commands=None, native_server=None, timeout=120.0, client=None,
record_identity=None)`.

Take the locator from a returned record definition binding and preserve its TU
and configuration. This pattern accepts an SDK `Binding` and a known TU:

```python
from astmatcher_lsp.native_client import NativeClient, native_binary_path
from astmatcher_lsp.run import inspect_record

def record_graph(workspace: str, translation_unit: str, record):
    if record.range is None:
        raise ValueError("Record binding has no source locator")
    span = record.range
    client = NativeClient(native_binary_path())
    try:
        return inspect_record(
            translation_unit, span.file,
            {"start": {"line": span.start.line, "character": span.start.character}},
            cwd=workspace,
            compile_commands="auto",
            record_identity=record.record_identity or None,
            client=client,
        )
    finally:
        client.close()
```

Supply the same explicit database path and supplemental flags used by the
preceding query when applicable. Check `ok`, `diagnostics`, `stderr`, and
`truncated` before interpreting the graph. IDs are local to this graph reply;
`recordIdentity` selects specializations sharing a source anchor.

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

```python
from astmatcher_lsp.analyze import analyze
from astmatcher_lsp.catalog import load
from astmatcher_lsp.parser import parse

diagnostics, analyzer = analyze(load(), parse('match functionDecl().bind("f")'))
print(diagnostics)
```

Inspect `load().matchers[name].signatures` to discover overloads rather than
guessing them. Static acceptance does not prove native registration or C++
behavior; treat native diagnostics as authoritative. Configure catalog data
for the installed backend version when available.

## Recovery

For missing modules/binaries, report the failed import/status and the setup
needed. For compilation errors, inspect API-returned flags, working directory,
and diagnostics, then correct the context and retry. For matcher errors,
simplify the expression, inspect catalog signatures, and rebuild incrementally.
For capped evidence, narrow the symbol, request fewer MATCH commands, or divide
known TUs into separate API requests. Never read the target file to recover.
