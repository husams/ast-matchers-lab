"use strict";

const crypto = require("crypto");
const path = require("path");
const vscode = require("vscode");

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
    const session = { ready: false, state: { status: "loading" }, graph: undefined };
    const post = () => {
      if (session.ready) panel.webview.postMessage({ type: "state", ...session.state });
    };
    panel.webview.onDidReceiveMessage(async (message) => {
      if (message.type === "ready") {
        session.ready = true;
        post();
      } else if (message.type === "navigate") {
        const node = session.graph?.nodes?.find((n) => n.id === message.id);
        if (node) await this.revealNode(node);
      }
    });
    try {
      const graph = await this.sendRequest("astmatcher/inspectRecord", request);
      session.graph = graph;
      if (graph?.ok && Array.isArray(graph.nodes)) {
        const root = graph.nodes.find((node) => node.id === graph.recordId) || graph.nodes[0];
        if (root) panel.title = graphTitle(root);
      }
      session.state = { status: graph?.ok ? "ready" : "error", graph };
    } catch (error) {
      session.state = { status: "error", message: error.message || String(error) };
    }
    post();
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
<link rel="stylesheet" href="${style}"><title>Record Explorer</title></head>
<body>
<header><div><h1 id="title">Record Explorer</h1><p id="subtitle">Inspecting record relationships…</p></div>
<div class="controls" role="group" aria-label="Graph controls">
<button id="zoom-out" type="button" aria-label="Zoom out" title="Zoom out">−</button>
<button id="zoom-in" type="button" aria-label="Zoom in" title="Zoom in">+</button>
<button id="fit" type="button" title="Fit graph to view">Fit</button></div></header>
<div id="notice" role="status"></div>
<main><section id="graph-pane" aria-label="Record relationship graph">
<div id="legend" aria-label="Relationship legend">
<span><i class="swatch inherits" aria-hidden="true"></i> Inherits</span>
<span><i class="swatch field" aria-hidden="true"></i> Field</span>
<span><i class="swatch method" aria-hidden="true"></i> Method</span>
<span><i class="swatch fieldType" aria-hidden="true"></i> Field type</span>
</div>
<svg id="graph" role="group" aria-label="Record relationships" tabindex="0"></svg>
<p id="graph-help">Click an entity for details. Double-click to open its source. Use +/− to zoom, arrow keys to pan, and 0 to fit.</p>
</section><aside id="details"><h2>Entity details</h2><div id="detail-content" role="status">Select a record or relation.</div></aside></main>
<script nonce="${nonce}" src="${script}"></script></body></html>`;
  }
}

module.exports = { RecordExplorer, makeRecordRequest, graphTitle };
