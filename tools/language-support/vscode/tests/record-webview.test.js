"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadRecordView() {
  const named = new Map();
  const messages = [];
  let document;
  class Element {
    constructor(tag) {
      this.tagName = tag;
      this.children = [];
      this.parent = undefined;
      this.dataset = {};
      this.attributes = {};
      this.listeners = new Map();
      this.className = "";
      this._text = "";
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text || this.children.map((child) => child.textContent).join(""); }
    append(...children) {
      for (const child of children) { child.parent = this; this.children.push(child); }
    }
    replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
    contains(element) {
      return !!element && (this === element || this.children.some((child) => child.contains(element)));
    }
    find(predicate) {
      if (predicate(this)) return this;
      for (const child of this.children) {
        const match = child.find(predicate);
        if (match) return match;
      }
      return undefined;
    }
    querySelectorAll(selector) {
      const className = selector.slice(1);
      const result = [];
      const walk = (element) => {
        for (const child of element.children) {
          if (child.className.split(/\s+/).includes(className)) result.push(child);
          walk(child);
        }
      };
      walk(this);
      return Object.assign({
        length: result.length,
        forEach(callback) { result.forEach(callback); },
        [Symbol.iterator]() { return result[Symbol.iterator](); },
      }, result);
    }
    closest(selector) {
      const classes = selector.split(",").map((part) => part.trim().slice(1));
      let current = this;
      while (current) {
        if (classes.some((name) => current.className.split(/\s+/).includes(name))) return current;
        current = current.parent;
      }
      return undefined;
    }
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === "class") this.className = String(value);
    }
    addEventListener(name, callback) {
      const listeners = this.listeners.get(name) || [];
      listeners.push(callback);
      this.listeners.set(name, listeners);
    }
    fire(name, event = {}) {
      const value = { target: this, preventDefault() {}, stopPropagation() {}, ...event };
      for (const callback of this.listeners.get(name) || []) callback(value);
    }
    focus() { document.activeElement = this; }
    getBoundingClientRect() { return { width: 1000, height: 600 }; }
    get classList() {
      return { toggle: (name, enabled) => {
        const parts = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled) parts.add(name); else parts.delete(name);
        this.className = [...parts].join(" ");
      } };
    }
  }
  document = {
    activeElement: undefined,
    createElement: (tag) => new Element(tag),
    createElementNS: (_namespace, tag) => new Element(tag),
    getElementById(id) {
      if (named.has(id)) return named.get(id);
      for (const root of named.values()) {
        const child = root.find((entry) => entry.id === id);
        if (child) return child;
      }
      return undefined;
    },
  };
  for (const id of ["graph", "graph-help", "title", "subtitle", "notice", "detail-content",
    "legend", "zoom-in", "zoom-out", "fit"]) {
    const element = new Element(id === "graph" ? "svg" : "div");
    element.id = id;
    named.set(id, element);
  }
  const window = { listeners: new Map(), addEventListener(name, callback) { this.listeners.set(name, callback); } };
  const script = fs.readFileSync(path.join(__dirname, "../media/record.js"), "utf8");
  vm.runInNewContext(script, { document, window,
    acquireVsCodeApi: () => ({ postMessage(message) { messages.push(message); } }) });
  return {
    document,
    messages,
    element: (id) => named.get(id),
    sendGraph(graph, focusId, background = false) {
      window.listeners.get("message")({ data: {
        type: "state", status: "ready", graph, focusId, background } });
    },
    sendExpansionError(message) {
      window.listeners.get("message")({ data: { type: "expansionError", message } });
    },
    cards() { return Array.from(named.get("graph").querySelectorAll(".record-card")); },
    edges() { return Array.from(named.get("graph").querySelectorAll(".relation-edge")); },
  };
}

function fixture() {
  const source = "/project/records.cpp";
  const range = { start: { line: 2, character: 1 }, end: { line: 2, character: 10 } };
  return {
    ok: true, recordId: "root", expandedRecordIds: ["root"], truncated: false,
    nodes: [
      { id: "root", kind: "CXXRecordDecl", recordKind: "class", name: "Root",
        definitionStatus: "defined", file: source, range },
      { id: "base", kind: "CXXRecordDecl", recordKind: "struct", name: "Base",
        definitionStatus: "defined", file: source, range },
      { id: "grand", kind: "CXXRecordDecl", recordKind: "class", name: "Grand",
        definitionStatus: "defined", file: source, range },
      { id: "peer", kind: "CXXRecordDecl", recordKind: "class", name: "Peer",
        definitionStatus: "defined", file: source, range },
      { id: "field", kind: "FieldDecl", name: "next", type: "Peer *", file: source, range },
      { id: "method", kind: "CXXMethodDecl", name: "run", signature: "void run()", file: source, range },
    ],
    edges: [
      { from: "root", to: "base", kind: "inherits", access: "public", virtual: true },
      { from: "base", to: "grand", kind: "inherits", access: "protected" },
      { from: "root", to: "field", kind: "field", access: "private" },
      { from: "root", to: "method", kind: "method", access: "protected" },
      { from: "field", to: "peer", kind: "fieldType" },
    ],
  };
}

function cardIds(view) { return view.cards().map((card) => card.dataset.id); }
function buttonWithText(content, text) {
  return content.find((entry) => entry.tagName === "button" && entry.textContent === text);
}
function filterInput(view, label) {
  const wrapper = view.element("legend").find((entry) =>
    entry.tagName === "label" && entry.textContent === label);
  assert.ok(wrapper, "missing relation filter " + label);
  return wrapper.find((entry) => entry.tagName === "input");
}
function shownEdges(view) { return view.edges().filter((edge) => !edge.className.includes("filtered-out")); }

test("projects raw AST members into bounded UML record cards with source-backed edges", () => {
  const view = loadRecordView();
  view.sendGraph(fixture());
  assert.deepEqual(cardIds(view), ["root", "base", "grand", "peer"]);
  assert.equal(view.cards().length, 4, "the full base chain is visible without changing card types");
  assert.equal(view.edges().length, 3, "only record-to-record relationships are drawn");
  assert.ok(view.element("graph").find((entry) => entry.attributes.id === "generalization"));
  assert.ok(view.element("graph").find((entry) => entry.className === "triangle"));
  const rows = Array.from(view.element("graph").querySelectorAll(".member-row"));
  assert.equal(rows.length, 2);
  assert.match(rows.find((row) => row.dataset.memberId === "field").textContent, /− next: Peer \*/);
  assert.match(rows.find((row) => row.dataset.memberId === "method").textContent, /# void run\(\)/);
  assert.match(view.element("subtitle").textContent, /4 of 4 classes.*Translation unit only/);
  assert.ok(view.element("graph").textContent.includes("Grand"));
  assert.equal(buttonWithText(view.element("detail-content"), "Reveal related classes"), undefined,
    "an already expanded root with all known neighbors visible has no reveal action");
});

test("multiple inheritance cards gain both parents' members without moving the selected view", () => {
  const view = loadRecordView();
  const source = "/project/multiple.cpp";
  const range = { start: { line: 1, character: 1 }, end: { line: 1, character: 8 } };
  const record = (id, name) => ({ id, kind: "CXXRecordDecl", recordKind: "class", name,
    definitionStatus: "defined", file: source, range });
  const graph = { ok: true, recordId: "root", expandedRecordIds: ["root"], truncated: true,
    nodes: [record("root", "Child"), record("left", "Left"), record("right", "Right")],
    edges: [{ from: "root", to: "left", kind: "inherits" },
      { from: "root", to: "right", kind: "inherits" }] };
  view.sendGraph(graph);
  assert.deepEqual(cardIds(view), ["root", "left", "right"]);
  assert.equal(view.edges().length, 2);
  view.element("zoom-in").fire("click");
  const before = view.element("graph").attributes.viewBox;
  for (const [parent, field, method] of [
    ["left", "leftValue", "leftRun"], ["right", "rightValue", "rightRun"],
  ]) {
    graph.nodes.push({ id: field, kind: "FieldDecl", name: field, type: "int", file: source, range },
      { id: method, kind: "CXXMethodDecl", name: method,
        signature: `void ${method}()`, file: source, range });
    graph.edges.push({ from: parent, to: field, kind: "field", access: "public" },
      { from: parent, to: method, kind: "method", access: "public" });
    graph.expandedRecordIds.push(parent);
    view.sendGraph(graph, undefined, true);
    if (parent === "left") {
      assert.ok(view.cards().find((card) => card.dataset.id === "root").className.includes("selected"),
        "loading the first parent keeps the root selected");
      view.cards().find((card) => card.dataset.id === "right").fire("click");
    }
  }
  assert.deepEqual(cardIds(view), ["root", "left", "right"]);
  const rows = Array.from(view.element("graph").querySelectorAll(".member-row"));
  assert.deepEqual(rows.map((row) => row.dataset.memberId),
    ["leftValue", "leftRun", "rightValue", "rightRun"]);
  assert.equal(view.element("graph").attributes.viewBox, before,
    "background member loading retains the user's zoom and pan");
  assert.ok(view.cards().find((card) => card.dataset.id === "right").className.includes("selected"));
  assert.match(view.element("detail-content").textContent, /Attributes1Operations1/);
});

test("edge selection explains its evidence and navigates to the contributing source", () => {
  const view = loadRecordView();
  view.sendGraph(fixture());
  const association = view.edges().find((edge) => edge.className.includes("fieldType"));
  association.fire("click");
  const detail = view.element("detail-content");
  assert.match(detail.textContent, /Field type association/);
  assert.match(detail.textContent, /next: Peer \*/);
  assert.match(detail.textContent, /ownership and cardinality are not inferred/);
  buttonWithText(detail, "Open source").fire("click");
  assert.equal(view.messages.at(-1).id, "field");
  const inheritance = view.edges().find((edge) => edge.className.includes("inherits"));
  inheritance.fire("click");
  assert.match(detail.textContent, /public/);
  assert.match(detail.textContent, /VirtualYes/);
  buttonWithText(detail, "Open source").fire("click");
  assert.equal(view.messages.at(-1).id, "root");
});

test("explicit reveal requests expansion once and retains discoveries after the host merges data", () => {
  const view = loadRecordView();
  const graph = fixture();
  view.sendGraph(graph);
  view.cards().find((card) => card.dataset.id === "base").fire("click");
  const reveal = () => buttonWithText(view.element("detail-content"), "Reveal related classes");
  reveal().fire("click");
  assert.deepEqual(cardIds(view), ["root", "base", "grand", "peer"]);
  assert.deepEqual(view.messages.filter((message) => message.type === "expand")
    .map((message) => ({ type: message.type, id: message.id })),
    [{ type: "expand", id: "base" }]);
  assert.equal(buttonWithText(view.element("detail-content"), "Finding related classes…").disabled, true);
  buttonWithText(view.element("detail-content"), "Finding related classes…").fire("click");
  assert.equal(view.messages.filter((message) => message.type === "expand").length, 1);
  graph.nodes.push({ id: "great", kind: "CXXRecordDecl", recordKind: "class", name: "Great" });
  graph.edges.push({ from: "grand", to: "great", kind: "inherits" });
  graph.expandedRecordIds = ["root", "base"];
  view.sendGraph(graph, "base");
  assert.deepEqual(cardIds(view), ["root", "base", "grand", "peer", "great"]);
  view.cards().find((card) => card.dataset.id === "grand").fire("click");
  reveal().fire("click");
  assert.deepEqual(cardIds(view), ["root", "base", "grand", "peer", "great"]);
  assert.deepEqual(view.messages.filter((message) => message.type === "expand").map((message) => message.id),
    ["base", "grand"]);
});

test("host expansion errors preserve the visible diagram and report the failure", () => {
  const view = loadRecordView();
  view.sendGraph(fixture());
  view.sendExpansionError("Inspection timed out");
  assert.match(view.element("notice").textContent, /Inspection timed out/);
  assert.deepEqual(cardIds(view), ["root", "base", "grand", "peer"]);
});

test("directional filters use the selected class and keep shown cards and keyboard focus", () => {
  const view = loadRecordView();
  view.sendGraph(fixture());
  const bases = filterInput(view, "Bases");
  bases.focus();
  bases.checked = false;
  bases.fire("change");
  assert.equal(shownEdges(view).length, 2);
  assert.equal(view.document.activeElement, bases);
  assert.deepEqual(cardIds(view), ["root", "base", "grand", "peer"]);
  assert.equal(view.edges().find((edge) => edge.className.includes("inherits"))
    .attributes["aria-hidden"], "true");
  view.cards().find((card) => card.dataset.id === "base").fire("click");
  assert.equal(shownEdges(view).length, 2,
    "the base-to-grand edge is filtered, while unrelated visible edges retain context");
  const derived = filterInput(view, "Known derived");
  derived.checked = false;
  derived.fire("change");
  assert.equal(shownEdges(view).length, 1, "reverse inheritance is hidden for the selected base");
  derived.checked = true;
  derived.fire("change");
  assert.equal(shownEdges(view).length, 2);
  const outgoing = filterInput(view, "Field types");
  outgoing.checked = false;
  outgoing.fire("change");
  view.cards().find((card) => card.dataset.id === "root").fire("click");
  assert.equal(shownEdges(view).length, 1, "the ancestor edge stays visible outside root's filters");
  view.cards().find((card) => card.dataset.id === "peer").fire("click");
  assert.equal(shownEdges(view).length, 3, "the same association is known incoming at Peer");
  const incoming = filterInput(view, "Known incoming fields");
  incoming.checked = false;
  incoming.fire("change");
  assert.equal(shownEdges(view).length, 2);
  assert.deepEqual(cardIds(view), ["root", "base", "grand", "peer"]);
});

test("base filtering preserves visible ancestors and self links remain selectable by either direction", () => {
  const view = loadRecordView();
  const graph = fixture();
  graph.nodes.push({ id: "self", kind: "FieldDecl", name: "self" });
  graph.edges.push({ from: "root", to: "self", kind: "field" },
    { from: "self", to: "root", kind: "fieldType" });
  view.sendGraph(graph);
  const bases = filterInput(view, "Bases");
  bases.checked = false;
  bases.fire("change");
  view.cards().find((card) => card.dataset.id === "base").fire("click");
  buttonWithText(view.element("detail-content"), "Reveal related classes").fire("click");
  assert.ok(cardIds(view).includes("grand"), "a known grandparent remains visible");
  const grandEdge = view.edges().find((edge) => edge.attributes["aria-label"].includes("Base inherits Grand"));
  assert.ok(grandEdge.className.includes("filtered-out"), "the disabled base direction hides its edge");
  graph.expandedRecordIds = ["root", "base"];
  view.sendGraph(graph, "base");
  assert.equal(buttonWithText(view.element("detail-content"), "Reveal related classes"), undefined);
  bases.checked = true;
  bases.fire("change");
  assert.ok(!view.edges().find((edge) => edge.attributes["aria-label"].includes("Base inherits Grand"))
    .className.includes("filtered-out"));
  view.cards().find((card) => card.dataset.id === "root").fire("click");
  const selfEdge = view.edges().find((edge) => edge.attributes["aria-label"].includes("Root.self"));
  assert.ok(selfEdge);
  const outgoing = filterInput(view, "Field types");
  const incoming = filterInput(view, "Known incoming fields");
  outgoing.checked = false;
  outgoing.fire("change");
  assert.ok(!selfEdge.className.includes("filtered-out"),
    "a self association remains visible through the incoming direction");
  incoming.checked = false;
  incoming.fire("change");
  assert.ok(selfEdge.className.includes("filtered-out"));
  assert.equal(selfEdge.attributes.tabindex, "-1");
});

test("large member compartments preview four rows, expand, and remain pannable", () => {
  const view = loadRecordView();
  const graph = { ok: true, recordId: "root", expandedRecordIds: ["root"], nodes: [
    { id: "root", kind: "CXXRecordDecl", recordKind: "struct", name: "Wide" },
  ], edges: [] };
  for (let i = 0; i < 80; i++) {
    graph.nodes.push({ id: "f" + i, kind: "FieldDecl", name: "field" + i });
    graph.edges.push({ from: "root", to: "f" + i, kind: "field" });
  }
  view.sendGraph(graph);
  assert.equal(view.cards().length, 1);
  assert.equal(view.element("graph").querySelectorAll(".member-row").length, 4);
  assert.match(view.element("graph").querySelectorAll(".member-more")[0].textContent, /Show 76 more/);
  view.element("graph").querySelectorAll(".member-more")[0].fire("click");
  assert.equal(view.element("graph").querySelectorAll(".member-row").length, 80);
  const after = view.element("graph").attributes.viewBox.split(" ").map(Number);
  assert.ok(Number(view.cards()[0].find((entry) => entry.className === "card-outline")
    .attributes.height) > 1700, "expanded card must contain its added members");
  assert.ok(after[2] <= 800, "expanded members should remain legible at the top of the card");
  view.element("zoom-in").fire("click");
  const zoomed = view.element("graph").attributes.viewBox.split(" ").map(Number);
  assert.ok(zoomed[2] < after[2]);
  const svg = view.element("graph");
  svg.fire("keydown", { target: svg, key: "ArrowRight" });
  const panned = svg.attributes.viewBox.split(" ").map(Number);
  assert.ok(panned[0] > zoomed[0]);
});

test("compartment Enter and Space preserve focus on the rebuilt toggle", () => {
  const view = loadRecordView();
  view.sendGraph(fixture());
  assert.equal(typeof view.element("graph").querySelectorAll(".compartment-toggle").find, "undefined",
    "the mock must expose browser NodeList behavior");
  const controls = () => Array.from(view.element("graph").querySelectorAll(".compartment-toggle"))
    .filter((entry) => entry.dataset.ownerId === "root" && entry.dataset.kind === "field");
  const original = controls()[0];
  original.focus();
  original.fire("keydown", { key: "Enter" });
  assert.equal(view.element("graph").querySelectorAll(".member-row").length, 1);
  assert.notEqual(view.document.activeElement, original, "redraw replaces the focused SVG node");
  assert.equal(view.document.activeElement, controls()[0]);
  assert.match(view.document.activeElement.attributes["aria-label"], /Show fields/);
  view.document.activeElement.fire("keydown", { key: " " });
  assert.equal(view.element("graph").querySelectorAll(".member-row").length, 2);
  assert.equal(view.document.activeElement, controls()[0]);
  assert.match(view.document.activeElement.attributes["aria-label"], /Hide fields/);
});

test("Show more with Space moves focus to the first newly visible member", () => {
  const view = loadRecordView();
  const graph = { ok: true, recordId: "root", expandedRecordIds: ["root"], nodes: [
    { id: "root", kind: "CXXRecordDecl", recordKind: "class", name: "Wide" },
  ], edges: [] };
  for (let i = 0; i < 8; i++) {
    graph.nodes.push({ id: "f" + i, kind: "FieldDecl", name: "field" + i });
    graph.edges.push({ from: "root", to: "f" + i, kind: "field" });
  }
  view.sendGraph(graph);
  const more = view.element("graph").querySelectorAll(".member-more")[0];
  more.focus();
  more.fire("keydown", { key: " " });
  assert.equal(view.element("graph").querySelectorAll(".member-row").length, 8);
  assert.equal(view.document.activeElement.dataset.memberId, "f4");
  assert.ok(view.element("graph").contains(view.document.activeElement),
    "focus must remain in the live diagram");
});

test("member and relation keyboard controls show details and keep focus", () => {
  const view = loadRecordView();
  view.sendGraph(fixture());
  const member = Array.from(view.element("graph").querySelectorAll(".member-row"))
    .find((row) => row.dataset.memberId === "field");
  member.fire("keydown", { key: "Enter" });
  assert.match(view.element("detail-content").textContent, /next.*private/);
  member.fire("keydown", { key: "Enter", shiftKey: true });
  assert.equal(view.messages.at(-1).id, "field");
  const relation = buttonWithText(view.element("detail-content"), "Focus class in graph");
  assert.ok(relation);
  view.cards().find((card) => card.dataset.id === "base").fire("click");
  const link = view.element("detail-content").find((entry) =>
    entry.className === "relation" && entry.textContent === "Derived: Root");
  link.focus();
  link.fire("click");
  assert.equal(view.document.activeElement.tagName, "h3");
  assert.equal(view.document.activeElement.textContent, "Root");
});

test("unresolved classes keep an explicit translation-unit status", () => {
  const view = loadRecordView();
  const graph = fixture();
  graph.nodes.find((node) => node.id === "base").definitionStatus = "unresolved";
  view.sendGraph(graph);
  const card = view.cards().find((entry) => entry.dataset.id === "base");
  assert.ok(card.className.includes("unresolved"));
  assert.match(card.attributes["aria-label"], /definition unavailable/);
  card.fire("click");
  assert.match(view.element("detail-content").textContent, /Unavailable in this translation unit/);
  assert.ok(cardIds(view).includes("grand"), "already known ancestors remain visible");
  assert.equal(buttonWithText(view.element("detail-content"), "Reveal related classes"), undefined);
  assert.equal(view.messages.filter((message) => message.type === "expand").length, 0,
    "an unresolved definition cannot be expanded through the host");
});

test("untrusted record and member names stay text in the diagram and details", () => {
  const view = loadRecordView();
  const graph = fixture();
  graph.nodes.find((node) => node.id === "root").name = "<script>alert(1)</script>";
  graph.nodes.find((node) => node.id === "field").name = "<img src=x>";
  view.sendGraph(graph);
  assert.match(view.element("graph").textContent, /<script>/);
  assert.match(view.element("detail-content").textContent, /<script>/);
  assert.equal(view.element("graph").find((entry) => entry.tagName === "script"), undefined);
  assert.equal(view.element("graph").find((entry) => entry.tagName === "img"), undefined);
});
