"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadMatchesView() {
  const elements = new Map();
  const listeners = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        addEventListener() {}, focus() {}, hidden: false, textContent: "", innerHTML: "",
      });
      return elements.get(id);
    },
    querySelectorAll() { return []; },
  };
  const window = { addEventListener(name, callback) { listeners.set(name, callback); } };
  const script = fs.readFileSync(path.join(__dirname, "../media/matches.js"), "utf8");
  vm.runInNewContext(script, { document, window,
    acquireVsCodeApi: () => ({ postMessage() {} }) });
  return {
    element: (id) => elements.get(id),
    send(state) { listeners.get("message")({ data: state }); },
  };
}

test("a transitive header match renders only the bound header, while scan progress counts its translation unit", () => {
  const view = loadMatchesView();
  const header = "/workspace/include/deep.hpp";
  const translationUnit = "/workspace/main.cpp";
  const binding = { kind: "CXXRecordDecl", file: header,
    range: { start: { line: 2, character: 0 }, end: { line: 2, character: 10 } } };
  const groups = [{ id: "record", nodes: [{ b: binding, detail: "class Deep",
    sels: [{ q: 0, m: 0, b: 0 }], matches: ["1"] }] }];
  const result = { sample: translationUnit, files: [translationUnit],
    queries: [{ translationUnit, count: 1, matches: [{}] }],
    cache: { enabled: false }, flags: ["-std=c++23"], durationMs: 5 };
  view.send({ type: "state", result, groups, running: false, generation: 1 });

  const rows = view.element("rows").innerHTML;
  assert.equal((rows.match(/class="file-group"/g) || []).length, 1);
  assert.match(rows, /deep\.hpp/);
  assert.match(rows, /class Deep/);
  assert.match(rows, /1 node/);
  assert.doesNotMatch(rows, /main\.cpp/);
  assert.match(view.element("summary").innerHTML, /<b>1<\/b> match/);

  view.send({ type: "state", result, groups, generation: 1,
    running: { completedFiles: 1, totalFiles: 1, sample: translationUnit, cancellable: true } });
  assert.match(view.element("summary").textContent, /1\/1 files scanned/);
  assert.deepEqual(result.files, [translationUnit]);
});
