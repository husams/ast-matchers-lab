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

async function withRecordExplorer(reply, run) {
  const originalLoad = Module._load;
  let panel;
  let receive;
  let dispose;
  const sent = [];
  const requests = [];
  const vscode = {
    ViewColumn: { Active: 1, Beside: 2 },
    Uri: { joinPath: (base, ...parts) => ({ fsPath: `${base.fsPath}/${parts.join("/")}` }) },
    window: { createWebviewPanel(_viewType, title) {
      panel = { title, onDidDispose: (callback) => { dispose = callback; }, webview: {
        cspSource: "vscode-webview-resource:",
        asWebviewUri: (uri) => `vscode-webview-resource:${uri.fsPath}`,
        onDidReceiveMessage: (callback) => { receive = callback; },
        postMessage: (message) => { sent.push(message); },
      } };
      return panel;
    } },
  };
  Module._load = function (request, parent, isMain) {
    if (request === "vscode") return vscode;
    return originalLoad.call(this, request, parent, isMain);
  };
  const modulePath = require.resolve("../record-explorer");
  delete require.cache[modulePath];
  try {
    const recordModule = require("../record-explorer");
    const explorer = new recordModule.RecordExplorer(
      { extensionUri: { fsPath: "/extension" } },
      async (method, params) => { requests.push({ method, params }); return reply(method, params); });
    await run(explorer, { receive: (message) => receive(message), dispose: () => dispose(),
      panel: () => panel, sent, requests }, recordModule);
  } finally {
    Module._load = originalLoad;
    delete require.cache[modulePath];
  }
}

const sourceRange = (line) => ({ start: { line, character: 1 }, end: { line, character: 9 } });
const sourceTarget = { file: "/project/main.cpp", translationUnit: "/project/main.cpp",
  range: sourceRange(1), recordIdentity: "app::Root" };
const record = (id, name, line, extra = {}) => ({ id, kind: "CXXRecordDecl", name,
  qualifiedName: `app::${name}`, recordIdentity: `app::${name}`,
  definitionStatus: "defined", file: "/project/main.cpp", range: sourceRange(line), ...extra });

test("expanding a resolved related record preserves context and merges reply-local identities", async () => {
  const initial = { ok: true, recordId: "n1", nodes: [record("n1", "Root", 1),
    record("n2", "Base", 5), { id: "n3", kind: "FieldDecl", name: "base", type: "app::Base*",
      qualifiedName: "app::Root::base", file: "/project/main.cpp", range: sourceRange(3) }],
  edges: [{ from: "n1", to: "n3", kind: "field" }, { from: "n3", to: "n2", kind: "fieldType" }],
  diagnostics: [], truncated: false };
  const next = { ok: true, recordId: "n1", nodes: [record("n1", "Base", 5),
    record("n2", "Ancestor", 9), { id: "n3", kind: "FieldDecl", name: "base", type: "app::Base*",
      qualifiedName: "app::Root::base", file: "/project/main.cpp", range: sourceRange(3) },
    { id: "n4", kind: "CXXMethodDecl", name: "run", signature: "void app::Base::run()",
      qualifiedName: "app::Base::run", file: "/project/main.cpp", range: sourceRange(7) }],
  edges: [{ from: "n1", to: "n2", kind: "inherits", access: "public" },
    { from: "n1", to: "n4", kind: "method" }, { from: "n3", to: "n1", kind: "fieldType" }],
  diagnostics: [], truncated: false };
  const replies = [initial, next];
  await withRecordExplorer(async () => replies.shift(), async (explorer, host) => {
    const options = { cwd: "/project/build", flags: ["-std=c++23", "-DDEBUG"],
      compileCommands: "/project/build/compile_commands.json", nativeServerPath: "/bin/native", timeout: 42 };
    const run = explorer.open(sourceTarget, options);
    host.receive({ type: "ready" });
    await run;
    assert.deepEqual(host.sent.at(-1).graph.expandedRecordIds, ["n1"]);
    await host.receive({ type: "expand", id: "n2" });
    assert.deepEqual(host.requests[1], { method: "astmatcher/inspectRecord", params: {
      translationUnit: "/project/main.cpp", file: "/project/main.cpp", range: sourceRange(5),
      recordIdentity: "app::Base", ...options,
    } });
    const state = host.sent.at(-1);
    assert.equal(state.status, "ready");
    assert.equal(state.focusId, "n2");
    assert.equal(state.graph.recordId, "n1");
    const ancestor = state.graph.nodes.find((node) => node.recordIdentity === "app::Ancestor");
    assert.deepEqual(state.graph.expandedRecordIds, ["n1", "n2", ancestor.id]);
    assert.equal(state.graph.nodes.length, 5, "shared records and members are deduplicated");
    const method = state.graph.nodes.find((node) => node.signature === "void app::Base::run()");
    assert.notEqual(ancestor.id, "n2", "reply-local IDs are remapped");
    assert.deepEqual(state.graph.edges.find((edge) => edge.kind === "inherits"),
      { from: "n2", to: ancestor.id, kind: "inherits", access: "public" });
    assert.deepEqual(state.graph.edges.find((edge) => edge.kind === "method"),
      { from: "n2", to: method.id, kind: "method" });
    assert.equal(state.graph.edges.filter((edge) => edge.kind === "fieldType").length, 1);
    await host.receive({ type: "expand", id: "n2" });
    await host.receive({ type: "expand", id: ancestor.id });
    assert.equal(host.requests.length, 2, "inspected records and their bases are not requested again");
  });
});

test("merge uses source fallback, keeps distinct template identities, and bounds accumulated nodes", async () => {
  await withRecordExplorer(async () => undefined, async (_explorer, _host, { mergeRecordGraphs }) => {
    const box = (id, identity) => record(id, "Box", 5,
      { kind: "ClassTemplateSpecializationDecl", recordKind: "class",
        qualifiedName: "app::Box", recordIdentity: identity });
    const current = { ok: true, recordId: "r", nodes: [record("r", "Root", 1),
      record("fallback", "Fallback", 7, { recordIdentity: "" }),
      box("int", "app::Box<int>"), box("double", "app::Box<double>")],
    edges: [], diagnostics: [], expandedRecordIds: ["r"], truncated: false };
    const reply = { ok: true, recordId: "x", nodes: [record("x", "Fallback", 7),
      box("y", "app::Box<double>")],
    edges: [{ from: "x", to: "y", kind: "fieldType" }], diagnostics: [], truncated: false };
    const merged = mergeRecordGraphs(current, reply, "fallback");
    assert.equal(merged.nodes.length, 4);
    assert.deepEqual(merged.edges, [{ from: "fallback", to: "double", kind: "fieldType" }]);
    assert.deepEqual(merged.expandedRecordIds, ["r", "fallback"]);
    const full = { ...current, nodes: [record("r", "Root", 1),
      ...Array.from({ length: 4095 }, (_, i) => record(`old-${i}`, `Old${i}`, i + 10))] };
    const capped = mergeRecordGraphs(full, { ok: true, recordId: "x", nodes: [
      record("x", "Root", 1), record("new", "New", 300)],
    edges: [{ from: "x", to: "new", kind: "inherits" }], diagnostics: [] }, "r");
    assert.equal(capped.nodes.length, 4096);
    assert.equal(capped.edges.length, 0, "edges to omitted nodes are not retained");
    assert.equal(capped.truncated, true);
  });
});

test("invalid, unresolved, duplicate, and failed expansions leave the existing graph intact", async () => {
  const initial = { ok: true, recordId: "r", nodes: [record("r", "Root", 1),
    record("base", "Base", 5), record("pending", "Pending", 8,
      { definitionStatus: "unresolved" })], edges: [], diagnostics: [], truncated: false };
  let rejectExpansion;
  await withRecordExplorer(async () => {
    if (!rejectExpansion) return initial;
    return new Promise((_resolve, reject) => { rejectExpansion = reject; });
  }, async (explorer, host) => {
    const run = explorer.open(sourceTarget, {});
    host.receive({ type: "ready" });
    await run;
    const before = host.sent.at(-1).graph;
    await host.receive({ type: "expand", id: "unknown" });
    await host.receive({ type: "expand", id: "pending" });
    await host.receive({ type: "expand", id: "r" });
    assert.equal(host.requests.length, 1);
    rejectExpansion = true;
    const pending = host.receive({ type: "expand", id: "base" });
    await host.receive({ type: "expand", id: "base" });
    assert.equal(host.requests.length, 2, "a pending expansion is not repeated");
    rejectExpansion(new Error("inspection failed"));
    await pending;
    assert.deepEqual(host.sent.at(-1), { type: "expansionError", message: "inspection failed" });
    assert.equal(host.sent.at(-2).graph, before, "the prior graph remains available");
  });
});

test("inherited bases start expanded, backend errors preserve the view, and disposal stops updates", async () => {
  const graph = { ok: true, recordId: "root", nodes: [record("root", "Root", 1),
    record("base", "Base", 4), record("related", "Related", 8)],
  edges: [{ from: "root", to: "base", kind: "inherits" },
    { from: "root", to: "related", kind: "fieldType" }],
  diagnostics: [], truncated: false };
  let calls = 0;
  let finish;
  await withRecordExplorer(async () => {
    calls++;
    if (calls === 1) return graph;
    if (calls === 2) return { ok: false, diagnostics: [{ message: "record is ambiguous" }] };
    return new Promise((resolve) => { finish = resolve; });
  }, async (explorer, host) => {
    const run = explorer.open(sourceTarget, {});
    host.receive({ type: "ready" });
    await run;
    assert.deepEqual(host.sent.at(-1).graph.expandedRecordIds, ["root", "base"]);
    assert.match(host.panel().webview.html, /Class relationship diagram/);
    assert.match(host.panel().webview.html, /Template links point from a concrete class to its template pattern/);
    assert.match(host.panel().webview.html, /This translation unit only/);
    await host.receive({ type: "expand", id: "base" });
    assert.equal(host.requests.length, 1);
    const firstGraph = host.sent.at(-1).graph;
    await host.receive({ type: "expand", id: "related" });
    assert.deepEqual(host.sent.at(-1), { type: "expansionError", message: "record is ambiguous" });
    assert.equal(firstGraph.expandedRecordIds.includes("related"), false);
    const messageCount = host.sent.length;
    const pending = host.receive({ type: "expand", id: "related" });
    host.dispose();
    finish({ ok: true, recordId: "n1", nodes: [record("n1", "Related", 8)],
      edges: [], diagnostics: [], truncated: false });
    await pending;
    assert.equal(host.sent.length, messageCount, "a disposed webview receives no late graph update");
    assert.equal(host.requests.length, 3, "a failed inspection can be retried");
  });
});

test("separate expansion clicks are inspected serially without losing either request", async () => {
  const initial = { ok: true, recordId: "root", nodes: [record("root", "Root", 1),
    record("a", "A", 4), record("b", "B", 8)], edges: [], diagnostics: [], truncated: false };
  let completeFirst;
  let calls = 0;
  await withRecordExplorer(async () => {
    calls++;
    if (calls === 1) return initial;
    if (calls === 2) return new Promise((resolve) => { completeFirst = resolve; });
    return { ok: true, recordId: "local", nodes: [record("local", "B", 8)],
      edges: [], diagnostics: [], truncated: false };
  }, async (explorer, host) => {
    const run = explorer.open(sourceTarget, {});
    host.receive({ type: "ready" });
    await run;
    const first = host.receive({ type: "expand", id: "a" });
    await host.receive({ type: "expand", id: "b" });
    await host.receive({ type: "expand", id: "a" });
    assert.equal(host.requests.length, 2, "only the first inspection starts while it is pending");
    completeFirst({ ok: true, recordId: "local", nodes: [record("local", "A", 4)],
      edges: [], diagnostics: [], truncated: false });
    await first;
    assert.equal(host.requests.length, 3);
    assert.deepEqual(host.sent.at(-1).graph.expandedRecordIds, ["root", "a", "b"]);
    assert.equal(host.sent.at(-1).focusId, "b");
  });
});

test("truncated inheritance loads visible bases and newly discovered ancestors", async () => {
  const replies = [
    { ok: true, recordId: "root", nodes: [record("root", "Root", 1),
      record("base", "Base", 4)], edges: [{ from: "root", to: "base", kind: "inherits" }],
    diagnostics: [], truncated: true },
    { ok: true, recordId: "local-base", nodes: [record("local-base", "Base", 4),
      record("local-deep", "Deep", 8)],
    edges: [{ from: "local-base", to: "local-deep", kind: "inherits" }],
    diagnostics: [], truncated: true },
    { ok: true, recordId: "local-deep", nodes: [record("local-deep", "Deep", 8)],
      edges: [], diagnostics: [], truncated: false },
  ];
  await withRecordExplorer(async () => replies.shift(), async (explorer, host) => {
    const run = explorer.open(sourceTarget, {});
    host.receive({ type: "ready" });
    await run;
    await new Promise((resolve) => setImmediate(resolve));
    const merged = host.sent.at(-1).graph;
    const deep = merged.nodes.find((node) => node.recordIdentity === "app::Deep");
    assert.ok(deep, "the visible deeper base is retained");
    assert.equal(host.requests.length, 3, "both bases are inspected in the background");
    assert.deepEqual(host.sent.at(-1).graph.expandedRecordIds,
      ["root", "base", deep.id]);
    assert.equal(host.sent.at(-1).background, true);
    assert.equal(host.sent.at(-1).focusId, undefined);
  });
});

test("a truncated 256-node graph loads fields and methods for both direct parents", async () => {
  const filler = Array.from({ length: 253 }, (_, i) => ({ id: `f${i}`, kind: "FieldDecl",
    name: `rootField${i}`, qualifiedName: `app::Root::rootField${i}`,
    file: "/project/main.cpp", range: sourceRange(i + 20) }));
  const initial = { ok: true, recordId: "root", nodes: [record("root", "Root", 1),
    record("left", "Left", 4), record("right", "Right", 8), ...filler],
  edges: [{ from: "root", to: "left", kind: "inherits" },
    { from: "root", to: "right", kind: "inherits" },
    ...filler.map((node) => ({ from: "root", to: node.id, kind: "field" }))],
  diagnostics: [], truncated: true };
  const parentReply = (name, line) => ({ ok: true, recordId: "local", nodes: [
    record("local", name, line),
    { id: "field", kind: "FieldDecl", name: name.toLowerCase() + "Value",
      qualifiedName: `app::${name}::${name.toLowerCase()}Value`, type: "int",
      file: "/project/main.cpp", range: sourceRange(line + 1) },
    { id: "method", kind: "CXXMethodDecl", name: "run",
      qualifiedName: `app::${name}::run`, signature: `void app::${name}::run()`,
      file: "/project/main.cpp", range: sourceRange(line + 2) }],
  edges: [{ from: "local", to: "field", kind: "field" },
    { from: "local", to: "method", kind: "method" }],
  diagnostics: [], truncated: false });
  const replies = [initial, parentReply("Left", 4), parentReply("Right", 8)];
  await withRecordExplorer(async () => replies.shift(), async (explorer, host) => {
    const run = explorer.open(sourceTarget, {});
    host.receive({ type: "ready" });
    await run;
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(host.requests.map((request) => request.params.recordIdentity),
      ["app::Root", "app::Left", "app::Right"]);
    const state = host.sent.at(-1);
    assert.equal(state.graph.recordId, "root");
    assert.equal(state.graph.nodes.length, 260, "both parents add members beyond the first 256 nodes");
    assert.deepEqual(state.graph.edges.filter((edge) => edge.kind === "inherits")
      .map((edge) => edge.to), ["left", "right"]);
    for (const id of ["left", "right"]) {
      assert.equal(state.graph.edges.filter((edge) => edge.from === id && edge.kind === "field").length, 1);
      assert.equal(state.graph.edges.filter((edge) => edge.from === id && edge.kind === "method").length, 1);
      await host.receive({ type: "expand", id });
    }
    assert.equal(host.requests.length, 3, "loaded parents are not inspected twice");
    assert.equal(state.background, true);
    assert.equal(state.focusId, undefined);
  });
});

test("automatic parent inspection is bounded while later parents remain manually inspectable", async () => {
  const bases = Array.from({ length: 10 }, (_, i) => record(`base${i}`, `Base${i}`, i + 4));
  const initial = { ok: true, recordId: "root", nodes: [record("root", "Root", 1), ...bases],
    edges: bases.map((node) => ({ from: "root", to: node.id, kind: "inherits" })),
    diagnostics: [], truncated: true };
  await withRecordExplorer(async (_method, request) => request.recordIdentity === "app::Root"
    ? initial : { ok: true, recordId: "local", nodes: [
      record("local", request.recordIdentity.slice(5), request.range.start.line)],
    edges: [], diagnostics: [], truncated: false }, async (explorer, host) => {
    const run = explorer.open(sourceTarget, {});
    host.receive({ type: "ready" });
    await run;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(host.requests.length, 9, "at most eight bases are inspected automatically");
    assert.deepEqual(host.sent.at(-1).graph.expandedRecordIds,
      ["root", ...bases.slice(0, 8).map((node) => node.id)]);
    await host.receive({ type: "expand", id: "base8" });
    assert.equal(host.requests.length, 10);
    assert.equal(host.sent.at(-1).focusId, "base8");
  });
});
