"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadMatchesView() {
  const elements = new Map();
  const posted = [];
  const listeners = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      hidden: false,
      textContent: "",
      innerHTML: "",
      checked: false,
      value: "",
      listeners: new Map(),
      addEventListener(name, callback) { this.listeners.set(name, callback); },
      fire(name) { this.listeners.get(name)?.(); },
      focus() {},
    });
    return elements.get(id);
  };
  const document = {
    getElementById: element,
    querySelectorAll: () => [],
  };
  const window = { addEventListener(name, callback) { listeners.set(name, callback); } };
  const script = fs.readFileSync(path.join(__dirname, "../media/matches.js"), "utf8");
  vm.runInNewContext(script, { document, window,
    acquireVsCodeApi: () => ({ postMessage(message) { posted.push(message); } }) });
  return { element, posted, send(data) { listeners.get("message")({ data }); } };
}

function result(file, scope = "file") {
  return { ok: true, sample: file, target: { scope }, flags: [], durationMs: 1,
    queries: [{ count: 1, translationUnit: file, matches: [{}] }], bindings: {} };
}

function group(file) {
  return { id: "v", nodes: [{
    b: { file, kind: "VarDecl", summary: "value", text: "int value;",
      range: { start: { line: 2, character: 4 }, end: { line: 2, character: 9 } } },
    matches: ["1"], sels: [{ q: 0, m: 0, b: 0 }],
  }] };
}

test("webview keeps run errors visible and clears them on the next run", () => {
  const view = loadMatchesView();
  assert.equal(view.posted[0].type, "ready");
  view.send({ type: "state", running: false, result: undefined, groups: [],
    failure: { message: "The selected run target was not found.", action: "select-target" } });
  assert.equal(view.element("run-error").hidden, false);
  assert.equal(view.element("run-error-message").textContent, "The selected run target was not found.");
  assert.equal(view.element("run-error-action").textContent, "Select run target");
  assert.equal(view.element("table").hidden, true);
  assert.equal(view.element("no-results").hidden, true);
  view.element("run-error-action").fire("click");
  assert.equal(view.posted.at(-1).action, "select-target");

  view.send({ type: "state", running: { sample: "sample.cpp", cancellable: true },
    result: undefined, groups: [], failure: undefined });
  assert.equal(view.element("run-error").hidden, true);
  assert.equal(view.element("cancel-query").hidden, false);
  view.send({ type: "state", running: false, result: result("/workspace/sample.cpp"),
    groups: [group("/workspace/sample.cpp")], failure: undefined });
  assert.equal(view.element("run-error").hidden, true);
  assert.equal(view.element("table").hidden, false);
});

test("default file results use Summary and Source without a redundant file row", () => {
  const view = loadMatchesView();
  const file = "/workspace/sample.cpp";
  view.send({ type: "state", running: false, result: result(file), groups: [group(file)] });
  const head = view.element("head").innerHTML;
  assert.match(head, /Summary/);
  assert.match(head, /Source/);
  assert.doesNotMatch(head, />Entity</);
  assert.doesNotMatch(view.element("rows").innerHTML, /class="file-group"/);
  assert.match(view.element("rows").innerHTML, /class="binding"/);

  const multi = result(file, "directory");
  multi.queries.push({ count: 1, translationUnit: "/workspace/other.cpp", matches: [{}] });
  view.send({ type: "state", running: false, result: multi,
    groups: [group(file), group("/workspace/other.cpp")] });
  assert.equal((view.element("rows").innerHTML.match(/class="file-group"/g) || []).length, 2);
  const columns = require("../package.json").contributes.configuration.properties["astmatcher.visibleColumns"];
  assert.deepEqual(columns.default, ["match", "kind", "summary", "text", "location"]);
  assert.ok(columns.items.enum.includes("detail"), "Entity remains selectable in Settings");
});
