# AST Matchers Lab

Hands-on lab for the Clang AST Matcher DSL, taught entirely through
`clang-query` — every entry of the official AST Matcher Reference, each with a
verified example.

Start at [`docs/README.md`](docs/README.md). Agent guide: [`CLAUDE.md`](CLAUDE.md).
Doc conventions: [`AUTHORING.md`](AUTHORING.md). Validate: `scripts/check.sh`.

Prefer a browser? Open [`web/index.html`](web/index.html) — a self-contained,
dark-mode lesson viewer (search, progress, sample viewer, copyable
`clang-query` commands, "How this result is reached" breakdowns). Rebuild it
after editing docs or samples: `python3 scripts/explain_steps.py &&
python3 scripts/build_web.py`.
