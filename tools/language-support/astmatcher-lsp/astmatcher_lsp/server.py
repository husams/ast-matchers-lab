"""A small LSP server for the matcher DSL — stdlib only, JSON-RPC over stdio.

Implements the requests an editor needs for this language and nothing else:
completion (+resolve), hover, signature help, diagnostics on change, document
symbols, go-to-definition for `let` names, and semantic tokens.

One custom request, `astmatcher/runQuery`, runs the document through the
native matcher server and answers with the JSON described in run.py. For requests with a
runId it also sends `astmatcher/queryProgress` notifications as files complete.
It runs on a worker thread so completion keeps working during the scan.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any

from . import __version__
from .analyze import analyze
from .catalog import Catalog, load
from .features import (SEMANTIC_TOKEN_MODIFIERS, SEMANTIC_TOKEN_TYPES, completions,
                       definition, document_symbols, hover, resolve, semantic_tokens,
                       signature_help)
from .lexer import LineIndex
from .native_client import close_global
from .parser import Document, parse
from .run import run_query

log = logging.getLogger("astmatcher-lsp")

# A handler returns this when it will send the response itself, later.
DEFERRED = object()

SERVER_CAPABILITIES: dict[str, Any] = {
    "positionEncoding": "utf-16",
    "textDocumentSync": {"openClose": True, "change": 1},   # full text
    "completionProvider": {
        "triggerCharacters": ["(", ",", ".", '"', " "],
        "resolveProvider": True,
    },
    "hoverProvider": True,
    "signatureHelpProvider": {"triggerCharacters": ["(", ","], "retriggerCharacters": [","]},
    "documentSymbolProvider": True,
    "definitionProvider": True,
    "semanticTokensProvider": {
        "legend": {"tokenTypes": SEMANTIC_TOKEN_TYPES,
                   "tokenModifiers": SEMANTIC_TOKEN_MODIFIERS},
        "full": True,
    },
}


class TextDocument:
    def __init__(self, uri: str, text: str, version: int = 0) -> None:
        self.uri = uri
        self.version = version
        self.update(text)

    def update(self, text: str, version: int | None = None) -> None:
        self.text = text
        self.index = LineIndex(text)
        self.doc: Document = parse(text)
        self.diagnostics, self.analyzer = analyze(_CATALOG, self.doc)
        if version is not None:
            self.version = version

    def offset(self, position: dict) -> int:
        return self.index.offset(position["line"], position["character"])


_CATALOG: Catalog = None                    # type: ignore[assignment]


class Server:
    def __init__(self, stdin=None, stdout=None, data_dir: str | None = None) -> None:
        global _CATALOG
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        _CATALOG = load(data_dir)
        self.catalog = _CATALOG
        self.documents: dict[str, TextDocument] = {}
        self.shutdown_requested = False
        self._write_lock = threading.Lock()
        self._request_id = None
        self._run_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None

    # -- transport ---------------------------------------------------------
    def _read(self) -> dict | None:
        headers: dict[str, str] = {}
        while True:
            line = self.stdin.readline()
            if not line:
                return None
            line = line.decode("utf-8", "replace").strip()
            if not line:
                break
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", 0))
        if length <= 0:
            return None
        body = self.stdin.read(length)
        return json.loads(body.decode("utf-8"))

    def _write(self, message: dict) -> None:
        body = json.dumps(message).encode("utf-8")
        with self._write_lock:
            self.stdout.write(b"Content-Length: %d\r\n\r\n" % len(body))
            self.stdout.write(body)
            self.stdout.flush()

    def _respond(self, request_id, result=None, error=None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        self._write(message)

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # -- loop --------------------------------------------------------------
    def run(self) -> int:
        try:
            while True:
                try:
                    message = self._read()
                except Exception:
                    log.exception("failed to read a message")
                    return 1
                if message is None:
                    return 0
                method = message.get("method", "")
                request_id = message.get("id")
                params = message.get("params") or {}
                try:
                    handler = getattr(self, "on_" + method.replace("/", "_").replace("$", "dollar"),
                                      None)
                    if handler is None:
                        if request_id is not None:
                            self._respond(request_id, error={"code": -32601,
                                                             "message": f"unhandled: {method}"})
                        continue
                    self._request_id = request_id
                    result = handler(params)
                    if result is DEFERRED:
                        continue
                    if request_id is not None:
                        self._respond(request_id, result)
                    if method == "exit":
                        return 0 if self.shutdown_requested else 1
                except Exception:
                    log.error("error handling %s\n%s", method, traceback.format_exc())
                    if request_id is not None:
                        self._respond(request_id, error={"code": -32603,
                                                         "message": traceback.format_exc()})
        finally:
            self._cancel_run()
            close_global()

    # -- lifecycle ---------------------------------------------------------
    def on_initialize(self, params: dict) -> dict:
        return {
            "capabilities": SERVER_CAPABILITIES,
            "serverInfo": {"name": "astmatcher-lsp", "version": __version__},
        }

    def on_initialized(self, params: dict) -> None:
        return None

    def on_shutdown(self, params: dict) -> None:
        self.shutdown_requested = True
        self._cancel_run()
        return None

    def on_exit(self, params: dict) -> None:
        return None

    def on_dollar_setTrace(self, params: dict) -> None:
        return None

    def on_workspace_didChangeConfiguration(self, params: dict) -> None:
        return None

    # -- documents ---------------------------------------------------------
    def _document(self, params: dict) -> TextDocument | None:
        uri = (params.get("textDocument") or {}).get("uri")
        return self.documents.get(uri) if uri else None

    def on_textDocument_didOpen(self, params: dict) -> None:
        item = params["textDocument"]
        doc = TextDocument(item["uri"], item.get("text", ""), item.get("version", 0))
        self.documents[item["uri"]] = doc
        self._publish(doc)

    def on_textDocument_didChange(self, params: dict) -> None:
        uri = params["textDocument"]["uri"]
        doc = self.documents.get(uri)
        changes = params.get("contentChanges") or []
        if doc is None or not changes:
            return None
        doc.update(changes[-1]["text"], params["textDocument"].get("version"))
        self._publish(doc)

    def on_textDocument_didSave(self, params: dict) -> None:
        doc = self._document(params)
        if doc is not None:
            self._publish(doc)

    def on_textDocument_didClose(self, params: dict) -> None:
        uri = params["textDocument"]["uri"]
        self.documents.pop(uri, None)
        self._notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})

    def _publish(self, doc: TextDocument) -> None:
        self._notify("textDocument/publishDiagnostics", {
            "uri": doc.uri,
            "version": doc.version,
            "diagnostics": [self._lsp_diagnostic(doc, d) for d in doc.diagnostics],
        })

    @staticmethod
    def _lsp_diagnostic(doc: TextDocument, diag) -> dict:
        sl, sc = doc.index.position(diag.start)
        el, ec = doc.index.position(diag.end)
        return {
            "range": {"start": {"line": sl, "character": sc},
                      "end": {"line": el, "character": ec}},
            "severity": diag.severity,
            "source": "astmatcher",
            "code": diag.code or None,
            "message": diag.message,
        }

    # -- features ----------------------------------------------------------
    def on_textDocument_completion(self, params: dict) -> dict:
        doc = self._document(params)
        if doc is None:
            return {"isIncomplete": False, "items": []}
        offset = doc.offset(params["position"])
        items = completions(self.catalog, doc.doc, offset, doc.analyzer)
        return {"isIncomplete": False, "items": items}

    def on_completionItem_resolve(self, params: dict) -> dict:
        return resolve(self.catalog, params)

    def on_textDocument_hover(self, params: dict):
        doc = self._document(params)
        if doc is None:
            return None
        return hover(self.catalog, doc.doc, doc.offset(params["position"]), doc.analyzer)

    def on_textDocument_signatureHelp(self, params: dict):
        doc = self._document(params)
        if doc is None:
            return None
        return signature_help(self.catalog, doc.doc, doc.offset(params["position"]),
                              doc.analyzer)

    def on_textDocument_documentSymbol(self, params: dict) -> list:
        doc = self._document(params)
        if doc is None:
            return []
        return document_symbols(doc.doc, doc.index)

    def on_textDocument_definition(self, params: dict):
        doc = self._document(params)
        if doc is None:
            return None
        return definition(doc.doc, doc.offset(params["position"]), doc.uri, doc.index)

    def on_textDocument_semanticTokens_full(self, params: dict) -> dict:
        doc = self._document(params)
        if doc is None:
            return {"data": []}
        return {"data": semantic_tokens(self.catalog, doc.doc, doc.index)}

    # -- native query -------------------------------------------------------
    def on_astmatcher_runQuery(self, params: dict):
        """Params: textDocument.uri, sample, flags?, target?, exclusions?,
        compileCommands?, traversal?, cache?, nativeServerPath?, cwd?, timeout?.

        Uses the editor's current text, saved or not.  A new run cancels the
        one still going.
        """
        uri = (params.get("textDocument") or {}).get("uri", "")
        doc = self.documents.get(uri)
        text = doc.text if doc else Path(_uri_path(uri)).read_text(encoding="utf-8")
        request_id = self._request_id
        run_id = params.get("runId")
        self._cancel_run()
        cancel_event = threading.Event()
        self._cancel_event = cancel_event

        def work() -> None:
            with self._run_lock:
                try:
                    def progress(event: dict) -> None:
                        if not cancel_event.is_set():
                            self._notify("astmatcher/queryProgress", {"runId": run_id, **event})

                    result = run_query(
                        text, params["sample"], params.get("flags") or [],
                        native_server=params.get("nativeServerPath") or None,
                        cwd=params.get("cwd") or None,
                        target=params.get("target"),
                        exclusions=params.get("exclusions") or [],
                        compile_commands=params.get("compileCommands") or None,
                        traversal=params.get("traversal"),
                        cache=params.get("cache") or None,
                        cancelled=cancel_event,
                        timeout=float(params.get("timeout") or 120),
                        on_start=self._started,
                        on_progress=progress if isinstance(run_id, str) and run_id else None)
                    self._respond(request_id, result)
                except Exception:
                    log.error("runQuery failed\n%s", traceback.format_exc())
                    self._respond(request_id, error={"code": -32603,
                                                     "message": traceback.format_exc()})
                finally:
                    self._proc = None

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        return DEFERRED

    def _started(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def _cancel_run(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()
            # A synchronous Clang run may keep the gRPC server's mutex after
            # its client disappears. This server belongs only to this LSP.
            close_global()

    def on_textDocument_diagnostic(self, params: dict) -> dict:
        doc = self._document(params)
        if doc is None:
            return {"kind": "full", "items": []}
        return {"kind": "full",
                "items": [self._lsp_diagnostic(doc, d) for d in doc.diagnostics]}


def _uri_path(uri: str) -> str:
    return unquote(urlparse(uri).path)


def serve(data_dir: str | None = None) -> int:
    return Server(data_dir=data_dir).run()
