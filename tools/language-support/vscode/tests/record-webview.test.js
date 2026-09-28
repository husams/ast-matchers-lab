"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadRecordView() {
  const named = new Map();
  const document = {
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
  class Element {
    constructor(tag) {
      this.tagName = tag;
      this.children = [];
      this.dataset = {};
      this.attributes = {};
      this.listeners = new Map();
      this.className = "";
      this.textContent = "";
    }
    append(...children) {
      for (const child of children) { child.parent = this; this.children.push(child); }
    }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    contains(element) { return !!element && (this === element || this.children.some((c) => c.contains(element))); }
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
      return result;
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
      for (const callback of this.listeners.get(name) || []) callback(event);
    }
    focus() { document.activeElement = this; }
    getBoundingClientRect() { return { width: 1000, height: 600 }; }
    get classList() { return { toggle: (name, enabled) => {
      const parts = new Set(this.className.split(/\s+/).filter(Boolean));
      if (enabled) parts.add(name); else parts.delete(name);
      this.className = [...parts].join(" ");
    } }; }
  }
  for (const id of ["graph", "graph-help", "title", "subtitle", "notice", "detail-content", "zoom-in", "zoom-out", "fit"]) {
    const element = new Element(id === "graph" ? "svg" : "div");
    element.id = id;
    named.set(id, element);
  }
  const window = { listeners: new Map(), addEventListener(name, callback) { this.listeners.set(name, callback); } };
  const script = fs.readFileSync(path.join(__dirname, "../media/record.js"), "utf8");
  vm.runInNewContext(script, { document, window, acquireVsCodeApi: () => ({ postMessage() {} }) });
  return {
    document,
    sendGraph(graph) { window.listeners.get("message")({ data: { type: "state", status: "ready", graph } }); },
    element: (id) => named.get(id),
  };
}

test("zooming out never shrinks a graph wider than the old fixed limit", () => {
  const view = loadRecordView();
  const nodes = [{ id: "root", kind: "CXXRecordDecl", name: "Root" }];
  for (let i = 0; i < 420; i++) nodes.push({ id: `n${i}`, kind: "CXXRecordDecl", name: `Record${i}` });
  view.sendGraph({ ok: true, recordId: "root", nodes, edges: [], truncated: false });
  const svg = view.element("graph");
  view.element("fit").fire("click");
  const fittedWidth = Number(svg.attributes.viewBox.split(" ")[2]);
  assert.ok(fittedWidth > 16000);
  view.element("zoom-out").fire("click");
  const zoomedWidth = Number(svg.attributes.viewBox.split(" ")[2]);
  assert.ok(zoomedWidth > fittedWidth, "zoom out must enlarge the visible width");
});

test("an 80-field record wraps members and opens on legible nearby context", () => {
  const view = loadRecordView();
  const nodes = [{ id: "root", kind: "CXXRecordDecl", name: "Root" }];
  const edges = [];
  for (let i = 0; i < 80; i++) {
    nodes.push({ id: `f${i}`, kind: "FieldDecl", name: `field${i}` });
    edges.push({ from: "root", to: `f${i}`, kind: "field" });
  }
  view.sendGraph({ ok: true, recordId: "root", nodes, edges, truncated: false });
  const svg = view.element("graph");
  const entities = svg.querySelectorAll(".entity");
  const rows = new Map();
  for (const entity of entities.slice(1)) {
    const [, x, y] = /translate\(([-\d.]+) ([-\d.]+)\)/.exec(entity.attributes.transform);
    const row = rows.get(y) || [];
    row.push(Number(x));
    rows.set(y, row);
  }
  assert.ok(rows.size >= 16, "wide sibling levels should occupy several rows");
  assert.ok([...rows.values()].every((points) => Math.max(...points) - Math.min(...points) <= 780),
    "each row should stay within four columns at this viewport width");
  const initial = svg.attributes.viewBox.split(" ").map(Number);
  assert.ok(initial[2] <= 1100, "the initial world width should keep labels legible");
  assert.match(view.element("graph-help").textContent, /Focused/);
  view.element("fit").fire("click");
  const overview = svg.attributes.viewBox.split(" ").map(Number);
  assert.ok(overview[2] > initial[2], "Fit should show the whole graph");
  view.element("zoom-in").fire("click");
  const zoomed = svg.attributes.viewBox.split(" ").map(Number);
  assert.ok(zoomed[2] < overview[2]);
  svg.fire("keydown", { target: svg, key: "ArrowRight", preventDefault() {} });
  const panned = svg.attributes.viewBox.split(" ").map(Number);
  assert.ok(panned[0] > zoomed[0], "keyboard pan should move the viewport");
});

test("a small record graph still opens fitted as one coherent view", () => {
  const view = loadRecordView();
  const nodes = [{ id: "root", kind: "CXXRecordDecl", name: "Widget" }];
  const edges = [];
  for (let i = 0; i < 7; i++) {
    nodes.push({ id: `m${i}`, kind: i < 2 ? "CXXRecordDecl" : "FieldDecl", name: `Member${i}` });
    edges.push({ from: "root", to: `m${i}`, kind: i < 2 ? "inherits" : "field" });
  }
  view.sendGraph({ ok: true, recordId: "root", nodes, edges, truncated: false });
  const svg = view.element("graph");
  const initial = svg.attributes.viewBox;
  view.element("fit").fire("click");
  assert.equal(svg.attributes.viewBox, initial);
  assert.match(view.element("graph-help").textContent, /Overview/);
});

test("keyboard activation of a relationship keeps focus in the new details", () => {
  const view = loadRecordView();
  view.sendGraph({ ok: true, recordId: "root", nodes: [
    { id: "root", kind: "CXXRecordDecl", name: "Root" },
    { id: "base", kind: "CXXRecordDecl", name: "Base" },
  ], edges: [{ from: "root", to: "base", kind: "inherits" }], truncated: false });
  const content = view.element("detail-content");
  const relation = content.find((entry) => entry.className === "relation");
  assert.ok(relation);
  relation.focus();
  relation.fire("click");
  assert.equal(view.document.activeElement.tagName, "h3");
  assert.equal(view.document.activeElement.textContent, "Base");
});

test("unresolved record definitions are labeled in the graph and details", () => {
  const view = loadRecordView();
  view.sendGraph({ ok: true, recordId: "root", nodes: [
    { id: "root", kind: "CXXRecordDecl", name: "Root", definitionStatus: "defined" },
    { id: "base", kind: "CXXRecordDecl", name: "ForwardBase", definitionStatus: "unresolved" },
  ], edges: [{ from: "root", to: "base", kind: "inherits" }], truncated: false });
  const entity = view.element("graph").querySelectorAll(".entity").find((node) => node.dataset.id === "base");
  assert.ok(entity.className.includes("unresolved"));
  assert.equal(entity.find((node) => node.className === "status").textContent, "Unresolved");
  assert.match(entity.attributes["aria-label"], /definition unavailable/);
  const relation = view.element("detail-content").find((node) => node.className === "relation");
  relation.fire("click");
  const definition = view.element("detail-content").find((node) =>
    node.tagName === "dd" && node.textContent === "Unavailable in this translation unit");
  assert.ok(definition);
});
