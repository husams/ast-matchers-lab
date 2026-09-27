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
const { BindingsTree, Highlighter, reveal } = require("../results");
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
