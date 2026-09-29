// Record Explorer webview. Source-derived names are always inserted as text.
(function () {
  "use strict";
  const vscode = acquireVsCodeApi();
  const ns = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);
  const svg = $("graph");
  const cardWidth = 264;
  const rowHeight = 22;
  let graph;
  let model;
  let rootId;
  let directionFocusId;
  let selected;
  let positions = new Map();
  let revealed = new Set();
  let pending = new Set();
  let compartments = new Map();
  let filters = { bases: true, derived: true, outgoingFields: true, incomingFields: true };
  let bounds = { x: -400, y: -300, w: 800, h: 600 };
  let view = { ...bounds };
  let maxViewWidth = 16000;
  let dragging;

  function el(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
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

  function short(value, limit) {
    const text = String(value || "");
    return text.length > limit ? text.slice(0, limit - 1) + "…" : text;
  }

  function isRecord(node) {
    return !!node && (!!node.recordKind || /RecordDecl$/.test(node.kind || ""));
  }

  function visibility(access) {
    return { public: "+", protected: "#", private: "−" }[access] || "";
  }

  function locationOf(node) {
    if (!node) return "";
    return node.file && node.range
      ? node.file + ":" + (node.range.start.line + 1) + ":" + (node.range.start.character + 1)
      : node.file || "";
  }

  function canInspect(node) {
    const start = node?.range?.start;
    const end = node?.range?.end;
    return node?.definitionStatus === "defined" && typeof node.file === "string" &&
      node.file.startsWith("/") && Number.isInteger(start?.line) &&
      Number.isInteger(start?.character) && Number.isInteger(end?.line) &&
      Number.isInteger(end?.character);
  }

  function setNotice(message, kind) {
    const notice = $("notice");
    notice.textContent = message;
    notice.className = kind || "";
    notice.hidden = !message;
  }

  function project(raw) {
    const nodes = Array.isArray(raw.nodes) ? raw.nodes : [];
    const edges = Array.isArray(raw.edges) ? raw.edges : [];
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const records = nodes.filter(isRecord);
    const members = new Map(records.map((node) => [node.id, { field: [], method: [] }]));
    const ownerOf = new Map();
    for (const edge of edges) {
      if ((edge.kind === "field" || edge.kind === "method") &&
          members.has(edge.from) && byId.has(edge.to)) {
        members.get(edge.from)[edge.kind].push({ node: byId.get(edge.to), edge });
        ownerOf.set(edge.to, edge.from);
      }
    }
    const relations = [];
    edges.forEach((edge, index) => {
      if (edge.kind === "inherits" && members.has(edge.from) && members.has(edge.to)) {
        relations.push({ key: "inherits:" + index, kind: "inherits", from: edge.from,
          to: edge.to, evidenceId: edge.from, edge });
      } else if (edge.kind === "fieldType" && ownerOf.has(edge.from) && members.has(edge.to)) {
        relations.push({ key: "fieldType:" + index, kind: "fieldType",
          from: ownerOf.get(edge.from), to: edge.to, memberId: edge.from,
          evidenceId: edge.from, edge });
      }
    });
    const around = new Map(records.map((node) => [node.id, []]));
    for (const relation of relations) {
      around.get(relation.from).push(relation);
      if (relation.to !== relation.from) around.get(relation.to).push(relation);
    }
    return { byId, records, members, ownerOf, relations, around };
  }

  function neighbors(id) {
    const result = new Set([id]);
    for (const relation of model.around.get(id) || []) {
      if (!relationAllowed(relation, id)) continue;
      result.add(relation.from);
      result.add(relation.to);
    }
    return result;
  }

  function relationAllowed(relation, id) {
    if (relation.kind === "inherits") {
      if (relation.from === id && relation.to === id) return filters.bases || filters.derived;
      return relation.from === id ? filters.bases : filters.derived;
    }
    if (relation.from === id && relation.to === id) {
      return filters.outgoingFields || filters.incomingFields;
    }
    return relation.from === id ? filters.outgoingFields : filters.incomingFields;
  }

  function revealNeighborhood(id) {
    for (const related of neighbors(id)) revealed.add(related);
  }

  function revealBaseChain(id) {
    const seen = new Set();
    const pendingBases = [id];
    while (pendingBases.length) {
      const current = pendingBases.pop();
      if (seen.has(current)) continue;
      seen.add(current);
      revealed.add(current);
      for (const relation of model.around.get(current) || []) {
        if (relation.kind === "inherits" && relation.from === current) {
          pendingBases.push(relation.to);
        }
      }
    }
  }

  function visibleRecords() {
    return model.records.filter((node) => revealed.has(node.id));
  }

  function visibleRelations() {
    return model.relations.filter((relation) =>
      revealed.has(relation.from) && revealed.has(relation.to));
  }

  function relationShown(relation) {
    if (relation.from !== directionFocusId && relation.to !== directionFocusId) return true;
    return relationAllowed(relation, directionFocusId);
  }

  function applyFilters() {
    if (!model) return;
    const byKey = new Map(model.relations.map((relation) => [relation.key, relation]));
    let count = 0;
    for (const edge of svg.querySelectorAll(".relation-edge")) {
      const shown = relationShown(byKey.get(edge.dataset.key));
      edge.classList.toggle("filtered-out", !shown);
      edge.setAttribute("aria-hidden", shown ? "false" : "true");
      edge.setAttribute("tabindex", shown ? "0" : "-1");
      if (shown) count++;
    }
    $("subtitle").textContent = visibleRecords().length + " of " + model.records.length +
      " classes · " + count + " relationships · Translation unit only";
  }

  function modeFor(id, kind, count) {
    return compartments.get(id + ":" + kind) || (count > 6 ? "preview" : "open");
  }

  function shownMembers(id, kind) {
    const all = model.members.get(id)[kind];
    const mode = modeFor(id, kind, all.length);
    return mode === "closed" ? [] : mode === "preview" ? all.slice(0, 4) : all;
  }

  function cardHeight(node) {
    let height = 58;
    for (const kind of ["field", "method"]) {
      const all = model.members.get(node.id)[kind];
      if (!all.length) continue;
      height += 25 + shownMembers(node.id, kind).length * rowHeight;
      if (modeFor(node.id, kind, all.length) === "preview") height += rowHeight;
    }
    return height + 6;
  }

  function levelsFor(records, relations) {
    const levels = new Map([[rootId, 0]]);
    const queue = [rootId];
    while (queue.length) {
      const id = queue.shift();
      for (const relation of relations) {
        let next;
        let delta;
        if (relation.from === id) {
          next = relation.to;
          delta = relation.kind === "inherits" ? -1 : 1;
        } else if (relation.to === id) {
          next = relation.from;
          delta = 1;
        } else continue;
        if (levels.has(next)) continue;
        levels.set(next, levels.get(id) + delta);
        queue.push(next);
      }
    }
    for (const node of records) if (!levels.has(node.id)) levels.set(node.id, 2);
    return levels;
  }

  function layout(records, relations) {
    positions = new Map();
    const levels = levelsFor(records, relations);
    const rows = new Map();
    for (const node of records) {
      const level = levels.get(node.id);
      if (!rows.has(level)) rows.set(level, []);
      rows.get(level).push(node);
    }
    const width = svg.getBoundingClientRect().width || 800;
    const columns = width < 650 ? 1 : width < 1050 ? 2 : 3;
    let y = 0;
    for (const level of [...rows.keys()].sort((a, b) => a - b)) {
      const nodes = rows.get(level);
      for (let start = 0; start < nodes.length; start += columns) {
        const chunk = nodes.slice(start, start + columns);
        const tallest = Math.max(...chunk.map(cardHeight));
        chunk.forEach((node, index) => {
          positions.set(node.id, { x: (index - (chunk.length - 1) / 2) * 326,
            y, h: cardHeight(node) });
        });
        y += tallest + 112;
      }
    }
    const rootY = positions.get(rootId)?.y || 0;
    for (const point of positions.values()) point.y -= rootY;
    const all = [...positions.values()];
    bounds = { x: Math.min(...all.map((p) => p.x)) - cardWidth / 2 - 72,
      y: Math.min(...all.map((p) => p.y)) - 82,
      w: Math.max(...all.map((p) => p.x)) - Math.min(...all.map((p) => p.x)) + cardWidth + 144,
      h: Math.max(...all.map((p) => p.y + p.h)) - Math.min(...all.map((p) => p.y)) + 164 };
  }

  function edgeGeometry(from, to, relation, lane) {
    if (relation.from === relation.to) {
      const x = from.x + cardWidth / 2;
      const y = from.y + Math.min(from.h / 2, 70);
      return { d: "M " + x + " " + y + " C " + (x + 96) + " " + (y - 55) +
        ", " + (x + 96) + " " + (y + 55) + ", " + x + " " + (y + 22),
      x: x + 76, y: y - 8 };
    }
    const fromCenterY = from.y + from.h / 2;
    const toCenterY = to.y + to.h / 2;
    const horizontal = Math.abs(from.x - to.x) > cardWidth + 20 &&
      Math.abs(fromCenterY - toCenterY) < Math.max(from.h, to.h);
    let x1, y1, x2, y2, d;
    if (horizontal) {
      const right = from.x < to.x;
      x1 = from.x + (right ? cardWidth / 2 : -cardWidth / 2);
      y1 = fromCenterY;
      x2 = to.x + (right ? -cardWidth / 2 : cardWidth / 2);
      y2 = toCenterY;
      const middle = (x1 + x2) / 2;
      d = "M " + x1 + " " + y1 + " C " + middle + " " + (y1 + lane) +
        ", " + middle + " " + (y2 + lane) + ", " + x2 + " " + y2;
    } else {
      const down = fromCenterY < toCenterY;
      x1 = from.x;
      y1 = from.y + (down ? from.h : 0);
      x2 = to.x;
      y2 = to.y + (down ? 0 : to.h);
      const middle = (y1 + y2) / 2;
      d = "M " + x1 + " " + y1 + " C " + (x1 + lane) + " " + middle +
        ", " + (x2 + lane) + " " + middle + ", " + x2 + " " + y2;
    }
    return { d, x: (x1 + x2) / 2 + (horizontal ? 0 : lane), y: (y1 + y2) / 2 - 8 };
  }

  function relationName(relation) {
    const from = model.byId.get(relation.from);
    const to = model.byId.get(relation.to);
    if (relation.kind === "inherits") return nameOf(from) + " inherits " + nameOf(to);
    const field = model.byId.get(relation.memberId);
    return nameOf(from) + "." + (field?.name || "field") + " uses " + nameOf(to);
  }

  function drawEdges(relations) {
    const edges = svgEl("g", { class: "edges" });
    const lanes = new Map();
    for (const relation of relations) {
      const from = positions.get(relation.from);
      const to = positions.get(relation.to);
      if (!from || !to) continue;
      const pair = relation.from + ">" + relation.to;
      const lane = lanes.get(pair) || 0;
      lanes.set(pair, lane + 1);
      const geometry = edgeGeometry(from, to, relation, lane * 18);
      const group = svgEl("g", { class: "relation-edge " + relation.kind,
        role: "button", tabindex: 0, "aria-label": relationName(relation) + ". Select for source evidence." });
      group.dataset.key = relation.key;
      group.append(svgEl("path", { d: geometry.d, class: "edge-line",
        ...(relation.kind === "inherits" ? { "marker-end": "url(#generalization)" } : {}) }));
      group.append(svgEl("path", { d: geometry.d, class: "edge-hit" }));
      if (relation.kind === "fieldType") {
        const field = model.byId.get(relation.memberId);
        const label = svgEl("text", { x: geometry.x, y: geometry.y,
          class: "edge-label", "text-anchor": "middle" });
        label.textContent = short(field?.name || "field", 24);
        group.append(label);
      }
      const title = svgEl("title");
      title.textContent = relationName(relation);
      group.append(title);
      group.addEventListener("click", (event) => {
        event.stopPropagation();
        selectRelation(relation);
      });
      group.addEventListener("dblclick", (event) => {
        event.stopPropagation();
        vscode.postMessage({ type: "navigate", id: relation.evidenceId });
      });
      group.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        if (event.shiftKey) vscode.postMessage({ type: "navigate", id: relation.evidenceId });
        else selectRelation(relation);
      });
      edges.append(group);
    }
    svg.append(edges);
  }

  function memberText(member, kind) {
    const node = member.node;
    const prefix = visibility(member.edge.access);
    const label = kind === "field"
      ? (node.name || nameOf(node)) + (node.type ? ": " + node.type : "")
      : node.signature || node.name || nameOf(node);
    return (prefix ? prefix + " " : "") + label;
  }

  function focusRebuiltControl(ownerId, kind, memberId) {
    const member = memberId && Array.from(svg.querySelectorAll(".member-row"))
      .find((row) => row.dataset.memberId === memberId);
    const compartment = Array.from(svg.querySelectorAll(".compartment-toggle"))
      .find((control) => control.dataset.ownerId === ownerId && control.dataset.kind === kind);
    const card = Array.from(svg.querySelectorAll(".record-card"))
      .find((entry) => entry.dataset.id === ownerId);
    (member || compartment || card)?.focus();
  }

  function drawCompartment(entity, node, kind, top) {
    const all = model.members.get(node.id)[kind];
    if (!all.length) return top;
    const mode = modeFor(node.id, kind, all.length);
    const group = svgEl("g", { class: "compartment-toggle", role: "button", tabindex: 0,
      "aria-label": (mode === "closed" ? "Show " : "Hide ") + kind + "s of " + nameOf(node) });
    group.dataset.ownerId = node.id;
    group.dataset.kind = kind;
    group.append(svgEl("rect", { x: -cardWidth / 2, y: top, width: cardWidth, height: 25 }));
    const title = svgEl("text", { x: -cardWidth / 2 + 12, y: top + 17 });
    title.textContent = (mode === "closed" ? "▸ " : "▾ ") +
      (kind === "field" ? "Attributes" : "Operations") + " (" + all.length + ")";
    group.append(title);
    const toggle = (event) => {
      event.stopPropagation();
      const restoreFocus = group.contains(document.activeElement);
      compartments.set(node.id + ":" + kind, mode === "closed" ? "open" : "closed");
      draw(true);
      focusNode(node.id);
      selectRecord(node.id, false);
      if (restoreFocus) focusRebuiltControl(node.id, kind);
    };
    group.addEventListener("click", toggle);
    group.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggle(event);
    });
    entity.append(group);
    top += 25;
    for (const member of shownMembers(node.id, kind)) {
      const row = svgEl("g", { class: "member-row", role: "button", tabindex: 0,
        "aria-label": memberText(member, kind) + ". Select for details." });
      row.dataset.memberId = member.node.id;
      row.append(svgEl("rect", { x: -cardWidth / 2 + 1, y: top,
        width: cardWidth - 2, height: rowHeight }));
      const text = svgEl("text", { x: -cardWidth / 2 + 12, y: top + 16 });
      text.textContent = short(memberText(member, kind), 36);
      row.append(text);
      const title = svgEl("title");
      title.textContent = memberText(member, kind);
      row.append(title);
      row.addEventListener("click", (event) => {
        event.stopPropagation();
        selectMember(member.node.id);
      });
      row.addEventListener("dblclick", (event) => {
        event.stopPropagation();
        vscode.postMessage({ type: "navigate", id: member.node.id });
      });
      row.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        if (event.shiftKey) vscode.postMessage({ type: "navigate", id: member.node.id });
        else selectMember(member.node.id);
      });
      entity.append(row);
      top += rowHeight;
    }
    if (mode === "preview") {
      const more = svgEl("g", { class: "member-more", role: "button", tabindex: 0,
        "aria-label": "Show all " + all.length + " " + kind + "s of " + nameOf(node) });
      more.append(svgEl("rect", { x: -cardWidth / 2 + 1, y: top,
        width: cardWidth - 2, height: rowHeight }));
      const text = svgEl("text", { x: -cardWidth / 2 + 12, y: top + 16 });
      text.textContent = "Show " + (all.length - 4) + " more…";
      more.append(text);
      const show = (event) => {
        event.stopPropagation();
        const restoreFocus = more.contains(document.activeElement);
        compartments.set(node.id + ":" + kind, "open");
        draw(true);
        focusNode(node.id);
        selectRecord(node.id, false);
        if (restoreFocus) focusRebuiltControl(node.id, kind, all[4]?.node.id);
      };
      more.addEventListener("click", show);
      more.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        show(event);
      });
      entity.append(more);
      top += rowHeight;
    }
    return top;
  }

  function drawCards(records) {
    const cards = svgEl("g", { class: "cards" });
    for (const node of records) {
      const point = positions.get(node.id);
      const classes = ["entity", "record-card"];
      if (node.id === rootId) classes.push("root");
      if (node.definitionStatus === "unresolved") classes.push("unresolved");
      const entity = svgEl("g", { class: classes.join(" "),
        transform: "translate(" + point.x + " " + point.y + ")",
        role: "button", tabindex: 0,
        "aria-label": (node.recordKind || "record") + " " + nameOf(node) +
          (node.definitionStatus === "unresolved" ? ", definition unavailable in this translation unit" : "") +
          ". Select for details; use the reveal action to explore related classes." });
      entity.dataset.id = node.id;
      entity.append(svgEl("rect", { class: "card-outline", x: -cardWidth / 2, y: 0,
        width: cardWidth, height: point.h, rx: 4 }));
      const kind = svgEl("text", { class: "kind", x: -cardWidth / 2 + 12, y: 19 });
      kind.textContent = node.recordKind || "record";
      entity.append(kind);
      const name = svgEl("text", { class: "name", x: -cardWidth / 2 + 12, y: 41 });
      name.textContent = short(nameOf(node), 30);
      entity.append(name);
      const title = svgEl("title");
      title.textContent = nameOf(node);
      entity.append(title);
      if (node.definitionStatus === "unresolved") {
        const status = svgEl("text", { class: "status", x: cardWidth / 2 - 12, y: 19,
          "text-anchor": "end" });
        status.textContent = "Unresolved";
        entity.append(status);
      }
      entity.append(svgEl("line", { class: "divider", x1: -cardWidth / 2, x2: cardWidth / 2,
        y1: 57, y2: 57 }));
      let top = 58;
      top = drawCompartment(entity, node, "field", top);
      drawCompartment(entity, node, "method", top);
      entity.addEventListener("click", () => selectRecord(node.id, false));
      entity.addEventListener("dblclick", () => vscode.postMessage({ type: "navigate", id: node.id }));
      entity.addEventListener("keydown", (event) => {
        if (event.target !== entity || (event.key !== "Enter" && event.key !== " ")) return;
        event.preventDefault();
        if (event.shiftKey) vscode.postMessage({ type: "navigate", id: node.id });
        else selectRecord(node.id, false);
      });
      cards.append(entity);
    }
    svg.append(cards);
  }

  function setView() {
    svg.setAttribute("viewBox", view.x + " " + view.y + " " + view.w + " " + view.h);
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
    $("graph-help").textContent = "Class diagram for this translation unit. Select a card or relation for details; use Reveal related classes to explore.";
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
    const point = positions.get(id);
    if (!point) return;
    const ratio = view.w / view.h;
    const w = Math.min(view.w, 800);
    view = { x: point.x - w / 2, y: point.y + Math.min(point.h / 2, 180) - w / ratio / 2,
      w, h: w / ratio };
    setView();
  }

  function updateSelection() {
    for (const card of svg.querySelectorAll(".entity")) {
      card.classList.toggle("selected", selected?.kind === "record" && card.dataset.id === selected.id);
    }
    for (const row of svg.querySelectorAll(".member-row")) {
      row.classList.toggle("selected", selected?.kind === "member" &&
        row.dataset.memberId === selected.id);
    }
    for (const relation of svg.querySelectorAll(".relation-edge")) {
      relation.classList.toggle("selected", selected?.kind === "relation" &&
        relation.dataset.key === selected.key);
    }
  }

  function beginDetail(title) {
    const content = $("detail-content");
    const restoreFocus = content.contains(document.activeElement);
    content.replaceChildren();
    const heading = el("h3", "", title);
    heading.tabIndex = -1;
    content.append(heading);
    const dl = el("dl");
    content.append(dl);
    return { content, heading, dl, restoreFocus };
  }

  function addDetail(dl, label, value) {
    if (value === undefined || value === null || value === "") return;
    dl.append(el("dt", "", label), el("dd", "", value));
  }

  function detailButton(content, label, action, className) {
    const button = el("button", className || "secondary", label);
    button.type = "button";
    button.addEventListener("click", action);
    content.append(button);
    return button;
  }

  function sourceAction(content, node, id) {
    if (node?.file || node?.uri) {
      detailButton(content, "Open source", () => vscode.postMessage({ type: "navigate", id }), "primary");
    } else {
      content.append(el("p", "muted", "No source location is available for this entity."));
    }
  }

  function restoreDetailFocus(detail) {
    if (detail.restoreFocus) detail.heading.focus();
  }

  function selectRecord(id, focus) {
    const node = model.byId.get(id);
    if (!isRecord(node)) return;
    directionFocusId = id;
    selected = { kind: "record", id };
    updateSelection();
    applyFilters();
    const detail = beginDetail(nameOf(node));
    addDetail(detail.dl, "Kind", node.recordKind || node.kind);
    addDetail(detail.dl, "Definition", node.definitionStatus === "unresolved"
      ? "Unavailable in this translation unit"
      : node.definitionStatus === "defined" ? "Available in this translation unit" : "");
    addDetail(detail.dl, "Location", locationOf(node));
    addDetail(detail.dl, "Attributes", model.members.get(id).field.length);
    addDetail(detail.dl, "Operations", model.members.get(id).method.length);
    addDetail(detail.dl, "Relations", (model.around.get(id) || []).length);
    sourceAction(detail.content, node, id);
    detailButton(detail.content, "Focus in graph", () => focusNode(id));
    const expanded = Array.isArray(graph.expandedRecordIds) ? graph.expandedRecordIds : [];
    const hiddenKnown = [...neighbors(id)].some((otherId) => otherId !== id && !revealed.has(otherId));
    if (hiddenKnown || (canInspect(node) && !expanded.includes(id))) {
      const reveal = detailButton(detail.content,
        pending.has(id) ? "Finding related classes…" : "Reveal related classes",
        () => revealRelated(id), "secondary");
      reveal.disabled = pending.has(id);
    }
    if (id !== rootId) {
      detailButton(detail.content, "Hide this class", () => {
        revealed.delete(id);
        draw(true);
        selectRecord(rootId, false);
      });
    }
    const relations = model.around.get(id) || [];
    if (relations.length) {
      detail.content.append(el("h4", "", "Relationships in this translation unit"));
      const list = el("ul", "relations");
      for (const relation of relations) {
        const otherId = relation.from === id ? relation.to : relation.from;
        const other = model.byId.get(otherId);
        const direction = relation.kind === "inherits"
          ? (relation.from === id ? "Base: " : "Derived: ")
          : (relation.from === id ? "Field type: " : "Used by field in: ");
        const item = el("li");
        const button = el("button", "relation", direction + nameOf(other));
        button.type = "button";
        button.addEventListener("click", () => {
          revealed.add(otherId);
          draw(true);
          selectRecord(otherId, true);
        });
        item.append(button);
        list.append(item);
      }
      detail.content.append(list);
    }
    if (focus) focusNode(id);
    restoreDetailFocus(detail);
  }

  function selectMember(id) {
    const node = model.byId.get(id);
    const ownerId = model.ownerOf.get(id);
    if (!node || !ownerId) return;
    const member = [...model.members.get(ownerId).field, ...model.members.get(ownerId).method]
      .find((entry) => entry.node.id === id);
    selected = { kind: "member", id };
    updateSelection();
    const detail = beginDetail(node.name || nameOf(node));
    addDetail(detail.dl, "Kind", node.kind);
    addDetail(detail.dl, "Owner", nameOf(model.byId.get(ownerId)));
    addDetail(detail.dl, "Visibility", member?.edge.access);
    addDetail(detail.dl, "Signature", node.signature);
    addDetail(detail.dl, "Type", node.type);
    addDetail(detail.dl, "Location", locationOf(node));
    sourceAction(detail.content, node, id);
    detailButton(detail.content, "Focus class in graph", () => focusNode(ownerId));
    restoreDetailFocus(detail);
  }

  function selectRelation(relation) {
    selected = { kind: "relation", key: relation.key };
    updateSelection();
    const from = model.byId.get(relation.from);
    const to = model.byId.get(relation.to);
    const evidence = model.byId.get(relation.evidenceId);
    const detail = beginDetail(relationName(relation));
    addDetail(detail.dl, "Relation", relation.kind === "inherits" ? "Inheritance" : "Field type association");
    addDetail(detail.dl, "From", nameOf(from));
    addDetail(detail.dl, "To", nameOf(to));
    if (relation.kind === "inherits") {
      addDetail(detail.dl, "Access", relation.edge.access);
      addDetail(detail.dl, "Virtual", relation.edge.virtual ? "Yes" : "No");
    } else {
      const field = model.byId.get(relation.memberId);
      addDetail(detail.dl, "Evidence", (field?.name || "field") +
        (field?.type ? ": " + field.type : ""));
      detail.content.append(el("p", "muted",
        "This link comes from a record-typed field; ownership and cardinality are not inferred."));
    }
    addDetail(detail.dl, "Source", locationOf(evidence));
    sourceAction(detail.content, evidence, relation.evidenceId);
    restoreDetailFocus(detail);
  }

  function draw(shouldFit) {
    if (!model?.records.length || !visibleRecords().length) return;
    const records = visibleRecords();
    const relations = visibleRelations();
    layout(records, model.relations.filter((relation) =>
      revealed.has(relation.from) && revealed.has(relation.to)));
    svg.replaceChildren();
    const defs = svgEl("defs");
    const triangle = svgEl("marker", { id: "generalization", viewBox: "0 0 14 14",
      refX: 13, refY: 7, markerWidth: 14, markerHeight: 14,
      markerUnits: "userSpaceOnUse", orient: "auto" });
    triangle.append(svgEl("path", { d: "M 0 0 L 13 7 L 0 14 Z", class: "triangle" }));
    defs.append(triangle);
    svg.append(defs);
    drawEdges(relations);
    drawCards(records);
    updateSelection();
    applyFilters();
    if (shouldFit) fit();
    else setView();
  }

  function revealRelated(id) {
    revealNeighborhood(id);
    draw(true);
    selectRecord(id, false);
    const expanded = Array.isArray(graph.expandedRecordIds) ? graph.expandedRecordIds : [];
    if (!expanded.includes(id) && !pending.has(id) && canInspect(model.byId.get(id))) {
      pending.add(id);
      setNotice("Finding related classes in this translation unit…", "loading");
      vscode.postMessage({ type: "expand", id });
      selectRecord(id, false);
    }
  }

  function makeFilters() {
    const legend = $("legend");
    legend.replaceChildren();
    const heading = el("span", "scope", "Selected class relations");
    legend.append(heading);
    for (const [kind, label, swatchKind] of [
      ["bases", "Bases", "inherits"],
      ["derived", "Known derived", "inherits"],
      ["outgoingFields", "Field types", "fieldType"],
      ["incomingFields", "Known incoming fields", "fieldType"],
    ]) {
      const wrapper = el("label", "filter");
      const input = el("input");
      input.type = "checkbox";
      input.checked = filters[kind];
      input.addEventListener("change", () => {
        filters[kind] = input.checked;
        applyFilters();
        if (selected?.kind === "record") selectRecord(selected.id, false);
      });
      const swatch = el("i", "swatch " + swatchKind);
      swatch.setAttribute("aria-hidden", "true");
      wrapper.append(input, swatch, el("span", "", label));
      legend.append(wrapper);
    }
    legend.append(el("span", "scope",
      "Reverse links include only known classes in this translation unit; shown cards stay visible."));
  }

  function render(message) {
    if (message.status === "loading") {
      setNotice("Inspecting the selected record…", "loading");
      return;
    }
    const nextGraph = message.graph;
    if (message.status === "error" || !nextGraph?.ok) {
      const diagnostics = (nextGraph?.diagnostics || []).map((entry) => entry.message).filter(Boolean);
      setNotice(diagnostics.join(" · ") || message.message || "The record could not be inspected.", "error");
      svg.replaceChildren();
      $("detail-content").textContent = "Choose another record or inspect the compiler diagnostics.";
      return;
    }
    graph = nextGraph;
    model = project(graph);
    if (!model.records.length) {
      setNotice("No record was found in this translation unit.", "empty");
      svg.replaceChildren();
      $("detail-content").textContent = "The selected record has no available definition.";
      return;
    }
    const root = model.byId.get(graph.recordId) || model.records[0];
    const first = rootId !== root.id;
    rootId = root.id;
    if (first) {
      directionFocusId = rootId;
      revealed = new Set();
      pending = new Set();
      compartments = new Map();
      revealNeighborhood(rootId);
      revealBaseChain(rootId);
    } else {
      revealed.add(rootId);
      if (message.focusId && model.byId.has(message.focusId)) {
        revealNeighborhood(message.focusId);
        revealBaseChain(message.focusId);
        pending.delete(message.focusId);
      }
      for (const id of graph.expandedRecordIds || []) pending.delete(id);
    }
    $("title").textContent = nameOf(root);
    setNotice(graph.truncated ? "Graph limit reached; some relationships may be omitted." : "",
      graph.truncated ? "warning" : "");
    draw(!(message.background && !first));
    if (message.focusId && revealed.has(message.focusId)) selectRecord(message.focusId, true);
    else if (message.background && selected?.kind === "member" && model.ownerOf.has(selected.id))
      selectMember(selected.id);
    else if (message.background && selected?.kind === "relation" &&
        model.relations.some((relation) => relation.key === selected.key))
      selectRelation(model.relations.find((relation) => relation.key === selected.key));
    else if (selected?.kind === "record" && model.byId.has(selected.id) && revealed.has(selected.id))
      selectRecord(selected.id, false);
    else selectRecord(rootId, false);
  }

  makeFilters();
  $("zoom-in").addEventListener("click", () => zoom(0.8));
  $("zoom-out").addEventListener("click", () => zoom(1.25));
  $("fit").addEventListener("click", fit);
  svg.addEventListener("wheel", (event) => {
    if (!model?.records.length) return;
    event.preventDefault();
    zoom(event.deltaY < 0 ? 0.9 : 1.1);
  }, { passive: false });
  svg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".entity, .relation-edge")) return;
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
    else if (event.data?.type === "expansionError") {
      pending.clear();
      setNotice(event.data.message || "Related classes could not be loaded.", "error");
      if (selected?.kind === "record") selectRecord(selected.id, false);
    } else if (event.data?.type === "backgroundExpansionError") {
      setNotice("Some parent members could not be loaded: " +
        (event.data.message || "record inspection failed."), "warning");
    }
  });
  vscode.postMessage({ type: "ready" });
})();
