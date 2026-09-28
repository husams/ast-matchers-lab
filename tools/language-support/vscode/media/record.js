// Record Explorer webview. All graph labels are inserted as text, never HTML.
(function () {
  "use strict";
  const vscode = acquireVsCodeApi();
  const ns = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);
  const svg = $("graph");
  let graph;
  let selectedId;
  let positions = new Map();
  let bounds = { x: -400, y: -300, w: 800, h: 600 };
  let view = { ...bounds };
  let maxViewWidth = 16000;
  let dragging;

  function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }

  function svgEl(tag, attributes = {}) {
    const element = document.createElementNS(ns, tag);
    for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
    return element;
  }

  function nameOf(node) {
    return node.qualifiedName || node.name || node.kind || "Unnamed entity";
  }

  function labelOf(node) {
    const value = nameOf(node);
    return value.length > 29 ? `${value.slice(0, 28)}…` : value;
  }

  function typeOf(node) {
    return node.recordKind || node.kind || "entity";
  }

  function setNotice(message, kind) {
    const notice = $("notice");
    notice.textContent = message;
    notice.className = kind || "";
    notice.hidden = !message;
  }

  function addDetail(label, value) {
    if (value === undefined || value === null || value === "") return;
    const dl = $("detail-list");
    dl.append(el("dt", "", label), el("dd", "", value));
  }

  function relatedEdges(node) {
    return graph.edges.filter((edge) => edge.from === node.id || edge.to === node.id);
  }

  function selectNode(id, focus) {
    const node = graph.nodes.find((entry) => entry.id === id);
    if (!node) return;
    selectedId = id;
    for (const entity of svg.querySelectorAll(".entity")) {
      entity.classList.toggle("selected", entity.dataset.id === id);
    }
    const content = $("detail-content");
    const restoreFocus = content.contains(document.activeElement);
    content.replaceChildren();
    const heading = el("h3", "", nameOf(node));
    heading.tabIndex = -1;
    content.append(heading);
    const dl = el("dl");
    dl.id = "detail-list";
    content.append(dl);
    addDetail("Kind", typeOf(node));
    addDetail("Signature", node.signature);
    addDetail("Type", node.type);
    if (node.definitionStatus === "unresolved") {
      addDetail("Definition", "Unavailable in this translation unit");
    }
    addDetail("Location", node.file && node.range
      ? `${node.file}:${node.range.start.line + 1}:${node.range.start.character + 1}`
      : node.file || "");
    if (node.file || node.uri) {
      const open = el("button", "primary", "Open source");
      open.type = "button";
      open.addEventListener("click", () => vscode.postMessage({ type: "navigate", id }));
      content.append(open);
    } else content.append(el("p", "muted", "No source location is available for this entity."));
    const focusButton = el("button", "secondary", "Focus in graph");
    focusButton.type = "button";
    focusButton.addEventListener("click", () => focusNode(id));
    content.append(focusButton);
    const relations = relatedEdges(node);
    if (relations.length) {
      content.append(el("h4", "", "Relationships"));
      const list = el("ul", "relations");
      for (const edge of relations) {
        const other = graph.nodes.find((entry) => entry.id === (edge.from === id ? edge.to : edge.from));
        if (!other) continue;
        const direction = edge.from === id ? "to" : "from";
        const item = el("li");
        const button = el("button", "relation", `${edge.kind} ${direction} ${nameOf(other)}`);
        button.type = "button";
        button.addEventListener("click", () => selectNode(other.id, true));
        item.append(button);
        list.append(item);
      }
      content.append(list);
    }
    if (focus) focusNode(id);
    if (restoreFocus) heading.focus();
  }

  function assignLevels(rootId) {
    const levels = new Map([[rootId, 0]]);
    const queue = [rootId];
    while (queue.length) {
      const from = queue.shift();
      for (const edge of graph.edges) {
        if (edge.from !== from || edge.kind !== "inherits" || levels.has(edge.to)) continue;
        levels.set(edge.to, Math.max(-5, levels.get(from) - 1));
        queue.push(edge.to);
      }
    }
    for (const kind of ["field", "method", "fieldType"]) {
      let changed = true;
      while (changed) {
        changed = false;
        for (const edge of graph.edges) {
          if (edge.kind !== kind || !levels.has(edge.from) || levels.has(edge.to)) continue;
          levels.set(edge.to, levels.get(edge.from) + 1);
          changed = true;
        }
      }
    }
    for (const node of graph.nodes) if (!levels.has(node.id)) levels.set(node.id, 2);
    return levels;
  }

  function layout() {
    positions = new Map();
    const rootId = graph.recordId || graph.nodes[0].id;
    const levels = assignLevels(rootId);
    const rows = new Map();
    for (const node of graph.nodes) {
      const level = levels.get(node.id);
      if (!rows.has(level)) rows.set(level, []);
      rows.get(level).push(node);
    }
    const width = svg.getBoundingClientRect().width || 800;
    const columns = width < 700 ? 3 : width < 1200 ? 4 : 5;
    let row = 0;
    for (const level of [...rows.keys()].sort((a, b) => a - b)) {
      const nodes = rows.get(level);
      for (let start = 0; start < nodes.length; start += columns) {
        const chunk = nodes.slice(start, start + columns);
        chunk.forEach((node, index) => {
          positions.set(node.id, { x: (index - (chunk.length - 1) / 2) * 260, y: row * 170 });
        });
        row++;
      }
    }
    const rootY = positions.get(rootId)?.y || 0;
    for (const point of positions.values()) point.y -= rootY;
    const all = [...positions.values()];
    const minX = Math.min(...all.map((p) => p.x)) - 155;
    const maxX = Math.max(...all.map((p) => p.x)) + 155;
    const minY = Math.min(...all.map((p) => p.y)) - 110;
    const maxY = Math.max(...all.map((p) => p.y)) + 110;
    bounds = { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  }

  function edgePath(from, to) {
    const startY = from.y < to.y ? from.y + 34 : from.y - 34;
    const endY = from.y < to.y ? to.y - 44 : to.y + 44;
    const midY = (startY + endY) / 2;
    return `M ${from.x} ${startY} C ${from.x} ${midY}, ${to.x} ${midY}, ${to.x} ${endY}`;
  }

  function renderGraph() {
    svg.replaceChildren();
    const defs = svgEl("defs");
    const marker = svgEl("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5,
      markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    marker.append(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z" }));
    defs.append(marker);
    svg.append(defs);
    const edges = svgEl("g", { class: "edges" });
    for (const edge of graph.edges) {
      const from = positions.get(edge.from);
      const to = positions.get(edge.to);
      if (!from || !to) continue;
      const path = svgEl("path", { d: edgePath(from, to), class: `edge ${edge.kind}`,
        "marker-end": "url(#arrow)" });
      const title = svgEl("title");
      title.textContent = `${edge.kind}${edge.access ? ` (${edge.access})` : ""}`;
      path.append(title);
      edges.append(path);
    }
    svg.append(edges);
    const nodes = svgEl("g", { class: "entities" });
    for (const node of graph.nodes) {
      const p = positions.get(node.id);
      if (!p) continue;
      const entity = svgEl("g", { class: `entity ${node.id === graph.recordId ? "root" : ""} ${node.definitionStatus === "unresolved" ? "unresolved" : ""}`,
        transform: `translate(${p.x} ${p.y})`, role: "button", tabindex: 0,
        "aria-label": `${typeOf(node)} ${nameOf(node)}${node.definitionStatus === "unresolved" ? ", definition unavailable in this translation unit" : ""}. Select for details; double-click to open source.` });
      entity.dataset.id = node.id;
      entity.append(svgEl("rect", { x: -104, y: -36, width: 208, height: 72, rx: 5 }));
      const kind = svgEl("text", { x: 0, y: node.definitionStatus === "unresolved" ? -15 : -9,
        class: "kind", "text-anchor": "middle" });
      kind.textContent = typeOf(node);
      entity.append(kind);
      const label = svgEl("text", { x: 0, y: node.definitionStatus === "unresolved" ? 6 : 16,
        class: "name", "text-anchor": "middle" });
      label.textContent = labelOf(node);
      entity.append(label);
      if (node.definitionStatus === "unresolved") {
        const status = svgEl("text", { x: 0, y: 27, class: "status", "text-anchor": "middle" });
        status.textContent = "Unresolved";
        entity.append(status);
      }
      entity.addEventListener("click", () => selectNode(node.id, false));
      entity.addEventListener("dblclick", () => vscode.postMessage({ type: "navigate", id: node.id }));
      entity.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (event.shiftKey) vscode.postMessage({ type: "navigate", id: node.id });
          else selectNode(node.id, false);
        }
      });
      nodes.append(entity);
    }
    svg.append(nodes);
    fit();
  }

  function setView() {
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  }

  function fit() {
    const box = svg.getBoundingClientRect();
    const ratio = (box.width || 800) / (box.height || 600);
    const w = Math.max(bounds.w, bounds.h * ratio);
    const h = w / ratio;
    maxViewWidth = Math.max(16000, w * 8);
    view = { x: bounds.x + bounds.w / 2 - w / 2,
      y: bounds.y + bounds.h / 2 - h / 2, w, h };
    setView();
    $("graph-help").textContent = "Overview of all entities. Click one for details, or zoom and pan to inspect a region.";
  }

  function initialFocus(rootId) {
    if (graph.nodes.length <= 24) return;
    const root = positions.get(rootId);
    if (!root) return;
    const box = svg.getBoundingClientRect();
    const screenWidth = box.width || 800;
    const ratio = screenWidth / (box.height || 600);
    const w = screenWidth < 700 ? 760 : screenWidth < 1200 ? 1000 : 1250;
    const h = w / ratio;
    view = { x: root.x - w / 2, y: root.y - h * 0.24, w, h };
    setView();
    $("graph-help").textContent = "Focused on the selected record and nearby members. Use Fit for the full overview; zoom and pan to inspect more.";
  }

  function zoom(factor) {
    const w = Math.max(140, Math.min(maxViewWidth, view.w * factor));
    const h = view.h * w / view.w;
    view.x += (view.w - w) / 2;
    view.y += (view.h - h) / 2;
    view.w = w;
    view.h = h;
    setView();
  }

  function focusNode(id) {
    const p = positions.get(id);
    if (!p) return;
    const ratio = view.w / view.h;
    const w = Math.min(view.w, 760);
    const h = w / ratio;
    view = { x: p.x - w / 2, y: p.y - h / 2, w, h };
    setView();
  }

  function render(message) {
    if (message.status === "loading") {
      setNotice("Inspecting the selected record…", "loading");
      return;
    }
    graph = message.graph;
    if (message.status === "error" || !graph?.ok) {
      const diagnostics = (graph?.diagnostics || []).map((entry) => entry.message).filter(Boolean);
      setNotice(diagnostics.join(" · ") || message.message || "The record could not be inspected.", "error");
      svg.replaceChildren();
      $("detail-content").textContent = "Choose another record or inspect the compiler diagnostics.";
      return;
    }
    graph.nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    graph.edges = Array.isArray(graph.edges) ? graph.edges : [];
    if (!graph.nodes.length) {
      setNotice("No record relationships were found in this translation unit.", "empty");
      svg.replaceChildren();
      $("detail-content").textContent = "The selected record has no available entities.";
      return;
    }
    const root = graph.nodes.find((node) => node.id === graph.recordId) || graph.nodes[0];
    $("title").textContent = nameOf(root);
    $("subtitle").textContent = `${graph.nodes.length} entities · ${graph.edges.length} relationships`;
    setNotice(graph.truncated ? "Graph limit reached; some relationships are omitted." : "",
      graph.truncated ? "warning" : "");
    layout();
    renderGraph();
    initialFocus(root.id);
    selectNode(root.id, false);
  }

  $("zoom-in").addEventListener("click", () => zoom(0.8));
  $("zoom-out").addEventListener("click", () => zoom(1.25));
  $("fit").addEventListener("click", fit);
  svg.addEventListener("wheel", (event) => {
    if (!graph?.nodes?.length) return;
    event.preventDefault();
    zoom(event.deltaY < 0 ? 0.9 : 1.1);
  }, { passive: false });
  svg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".entity")) return;
    dragging = { x: event.clientX, y: event.clientY };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const width = svg.getBoundingClientRect().width || 1;
    const factor = view.w / width;
    view.x -= (event.clientX - dragging.x) * factor;
    view.y -= (event.clientY - dragging.y) * factor;
    dragging = { x: event.clientX, y: event.clientY };
    setView();
  });
  svg.addEventListener("pointerup", () => { dragging = undefined; });
  svg.addEventListener("pointercancel", () => { dragging = undefined; });
  svg.addEventListener("keydown", (event) => {
    if (event.target !== svg) return;
    const amount = view.w * 0.1;
    if (event.key === "+" || event.key === "=") zoom(0.8);
    else if (event.key === "-" || event.key === "_") zoom(1.25);
    else if (event.key === "0") fit();
    else if (event.key === "ArrowLeft") { view.x -= amount; setView(); }
    else if (event.key === "ArrowRight") { view.x += amount; setView(); }
    else if (event.key === "ArrowUp") { view.y -= amount; setView(); }
    else if (event.key === "ArrowDown") { view.y += amount; setView(); }
    else return;
    event.preventDefault();
  });
  window.addEventListener("message", (event) => {
    if (event.data?.type === "state") render(event.data);
  });
  vscode.postMessage({ type: "ready" });
})();
