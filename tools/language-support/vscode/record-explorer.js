"use strict";

const crypto = require("crypto");
const path = require("path");
const vscode = require("vscode");

const MAX_GRAPH_NODES = 256;
const MAX_GRAPH_EDGES = 512;

function isRecordNode(node) {
  return !!node && (["class", "struct", "union"].includes(node.recordKind) ||
    node.kind === "RecordDecl" || node.kind === "CXXRecordDecl");
}

function sourceSpan(node) {
  const start = node?.range?.start;
  const end = node?.range?.end;
  const position = (point) => Number.isInteger(point?.line) && point.line >= 0 &&
    Number.isInteger(point?.character) && point.character >= 0;
  if (!path.isAbsolute(node?.file || "") || !position(start) || !position(end)) return "";
  return JSON.stringify([node.file, start.line, start.character, end.line, end.character]);
}

function recordSourceKey(node) {
  const span = sourceSpan(node);
  const name = node?.qualifiedName || node?.name;
  return span && name ? JSON.stringify([span, name]) : "";
}

function memberKey(node) {
  const span = sourceSpan(node);
  if (!span || !node?.kind) return "";
  return JSON.stringify([node.kind, span, node.qualifiedName || node.name || "",
    node.type || "", node.signature || ""]);
}

function sameRecord(first, second) {
  if (!isRecordNode(first) || !isRecordNode(second)) return false;
  if (first.recordIdentity && second.recordIdentity) {
    return first.recordIdentity === second.recordIdentity;
  }
  const source = recordSourceKey(first);
  return !!source && source === recordSourceKey(second);
}

function inspectedRecordIds(graph, idMap) {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  if (graph.truncated) {
    const root = nodes.get(graph.recordId);
    const mapped = idMap ? idMap.get(graph.recordId) : graph.recordId;
    return isRecordNode(root) && mapped ? [mapped] : [];
  }
  const ids = [];
  const visited = new Set();
  const pending = [graph.recordId];
  while (pending.length) {
    const id = pending.shift();
    if (visited.has(id) || !isRecordNode(nodes.get(id))) continue;
    visited.add(id);
    const mapped = idMap ? idMap.get(id) : id;
    if (mapped) ids.push(mapped);
    for (const edge of graph.edges) {
      if (edge.kind === "inherits" && edge.from === id) pending.push(edge.to);
    }
  }
  return ids;
}

function mergeRecordGraphs(current, incoming, focusId) {
  const focus = current.nodes.find((node) => node.id === focusId);
  const replyRoot = incoming.nodes.find((node) => node.id === incoming.recordId);
  if (!sameRecord(focus, replyRoot)) {
    throw new Error("The inspected record did not match the selected record.");
  }

  const nodes = [...current.nodes];
  const edges = [...current.edges];
  const usedIds = new Set(nodes.map((node) => node.id));
  const byIdentity = new Map();
  const bySource = new Map();
  const byMember = new Map();
  const index = (node) => {
    if (isRecordNode(node)) {
      if (node.recordIdentity) byIdentity.set(node.recordIdentity, node.id);
      const source = recordSourceKey(node);
      if (source) {
        if (!bySource.has(source)) bySource.set(source, new Set());
        bySource.get(source).add(node.id);
      }
    } else {
      const key = memberKey(node);
      if (key) byMember.set(key, node.id);
    }
  };
  nodes.forEach(index);
  const knownNode = (node) => {
    if (!isRecordNode(node)) return byMember.get(memberKey(node));
    if (node.recordIdentity && byIdentity.has(node.recordIdentity)) {
      return byIdentity.get(node.recordIdentity);
    }
    const candidates = bySource.get(recordSourceKey(node));
    if (candidates?.size !== 1) return undefined;
    const candidate = nodes.find((entry) => entry.id === [...candidates][0]);
    if (node.recordIdentity && candidate.recordIdentity &&
        node.recordIdentity !== candidate.recordIdentity) return undefined;
    return candidate.id;
  };
  let nextId = 1;
  const freshId = () => {
    while (usedIds.has(`n${nextId}`)) nextId++;
    const id = `n${nextId++}`;
    usedIds.add(id);
    return id;
  };
  const idMap = new Map();
  let truncated = !!(current.truncated || incoming.truncated);
  for (const node of incoming.nodes) {
    if (!node?.id) continue;
    let id = knownNode(node);
    if (!id && nodes.length < MAX_GRAPH_NODES) {
      id = freshId();
      const added = { ...node, id };
      nodes.push(added);
      index(added);
    } else if (!id) {
      truncated = true;
    }
    if (id) idMap.set(node.id, id);
  }
  if (idMap.get(incoming.recordId) !== focusId) {
    throw new Error("The inspected record could not be merged.");
  }

  const edgeKey = (edge) => JSON.stringify([edge.from, edge.to, edge.kind,
    edge.access || "", !!edge.virtual]);
  const knownEdges = new Set(edges.map(edgeKey));
  for (const edge of incoming.edges) {
    const from = idMap.get(edge?.from);
    const to = idMap.get(edge?.to);
    if (!from || !to || !edge.kind) continue;
    const mapped = { ...edge, from, to };
    const key = edgeKey(mapped);
    if (knownEdges.has(key)) continue;
    if (edges.length >= MAX_GRAPH_EDGES) {
      truncated = true;
      continue;
    }
    edges.push(mapped);
    knownEdges.add(key);
  }
  const diagnostics = [...(current.diagnostics || [])];
  const knownDiagnostics = new Set(diagnostics.map((entry) => JSON.stringify(entry)));
  for (const diagnostic of incoming.diagnostics || []) {
    const key = JSON.stringify(diagnostic);
    if (!knownDiagnostics.has(key)) {
      diagnostics.push(diagnostic);
      knownDiagnostics.add(key);
    }
  }
  return { ...current, nodes, edges, diagnostics, truncated,
    expandedRecordIds: [...new Set([...(current.expandedRecordIds || []),
      ...inspectedRecordIds(incoming, idMap)])] };
}

function makeRecordRequest(target, options = {}) {
  if (!target || !path.isAbsolute(target.file || "") || !target.range) {
    throw new Error("Select a record with a source location to explore it.");
  }
  const translationUnit = target.translationUnit || target.file;
  return {
    translationUnit,
    file: target.file,
    range: target.range,
    ...(target.recordIdentity ? { recordIdentity: target.recordIdentity } : {}),
    cwd: options.cwd || path.dirname(translationUnit),
    flags: options.flags || [],
    compileCommands: options.compileCommands || "",
    nativeServerPath: options.nativeServerPath || "",
    timeout: options.timeout || 60,
  };
}

function graphTitle(target) {
  const name = target.signature || target.recordIdentity || target.qualifiedName || target.name ||
    target.summary || path.basename(target.file || "record");
  return `Record: ${String(name).slice(0, 72)}`;
}

class RecordExplorer {
  constructor(context, sendRequest) {
    this.context = context;
    this.sendRequest = sendRequest;
  }

  async open(target, options) {
    const request = makeRecordRequest(target, options);
    const panel = vscode.window.createWebviewPanel("astmatcher.recordExplorer", graphTitle(target),
      vscode.ViewColumn.Active, {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "media")],
      });
    panel.webview.html = this.html(panel.webview);
    const session = { ready: false, disposed: false, expanding: false,
      activeExpandId: undefined, expansionQueue: [],
      state: { status: "loading" }, graph: undefined };
    const post = (message) => {
      if (session.ready && !session.disposed) panel.webview.postMessage(message);
    };
    const postState = () => post({ type: "state", ...session.state });
    panel.onDidDispose?.(() => { session.disposed = true; });
    const processExpansions = async () => {
      if (session.expanding) return;
      session.expanding = true;
      try {
        while (session.expansionQueue.length && !session.disposed) {
          const id = session.expansionQueue.shift();
          const node = session.graph?.nodes?.find((entry) => entry.id === id);
          if (session.state.status !== "ready" || !isRecordNode(node) ||
              node.definitionStatus !== "defined" || !sourceSpan(node) ||
              session.graph.expandedRecordIds.includes(id)) continue;
          session.activeExpandId = id;
          try {
            const locator = { ...node, translationUnit: request.translationUnit };
            const response = await this.sendRequest("astmatcher/inspectRecord",
              makeRecordRequest(locator, request));
            if (session.disposed) return;
            if (!response?.ok || !Array.isArray(response.nodes) || !Array.isArray(response.edges)) {
              const diagnostic = response?.diagnostics?.map((entry) => entry.message)
                .filter(Boolean).join(" · ");
              throw new Error(diagnostic || "Record inspection failed.");
            }
            const graph = mergeRecordGraphs(session.graph, response, id);
            session.graph = graph;
            session.state = { status: "ready", graph, focusId: id };
            postState();
          } catch (error) {
            post({ type: "expansionError", message: error?.message || String(error) });
          } finally {
            session.activeExpandId = undefined;
          }
        }
      } finally {
        session.expanding = false;
      }
    };
    panel.webview.onDidReceiveMessage(async (message) => {
      if (session.disposed || !message || typeof message !== "object") return;
      if (message.type === "ready") {
        session.ready = true;
        postState();
      } else if (message.type === "navigate") {
        const node = session.graph?.nodes?.find((n) => n.id === message.id);
        if (node) await this.revealNode(node);
      } else if (message.type === "expand") {
        const node = session.graph?.nodes?.find((entry) => entry.id === message.id);
        if (session.state.status !== "ready" || !isRecordNode(node) ||
            node.definitionStatus !== "defined" || !sourceSpan(node) ||
            session.graph.expandedRecordIds.includes(node.id)) return;
        if (session.activeExpandId === node.id || session.expansionQueue.includes(node.id)) return;
        session.expansionQueue.push(node.id);
        await processExpansions();
      }
    });
    try {
      const graph = await this.sendRequest("astmatcher/inspectRecord", request);
      session.graph = graph?.ok && Array.isArray(graph.nodes)
        ? { ...graph, expandedRecordIds: inspectedRecordIds(graph) } : graph;
      if (session.disposed) return session.graph;
      if (graph?.ok && Array.isArray(graph.nodes)) {
        const root = graph.nodes.find((node) => node.id === graph.recordId) || graph.nodes[0];
        if (root) panel.title = graphTitle(root);
      }
      session.state = { status: graph?.ok ? "ready" : "error", graph: session.graph };
    } catch (error) {
      if (session.disposed) return session.graph;
      session.state = { status: "error", message: error.message || String(error) };
    }
    postState();
    return session.graph;
  }

  async revealNode(node) {
    const file = node.file || (typeof node.uri === "string" && node.uri.startsWith("file:")
      ? vscode.Uri.parse(node.uri).fsPath : "");
    if (!file || !path.isAbsolute(file)) return;
    const editor = await vscode.window.showTextDocument(vscode.Uri.file(file), {
      viewColumn: vscode.ViewColumn.Beside, preserveFocus: true, preview: false,
    });
    if (node.range) {
      const { start, end } = node.range;
      editor.selection = new vscode.Selection(start.line, start.character, end.line, end.character);
      editor.revealRange(editor.selection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    }
  }

  html(webview) {
    const nonce = crypto.randomBytes(16).toString("base64");
    const script = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, "media", "record.js"));
    const style = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, "media", "record.css"));
    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${style}"><title>Record class diagram</title></head>
<body>
<header><div><h1>Class relationship diagram: <span id="title">Record Explorer</span></h1><p id="subtitle">Inspecting record relationships…</p></div>
<div class="controls" role="group" aria-label="Graph controls">
<button id="zoom-out" type="button" aria-label="Zoom out" title="Zoom out">−</button>
<button id="zoom-in" type="button" aria-label="Zoom in" title="Zoom in">+</button>
<button id="fit" type="button" title="Fit graph to view">Fit</button></div></header>
<div id="notice" role="status"></div>
<main><section id="graph-pane" aria-label="Record class diagram">
<div id="legend" aria-label="Relationship legend">
<span><i class="swatch inherits" aria-hidden="true"></i> Generalization: derived to base</span>
<span><i class="swatch fieldType" aria-hidden="true"></i> Field association</span>
<span class="scope">This translation unit only</span>
</div>
<svg id="graph" role="group" aria-label="Record class diagram relationships" tabindex="0"></svg>
<p id="graph-help">Records are class diagram cards with fields and methods from this translation unit. Select a card for details or expand its related records; double-click to open source. Use +/− to zoom, arrow keys to pan, and 0 to fit.</p>
</section><aside id="details"><h2>Entity details</h2><div id="detail-content" role="status">Select a record or relation.</div></aside></main>
<script nonce="${nonce}" src="${script}"></script></body></html>`;
  }
}

module.exports = { RecordExplorer, makeRecordRequest, graphTitle, mergeRecordGraphs };
