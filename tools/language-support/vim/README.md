# AST Matcher DSL for Vim and Neovim

Syntax highlighting for `clang-query` matcher scripts, with the 516 matcher
names split into three highlight groups so that the shape of a matcher
expression is readable at a glance.

## Install

Point the runtime path at this directory:

```vim
set runtimepath+=~/workspace/qemu-vms/ast-matchers-lab/tools/language-support/vim
```

or with a plugin manager, e.g. lazy.nvim:

```lua
{ dir = "~/workspace/qemu-vms/ast-matchers-lab/tools/language-support/vim" }
```

`*.query` files then get `filetype=astmatcher` when their first non-comment
line is a clang-query command (or when they are empty), so a `.query` file
belonging to another language is left alone. `*.cq` and `*.clang-query` are
claimed the same way, but not when empty.

## Highlight groups

| Group | Linked to | Covers |
|-------|-----------|--------|
| `astmatcherCommand` | `Statement` | `match`, `let`, `set`, `enable`, `disable`, `quit`, `help` |
| `astmatcherSetting` / `astmatcherSettingValue` | `Identifier` / `Constant` | `print-matcher`, `traversal`, `AsIs`, `detailed-ast`, … |
| `astmatcherNodeMatcher` | `Structure` | the 226 node matchers (`functionDecl`, `ifStmt`, `qualType`) |
| `astmatcherNarrowing` | `Function` | the 152 narrowing matchers (`hasName`, `isDefinition`, `unless`) |
| `astmatcherTraversal` | `Keyword` | the 138 traversal matchers (`has`, `hasDescendant`, `forEachArgumentWithParam`) |
| `astmatcherLetName` | `Define` | the name in `let NAME …` |
| `astmatcherBind` | `Special` | `.bind` |
| `astmatcherEnumValue` | `Constant` | `CK_…`, `attr::…`, `UETT_…`, `OMPC_…` inside strings |

Override any of them in your colorscheme, e.g.
`hi link astmatcherTraversal Type`.

## Completion

The ftplugin adds the generated word list to `dictionary`, so
<kbd>Ctrl-X</kbd><kbd>Ctrl-K</kbd> completes matcher names, settings and enum
values with no extra machinery.

For real, type-aware completion, run the language server. Either attach it with
your LSP client (see `../astmatcher-lsp/README.md` for a `vim.lsp.start`
snippet), or use the bundled batch bridge:

```vim
let g:astmatcher_omnifunc = 1     " <C-x><C-o> asks the server
```

`:AstMatcherCheck` type-checks the buffer into the quickfix list.
