"""Language support for the Clang AST Matcher DSL (clang-query files).

Editor-agnostic: `astmatcher_lsp.server` speaks LSP over stdio, and
`astmatcher_lsp.cli` exposes the same analysis as a batch checker so that
editors without an LSP client (and CI) can use it too.
"""

__version__ = "1.0.0"

DEFAULT_LANGUAGE_ID = "astmatcher"
