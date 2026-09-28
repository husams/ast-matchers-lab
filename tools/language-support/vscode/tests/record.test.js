"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const test = require("node:test");
const { detailForBinding, isRecordBinding } = require("../binding-detail");

test("binding details prefer semantic declarations and identify records", () => {
  assert.equal(detailForBinding({ kind: "CXXMethodDecl", summary: "f",
    qualifiedName: "ns::C::f", signature: "int ns::C::f(double) const" }),
  "int ns::C::f(double) const");
  assert.equal(detailForBinding({ kind: "FieldDecl", qualifiedName: "ns::C::value",
    type: "const long" }), "ns::C::value: const long");
  assert.equal(detailForBinding({ kind: "CXXRecordDecl", recordKind: "struct",
    qualifiedName: "ns::C" }), "struct ns::C");
  assert.equal(detailForBinding({ kind: "BinaryOperator", summary: "a + b" }), "a + b");
  assert.equal(isRecordBinding({ kind: "CXXRecordDecl" }), true);
  assert.equal(isRecordBinding({ kind: "FieldDecl" }), false);
});

test("record explorer sends source locators and opens only graph-owned source nodes", async () => {
  const originalLoad = Module._load;
  let panel;
  let receive;
  const opened = [];
  const sent = [];
  const vscode = {
    ViewColumn: { Active: 1, Beside: 2 },
    TextEditorRevealType: { InCenterIfOutsideViewport: 1 },
    Selection: class Selection {
      constructor(startLine, startCharacter, endLine, endCharacter) {
        this.start = { line: startLine, character: startCharacter };
        this.end = { line: endLine, character: endCharacter };
      }
    },
    Uri: {
      file: (fsPath) => ({ fsPath }),
      joinPath: (base, ...parts) => ({ fsPath: `${base.fsPath}/${parts.join("/")}` }),
      parse: (uri) => ({ fsPath: uri.replace(/^file:\/\//, "") }),
    },
    window: {
      createWebviewPanel(_viewType, title) {
        panel = { title, webview: {
          cspSource: "vscode-webview-resource:",
          asWebviewUri: (uri) => `vscode-webview-resource:${uri.fsPath}`,
          onDidReceiveMessage: (callback) => { receive = callback; },
          postMessage: (message) => { sent.push(message); },
        } };
        return panel;
      },
      async showTextDocument(uri, options) {
        const editor = { uri, options, revealRange(range) { this.revealed = range; } };
        opened.push(editor);
        return editor;
      },
    },
  };
  Module._load = function (request, parent, isMain) {
    if (request === "vscode") return vscode;
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    const modulePath = require.resolve("../record-explorer");
    delete require.cache[modulePath];
    const { RecordExplorer, makeRecordRequest } = require("../record-explorer");
    const range = { start: { line: 4, character: 2 }, end: { line: 4, character: 8 } };
    const target = { file: "/project/include/widget.h", translationUnit: "/project/main.cpp",
      range, recordIdentity: "app::Widget" };
    const expected = makeRecordRequest(target, { flags: ["-std=c++23"],
      compileCommands: "auto", nativeServerPath: "/bin/astmatcher-native" });
    assert.deepEqual(expected, { translationUnit: "/project/main.cpp", file: target.file,
      range, recordIdentity: "app::Widget", cwd: "/project", flags: ["-std=c++23"], compileCommands: "auto",
      nativeServerPath: "/bin/astmatcher-native", timeout: 60 });
    assert.throws(() => makeRecordRequest({ file: "relative.h", range }), /source location/);
    assert.equal("recordIdentity" in makeRecordRequest({ file: target.file, range }), false);
    const graph = { ok: true, recordId: "r", nodes: [
      { id: "r", kind: "CXXRecordDecl", name: "Root", qualifiedName: "app::Root", file: target.file, range },
      { id: "b", kind: "CXXRecordDecl", name: "Base", file: "/project/base.h", range },
    ], edges: [{ from: "r", to: "b", kind: "inherits" }], truncated: false, diagnostics: [] };
    const calls = [];
    const explorer = new RecordExplorer({ extensionUri: { fsPath: "/extension" } },
      async (method, request) => { calls.push({ method, request }); return graph; });
    const run = explorer.open(target, expected);
    assert.equal(panel.title, "Record: app::Widget");
    receive({ type: "ready" });
    await run;
    assert.equal(panel.title, "Record: app::Root", "resolved record replaces the source-based tab title");
    assert.equal(calls[0].method, "astmatcher/inspectRecord");
    assert.deepEqual(calls[0].request, expected);
    assert.equal(sent.at(-1).status, "ready");
    assert.match(panel.webview.html, /default-src 'none'/);
    assert.match(panel.webview.html, /script-src 'nonce-/);
    await receive({ type: "navigate", id: "unknown" });
    assert.equal(opened.length, 0);
    await receive({ type: "navigate", id: "b" });
    assert.equal(opened[0].uri.fsPath, "/project/base.h");
    assert.equal(opened[0].options.viewColumn, vscode.ViewColumn.Beside);
    assert.deepEqual(opened[0].selection.start, range.start);
  } finally {
    Module._load = originalLoad;
    delete require.cache[require.resolve("../record-explorer")];
  }
});
