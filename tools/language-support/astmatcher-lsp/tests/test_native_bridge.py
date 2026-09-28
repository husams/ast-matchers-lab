"""Contract tests for the stdlib LSP to native matcher bridge."""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from astmatcher_lsp.native_client import (NativeClient, NativeClientError,  # noqa: E402
                                          close_global, get_client, native_binary_path)
from astmatcher_lsp.cli import main  # noqa: E402
from astmatcher_lsp.run import inspect_record, run_query  # noqa: E402
from astmatcher_lsp.server import Server  # noqa: E402
from astmatcher_lsp.targets import translation_unit_dependencies  # noqa: E402


class FakeClient:
    binary = sys.executable
    compiler_path = sys.executable

    def __init__(self, reply: dict, progress_event: dict | None = None) -> None:
        self.reply = reply
        self.progress_event = progress_event
        self.requests: list[dict] = []
        self.inspect_reply: dict = {}
        self.inspect_requests: list[dict] = []

    def run(self, request: dict, *, cwd: str, timeout: float, on_start=None,
            on_progress=None):
        self.requests.append(request)
        if self.progress_event and on_progress:
            on_progress(self.progress_event)
        return self.reply, [self.binary, "query", "--socket", "/tmp/fake/s"], 0, ""

    def inspect(self, request: dict, *, cwd: str, timeout: float) -> dict:
        self.inspect_requests.append(request)
        return self.inspect_reply


def reply_for(source: Path) -> dict:
    binding = {"id": "v", "node": "node-1", "kind": "VarDecl",
               "semanticKind": "variable", "summary": "answer 'int'",
               "text": "int answer", "range": {"file": str(source),
               "start": {"line": 0, "character": 0},
               "end": {"line": 0, "character": 10}}}
    return {"queries": [{"commandIndex": 1, "matcher": "varDecl()", "count": 1,
                         "matches": [{"index": 1, "bindings": [binding]}]},
                        {"commandIndex": 2, "matcher": "varDecl()", "count": 1,
                         "matches": [{"index": 1, "bindings": [binding]}]}],
            "diagnostics": [], "stderr": "", "truncated": False}


class TestNativeBridge(unittest.TestCase):
    def test_binding_details_reach_queries_and_grouped_nodes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("struct Widget {};\n")
            reply = reply_for(source)
            binding = reply["queries"][0]["matches"][0]["bindings"][0]
            binding.update({"qualifiedName": "Widget", "recordKind": "struct",
                            "type": "Widget", "signature": "Widget::Widget()",
                            "recordIdentity": "Widget"})
            client = FakeClient(reply)
            result = run_query("match varDecl()\nmatch varDecl()", str(source),
                               client=client)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["queries"][0]["matches"][0]["bindings"][0]
                             ["qualifiedName"], "Widget")
            self.assertEqual(result["bindings"]["v"][0]["recordKind"], "struct")
            self.assertEqual(result["bindings"]["v"][0]["signature"], "Widget::Widget()")
            self.assertEqual(result["bindings"]["v"][0]["recordIdentity"], "Widget")

    def test_inspect_record_uses_tu_and_source_position_and_maps_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("struct Base {};\nstruct Child : Base {};\n")
            client = FakeClient({})
            client.inspect_reply = {
                "ok": True, "recordId": "n1", "truncated": False,
                "nodes": [{"id": "n1", "kind": "CXXRecordDecl", "name": "Child",
                           "qualifiedName": "Child", "recordKind": "struct",
                           "recordIdentity": "Child", "definitionStatus": "defined",
                           "range": {"file": str(source),
                                     "start": {"line": 1, "character": 0},
                                     "end": {"line": 1, "character": 23}}},
                          {"id": "n2", "kind": "CXXRecordDecl", "name": "Base",
                           "definitionStatus": "unresolved"}],
                "edges": [{"from": "n1", "to": "n2", "kind": "inherits",
                           "access": "public", "isVirtual": True}],
                "diagnostics": [], "stderr": ""}
            result = inspect_record(str(source), str(source),
                                    {"start": {"line": 1, "character": 10},
                                     "end": {"line": 1, "character": 10}},
                                    flags=["-std=c++23"], cwd=temporary, client=client,
                                    record_identity="Child")
            self.assertTrue(result["ok"], result)
            self.assertEqual(client.inspect_requests[0]["sourcePath"], str(source.resolve()))
            self.assertEqual(client.inspect_requests[0]["file"], str(source.resolve()))
            self.assertEqual(client.inspect_requests[0]["position"],
                             {"line": 1, "character": 10})
            self.assertEqual(client.inspect_requests[0]["recordIdentity"], "Child")
            self.assertEqual(result["nodes"][0]["range"]["start"]["line"], 1)
            self.assertEqual(result["nodes"][0]["uri"], source.resolve().as_uri())
            self.assertEqual(result["nodes"][1]["definitionStatus"], "unresolved")
            self.assertEqual(result["edges"][0]["virtual"], True)
            self.assertFalse(inspect_record(str(source), str(source),
                                           {"start": {"line": -1, "character": 0}},
                                           cwd=temporary, client=client)["ok"])
            self.assertEqual(len(client.inspect_requests), 1)

    def test_progress_includes_current_file_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            client = FakeClient(reply_for(source), {"elapsedMs": 725})
            events = []
            result = run_query("match varDecl()", str(source), client=client,
                               on_progress=events.append)
            self.assertTrue(result["ok"], result)
            self.assertEqual([event["kind"] for event in events],
                             ["start", "file-start", "heartbeat", "file"])
            self.assertEqual(events[1]["file"], str(source))
            self.assertEqual(events[2]["file"], str(source))
            self.assertEqual(events[2]["fileDurationMs"], 725)
            self.assertEqual(events[-1]["completedFiles"], 1)

    def test_server_exits_when_lsp_parent_is_terminated(self):
        try:
            binary = native_binary_path()
        except NativeClientError as exc:
            self.skipTest(str(exc))
        script = ("import json,time\n"
                  "from astmatcher_lsp.native_client import NativeClient\n"
                  f"client=NativeClient({binary!r})\n"
                  "socket=client._ensure_server()\n"
                  "print(json.dumps({'socket':socket,'pid':client._server.pid}),flush=True)\n"
                  "time.sleep(60)\n")
        env = {**os.environ, "PYTHONPATH": str(HERE.parent)}
        parent = subprocess.Popen([sys.executable, "-c", script], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True)
        socket_path = None
        server_pid = None
        try:
            line = parent.stdout.readline()
            if not line:
                self.fail(parent.stderr.read())
            details = json.loads(line)
            socket_path = Path(details["socket"])
            server_pid = details["pid"]
            self.assertTrue(socket_path.exists())
            parent.terminate()
            parent.wait(timeout=5)
            deadline = time.monotonic() + 5
            while socket_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(socket_path.exists(), "native server outlived its LSP parent")
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            parent.stdout.close()
            parent.stderr.close()
            if socket_path is not None and socket_path.exists() and server_pid:
                try:
                    os.kill(server_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if socket_path is not None:
                shutil.rmtree(socket_path.parent, ignore_errors=True)

    def test_extra_setting_operands_reject_later_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            for setting in ("set traversal AsIs junk", "set bind-root false junk",
                            "set output print junk", "enable output diag junk",
                            "disable output dump junk"):
                with self.subTest(setting=setting):
                    client = FakeClient({})
                    result = run_query(setting + "\nmatch varDecl()", str(source),
                                       client=client)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["queries"], [])
                    self.assertEqual(client.requests, [])
                    self.assertEqual(result["errors"][0]["range"]["start"]["line"], 0)

    def test_ping_captures_matching_compiler(self):
        client = NativeClient(sys.executable)
        server = Mock()
        server.poll.return_value = None
        serve_commands = []

        def spawn(command, **kwargs):
            serve_commands.append(command)
            Path(command[3]).touch()
            return server

        ping = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"version": "1",
                                      "compilerPath": sys.executable}).encode(), stderr=b"")
        with patch("astmatcher_lsp.native_client.subprocess.Popen", side_effect=spawn):
            with patch("astmatcher_lsp.native_client.subprocess.run", return_value=ping):
                self.assertEqual(client.compiler_path, sys.executable)
                self.assertEqual(client.compiler_path, sys.executable)
                client.close()
        self.assertEqual(serve_commands[0][-2:], ["--parent-pid", str(os.getpid())])
        server.terminate.assert_called_once()

    def test_missing_ping_compiler_disables_cache_without_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            client = FakeClient({"queries": [], "diagnostics": [], "stderr": "",
                                 "truncated": False})
            client.compiler_path = None
            options = {"client": client, "cache": {"enabled": True,
                       "location": str(Path(temporary) / "cache")}}
            with patch("astmatcher_lsp.run.translation_unit_dependencies") as scan:
                first = run_query("match varDecl()", str(source), **options)
                second = run_query("match varDecl()", str(source), **options)
            self.assertTrue(first["ok"] and second["ok"])
            scan.assert_not_called()
            self.assertEqual(second["cache"]["hits"], 0)
            self.assertEqual(len(client.requests), 2)

    def test_cache_invalidates_when_native_compiler_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.cpp"
            source.write_text("int value;\n")
            compiler = root / "clang"
            compiler.write_text("#!/bin/sh\nexit 0\n")
            compiler.chmod(0o700)
            client = FakeClient({"queries": [], "diagnostics": [], "stderr": "",
                                 "truncated": False})
            client.compiler_path = str(compiler)
            options = {"client": client, "cache": {"enabled": True,
                       "location": str(root / "cache")}}
            with patch("astmatcher_lsp.run.translation_unit_dependencies",
                       return_value=[str(source)]) as scan:
                first = run_query("match varDecl()", str(source), **options)
                second = run_query("match varDecl()", str(source), **options)
                compiler.write_text("#!/bin/sh\nexit 1\n# changed\n")
                third = run_query("match varDecl()", str(source), **options)
            self.assertEqual((first["cache"]["misses"], second["cache"]["hits"],
                              third["cache"]["misses"]), (1, 1, 1))
            self.assertTrue(all(call.args[3] == str(compiler) for call in scan.call_args_list))
            self.assertEqual(len(client.requests), 2)

    def test_cache_distinguishes_compile_working_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.cpp"
            source.write_text("int value;\n")
            workdirs = [root / "first", root / "second"]
            databases = []
            for workdir in workdirs:
                workdir.mkdir()
                database = workdir / "compile_commands.json"
                database.write_text(json.dumps([{
                    "directory": str(workdir), "file": str(source),
                    "arguments": ["clang++", "-std=c++23", "-c", str(source)],
                }]))
                databases.append(database)
            client = FakeClient({"queries": [], "diagnostics": [], "stderr": "",
                                 "truncated": False})
            options = {"client": client, "cache": {"enabled": True,
                       "location": str(root / "cache")}}
            with patch("astmatcher_lsp.run.translation_unit_dependencies",
                       return_value=[str(source)]):
                first = run_query("match varDecl()", str(source),
                                  compile_commands=str(databases[0]), **options)
                second = run_query("match varDecl()", str(source),
                                   compile_commands=str(databases[1]), **options)
                third = run_query("match varDecl()", str(source),
                                  compile_commands=str(databases[0]), **options)
            self.assertTrue(first["ok"] and second["ok"] and third["ok"])
            self.assertEqual((first["cache"]["misses"], second["cache"]["misses"],
                              third["cache"]["hits"]), (1, 1, 1))
            self.assertEqual([request["workingDirectory"] for request in client.requests],
                             [str(workdir) for workdir in workdirs])
            self.assertEqual(len(list((root / "cache").glob("*.json"))), 2)

    def test_malformed_cache_entries_are_recomputed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.cpp"
            source.write_text("int value;\n")
            client = FakeClient(reply_for(source))
            options = {"client": client, "cache": {"enabled": True,
                       "location": str(root / "cache")}}
            with patch("astmatcher_lsp.run.translation_unit_dependencies",
                       return_value=[str(source)]):
                first = run_query("match varDecl()\nmatch varDecl()", str(source), **options)
                cache_file, = (root / "cache").glob("*.json")
                for malformed in (None, {"schema": 5, "queries": None,
                                          "stderr": "", "exitCode": 0},
                                  {"schema": 5, "queries": [{"matches": None}],
                                   "stderr": "", "exitCode": 0}):
                    with self.subTest(malformed=malformed):
                        cache_file.write_text(json.dumps(malformed))
                        result = run_query("match varDecl()\nmatch varDecl()",
                                           str(source), **options)
                        self.assertTrue(result["ok"], result["errors"])
                        self.assertEqual(result["cache"]["hits"], 0)
                        self.assertEqual(result["cache"]["misses"], 1)
                final = run_query("match varDecl()\nmatch varDecl()", str(source), **options)
            self.assertTrue(first["ok"] and final["ok"])
            self.assertEqual(final["cache"]["hits"], 1)
            self.assertEqual(len(client.requests), 4)

    def test_real_cache_scans_with_native_compiler(self):
        try:
            native_binary_path()
        except NativeClientError as exc:
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            client = get_client()
            compiler = client.compiler_path
            self.assertTrue(compiler and Path(compiler).is_file())
            options = {"client": client, "cache": {"enabled": True,
                       "location": str(Path(temporary) / "cache")}}
            with patch("astmatcher_lsp.run.translation_unit_dependencies",
                       wraps=translation_unit_dependencies) as scan:
                first = run_query("match varDecl().bind(\"v\")", str(source),
                                  ["-std=c++23"], **options)
                second = run_query("match varDecl().bind(\"v\")", str(source),
                                   ["-std=c++23"], **options)
            self.assertTrue(first["ok"] and second["ok"])
            self.assertEqual(first["cache"]["misses"], 1)
            self.assertEqual(second["cache"]["hits"], 1)
            self.assertEqual(scan.call_args.args[3], compiler)

    def test_same_line_trailing_word_rejects_that_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            client = FakeClient({})
            result = run_query("match varDecl() junk\nmatch functionDecl()",
                               str(source), client=client)
            self.assertFalse(result["ok"])
            self.assertEqual(result["queries"], [])
            self.assertEqual(client.requests, [])
            self.assertEqual(result["errors"][0]["range"]["start"],
                             {"line": 0, "character": 16})

    def test_next_line_stray_keeps_prior_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            reply = {"queries": [{"commandIndex": 0, "matcher": "varDecl()",
                     "count": 1, "matches": [{"index": 1, "bindings": []}]}],
                     "diagnostics": [], "stderr": "", "truncated": False}
            client = FakeClient(reply)
            result = run_query("match varDecl()\njunk\nmatch functionDecl()",
                               str(source), client=client)
            self.assertFalse(result["ok"])
            self.assertEqual(len(result["queries"]), 1)
            self.assertEqual(len(client.requests[0]["commands"]), 1)
            self.assertEqual(result["errors"][0]["range"]["start"],
                             {"line": 1, "character": 0})

    def test_same_line_second_command_rejects_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            client = FakeClient({})
            result = run_query("match varDecl() match functionDecl()",
                               str(source), client=client)
            self.assertFalse(result["ok"])
            self.assertEqual(result["queries"], [])
            self.assertEqual(client.requests, [])

    def test_unknown_leading_word_prevents_later_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            client = FakeClient({})
            result = run_query("nonsense\nmatch varDecl()", str(source), client=client)
            self.assertFalse(result["ok"])
            self.assertEqual(result["queries"], [])
            self.assertEqual(client.requests, [])
            self.assertEqual(result["errors"][0]["range"]["start"],
                             {"line": 0, "character": 0})

    def test_quit_stops_later_commands_without_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            reply = {"queries": [{"commandIndex": 0, "matcher": "varDecl()",
                     "count": 1, "matches": [{"index": 1, "bindings": []}]}],
                     "diagnostics": [], "stderr": "", "truncated": False}
            client = FakeClient(reply)
            result = run_query("match varDecl()\nquit\nmatch functionDecl()",
                               str(source), client=client)
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["queries"]), 1)
            self.assertEqual(len(client.requests[0]["commands"]), 1)

    def test_deadline_reaches_cli_and_python_waits_for_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            cli = Path(temporary) / "native-cli"
            cli.write_text("#!/usr/bin/env python3\nprint('{}')\n")
            cli.chmod(0o700)
            client = NativeClient(str(cli))
            with patch.object(client, "_ensure_server", return_value="/tmp/am-test/s"):
                reply, command, _, _ = client.run({}, cwd=temporary, timeout=0.25)
            self.assertEqual(reply, {})
            self.assertEqual(command[-3:], ["--timeout-ms", "250", "--progress"])

    def test_client_timeout_stops_owned_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            cli = Path(temporary) / "native-cli"
            cli.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(3)\n")
            cli.chmod(0o700)
            client = NativeClient(str(cli))
            with patch.object(client, "_ensure_server", return_value="/tmp/am-test/s"):
                with patch.object(client, "close") as close:
                    with self.assertRaisesRegex(NativeClientError, "timed out"):
                        client.run({}, cwd=temporary, timeout=0.25)
            close.assert_called_once()

    def test_cancel_active_rpc_restarts_owned_server(self):
        class RunningProcess:
            killed = False

            def poll(self):
                return None

            def kill(self):
                self.killed = True

        server = Server(stdin=io.BytesIO(), stdout=io.BytesIO())
        process = RunningProcess()
        server._proc = process
        server._cancel_event = threading.Event()
        with patch("astmatcher_lsp.server.close_global") as close:
            server._cancel_run()
        self.assertTrue(process.killed)
        self.assertTrue(server._cancel_event.is_set())
        close.assert_called_once()

    def test_cancel_idle_run_keeps_owned_server(self):
        server = Server(stdin=io.BytesIO(), stdout=io.BytesIO())
        with patch("astmatcher_lsp.server.close_global") as close:
            server._cancel_run()
        close.assert_not_called()

    def test_native_startup_error_includes_server_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            failed = Path(temporary) / "failed-server"
            failed.write_text("#!/bin/sh\necho 'socket bind failed' >&2\nexit 3\n")
            failed.chmod(0o700)
            with self.assertRaisesRegex(NativeClientError, "socket bind failed"):
                NativeClient(str(failed)).run({}, cwd=temporary, timeout=1)

    def test_real_server_is_reused_and_cleaned_up(self):
        try:
            native_binary_path()
        except NativeClientError as exc:
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int answer;\n")
            request = {"sourcePath": str(source), "workingDirectory": temporary,
                       "flags": ["-std=c++23"], "traversal": "AsIs",
                       "maxMatches": 10, "commands": [{"kind": "MATCH",
                       "expression": "varDecl().bind(\"v\")"}]}
            client = get_client()
            first, _, _, _ = client.run(request, cwd=temporary, timeout=5)
            server_pid = client._server.pid
            socket_path = Path(client._socket)
            second, _, _, _ = client.run(request, cwd=temporary, timeout=5)
            self.assertEqual(client._server.pid, server_pid)
            self.assertEqual(first["queries"][0]["count"], 1)
            self.assertEqual(second["queries"][0]["count"], 1)
            close_global()
            self.assertFalse(socket_path.exists())

    def test_typed_commands_ranges_and_grouping(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int answer = 42;\n")
            client = FakeClient(reply_for(source))
            text = ('let selected varDecl(hasName("answer"))\n'
                    'match varDecl()\nmatch varDecl()\n')
            result = run_query(text, str(source), ["-std=c++23"], client=client)
            self.assertTrue(result["ok"], result)
            request = client.requests[0]
            self.assertEqual(request["sourcePath"], str(source))
            self.assertEqual(request["flags"], ["-std=c++23"])
            self.assertEqual([c["kind"] for c in request["commands"]],
                             ["LET", "MATCH", "MATCH"])
            self.assertEqual(request["commands"][0]["expression"],
                             'varDecl(hasName("answer"))')
            self.assertEqual([q["range"]["start"]["line"] for q in result["queries"]],
                             [1, 2])
            node = result["bindings"]["v"][0]
            self.assertEqual(len(result["bindings"]["v"]), 1)
            self.assertEqual([ref["query"] for ref in node["matches"]], [0, 1])
            self.assertEqual(node["range"]["end"], {"line": 0, "character": 10})
            self.assertEqual(node["uri"], source.resolve().as_uri())

    def test_diagnostic_uses_exact_let_command_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            reply = {"queries": [], "diagnostics": [{"commandIndex": 0,
                     "message": "Matcher not found: unknownMatcher", "line": 0,
                     "column": 0}], "stderr": "", "truncated": False}
            result = run_query("let name unknownMatcher()\nmatch varDecl()", str(source),
                               client=FakeClient(reply))
            self.assertFalse(result["ok"])
            self.assertEqual(result["errors"][0]["range"]["start"],
                             {"line": 0, "character": 9})
            self.assertEqual(result["errors"][0]["file"], str(source))

    def test_cache_invalidates_on_source_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int answer = 42;\n")
            client = FakeClient(reply_for(source))
            options = {"client": client, "cache": {"enabled": True,
                       "location": str(Path(temporary) / "cache")}}
            with patch("astmatcher_lsp.run.translation_unit_dependencies",
                       return_value=[str(source)]):
                first = run_query("match varDecl()\nmatch varDecl()", str(source), **options)
                second = run_query("match varDecl()\nmatch varDecl()", str(source), **options)
                source.write_text("int answer = 43;\n")
                third = run_query("match varDecl()\nmatch varDecl()", str(source), **options)
            self.assertEqual((first["cache"]["misses"], second["cache"]["hits"],
                              third["cache"]["misses"]), (1, 1, 1))
            self.assertEqual(len(client.requests), 2)

    def test_missing_native_binary_reports_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            source.write_text("int value;\n")
            with patch("astmatcher_lsp.run.get_client",
                       side_effect=NativeClientError("native matcher unavailable")):
                result = run_query("match varDecl()", str(source))
            self.assertFalse(result["ok"])
            self.assertIn("native matcher unavailable", result["errors"][0]["message"])

    def test_cli_passes_native_server_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.cpp"
            query = Path(temporary) / "match.query"
            source.write_text("int value;\n")
            query.write_text("match varDecl()\n")
            with patch("astmatcher_lsp.cli.run_query", return_value={"ok": True}) as run:
                with redirect_stdout(StringIO()):
                    status = main(["--run", str(query), "--sample", str(source),
                                   "--native-server", "/tmp/astmatcher-native",
                                   "--", "-std=c++23"])
            self.assertEqual(status, 0)
            self.assertEqual(run.call_args.kwargs["native_server"],
                             "/tmp/astmatcher-native")
            self.assertEqual(run.call_args.args[2], ["-std=c++23"])


if __name__ == "__main__":
    unittest.main()
