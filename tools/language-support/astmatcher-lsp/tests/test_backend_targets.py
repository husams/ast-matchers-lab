"""Fixture-backed integration coverage for multi-TU clang-query runs."""

from __future__ import annotations

import json
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from astmatcher_lsp.run import parse_dump_header, run_query  # noqa: E402
from astmatcher_lsp.server import DEFERRED, Server, TextDocument  # noqa: E402


class TestBackendTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang-query") and not Path("/opt/homebrew/opt/llvm/bin/clang-query").exists():
            raise unittest.SkipTest("clang-query is unavailable")

    def test_semantic_kind_uses_declaration_tag(self):
        self.assertEqual(parse_dump_header(
            "CXXRecordDecl 0x123 </tmp/a.cpp:1:1, col:14> col:8 union U definition"
        )["semanticKind"], "union")
        self.assertEqual(parse_dump_header("CXXMethodDecl 0x123 col:3 f 'void ()'")["semanticKind"],
                         "method")
        self.assertEqual(parse_dump_header("IntegerLiteral 0x123 <col:3> 'int' 2")["semanticKind"], "")

    def test_directory_target_respects_gitignore_and_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text("ignored/\n")
            (root / "a.cpp").write_text("struct A {};\n")
            (root / "skip_test.cpp").write_text("struct Skip {};\n")
            (root / "ignored").mkdir()
            (root / "ignored" / "b.cpp").write_text("struct B {};\n")
            result = run_query("match cxxRecordDecl()", str(root), ["-std=c++23"],
                               target={"scope": "directory", "path": str(root)},
                               exclusions=["*_test.cpp"])
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["files"], [str(root / "a.cpp")])

    def test_nested_gitignore_rules_and_anchored_patterns(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text("/root_only.cpp\n**/build/**\n")
            selected = root / "project" / "src"
            selected.mkdir(parents=True)
            (root / "project" / ".gitignore").write_text("nested.cpp\n")
            (root / "root_only.cpp").write_text("struct Root {};\n")
            (root / "project" / "root_only.cpp").write_text("struct NestedRoot {};\n")
            (selected / "nested.cpp").write_text("struct Nested {};\n")
            (selected / "keep.cpp").write_text("struct Keep {};\n")
            (selected / "build").mkdir()
            (selected / "build" / "generated.cpp").write_text("struct Generated {};\n")
            result = run_query("match cxxRecordDecl()", str(selected), ["-std=c++23"],
                               target={"scope": "directory", "path": str(selected)})
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["files"], [str(selected / "keep.cpp")])

    def test_compile_database_cache_tracks_included_header_and_tu_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "include").mkdir()
            header = root / "include" / "model.hpp"
            header.write_text("struct Shared {};\n")
            sources = [root / "one.cpp", root / "two.cpp"]
            for source in sources:
                source.write_text('#include "model.hpp"\n')
            db = root / "build"
            db.mkdir()
            (db / "compile_commands.json").write_text(json.dumps([
                {"directory": str(root), "file": str(source),
                 "arguments": ["clang++", "-std=c++23", "-Iinclude", "-c", str(source)]}
                for source in sources
            ]))
            query = ('match cxxRecordDecl(hasName("Shared"), '
                     'unless(isImplicit())).bind("record")')
            target = {"scope": "workspace", "path": str(root), "roots": [str(root)]}
            options = {"target": target, "compile_commands": str(db),
                       "cache": {"enabled": True, "location": str(root / "cache")}}
            first = run_query(query, str(root), **options)
            self.assertTrue(first["ok"], first["errors"])
            self.assertEqual(len(first["bindings"]["record"]), 2)
            self.assertEqual(len({node["translationUnit"] for node in first["bindings"]["record"]}), 2)
            self.assertEqual({node["semanticKind"] for node in first["bindings"]["record"]}, {"struct"})
            second = run_query(query, str(root), **options)
            self.assertEqual(second["cache"]["hits"], 2)
            header.write_text("union Shared {};\n")
            third = run_query(query, str(root), **options)
            self.assertEqual(third["cache"]["hits"], 0)
            self.assertEqual({node["semanticKind"] for node in third["bindings"]["record"]}, {"union"})

    def test_compile_database_preserves_cpp_forced_include_operand(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forced = root / "generated.cpp"
            source = root / "main.cpp"
            forced.write_text("#define FROM_FORCED_INCLUDE 1\n")
            source.write_text("int from_forced_include = FROM_FORCED_INCLUDE;\n")
            database = root / "compile_commands.json"
            database.write_text(json.dumps([{
                "directory": str(root), "file": str(source),
                "arguments": ["clang++", "-std=c++23", "-include", "generated.cpp",
                              "-c", "main.cpp"]
            }]))
            result = run_query('match varDecl(hasName("from_forced_include")).bind("v")',
                               str(source), compile_commands=str(database))
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["bindings"]["v"][0]["semanticKind"], "variable")

    def test_jsonrpc_streams_each_file_before_the_full_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("a.cpp", "b.cpp"):
                (root / name).write_text(f"int {name[0]}() {{ return 1; }}\n")
            output = io.BytesIO()
            server = Server(stdin=io.BytesIO(), stdout=output)
            uri = (root / "query.astmatcher").as_uri()
            server.documents[uri] = TextDocument(uri, 'match functionDecl().bind("f")')
            server._request_id = 17
            self.assertIs(server.on_astmatcher_runQuery({
                "textDocument": {"uri": uri}, "sample": str(root / "a.cpp"),
                "flags": ["-std=c++23"], "runId": "stream-17",
                "target": {"scope": "directory", "path": str(root)},
            }), DEFERRED)
            server._worker.join(timeout=15)
            self.assertFalse(server._worker.is_alive())
            raw = output.getvalue()
            messages = []
            while raw:
                header, _, body = raw.partition(b"\r\n\r\n")
                length = int(header.split(b":")[1])
                messages.append(json.loads(body[:length]))
                raw = body[length:]
            self.assertEqual([m.get("method", "response") for m in messages],
                             ["astmatcher/queryProgress"] * 3 + ["response"])
            progress = [m["params"] for m in messages[:-1]]
            self.assertEqual([m["kind"] for m in progress], ["start", "file", "file"])
            self.assertEqual([m["runId"] for m in progress], ["stream-17"] * 3)
            self.assertEqual([m["completedFiles"] for m in progress[1:]], [1, 2])
            self.assertEqual([Path(m["file"]).name for m in progress[1:]],
                             ["a.cpp", "b.cpp"])
            self.assertEqual([m["queries"][0]["count"] for m in progress[1:]], [1, 1])
            final = messages[-1]["result"]
            self.assertTrue(final["ok"], final["errors"])
            self.assertEqual(sum(q["count"] for q in final["queries"]), 2)


if __name__ == "__main__":
    unittest.main()
