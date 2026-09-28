"""End-to-end protobuf JSON, Unix socket, and real Clang matcher smoke test."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time


def run_query(binary: str, socket: str, request: dict, timeout_ms: int | None = None) -> dict:
    command = [binary, "query", "--socket", socket]
    if timeout_ms is not None:
        command.extend(["--timeout-ms", str(timeout_ms)])
    result = subprocess.run(
        command,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_inspect(binary: str, socket: str, request: dict) -> dict:
    result = subprocess.run(
        [binary, "inspect", "--socket", socket], input=json.dumps(request),
        text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def wait_process_exit(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        proc_stat = Path(f"/proc/{pid}/stat")
        if proc_stat.is_file() and proc_stat.read_text().split()[2] == "Z":
            return True
        time.sleep(0.05)
    return False


def main() -> None:
    binary = str(Path(sys.argv[1]).resolve())
    sample = str(Path(sys.argv[2]).resolve())
    with tempfile.TemporaryDirectory(prefix="am-", dir="/tmp") as directory:
        socket = str(Path(directory) / "m.sock")
        source = Path(directory) / "main.cpp"
        source.write_text("int main() { return 1; }\n", encoding="utf-8")
        server = subprocess.Popen(
            [binary, "serve", "--socket", socket],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while not os.path.exists(socket) and time.monotonic() < deadline:
                assert server.poll() is None, server.stderr.read()
                time.sleep(0.05)
            assert os.path.exists(socket), "Server socket was not created"
            assert stat.S_IMODE(os.stat(socket).st_mode) == 0o600
            ping = subprocess.run(
                [binary, "ping", "--socket", socket],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            assert ping.returncode == 0, ping.stderr
            ping_reply = json.loads(ping.stdout)
            assert ping_reply["version"] == "1", ping_reply
            compiler_path = Path(ping_reply["compilerPath"])
            assert compiler_path.is_absolute() and compiler_path.is_file(), ping_reply
            assert os.access(compiler_path, os.X_OK), ping_reply

            supported = subprocess.run(
                [binary, "capabilities"],
                input="functionDecl\nnotARegisteredMatcher\n",
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            assert supported.returncode == 0, supported.stderr
            assert supported.stdout.splitlines() == ["functionDecl"], supported

            orphan_socket = str(Path(directory) / "orphan.sock")
            parent_script = """
import os, signal, subprocess, sys, time
server = subprocess.Popen([sys.argv[1], 'serve', '--socket', sys.argv[2],
                           '--parent-pid', str(os.getpid())],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 8
while not os.path.exists(sys.argv[2]) and time.monotonic() < deadline:
    if server.poll() is not None:
        raise RuntimeError('watched server exited before listening')
    time.sleep(0.05)
if not os.path.exists(sys.argv[2]):
    raise RuntimeError('watched server did not create a socket')
print(server.pid, flush=True)
os.kill(os.getpid(), signal.SIGTERM)
"""
            parent = subprocess.run(
                [sys.executable, "-c", parent_script, binary, orphan_socket],
                text=True,
                capture_output=True,
                timeout=12,
                check=False,
            )
            assert parent.returncode == -signal.SIGTERM, parent.stderr
            orphan_pid = int(parent.stdout.strip())
            deadline = time.monotonic() + 8
            while os.path.exists(orphan_socket) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not os.path.exists(orphan_socket), "Watched server left its socket behind"
            assert wait_process_exit(orphan_pid, 5), "Watched server is still running"

            # Keep a Run blocked inside Clang on a FIFO include while its
            # parent dies. gRPC shutdown alone cannot wait for that call.
            slow_header = Path(directory) / "slow.h"
            os.mkfifo(slow_header)
            slow_source = Path(directory) / "slow.cpp"
            slow_source.write_text('#include "slow.h"\nint main() { return 0; }\n', encoding="utf-8")
            slow_socket = str(Path(directory) / "slow.sock")
            blocked_parent_script = """
import json, os, signal, subprocess, sys, time
server = subprocess.Popen([sys.argv[1], 'serve', '--socket', sys.argv[2],
                           '--parent-pid', str(os.getpid())],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 8
while not os.path.exists(sys.argv[2]) and time.monotonic() < deadline:
    if server.poll() is not None:
        raise RuntimeError('watched server exited before listening')
    time.sleep(0.05)
if not os.path.exists(sys.argv[2]):
    raise RuntimeError('watched server did not create a socket')
query = subprocess.Popen([sys.argv[1], 'query', '--socket', sys.argv[2],
                          '--timeout-ms', '10000'], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
query.stdin.write(json.dumps({'sourcePath': sys.argv[3], 'workingDirectory': sys.argv[4],
                              'flags': ['-std=c++23'],
                              'commands': [{'kind': 'MATCH', 'expression': 'functionDecl()'}]}))
query.stdin.close()
time.sleep(0.5)
if query.poll() is not None:
    raise RuntimeError('blocked query exited before parent death')
print(server.pid, query.pid, flush=True)
os.kill(os.getpid(), signal.SIGTERM)
"""
            blocked_parent = subprocess.run(
                [sys.executable, "-c", blocked_parent_script, binary, slow_socket,
                 str(slow_source), directory],
                text=True,
                capture_output=True,
                timeout=12,
                check=False,
            )
            assert blocked_parent.returncode == -signal.SIGTERM, blocked_parent.stderr
            slow_server_pid, slow_query_pid = map(int, blocked_parent.stdout.split())
            deadline = time.monotonic() + 7
            while os.path.exists(slow_socket) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not os.path.exists(slow_socket), "Blocked Run left its server socket behind"
            assert wait_process_exit(slow_server_pid, 5), "Blocked Run kept server alive"
            assert wait_process_exit(slow_query_pid, 5), "Blocked Run kept client alive"

            for invalid_timeout in ("0", "3600001", "not-a-number", "-1"):
                invalid = subprocess.run(
                    [binary, "query", "--socket", socket, "--timeout-ms", invalid_timeout],
                    input="{}",
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                assert invalid.returncode == 2, invalid
                assert "--timeout-ms" in invalid.stderr, invalid

            request = {
                "sourcePath": str(source),
                "workingDirectory": directory,
                "flags": ["-std=c++23"],
                "commands": [
                    {"kind": "LET", "name": "f", "expression": 'functionDecl(hasName("main"))'},
                    {"kind": "MATCH", "expression": "f"},
                    {"kind": "MATCH", "expression": 'functionDecl(hasName("main")).bind("fn")'},
                    {"kind": "MATCH", "expression": "noSuchMatcher()"},
                    {"kind": "MATCH", "expression": 'functionDecl(hasName("main"))'},
                ],
            }
            reply = run_query(binary, socket, request)
            assert len(reply["queries"]) == 2, reply
            assert [query["count"] for query in reply["queries"]] == [1, 1], reply
            first = reply["queries"][0]["matches"][0]
            second = reply["queries"][1]["matches"][0]
            assert first["index"] == 1 and second["index"] == 1, reply
            root = next(binding for binding in first["bindings"] if binding["id"] == "root")
            explicit = next(binding for binding in second["bindings"] if binding["id"] == "fn")
            assert root["node"] == explicit["node"], reply
            assert explicit["kind"] == "FunctionDecl", reply
            assert explicit["semanticKind"] == "function", reply
            assert explicit["range"]["file"] == str(source), reply
            assert explicit["range"]["start"] == {"line": 0, "character": 0}, reply
            assert explicit["range"]["end"] == {"line": 0, "character": 24}, reply
            assert explicit["text"] == "int main() { return 1; }", reply
            assert reply["diagnostics"][0]["commandIndex"] == 3, reply
            assert "noSuchMatcher" in reply["diagnostics"][0]["message"], reply

            record_source = Path(directory) / "records.cpp"
            record_source.write_text(
                "struct Root { int id; };\n"
                "struct Other {};\n"
                "struct Mid : virtual public Root {};\n"
                "class Leaf : public Mid {\n"
                "public:\n"
                "  Other other;\n"
                "  int compute(int value) const { return value; }\n"
                "private:\n"
                "  int hidden;\n"
                "};\n"
                "struct Outer { struct Inner {}; };\n"
                "union Payload { int number; };\n"
                "struct Pending;\n"
                "struct Holder { Pending* next; };\n"
                "int globalValue;\n"
                "class Factory { public: int (*make())(double); };\n", encoding="utf-8")
            record_query = run_query(binary, socket, {
                "sourcePath": str(record_source), "workingDirectory": directory,
                "flags": ["-std=c++23"], "commands": [{"kind": "MATCH",
                "expression": 'cxxRecordDecl(hasName("Leaf")).bind("record")'}]})
            record_binding = next(binding for binding in
                                  record_query["queries"][0]["matches"][0]["bindings"]
                                  if binding["id"] == "record")
            assert record_binding["qualifiedName"] == "Leaf", record_binding
            assert record_binding["recordKind"] == "class", record_binding
            inspection = run_inspect(binary, socket, {
                "sourcePath": str(record_source), "workingDirectory": directory,
                "flags": ["-std=c++23"], "file": str(record_source),
                "position": record_binding["range"]["start"]})
            assert inspection["ok"] and not inspection["truncated"], inspection
            nodes = {node["id"]: node for node in inspection["nodes"]}
            root_node = nodes[inspection["recordId"]]
            assert root_node["name"] == "Leaf" and root_node["recordKind"] == "class", inspection
            relations = {(nodes[edge["from"]]["name"], nodes[edge["to"]]["name"],
                          edge["kind"]) for edge in inspection["edges"]}
            assert ("Leaf", "Mid", "inherits") in relations, inspection
            assert ("Mid", "Root", "inherits") in relations, inspection
            assert ("Leaf", "other", "field") in relations, inspection
            assert ("other", "Other", "fieldType") in relations, inspection
            assert ("Leaf", "compute", "method") in relations, inspection
            member_edges = {(nodes[edge["from"]]["name"], nodes[edge["to"]]["name"]): edge
                            for edge in inspection["edges"] if edge["kind"] in {"field", "method"}}
            assert member_edges[("Leaf", "other")]["access"] == "public", inspection
            assert member_edges[("Leaf", "compute")]["access"] == "public", inspection
            assert member_edges[("Leaf", "hidden")]["access"] == "private", inspection
            inherit_edges = {(nodes[edge["from"]]["name"], nodes[edge["to"]]["name"]): edge
                             for edge in inspection["edges"] if edge["kind"] == "inherits"}
            assert inherit_edges[("Leaf", "Mid")]["access"] == "public", inspection
            assert inherit_edges[("Mid", "Root")]["isVirtual"], inspection
            method = next(node for node in nodes.values() if node["name"] == "compute")
            assert method["signature"] == "int Leaf::compute(int) const", inspection
            assert all(node["range"]["file"] == str(record_source)
                       for node in nodes.values() if node.get("range")), inspection
            nested = run_inspect(binary, socket, {
                "sourcePath": str(record_source), "workingDirectory": directory,
                "flags": ["-std=c++23"], "file": str(record_source),
                "position": {"line": 10, "character": 25}})
            assert nested["ok"], nested
            assert next(node for node in nested["nodes"]
                        if node["id"] == nested["recordId"])["name"] == "Inner", nested
            union = run_inspect(binary, socket, {
                "sourcePath": str(record_source), "workingDirectory": directory,
                "flags": ["-std=c++23"], "file": str(record_source),
                "position": {"line": 11, "character": 8}})
            assert union["ok"], union
            assert next(node for node in union["nodes"]
                        if node["id"] == union["recordId"])["recordKind"] == "union", union
            holder = run_inspect(binary, socket, {
                "sourcePath": str(record_source), "workingDirectory": directory,
                "flags": ["-std=c++23"], "file": str(record_source),
                "position": {"line": 13, "character": 8}})
            assert holder["ok"], holder
            pending = next(node for node in holder["nodes"] if node["name"] == "Pending")
            assert pending["definitionStatus"] == "unresolved", holder
            semantic_query = run_query(binary, socket, {
                "sourcePath": str(record_source), "workingDirectory": directory,
                "flags": ["-std=c++23"], "commands": [
                    {"kind": "MATCH", "expression":
                     'varDecl(hasName("globalValue")).bind("value")'},
                    {"kind": "MATCH", "expression":
                     'cxxMethodDecl(hasName("make")).bind("method")'}]})
            variable = next(binding for binding in
                            semantic_query["queries"][0]["matches"][0]["bindings"]
                            if binding["id"] == "value")
            assert variable["qualifiedName"] == "globalValue" and variable["type"] == "int", variable
            callable_binding = next(binding for binding in
                                    semantic_query["queries"][1]["matches"][0]["bindings"]
                                    if binding["id"] == "method")
            assert callable_binding["signature"] == "int (*Factory::make())(double)", callable_binding
            missing = run_inspect(binary, socket, {
                "sourcePath": str(record_source), "workingDirectory": directory,
                "flags": ["-std=c++23"], "file": str(record_source),
                "position": {"line": 50, "character": 0}})
            assert not missing["ok"] and missing["diagnostics"], missing

            large_record = Path(directory) / "large-record.cpp"
            large_record.write_text("struct Big {\n" + "".join(
                f"  int field_{index};\n" for index in range(300)) + "};\n",
                encoding="utf-8")
            bounded = run_inspect(binary, socket, {
                "sourcePath": str(large_record), "workingDirectory": directory,
                "flags": ["-std=c++23"], "file": str(large_record),
                "position": {"line": 0, "character": 0}})
            assert bounded["ok"] and bounded["truncated"], bounded
            assert len(bounded["nodes"]) <= 256 and len(bounded["edges"]) <= 512, bounded

            template_source = Path(directory) / "templates.cpp"
            template_source.write_text(
                "template<class T> struct Box { T value; };\n"
                "Box<int> i; Box<long> l;\n"
                "template<class T> struct Choice { T value; };\n"
                "template<class T> struct Choice<T*> { T* pointer; };\n"
                "Choice<int*> choice;\n", encoding="utf-8")
            template_request = {"sourcePath": str(template_source),
                                "workingDirectory": directory, "flags": ["-std=c++23"]}
            template_query = run_query(binary, socket, template_request | {
                "commands": [{"kind": "MATCH", "expression":
                              'classTemplateSpecializationDecl(hasName("Box")).bind("record")'}]})
            specializations = [binding for match in template_query["queries"][0]["matches"]
                               for binding in match["bindings"] if binding["id"] == "record"]
            assert {binding["recordIdentity"] for binding in specializations} == {
                "Box<int>", "Box<long>"}, specializations
            assert len({json.dumps(binding["range"], sort_keys=True)
                        for binding in specializations}) == 1, specializations
            for binding in specializations:
                selected = run_inspect(binary, socket, template_request | {
                    "file": str(template_source),
                    "position": binding["range"]["start"],
                    "recordIdentity": binding["recordIdentity"]})
                assert selected["ok"] and selected["recordId"], selected
                selected_root = next(node for node in selected["nodes"]
                                     if node["id"] == selected["recordId"])
                assert selected_root["recordIdentity"] == binding["recordIdentity"], selected
                field_type = next(node["type"] for node in selected["nodes"]
                                  if node["name"] == "value")
                assert field_type in ("int", "long"), selected
            primary = run_inspect(binary, socket, template_request | {
                "file": str(template_source), "position": {"line": 0, "character": 0}})
            assert primary["ok"], primary
            assert next(node for node in primary["nodes"]
                        if node["id"] == primary["recordId"])["recordIdentity"] == "Box", primary
            partial = run_inspect(binary, socket, template_request | {
                "file": str(template_source), "position": {"line": 3, "character": 0}})
            assert partial["ok"] and any(node["name"] == "pointer"
                                         for node in partial["nodes"]), partial

            large_source = Path(directory) / "large.cpp"
            large_source.write_text("".join(
                f"int global_{index} = {index};\n" for index in range(40000)),
                encoding="utf-8")
            progress_result = subprocess.run(
                [binary, "query", "--socket", socket, "--timeout-ms", "30000",
                 "--progress"],
                input=json.dumps({"sourcePath": str(large_source),
                                 "workingDirectory": directory,
                                 "flags": ["-std=c++23"], "maxMatches": 10,
                                 "commands": [{"kind": "MATCH",
                                               "expression": "varDecl()"}]}),
                text=True, capture_output=True, timeout=35, check=False)
            assert progress_result.returncode == 0, progress_result.stderr
            records = [json.loads(line) for line in progress_result.stdout.splitlines()]
            heartbeats = [record["progress"] for record in records
                          if "progress" in record]
            assert heartbeats, progress_result.stdout[:1000]
            assert all(event["sourcePath"] == str(large_source)
                       for event in heartbeats), heartbeats
            assert all("elapsedMs" in event for event in heartbeats), heartbeats
            assert records[-1]["queries"][0]["count"] == 40000, records[-1]

            no_root = run_query(binary, socket, {
                "sourcePath": str(source),
                "workingDirectory": directory,
                "flags": ["-std=c++23"],
                "commands": [
                    {"kind": "SET_BIND_ROOT", "value": "false"},
                    {"kind": "MATCH", "expression": 'functionDecl(hasName("main")).bind("fn")'},
                ],
            })
            assert [b["id"] for b in no_root["queries"][0]["matches"][0]["bindings"]] == ["fn"], no_root

            unicode_source = Path(directory) / "unicode.cpp"
            unicode_source.write_text("/* 😀 */ int main() {}\n", encoding="utf-8")
            unicode_reply = run_query(binary, socket, {
                "sourcePath": str(unicode_source),
                "workingDirectory": directory,
                "flags": ["-std=c++23"],
                "commands": [{"kind": "MATCH", "expression": 'functionDecl(hasName("main"))'}],
            })
            unicode_range = unicode_reply["queries"][0]["matches"][0]["bindings"][0]["range"]
            assert unicode_range["start"] == {"line": 0, "character": 9}, unicode_reply

            c_source = Path(directory) / "plain.c"
            c_source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            c_reply = run_query(binary, socket, {
                "sourcePath": str(c_source),
                "workingDirectory": directory,
                "flags": [],
                "commands": [{"kind": "MATCH", "expression": 'functionDecl(hasName("main"))'}],
            })
            assert c_reply["queries"][0]["count"] == 1, c_reply
            assert c_reply["diagnostics"] == [], c_reply
            assert c_reply["stderr"] == "", c_reply

            header_source = Path(directory) / "headers.cpp"
            header_source.write_text(
                "#include <stddef.h>\n#include <string_view>\n"
                "size_t value = 1;\nstd::string_view text = \"x\";\n"
                "int main() { return (int)(value + text.size()); }\n",
                encoding="utf-8",
            )
            header_reply = run_query(binary, socket, {
                "sourcePath": str(header_source),
                "workingDirectory": directory,
                "flags": ["-std=c++23"],
                "commands": [{"kind": "MATCH", "expression": 'functionDecl(hasName("main"))'}],
            })
            assert header_reply["queries"][0]["count"] == 1, header_reply
            assert header_reply["diagnostics"] == [], header_reply
            assert header_reply["stderr"] == "", header_reply

            declarations = Path(directory) / "declarations.cpp"
            declarations.write_text("namespace Demo { typedef int Count; }\n", encoding="utf-8")
            declaration_reply = run_query(binary, socket, {
                "sourcePath": str(declarations),
                "workingDirectory": directory,
                "flags": ["-std=c++23"],
                "commands": [
                    {"kind": "MATCH", "expression": 'typedefDecl(hasName("Count")).bind("alias")'},
                    {"kind": "MATCH", "expression": 'namespaceDecl(hasName("Demo")).bind("space")'},
                ],
            })
            assert [q["count"] for q in declaration_reply["queries"]] == [1, 1], declaration_reply
            alias = next(b for b in declaration_reply["queries"][0]["matches"][0]["bindings"] if b["id"] == "alias")
            space = next(b for b in declaration_reply["queries"][1]["matches"][0]["bindings"] if b["id"] == "space")
            assert alias["semanticKind"] == "type alias", declaration_reply
            assert space["semanticKind"] == "namespace", declaration_reply

            warning_source = Path(directory) / "warnings.cpp"
            warning_source.write_text("#warning noisy\n" * 2000 + "int main() { return 0; }\n", encoding="utf-8")
            warning_reply = run_query(binary, socket, {
                "sourcePath": str(warning_source),
                "workingDirectory": directory,
                "flags": ["-std=c++23"],
                "commands": [{"kind": "MATCH", "expression": 'functionDecl(hasName("main"))'}],
            })
            assert warning_reply["queries"][0]["count"] == 1, warning_reply
            assert len(warning_reply["stderr"].encode("utf-8")) <= 64 * 1024
            assert warning_reply["stderr"].count("[Clang diagnostics truncated]") == 1

            limited = run_query(binary, socket, {
                "sourcePath": sample,
                "workingDirectory": str(Path(sample).parent),
                "flags": ["-std=c++23"],
                "maxMatches": 1,
                "commands": [{"kind": "MATCH", "expression": "functionDecl()"}],
            }, timeout_ms=5000)
            assert limited["queries"][0]["count"] > 1, limited
            assert len(limited["queries"][0]["matches"]) == 1, limited
            assert limited["truncated"] is True, limited

            traversal = run_query(binary, socket, {
                "sourcePath": sample,
                "workingDirectory": str(Path(sample).parent),
                "flags": ["-std=c++23"],
                "commands": [
                    {"kind": "MATCH", "expression": "cxxConstructExpr()"},
                    {"kind": "SET_TRAVERSAL", "value": "IgnoreUnlessSpelledInSource"},
                    {"kind": "MATCH", "expression": "cxxConstructExpr()"},
                ],
            })
            assert len(traversal["queries"]) == 2, traversal
            assert traversal["queries"][0]["count"] > traversal["queries"][1]["count"], traversal
            print("native matcher smoke passed")
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
