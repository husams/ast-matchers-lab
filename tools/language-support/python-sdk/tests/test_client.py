import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astmatcher_sdk import Definition, MatcherClient, MatcherError, MatcherQuery


ROOT = Path(__file__).resolve().parents[4]
SAMPLE = ROOT / "manifests" / "intro.cpp"


class QueryTests(unittest.TestCase):
    def test_workspace_build_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src" / "unit.cpp"
            source.parent.mkdir()
            source.write_text("int enabled() { return 1; }")
            build = root / "build"
            build.mkdir()
            (build / "compile_commands.json").write_text(json.dumps([{
                "directory": str(build),
                "file": str(source),
                "arguments": ["clang++", "-DFEATURE", "-std=c++23", "-c",
                              str(source), "-o", "unit.o"],
            }]))
            other = root / "other"
            other.mkdir()
            (other / "compile_commands.json").write_text(json.dumps([{
                "directory": str(other), "file": str(source),
                "arguments": ["clang++", "-DWRONG", "-c", str(source)],
            }]))
            with patch.object(Path, "cwd", return_value=other):
                request = MatcherQuery(
                    source="src/unit.cpp", matches=("functionDecl()",),
                    flags=("-Wall", "-std=c++20"),
                    workspace=root,
                ).request()
            self.assertEqual(request["sourcePath"], str(source.resolve()))
            self.assertEqual(request["workingDirectory"], str(build.resolve()))
            self.assertEqual(request["flags"], ["-DFEATURE", "-std=c++23", "-Wall"])

    def test_current_directory_is_default_search_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "workspace"
            root.mkdir()
            source = Path(temporary) / "other" / "unit.cpp"
            source.parent.mkdir()
            (root / "compile_commands.json").write_text(json.dumps([{
                "directory": str(root), "file": str(source),
                "arguments": ["clang++", "-DCURRENT_DIRECTORY", "-c", str(source)],
            }]))
            with patch.object(Path, "cwd", return_value=root):
                request = MatcherQuery(
                    source=source, matches=("functionDecl()",),
                ).request()
            self.assertEqual(request["sourcePath"], str(source.resolve()))
            self.assertEqual(request["flags"], ["-DCURRENT_DIRECTORY"])

    def test_header_uses_related_translation_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "widget.cpp"
            header = root / "widget.hpp"
            database = root / "compile_commands.json"
            database.write_text(json.dumps([{
                "directory": str(root), "file": str(source),
                "command": f"clang++ -DHEADER_FLAG -c {source} -o widget.o",
            }]))
            request = MatcherQuery(
                source=header, matches=("recordDecl()",),
                compile_commands=database,
            ).request()
            self.assertEqual(request["flags"], ["-DHEADER_FLAG"])

    def test_no_database_keeps_explicit_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, "cwd", return_value=Path(temporary)):
                request = MatcherQuery(
                    source="unit.cpp", matches=("functionDecl()",),
                    flags=("-std=c++23",),
                ).request()
            self.assertEqual(request["flags"], ["-std=c++23"])

    def test_declarative_request_orders_definitions_before_matches(self) -> None:
        query = MatcherQuery(
            source=SAMPLE,
            definitions=(Definition("named", 'functionDecl(hasName("add"))'),),
            matches=("named",),
            flags=("-std=c++23",),
        )
        request = query.request()
        self.assertEqual(request["commands"], [
            {"kind": "LET", "name": "named",
             "expression": 'functionDecl(hasName("add"))'},
            {"kind": "MATCH", "expression": "named"},
        ])
        self.assertEqual(request["workingDirectory"], str(Path.cwd().resolve()))

    def test_rejects_empty_matcher_and_invalid_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            MatcherQuery(source=SAMPLE, matches=())
        with self.assertRaisesRegex(ValueError, "max_matches"):
            MatcherQuery(source=SAMPLE, matches=("functionDecl()",),
                         max_matches=10001)


class NativeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_query_uses_discovered_database_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "unit.cpp"
            source.write_text(
                "#ifdef FEATURE\nint enabled() { return 1; }\n#endif\n"
            )
            build = root / "build"
            build.mkdir()
            (build / "compile_commands.json").write_text(json.dumps([{
                "directory": str(root), "file": str(source),
                "arguments": ["clang++", "-DFEATURE", "-std=c++23",
                              "-c", str(source)],
            }]))
            async with MatcherClient() as client:
                result = await client.run(MatcherQuery(
                    source=source, matches=('functionDecl(hasName("enabled"))',),
                    workspace=root,
                ))
            self.assertEqual(result.queries[0].count, 1)

    async def test_unavailable_binary_reports_status(self) -> None:
        client = MatcherClient(binary="/missing/astmatcher-native")
        status = await client.status()
        self.assertEqual(status.state, "unavailable")
        with self.assertRaisesRegex(MatcherError, "unavailable"):
            await client.start()

    async def test_auto_start_query_status_and_cleanup(self) -> None:
        client = MatcherClient()
        try:
            self.assertEqual((await client.status()).state, "stopped")
            result = await client.run(MatcherQuery(
                source=SAMPLE,
                definitions=(Definition("named", 'functionDecl(hasName("add"))'),),
                matches=("named",),
                flags=("-std=c++23",),
            ))
            status = await client.status()
            self.assertTrue(status.ready)
            self.assertTrue(status.compiler_path)
            self.assertEqual(len(result.queries), 1)
            self.assertEqual(result.queries[0].command_index, 1)
            self.assertGreaterEqual(result.queries[0].count, 1)
            self.assertEqual(result.diagnostics, ())
        finally:
            await client.close()
        self.assertEqual((await client.status()).state, "stopped")

    async def test_native_matcher_diagnostic_is_structured(self) -> None:
        async with MatcherClient() as client:
            result = await client.run(MatcherQuery(
                source=SAMPLE, matches=("notRegisteredMatcher()",),
                flags=("-std=c++23",),
            ))
        self.assertTrue(result.diagnostics)
        self.assertIn("Matcher not found", result.diagnostics[0].message)
