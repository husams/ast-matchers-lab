"use strict";

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

const SCOPES = new Set(["file", "directory", "workspace"]);

function workspaceRoots() {
  return (vscode.workspace.workspaceFolders || []).map((folder) =>
    path.resolve(folder.uri.fsPath));
}

function config() {
  return vscode.workspace.getConfiguration("astmatcher");
}

class RunTarget {
  constructor() {
    this.roots = workspaceRoots();
  }

  resolve(samplePath) {
    const roots = workspaceRoots();
    const configuredPath = config().get("targetPath");
    let scope = config().get("scope") || "file";
    // Query-local samples and picks define file runs; the workspace setting is
    // only a fallback for queries that do not declare or pick a sample.
    let targetPath = scope === "file"
      ? samplePath || configuredPath || roots[0] || process.cwd()
      : scope === "workspace" ? roots[0] || process.cwd()
        : configuredPath || samplePath || roots[0] || process.cwd();
    if (!SCOPES.has(scope)) scope = "file";
    if (!path.isAbsolute(targetPath)) {
      const folder = vscode.workspace.workspaceFolders?.[0];
      targetPath = path.resolve(folder ? folder.uri.fsPath : process.cwd(), targetPath);
    }
    return { scope, path: path.resolve(targetPath), roots };
  }

  exclusions() {
    const values = config().get("exclusions");
    return Array.isArray(values) ? values.map(String).filter(Boolean) : [];
  }

  async set(scope, targetPath) {
    if (!SCOPES.has(scope)) throw new Error(`Unsupported target scope: ${scope}`);
    if (scope === "workspace") {
      const workspace = vscode.ConfigurationTarget?.Workspace;
      await config().update("scope", scope, workspace);
      return this.resolve(targetPath);
    }
    const base = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
    const resolved = path.isAbsolute(targetPath) ? path.resolve(targetPath) : path.resolve(base, targetPath);
    const stat = fs.statSync(resolved);
    if (scope === "file" && !stat.isFile()) throw new Error("File scope requires a file.");
    if (scope === "directory" && !stat.isDirectory()) {
      throw new Error("Directory scope requires a directory.");
    }
    if (scope === "workspace" && !stat.isDirectory()) {
      throw new Error("Workspace scope requires a workspace directory.");
    }
    const workspace = vscode.ConfigurationTarget?.Workspace;
    await config().update("scope", scope, workspace);
    await config().update("targetPath", resolved, workspace);
    return this.resolve(resolved);
  }
}

module.exports = { RunTarget, SCOPES, workspaceRoots };
