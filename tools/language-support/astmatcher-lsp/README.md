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
```

`ASTMATCHER_PYTHON` picks the interpreter, `ASTMATCHER_DATA` (or `--data`)
points at a different generated `data/` directory.

## LSP surface

| Request | Notes |
|---------|-------|
| `textDocument/completion` (+ `completionItem/resolve`) | type-filtered; documentation is attached on resolve to keep the list small |
| `textDocument/hover` | every overload, the reference docs, the lab part |
| `textDocument/signatureHelp` | tracks the active overload and argument |
| `textDocument/publishDiagnostics` | on open/change/save; also `textDocument/diagnostic` (pull) |
| `textDocument/documentSymbol` | one entry per `match`, `let`, `set` |
| `textDocument/definition` | jumps to a `let` definition |
| `textDocument/semanticTokens/full` | node vs narrowing vs traversal matchers, `let` names, bound ids |

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
| `server.py` | JSON-RPC loop |
| `cli.py` | `--stdio` / `--check` / `--complete` / `--hover` / `--signature` |

Tests: `python3 -m unittest discover -s tests`.
