"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");

test("file scope follows each query sample and its explicit per-query pick", async () => {
  const root = "/workspace/project";
  const values = { scope: "file", targetPath: "/workspace/old-query.cpp", flags: ["-std=c++23"] };
  const state = new Map();
  class EventEmitter { constructor() { this.event = () => ({ dispose() {} }); } fire() {} }
  const workspace = {
    workspaceFolders: [{ uri: { fsPath: root } }],
    getWorkspaceFolder: () => ({ uri: { fsPath: root } }),
    getConfiguration: () => ({
      get: (key) => values[key],
      update: async (key, value) => { values[key] = value; },
    }),
    ConfigurationTarget: { Workspace: 2 },
  };
  const vscode = { workspace, EventEmitter, ConfigurationTarget: { Workspace: 2 } };
  const originalLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === "vscode") return vscode;
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    delete require.cache[require.resolve("../sample")];
    delete require.cache[require.resolve("../target")];
    const { Samples } = require("../sample");
    const { RunTarget } = require("../target");
    const samples = new Samples({ workspaceState: {
      get: (key) => state.get(key),
      update: async (key, value) => value === undefined ? state.delete(key) : state.set(key, value),
    } });
    const targets = new RunTarget();
    const query = (name, sample) => ({
      uri: { toString: () => `file://${root}/queries/${name}.astmatcher` },
      lineCount: 1,
      lineAt: () => ({ text: `# sample: ${sample}` }),
    });
    const queryA = query("a", "src/a.cpp");
    const queryB = query("b", "src/b.cpp");
    const sampleA = samples.resolve(queryA);
    const sampleB = samples.resolve(queryB);

    assert.equal(targets.resolve(sampleA.absolute).path, path.join(root, "src/a.cpp"));
    assert.equal(targets.resolve(sampleB.absolute).path, path.join(root, "src/b.cpp"),
      "a persisted target from query A must not override query B's # sample line");

    const configuredFlags = ["-std=c++23", "-fblocks", "-fopenmp"];
    await samples.set(queryB, sampleB.sample, configuredFlags);
    await samples.setTarget(queryB, "picked/b-special.cpp");
    const pickedB = samples.resolve(queryB);
    assert.equal(pickedB.origin, "picked");
    assert.deepEqual(pickedB.flags, configuredFlags);
    assert.equal(targets.resolve(pickedB.absolute).path, path.join(root, "picked/b-special.cpp"),
      "the current query's explicit pick wins over its header and the persisted target");
  } finally {
    Module._load = originalLoad;
    delete require.cache[require.resolve("../sample")];
    delete require.cache[require.resolve("../target")];
  }
});
