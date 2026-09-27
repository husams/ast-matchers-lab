# astmatcher-lsp

A language server for the Clang AST Matcher DSL. Pure standard-library
Python 3.10+ — no pip install, no virtualenv.

```sh
bin/astmatcher-lsp --stdio                       # speak LSP over stdin/stdout
bin/astmatcher-lsp --check manifests/queries/*.query
bin/astmatcher-lsp --check - < my.query --json
bin/astmatcher-lsp --complete my.query --at 4:22 # what belongs at line 4, column 22
bin/astmatcher-lsp --hover my.query --at 4:22
bin/astmatcher-lsp --signature my.query --at 4:22
bin/astmatcher-lsp --run my.query --sample manifests/decls.cpp -- -std=c++23   # matches as JSON
bin/astmatcher-lsp --run my.query --sample src --target-scope directory \
  --compile-commands build/compile_commands.json --traversal AsIs --cache -- -std=c++23
```

`ASTMATCHER_PYTHON` picks the interpreter, `ASTMATCHER_DATA` (or `--data`)
points at a different generated `data/` directory.

## LSP surface

| Request | Notes |
|---------|-------|
| `textDocument/completion` (+ `completionItem/resolve`) | type-filtered; documentation is attached on resolve to keep the list small |
| `textDocument/hover` | every overload, the reference docs, the lab part |
| `textDocument/signatureHelp` | tracks the active overload and argument |
| `textDocument/publishDiagnostics` | on open/change/save |
| `textDocument/documentSymbol` | one entry per `match`, `let`, `set` |
| `textDocument/definition` | jumps to a `let` definition |
| `textDocument/semanticTokens/full` | custom `nodeMatcher` / `narrowingMatcher` / `traversalMatcher` / `literal` types, `let` names, bound ids |
| `astmatcher/runQuery` (custom) | runs the document through clang-query, answers with the matches as JSON (below) |

### `astmatcher/runQuery`

Params: `{textDocument: {uri}, sample, flags?, target?, exclusions?, compileCommands?, traversal?, cache?, clangQuery?, cwd?, timeout?, runId?}`.
The document's current text (saved or not) is run with `clang-query -f` against
the selected file, directory, or workspace roots; a new request kills a run
still in progress. `target` is `{scope: "file"|"directory"|"workspace",
path, roots?}`. Directory/workspace discovery applies `.gitignore` files and
the `exclusions` glob list. `compileCommands` accepts a compilation database
file or build directory; its per-source flags are used, with `flags` appended
as explicit overrides. `traversal` accepts `AsIs` or
`IgnoreUnlessSpelledInSource`. `cache` is `{enabled, location?}` and is off by
default; when enabled, entries are keyed by query/tool/flags and the Clang
dependency list, so included-header changes invalidate them. A TU is skipped
from caching when dependency discovery fails. The answer includes `files`,
normalized `target`, cache hit/miss metadata, and `translationUnit` for each
result. `semanticKind` identifies declaration meaning (for example `struct`,
`union`, `function`, or `method`) and is empty for non-declarations.

When `runId` is supplied, the server also sends `astmatcher/queryProgress`
notifications on the same LSP connection: one `kind: "start"` event with
`totalFiles`, then a `kind: "file"` event after each source file finishes.
Each file event carries that file's queries, bindings, errors, cache delta,
and `completedFiles`. Notifications include `runId` so clients can discard
events from a cancelled or replaced run. The final response remains the full
result for clients that do not consume progress notifications.

```jsonc
{
  "ok": true, "sample": "/abs/manifests/decls.cpp", "flags": ["-std=c++23"],
  "command": ["…/clang-query", "-f", "…", "…", "--", "-std=c++23"],
  "exitCode": 0, "durationMs": 212, "truncated": false, "stderr": "",
  "errors": [{"message": "Matcher not found: hasNamex", "range": {…}}],  // range in the query file
  "queries": [{                                 // one per `match`, in order
    "matcher": "cxxRecordDecl(hasName(\"Pair\"))", "range": {…}, "count": 1,
    "matches": [{"index": 1, "bindings": [{
      "id": "root", "kind": "CXXRecordDecl", "summary": "struct Pair definition",
      "text": "struct Pair { int first; }", "location": "decls.cpp:47:1",
      "file": "/abs/…/decls.cpp", "uri": "file:///abs/…/decls.cpp",
      "node": "0x9692a0b90",                                          // AST address
      "range": {"start": {"line": 46, "character": 0}, "end": {…}}   // null for types
    }]}]
  }],
  "bindings": {                                  // same data by bind id, each node once
    "root": [{"node": "0x9692a0b90", "kind": "CXXRecordDecl", …,
              "matches": [{"query": 0, "match": 0, "binding": 0, "index": 1}]}]
  }
}
```

clang-query has no machine-readable output, so `run.py` prepends
`set print-matcher true`, `set output dump`, `enable output diag`, blanks the
script's own output settings (keeping offsets), and parses the text: the
"binds here" note and the AST dump's `<begin, end>` give each binding's range,
widened to the end of the last token.

## Wiring it up by hand

Neovim (0.8+), in `init.lua`:

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = "astmatcher",
  callback = function(args)
    vim.lsp.start({
      name = "astmatcher",
      cmd = { vim.fn.expand("~/workspace/qemu-vms/ast-matchers-lab/tools/language-support/astmatcher-lsp/bin/astmatcher-lsp"), "--stdio" },
      root_dir = vim.fs.dirname(args.file),
    })
  end,
})
```

Emacs (`eglot`):

```elisp
(add-to-list 'eglot-server-programs
             '(astmatcher-mode . ("astmatcher-lsp" "--stdio")))
```

Helix (`languages.toml`):

```toml
[language-server.astmatcher]
command = "astmatcher-lsp"
args = ["--stdio"]

[[language]]
name = "astmatcher"
file-types = ["query"]
language-servers = ["astmatcher"]
```

## Modules

| File | Responsibility |
|------|----------------|
| `catalog.py` | loads `data/*.json`; answers "is A related to B", "how specific is this matcher for that slot" |
| `lexer.py` | tokens and offset↔line/character conversion |
| `parser.py` | error-tolerant tree (a half-typed document must still parse) |
| `analyze.py` | overload resolution and the diagnostics, worded like clang-query's |
| `features.py` | what the cursor is inside, and the LSP payloads |
| `run.py` | runs clang-query and parses its output into the `runQuery` JSON |
| `server.py` | JSON-RPC loop |
| `cli.py` | `--stdio` / `--check` / `--complete` / `--hover` / `--signature` / `--run` |

Tests: `python3 -m unittest discover -s tests`.
