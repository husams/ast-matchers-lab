"""LSP protocol regressions for matcher files opened as untitled documents."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from astmatcher_lsp.server import Server  # noqa: E402


class TestUntitledDocumentProtocol(unittest.TestCase):
    uri = "untitled:Untitled-1"
    source = (
        'match cxxRecordDecl(\n'
        '  hasName("Pair"),\n'
        '  anyOf(\n'
        '    has(fieldDecl(hasName("first")).bind("v")),\n'
        '    has(fieldDecl(hasName("second")).bind("v"))\n'
        '  )\n'
        ')'
    )

    def session(self, messages: list[dict]) -> list[dict]:
        payload = b""
        for message in messages:
            body = json.dumps(message).encode("utf-8")
            payload += b"Content-Length: %d\r\n\r\n" % len(body) + body
        output = io.BytesIO()
        Server(stdin=io.BytesIO(payload), stdout=output).run()
        raw, replies = output.getvalue(), []
        while raw:
            header, _, rest = raw.partition(b"\r\n\r\n")
            length = int(header.split(b":")[1])
            replies.append(json.loads(rest[:length]))
            raw = rest[length:]
        return replies

    def test_untitled_open_change_recovery_and_nested_completion(self):
        bad = self.source + "\n}"
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "textDocument/didOpen",
             "params": {"textDocument": {"uri": self.uri,
                                            "languageId": "astmatcher",
                                            "version": 1, "text": self.source}}},
            {"jsonrpc": "2.0", "method": "textDocument/didChange",
             "params": {"textDocument": {"uri": self.uri, "version": 2},
                        "contentChanges": [{"text": bad}]}},
            {"jsonrpc": "2.0", "method": "textDocument/didChange",
             "params": {"textDocument": {"uri": self.uri, "version": 3},
                        "contentChanges": [{"text": self.source}]}},
            {"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion",
             "params": {"textDocument": {"uri": self.uri},
                        "position": {"line": 3, "character": 18}}},
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
            {"jsonrpc": "2.0", "method": "exit", "params": {}},
        ]
        replies = self.session(messages)
        publications = [r["params"] for r in replies
                        if r.get("method") == "textDocument/publishDiagnostics"]

        self.assertEqual([p["uri"] for p in publications], [self.uri] * 3)
        self.assertEqual(publications[0]["diagnostics"], [])
        self.assertEqual(len(publications[1]["diagnostics"]), 1)
        extra_brace = publications[1]["diagnostics"][0]
        self.assertEqual(extra_brace["message"], "unexpected input: '}'")
        self.assertEqual(extra_brace["code"], "stray")
        self.assertEqual(extra_brace["severity"], 1)
        self.assertEqual(extra_brace["range"], {
            "start": {"line": 7, "character": 0},
            "end": {"line": 7, "character": 1},
        })
        self.assertEqual(publications[2]["diagnostics"], [])

        completion = next(r for r in replies if r.get("id") == 2)["result"]
        labels = {item["label"] for item in completion["items"]}
        self.assertIn("hasName", labels)
        self.assertNotIn("functionDecl", labels)


if __name__ == "__main__":
    unittest.main()
