# AST Matcher Python SDK

An async, declarative Python 3.14+ client for the native AST matcher service.
The client starts a private local server, chooses its Unix socket, and closes
both when the context exits. Python dependencies are not required.

By default, the SDK looks for `compile_commands.json` in the process's
current directory and its `build/`, `out/`, `cmake-build-debug/`, and
`cmake-build-release/` directories. Set `MatcherQuery.workspace` to look
there instead; a relative `source` is then resolved from that workspace.
The source's database entry supplies flags and working directory, while a
header borrows the closest related translation unit. Without a database,
`MatcherQuery.flags` is used. Set `compile_commands` to a file or build
directory for a nonstandard location, or to `None` to disable discovery.

Install the native `astmatcher-native` executable from
[`../native`](../native/README.md) on `PATH`, or set `ASTMATCHER_NATIVE`
to its path. The native service is a C++ program and is not bundled into the
Python wheel.

```sh
cd tools/language-support/python-sdk
uv sync
uv build
uv pip install --python /path/to/venv/bin/python dist/astmatcher_sdk-0.1.1-py3-none-any.whl
```

```python
import asyncio
from astmatcher_sdk import Definition, MatcherClient, MatcherQuery

async def main():
    query = MatcherQuery(
        source="../../../manifests/intro.cpp",
        definitions=(Definition("add_fn", 'functionDecl(hasName("add"))'),),
        matches=("add_fn",),
        flags=("-std=c++23",),
    )
    async with MatcherClient() as client:
        status = await client.status()
        print(status.state, status.version, status.compiler_path)
        result = await client.run(query)
        for found in result.queries:
            print(found.matcher, found.count)
            for match in found.matches:
                print(match.index, match.bindings)
        print(result.diagnostics)

asyncio.run(main())
```

`client.run(query)` also starts the server on first use when the client is
created without a context manager. Call `await client.close()` when finished.
`await client.status()` reports `stopped`, `ready`, or `unavailable`;
`client.watch_status()` yields status changes. Matcher parse errors are returned
in `result.diagnostics`; service failures raise `MatcherError`. Source
positions use zero-based UTF-16 columns and exclusive ends.

For development, run `uv run python -m unittest discover -s tests -v`.

The commented [function-query example](examples/query_functions.py) runs from
any C++ project. To try it on this lab's sample from the SDK directory:

```sh
uv run python examples/query_functions.py manifests/intro.cpp --workspace ../../..
```

To add the SDK to another uv project on the same machine, run
`uv add --editable /absolute/path/to/ast-matchers-lab/tools/language-support/python-sdk`
from that project's directory. The project must support Python 3.14 or newer.
