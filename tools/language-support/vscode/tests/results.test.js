"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const test = require("node:test");

class Position {
  constructor(line, character) { this.line = line; this.character = character; }
}
class Range {
  constructor(start, startCharacter, end, endCharacter) {
    if (typeof start === "number") {
      this.start = new Position(start, startCharacter);
      this.end = new Position(end, endCharacter);
    } else {
      this.start = start;
      this.end = startCharacter;
    }
  }
}
class Selection extends Range {}
class EventEmitter {
  constructor() { this.event = () => ({ dispose() {} }); }
  fire() {}
}
class TreeItem {
  constructor(label, collapsibleState) { this.label = label; this.collapsibleState = collapsibleState; }
}
class ThemeColor { constructor(id) { this.id = id; } }
class ThemeIcon { constructor(id, color) { this.id = id; this.color = color; } }
class MarkdownString {
  appendMarkdown() { return this; }
  appendCodeblock() { return this; }
}

let decorationId = 0;
const editors = new Map();
const vscode = {
  EventEmitter,
  Range,
  Selection,
  Position,
  ThemeColor,
  ThemeIcon,
  TreeItem,
  MarkdownString,
  TreeItemCollapsibleState: { None: 0, Expanded: 2 },
  OverviewRulerLane: { Center: 1, Full: 2 },
  TextEditorRevealType: { InCenterIfOutsideViewport: 1 },
  ViewColumn: { Active: -1 },
  Uri: { file: (fsPath) => ({ fsPath }), joinPath: (...parts) => ({ fsPath: parts.join("/") }) },
  commands: { executeCommand() {} },
  window: {
    visibleTextEditors: [],
    onDidChangeVisibleTextEditors: () => ({ dispose() {} }),
    createTextEditorDecorationType: () => ({ id: ++decorationId }),
    setStatusBarMessage(message) { this.statusMessage = message; },
    async showTextDocument(uri, options = {}) {
      let editor = editors.get(uri.fsPath);
      if (!editor) {
        editor = {
          document: { uri },
          viewColumn: options.viewColumn || 1,
          decorations: new Map(),
          _selections: [],
          get selections() { return this._selections; },
          set selections(values) { this._selections = values; },
          get selection() { return this._selections[0]; },
          set selection(value) { this._selections = [value]; },
          setDecorations(type, values) { this.decorations.set(type, values); },
          revealRange(range) { this.revealed = range; },
        };
        editors.set(uri.fsPath, editor);
      }
      this.visibleTextEditors = [...editors.values()];
      return editor;
    },
  },
};
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "vscode") return vscode;
  return originalLoad.call(this, request, parent, isMain);
};
const { ResultStore, BindingsTree, Highlighter, reveal, formatLocation } = require("../results");
Module._load = originalLoad;

const file = "/workspace/pair.cpp";
const loc = (start, end) => ({ start: { line: 15, character: start },
                                end: { line: 15, character: end } });
const node = (id, kind, start, end) => ({
  id, kind, file, range: loc(start, end), text: "", matches: [],
});
const pair = node("d", "CXXRecordDecl", 0, 37);
const first = node("v", "FieldDecl", 13, 22);
const second = node("v", "FieldDecl", 24, 34);
const duplicateSecond = { ...second };
const root = node("root", "CXXRecordDecl", 0, 37);

function createStore() {
  const bound = { q: 0, m: 0, b: 1 };
  const match = { bindings: [pair, first, second, root] };
  const groups = [
    { id: "d", nodes: [{ b: pair }] },
    { id: "v", nodes: [{ b: first }, { b: second }, { b: duplicateSecond }] },
    { id: "root", nodes: [{ b: root }] },
  ];
  return {
    selected: undefined,
    showRoot: false,
    onDidChange: () => ({ dispose() {} }),
    groups: () => groups,
    binding: (sel) => sel && sel.q === 0 && sel.m === 0 ? match.bindings[sel.b] : undefined,
    match: () => match,
    select(sel) { this.selected = sel; },
    get bound() { return bound; },
  };
}

function spans(editor) {
  return editor.selections.map((s) => [s.start.line, s.start.character, s.end.line, s.end.character]);
}

test("a result row selects and decorates only that exact bound node", async () => {
  editors.clear();
  vscode.window.visibleTextEditors = [];
  const store = createStore();
  await reveal(store, { q: 0, m: 0, b: 1 });
  const editor = editors.get(file);
  assert.deepEqual(spans(editor), [[15, 13, 15, 22]]);
  assert.deepEqual(store.selected, { q: 0, m: 0, b: 1 });

  const highlighter = new Highlighter(store);
  highlighter.paint(editor);
  const painted = [...editor.decorations.values()];
  assert.equal(painted.length, 1);
  assert.deepEqual(painted[0].map((d) => [d.range.start.character, d.range.end.character]), [[13, 22]]);
});

test("a binding group selects every distinct range and a later row resets it", async () => {
  editors.clear();
  vscode.window.visibleTextEditors = [];
  const store = createStore();
  await reveal(store, { id: "v" });
  const editor = editors.get(file);
  assert.deepEqual(spans(editor), [[15, 13, 15, 22], [15, 24, 15, 34]]);
  assert.deepEqual(store.selected, { id: "v" });

  const highlighter = new Highlighter(store);
  highlighter.paint(editor);
  const groupPaint = [...editor.decorations.values()][0];
  assert.deepEqual(groupPaint.map((d) => [d.range.start.character, d.range.end.character]),
                   [[13, 22], [24, 34]]);

  await reveal(store, { q: 0, m: 0, b: 1 });
  assert.deepEqual(spans(editor), [[15, 13, 15, 22]]);
  highlighter.paint(editor);
  assert.deepEqual([...editor.decorations.values()][0]
    .map((d) => [d.range.start.character, d.range.end.character]), [[13, 22]]);
});

test("Explorer group and node items dispatch group and single-node selectors", () => {
  const tree = new BindingsTree(createStore());
  const group = tree.getTreeItem({ type: "bind", group: { id: "v", nodes: [{ b: first }] } });
  assert.deepEqual(group.command.arguments, [{ id: "v" }]);
  const row = tree.getTreeItem({ type: "node", node: {
    b: first, matches: ["1"], sels: [{ q: 0, m: 0, b: 1 }],
  } });
  assert.deepEqual(row.command.arguments, [{ q: 0, m: 0, b: 1 }]);
});

test("Explorer groups bindings under themed source-file parents with scoped selection", () => {
  const store = createStore();
  store.groups = () => [{ id: "v", nodes: [{ b: first, matches: ["1"],
    sels: [{ q: 0, m: 0, b: 1 }] }] }];
  store.result = { sample: file, files: [file, "/workspace/second.cpp"], errors: [] };
  const tree = new BindingsTree(store);
  const files = tree.getChildren();
  assert.deepEqual(files.map((entry) => entry.file), [file]);
  const fileItem = tree.getTreeItem(files[0]);
  assert.equal(fileItem.label, "pair.cpp");
  assert.equal(fileItem.description, file);
  assert.equal(fileItem.iconPath.id, "file");
  assert.equal(fileItem.iconPath.color.id, "symbolIcon-fileForeground");

  const bind = tree.getChildren(files[0]).find((entry) => entry.group.id === "v");
  const bindItem = tree.getTreeItem(bind);
  assert.deepEqual(bindItem.command.arguments, [{ id: "v", file }]);
  const child = tree.getChildren(bind)[0];
  const nodeItem = tree.getTreeItem(child);
  assert.deepEqual(nodeItem.command.arguments, [{ q: 0, m: 0, b: 1, file }]);
  assert.match(nodeItem.description, /16:14$/);
  assert.equal(formatLocation({ range: loc(12, 18) }), "16:13");
  assert.equal(formatLocation({}), "");
});

test("streamed file batches appear before completion with globally correct selectors", () => {
  const store = new ResultStore();
  store.setRunning({ sample: "workspace", scope: "workspace" });
  store.startStreaming({ sample: "/workspace", flags: ["-std=c++23"],
    target: { scope: "workspace", path: "/workspace" }, totalFiles: 2,
    cache: { enabled: true, location: "/tmp/cache" } });
  for (let i = 0; i < 2; i++) {
    const path = `/workspace/${i}.cpp`;
    const b = { id: "v", node: `0x${i + 1}`, kind: "VarDecl", file: path,
      translationUnit: path, range: loc(i, i + 1) };
    store.appendStreamingFile({ kind: "file", file: path, completedFiles: i + 1,
      totalFiles: 2, queries: [{ matcher: "varDecl()", translationUnit: path,
        count: 1, matches: [{ index: 1, bindings: [b] }] }],
      bindings: { v: [{ ...b, matches: [{ query: 0, match: 0, binding: 0, index: 1 }] }] },
      errors: [], stderr: "", cache: { hits: i, misses: 1 - i }, durationMs: i + 1 });
    assert.equal(store.result.files.length, i + 1);
    assert.equal(store.running.completedFiles, i + 1);
  }
  assert.equal(store.groups()[0].nodes.length, 2);
  assert.deepEqual(store.groups()[0].nodes.map((n) => n.sels[0].q), [0, 1]);
  assert.equal(store.binding({ q: 1, m: 0, b: 0 }).file, "/workspace/1.cpp");
  assert.deepEqual([store.result.cache.hits, store.result.cache.misses], [1, 1]);
  assert.equal(new BindingsTree(store).getChildren().length, 2);
});

test("scanned files without matches stay out of the results outline", () => {
  const store = new ResultStore();
  store.setRunning({ sample: "/workspace", scope: "workspace" });
  store.startStreaming({ sample: "/workspace", totalFiles: 2 });
  store.appendStreamingFile({ file: "/workspace/empty.cpp", completedFiles: 1,
    totalFiles: 2, queries: [], bindings: {}, errors: [] });
  assert.equal(store.running.completedFiles, 1);
  assert.deepEqual(new BindingsTree(store).getChildren(), []);

  const b = { id: "v", node: "0x1", kind: "VarDecl", file,
    range: loc(0, 1), matches: [{ query: 0, match: 0, binding: 0, index: 1 }] };
  store.appendStreamingFile({ file, completedFiles: 2, totalFiles: 2,
    queries: [{ matcher: "varDecl()", count: 1, matches: [{ index: 1, bindings: [b] }] }],
    bindings: { v: [b] }, errors: [] });
  assert.equal(store.result.files.length, 2);
  assert.deepEqual(new BindingsTree(store).getChildren().map((entry) => entry.file), [file]);
});

test("a matched translation unit remains listed without a visible binding group", () => {
  const store = createStore();
  store.groups = () => [{ id: "v", nodes: [{ b: first }] }];
  store.result = { sample: file, files: [file, "/workspace/root-only.cpp", "/workspace/empty.cpp"],
    queries: [
      { translationUnit: file, count: 1, matches: [{}] },
      { translationUnit: "/workspace/root-only.cpp", count: 1, matches: [{}] },
      { translationUnit: "/workspace/empty.cpp", count: 0, matches: [] },
    ], errors: [] };
  assert.deepEqual(new BindingsTree(store).getChildren().map((entry) => entry.file),
    [file, "/workspace/root-only.cpp"]);
});

test("run errors never become binding-outline rows", () => {
  const store = createStore();
  store.result = { sample: file, queries: [], errors: [
    { file: "/workspace/broken.cpp", message: "Clang failed to parse the source file" },
  ] };
  store.groups = () => [];
  assert.deepEqual(new BindingsTree(store).getChildren(), []);
});
