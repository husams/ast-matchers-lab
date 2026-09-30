"""List defined functions in one C++ source file using the native matcher SDK.

Run from a C++ project root:
    uv run python /path/to/query_functions.py src/example.cpp

Or select a workspace explicitly:
    uv run python /path/to/query_functions.py src/example.cpp --workspace /path/to/project
"""

import argparse
import asyncio
from pathlib import Path

from astmatcher_sdk import MatcherClient, MatcherQuery


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="C++ file to search")
    parser.add_argument(
        "--workspace", type=Path,
        help="Project root; defaults to the process's current directory",
    )
    args = parser.parse_args()

    # The SDK looks for compile_commands.json in the current directory (or
    # --workspace) and common build directories. The source path is relative
    # to that same root, so no socket address or compiler flags are needed.
    query = MatcherQuery(
        source=args.source,
        workspace=args.workspace,
        matches=('functionDecl(isDefinition(), unless(isImplicit())).bind("function")',),
    )

    # Entering the context starts a private native server; leaving stops it.
    async with MatcherClient() as client:
        status = await client.status()
        print(f"Native server: {status.state} (version {status.version})")

        # run() is async; the result keeps matcher errors separate from
        # source compilation diagnostics.
        result = await client.run(query)

    for diagnostic in result.diagnostics:
        print(f"Matcher error: {diagnostic.message}")
    if result.stderr:
        print(f"Compiler diagnostics:\n{result.stderr}")

    for found in result.queries:
        print(f"Functions matched: {found.count}")
        for match in found.matches:
            for binding in match.bindings:
                if binding.id != "function":
                    continue
                # Source ranges use zero-based lines, so add one for display.
                location = binding.range
                place = (f"{location.file}:{location.start.line + 1}"
                         if location else "(no source location)")
                print(f"  {place}: {binding.summary}")


if __name__ == "__main__":
    asyncio.run(main())
