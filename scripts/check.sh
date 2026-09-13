#!/usr/bin/env bash
# Run every clang-query example in the lab docs and the coverage audit.
set -uo pipefail
cd "$(dirname "$0")/.."
export LLVM="${LLVM:-$(brew --prefix llvm)}"
python3 scripts/check.py "$@"; a=$?
python3 scripts/coverage.py; b=$?
[ $a -eq 0 ] && [ $b -eq 0 ]
