"""Fixture-backed integration coverage for multi-TU clang-query runs."""

from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from astmatcher_lsp.native_client import NativeClientError, native_binary_path  # noqa: E402
from astmatcher_lsp.run import run_query  # noqa: E402
from astmatcher_lsp.server import DEFERRED, Server, TextDocument  # noqa: E402
from astmatcher_lsp.targets import discover_target  # noqa: E402


class TestBackendTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            native_binary_path()
        except NativeClientError as exc:
            raise unittest.SkipTest(str(exc)) from exc

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

    def test_directory_discovery_adds_only_the_selected_sample(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("main.cpp", "legacy.c", "screen.m", "screen.mm",
                         "kernel.cu", "model.h", "model.hh", "model.hpp",
                         "model.hxx", "module.ixx"):
                (root / name).write_text("struct Item {};\n")
            target = {"scope": "directory", "path": str(root)}
            for selected in ("model.h", "model.hh", "model.hpp", "model.hxx"):
                with self.subTest(selected=selected):
                    _, files = discover_target(target, str(root / selected), str(root))
                    self.assertEqual([Path(file).name for file in files],
                                     sorted(["main.cpp", "module.ixx", selected]))
            _, files = discover_target(target, str(root / "legacy.c"), str(root))
            self.assertEqual([Path(file).name for file in files],
                             ["main.cpp", "module.ixx"])

    def test_directory_header_only_runs_matcher_in_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "pair.hpp"
            header.write_text("struct Pair {};\n")
            for scope in ("directory", "workspace"):
                with self.subTest(scope=scope):
                    target = {"scope": scope, "path": str(root), "roots": [str(root)]}
                    result = run_query(
                        'match cxxRecordDecl(hasName("Pair"), isDefinition()).bind("record")',
                        str(header), ["-std=c++23"], target=target)
                    self.assertTrue(result["ok"], result["errors"])
                    self.assertEqual(result["files"], [str(header)])
                    self.assertEqual(len(result["bindings"]["record"]), 1)
                    self.assertEqual(result["bindings"]["record"][0]["file"],
                                     str(header.resolve()))

    def test_selected_h_header_uses_explicit_cpp_language_in_file_and_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "pair.h"
            header.write_text("struct Pair {};\n")
            query = 'match cxxRecordDecl(hasName("Pair"), isDefinition()).bind("record")'
            flags = ["-x", "c++", "-std=c++23"]
            file_result = run_query(query, str(header), flags)
            directory_result = run_query(
                query, str(header), flags,
                target={"scope": "directory", "path": str(root)})
            for result in (file_result, directory_result):
                self.assertTrue(result["ok"], result["errors"])
                self.assertEqual(result["files"], [str(header)])
                self.assertEqual(len(result["bindings"]["record"]), 1)
                self.assertEqual(result["bindings"]["record"][0]["file"],
                                 str(header.resolve()))

    def test_directory_selected_header_matches_after_cpp_only_run_does_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "model.hpp"
            source = root / "main.cpp"
            header.write_text("struct FromHeader {};\n")
            source.write_text('#include "model.hpp"\nstruct Local {};\n')
            query = 'match cxxRecordDecl(hasName("FromHeader"), isDefinition()).bind("record")'
            target = {"scope": "directory", "path": str(root)}
            before = run_query(query, str(source), ["-std=c++23"], target=target)
            self.assertTrue(before["ok"], before["errors"])
            self.assertEqual(before["files"], [str(source)])
            self.assertEqual(before["queries"][0]["count"], 0)

            result = run_query(query, str(header), ["-std=c++23"], target=target)
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["files"], [str(source), str(header)])
            records = result["bindings"]["record"]
            self.assertEqual(len(records), 1)
            self.assertEqual((records[0]["summary"], records[0]["file"],
                              records[0]["translationUnit"]),
                             ("FromHeader", str(header.resolve()), str(header)))

    def test_directory_ignores_excluded_or_gitignored_selected_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "keep.cpp").write_text("int keep;\n")
            ignored = root / "ignored"
            ignored.mkdir()
            (ignored / "hidden.hpp").write_text("struct Hidden {};\n")
            (root / ".gitignore").write_text("ignored/\n")
            excluded = root / "skip.hpp"
            excluded.write_text("struct Skip {};\n")
            excluded_dir = root / "exclude"
            excluded_dir.mkdir()
            (excluded_dir / "nested.hpp").write_text("struct Nested {};\n")
            target = {"scope": "directory", "path": str(root)}
            for sample, exclusions in ((ignored / "hidden.hpp", None),
                                       (excluded, ["*.hpp"]),
                                       (excluded_dir / "nested.hpp", ["exclude/"])):
                with self.subTest(sample=sample):
                    _, files = discover_target(target, str(sample), str(root), exclusions)
                    self.assertEqual(files, [str(root / "keep.cpp")])

    def test_unselected_non_self_contained_header_does_not_break_directory_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "requires_setup.hpp"
            header.write_text("#ifndef READY\n#error requires setup\n#endif\n")
            source = root / "main.cpp"
            source.write_text('#define READY 1\n#include "requires_setup.hpp"\nint answer = 42;\n')
            result = run_query('match varDecl(hasName("answer")).bind("v")',
                               str(source), ["-std=c++23"],
                               target={"scope": "directory", "path": str(root)})
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["files"], [str(source)])
            self.assertEqual(len(result["bindings"]["v"]), 1)
            self.assertNotIn("requires setup", result["stderr"])

    def test_file_target_includes_matches_from_transitive_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deep = root / "deep.hpp"
            deep.write_text("class Deep {};\n")
            middle = root / "middle.hpp"
            middle.write_text('#include "deep.hpp"\n')
            source = root / "main.cpp"
            source.write_text('#include "middle.hpp"\n')
            query = ('match cxxRecordDecl(hasName("Deep"), isDefinition(), '
                     'unless(isImplicit()))\n'
                     'match cxxRecordDecl(hasName("Deep"), isDefinition(), '
                     'unless(isImplicit())).bind("record")')
            result = run_query(query, str(source), ["-std=c++23"])
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual([q["count"] for q in result["queries"]], [1, 1])
            self.assertEqual(result["bindings"]["record"][0]["file"], str(deep.resolve()))
            self.assertEqual(result["bindings"]["record"][0]["translationUnit"], str(source))

    def test_file_target_preserves_header_bindings_for_main_file_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "model.hpp"
            header.write_text("struct FromHeader {};\n")
            source = root / "main.cpp"
            source.write_text('#include "model.hpp"\nstruct Local { FromHeader member; };\n')
            query = ('match fieldDecl(hasType(recordDecl(hasName("FromHeader"))'
                     '.bind("header"))).bind("field")')
            result = run_query(query, str(source), ["-std=c++23"])
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["queries"][0]["count"], 1)
            self.assertEqual(result["bindings"]["field"][0]["file"], str(source.resolve()))
            self.assertEqual(result["bindings"]["header"][0]["file"], str(header.resolve()))

            directory_result = run_query(
                query, str(source), ["-std=c++23"],
                target={"scope": "directory", "path": str(root)})
            self.assertTrue(directory_result["ok"], directory_result["errors"])
            self.assertEqual(directory_result["queries"][0]["count"], 1)
            self.assertIn("field", directory_result["bindings"])
            self.assertNotIn("header", directory_result["bindings"])

    def test_directory_results_exclude_matches_spelled_in_included_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "model.hpp"
            header.write_text("struct FromHeader {};\n")
            source = root / "main.cpp"
            source.write_text('#include "model.hpp"\nstruct Local {};\n')
            result = run_query(
                'match cxxRecordDecl(isDefinition(), unless(isImplicit())).bind("record")',
                str(source), ["-std=c++23"],
                target={"scope": "directory", "path": str(root)})
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(len(result["bindings"]["record"]), 1)
            self.assertEqual(result["bindings"]["record"][0]["file"], str(source.resolve()))
            self.assertIn("Local", result["bindings"]["record"][0]["summary"])

    def test_cache_distinguishes_file_from_directory_header_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "deep.hpp"
            header.write_text("class Deep {};\n")
            (root / "middle.hpp").write_text('#include "deep.hpp"\n')
            source = root / "main.cpp"
            source.write_text('#include "middle.hpp"\n')
            query = ('match cxxRecordDecl(hasName("Deep"), isDefinition(), '
                     'unless(isImplicit())).bind("record")')
            options = {"cache": {"enabled": True, "location": str(root / "cache")}}
            file_target = {"scope": "file", "path": str(source)}
            directory_target = {"scope": "directory", "path": str(root)}
            file_result = run_query(query, str(source), ["-std=c++23"],
                                    target=file_target, **options)
            self.assertTrue(file_result["ok"], file_result["errors"])
            self.assertEqual(file_result["queries"][0]["count"], 1)
            self.assertEqual(file_result["cache"]["misses"], 1)
            directory_result = run_query(query, str(source), ["-std=c++23"],
                                         target=directory_target, **options)
            self.assertTrue(directory_result["ok"], directory_result["errors"])
            self.assertEqual(directory_result["queries"][0]["count"], 0)
            self.assertEqual(directory_result["cache"]["misses"], 1)
            cached_file = run_query(query, str(source), ["-std=c++23"],
                                    target=file_target, **options)
            self.assertEqual(cached_file["queries"][0]["count"], 1)
            self.assertEqual(cached_file["cache"]["hits"], 1)

    def test_parse_errors_keep_source_path_without_blocking_other_cpp_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / "good.cpp"
            bad = root / "bad.cpp"
            good.write_text("int answer = 42;\n")
            bad.write_text("int broken( {\n")
            result = run_query('match varDecl(hasName("answer")).bind("v")', str(root),
                               ["-std=c++23"],
                               target={"scope": "directory", "path": str(root)})
            self.assertEqual(result["bindings"]["v"][0]["file"], str(good.resolve()))
            self.assertFalse(any(query["translationUnit"] == str(bad.absolute())
                                 for query in result["queries"]))
            failures = [error for error in result["errors"]
                        if error.get("file") == str(bad.absolute())]
            self.assertTrue(failures, result)
            self.assertIn("parse", failures[0]["message"].lower())

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
                source.write_text('#include "model.hpp"\nstruct Local {};\n')
            db = root / "build"
            db.mkdir()
            (db / "compile_commands.json").write_text(json.dumps([
                {"directory": str(root), "file": str(source),
                 "arguments": ["clang++", "-std=c++23", "-Iinclude", "-c", str(source)]}
                for source in sources
            ]))
            query = ('match cxxRecordDecl(isDefinition(), '
                     'unless(isImplicit())).bind("record")')
            target = {"scope": "workspace", "path": str(root), "roots": [str(root)]}
            options = {"target": target, "compile_commands": str(db),
                       "cache": {"enabled": True, "location": str(root / "cache")}}
            first = run_query(query, str(root), **options)
            self.assertTrue(first["ok"], first["errors"])
            self.assertEqual(len(first["bindings"]["record"]), 2)
            self.assertEqual({node["summary"] for node in first["bindings"]["record"]}, {"Local"})
            self.assertEqual(len({node["translationUnit"] for node in first["bindings"]["record"]}), 2)
            self.assertEqual({node["semanticKind"] for node in first["bindings"]["record"]}, {"struct"})
            second = run_query(query, str(root), **options)
            self.assertEqual(second["cache"]["hits"], 2)
            header.write_text("union Shared {};\n")
            third = run_query(query, str(root), **options)
            self.assertEqual(third["cache"]["hits"], 0)
            self.assertEqual({node["semanticKind"] for node in third["bindings"]["record"]}, {"struct"})

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

    def test_header_target_borrows_the_include_paths_of_a_related_tu(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "include").mkdir()
            (root / "src").mkdir()
            (root / "include" / "shared.hpp").write_text("struct Shared {};\n")
            header = root / "include" / "model.hpp"
            header.write_text("#include <shared.hpp>\nstruct Model { Shared s; };\n")
            (root / "src" / "model.cpp").write_text("#include <model.hpp>\n")
            database = root / "compile_commands.json"
            database.write_text(json.dumps([{
                "directory": str(root / "src"), "file": "model.cpp",
                "arguments": ["clang++", "-std=c++23", "-I../include", "-c", "model.cpp"]}]))

            # Without the database the angled include is not on any search path,
            # and clang matches a broken AST.
            bare = run_query('match fieldDecl(hasType(recordDecl())).bind("f")',
                             str(header), ["-std=c++23"])
            self.assertIn("shared.hpp", bare["stderr"])
            self.assertIn("file not found", bare["stderr"])

            result = run_query('match fieldDecl(hasType(recordDecl())).bind("f")',
                               str(header), ["-std=c++23"],
                               compile_commands=str(database))
            self.assertTrue(result["ok"], result["errors"])
            self.assertNotIn("file not found", result["stderr"])
            self.assertEqual(len(result["bindings"]["f"]), 1)

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
                             ["astmatcher/queryProgress"] * 7 + ["response"])
            progress = [m["params"] for m in messages[:-1]]
            self.assertEqual([m["kind"] for m in progress],
                             ["start", "file-start", "heartbeat", "file",
                              "file-start", "heartbeat", "file"])
            # Native heartbeat events can also arrive during either file.
            self.assertEqual([m["runId"] for m in progress], ["stream-17"] * 7)
            files = [m for m in progress if m["kind"] != "start"]
            self.assertEqual([m["completedFiles"] for m in files], [0, 0, 1, 1, 1, 2])
            self.assertEqual([Path(m["file"]).name for m in files],
                             ["a.cpp", "a.cpp", "a.cpp", "b.cpp", "b.cpp", "b.cpp"])
            completed = [m for m in progress if m["kind"] == "file"]
            self.assertEqual([m["queries"][0]["count"] for m in completed], [1, 1])
            final = messages[-1]["result"]
            self.assertTrue(final["ok"], final["errors"])
            self.assertEqual(sum(q["count"] for q in final["queries"]), 2)

    def test_run_errors_are_logged_with_the_translation_unit_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "slow.cpp"
            source.write_text("int value;\n")
            uri = source.with_suffix(".query").as_uri()
            server = Server(stdin=io.BytesIO(), stdout=io.BytesIO())
            server.documents[uri] = TextDocument(uri, "match varDecl()")
            server._request_id = 19
            timed_out = {"ok": False, "sample": str(source), "errors": [{
                "message": "native matcher timed out after 120s", "file": str(source)}]}
            with patch("astmatcher_lsp.server.run_query", return_value=timed_out):
                with self.assertLogs("astmatcher-lsp", level="ERROR") as captured:
                    server.on_astmatcher_runQuery({
                        "textDocument": {"uri": uri}, "sample": str(source),
                        "runId": "timeout-log-19"})
                    server._worker.join(timeout=5)
            self.assertFalse(server._worker.is_alive())
            self.assertIn(str(source), "\n".join(captured.output))
            self.assertIn("timed out after 120s", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
