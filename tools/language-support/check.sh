#!/bin/sh
# Validate the language support: generated data in sync, unit tests, and no
# false positives on the lab's own (clang-query-verified) examples.
set -e
cd "$(dirname "$0")"

echo "== generated data"
python3 generate.py --check

echo "== unit tests"
(
  cd astmatcher-lsp
  python3 -m unittest discover -s tests -q
)

echo "== installer tests"
python3 -m unittest discover -s tests -p 'test_deploy_rhel.py' -q

echo "== VS Code selection tests"
node --test vscode/tests/*.test.js

echo "== corpus"
python3 corpus_check.py
