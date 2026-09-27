# AST Matcher DSL for VS Code

Highlighting, completion, hover, signature help and diagnostics for
`clang-query` matcher scripts (`.query`).

## Install

```sh
cd tools/language-support/vscode
npm install
npx @vscode/vsce package
code --install-extension astmatcher-dsl-1.0.0.vsix
```

For development instead: open this folder in VS Code and press <kbd>F5</kbd>.

The extension finds the language server at
`tools/language-support/astmatcher-lsp/bin/astmatcher-lsp` inside the open
workspace. Set `astmatcher.server.path` if the lab lives elsewhere; with no
server the grammar and snippets still work (`astmatcher.server.enabled: false`
if you want only those).

## Commands

| Command | Default key | What it does |
|---------|-------------|--------------|
| AST Matcher: Run this query with clang-query | <kbd>⌘↵</kbd> / <kbd>Ctrl↵</kbd> | saves the file and runs `clang-query -f <file> <sample> -- <flags>` in a terminal |
| AST Matcher: Restart language server | — | after editing the server or regenerating `data/` |

The run command takes its sample and flags from `astmatcher.sample` /
`astmatcher.flags` (defaults `manifests/intro.cpp` and `-std=c++23`), and honours
the lab's per-file override convention — a first line such as

```
# sample: manifests/objc.m -fobjc-exceptions
```

`astmatcher.clangQueryPath` defaults to `$LLVM/bin/clang-query`, else
`clang-query` on `PATH`.

## Settings

| Setting | Default |
|---------|---------|
| `astmatcher.server.enabled` | `true` |
| `astmatcher.server.path` | `""` (auto-detect in the workspace) |
| `astmatcher.server.python` | `python3` |
| `astmatcher.clangQueryPath` | `""` (`$LLVM/bin/clang-query`) |
| `astmatcher.sample` | `manifests/intro.cpp` |
| `astmatcher.flags` | `["-std=c++23"]` |
