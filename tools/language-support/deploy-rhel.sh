#!/usr/bin/env bash
# Build and install the AST Matcher DSL tooling (language server + VS Code
# extension + optional Vim files) on RHEL / Rocky / Alma / Fedora.
#
#   ./deploy-rhel.sh --prefix /opt/astmatcher
#
# Everything lands under --prefix (the install root); nothing is written
# outside it except the VS Code extension and user settings, which live in the
# invoking user's VS Code directories. Run --help for all options.
set -euo pipefail

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LAB=$(CDPATH= cd -- "$SRC/../.." && pwd)

PREFIX=""
PYTHON=""
CLANG_QUERY=""
CODE_CLI=""
LLVM_PREFIX="${LLVM:-/usr}"
VSIX=""
VSCE_SPEC=""
SETTINGS_FILES=()
SAMPLE=""
FLAGS=""
DO_DEPS=0
DO_REGEN=0
DO_TESTS=1
DO_VSIX=1
DO_EXT=1
DO_CONFIG=1
DO_VIM=0
DO_UNINSTALL=0
OFFLINE=0

log()  { printf '\033[1;32m==\033[0m %s\n' "$*"; }
step() { printf '\033[1;34m--\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options
  -p, --prefix DIR       install root (required unless --uninstall gives it too)
      --install-deps     dnf install python3.11, nodejs 20, clang-tools-extra
      --python PATH      Python 3.10+ interpreter (default: autodetect)
      --clang-query PATH clang-query binary (default: $LLVM/bin, then PATH)
      --llvm DIR         LLVM prefix used by --regenerate (default: $LLVM or /usr)
      --code PATH        VS Code CLI (default: code, codium, remote-cli/code)
      --vsix FILE        install this prebuilt .vsix instead of building one
      --vsce SPEC        npx spec for the packager (default: picked per node major)
      --settings FILE    VS Code settings.json to configure (repeatable; it is
                         rewritten as plain JSON, comments dropped, .bak kept)
      --sample PATH      astmatcher.sample default (default: <lab>/manifests/intro.cpp)
      --flags "A B"      astmatcher.flags default (default: -std=c++23)
      --regenerate       re-run generate.py against --llvm headers before building
      --vim              also install the Vim/Neovim files for this user
      --offline          npm ci --offline, no npx download (needs a warm cache)
      --skip-tests       do not run check.sh
      --skip-extension   build the vsix but do not install it into VS Code
      --skip-config      do not touch VS Code settings.json
      --server-only      no vsix, no extension, no settings (implies the above)
      --uninstall        remove the installed tree and the extension
  -h, --help             this text
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--prefix)      PREFIX=${2:?}; shift 2;;
    --install-deps)   DO_DEPS=1; shift;;
    --python)         PYTHON=${2:?}; shift 2;;
    --clang-query)    CLANG_QUERY=${2:?}; shift 2;;
    --llvm)           LLVM_PREFIX=${2:?}; shift 2;;
    --code)           CODE_CLI=${2:?}; shift 2;;
    --vsix)           VSIX=${2:?}; DO_VSIX=0; shift 2;;
    --vsce)           VSCE_SPEC=${2:?}; shift 2;;
    --settings)       SETTINGS_FILES+=("${2:?}"); shift 2;;
    --sample)         SAMPLE=${2:?}; shift 2;;
    --flags)          FLAGS=${2:?}; shift 2;;
    --regenerate)     DO_REGEN=1; shift;;
    --vim)            DO_VIM=1; shift;;
    --offline)        OFFLINE=1; shift;;
    --skip-tests)     DO_TESTS=0; shift;;
    --skip-extension) DO_EXT=0; shift;;
    --skip-config)    DO_CONFIG=0; shift;;
    --server-only)    DO_VSIX=0; DO_EXT=0; DO_CONFIG=0; shift;;
    --uninstall)      DO_UNINSTALL=1; shift;;
    -h|--help)        usage; exit 0;;
    *)                usage >&2; die "unknown argument: $1";;
  esac
done

[ -n "$PREFIX" ] || { usage >&2; die "--prefix is required"; }
case "$PREFIX" in /*) ;; *) PREFIX=$(CDPATH= cd -- "$(dirname -- "$PREFIX")" 2>/dev/null && pwd)/$(basename -- "$PREFIX") || die "cannot resolve --prefix";; esac

[ -n "$SAMPLE" ] || SAMPLE=$LAB/manifests/intro.cpp
[ -n "$FLAGS" ]  || FLAGS="-std=c++23"

SHAREDIR=$PREFIX/libexec/astmatcher-lsp     # server package + data
BINDIR=$PREFIX/bin                          # astmatcher-lsp wrapper
VSIXDIR=$PREFIX/share/astmatcher-dsl        # packaged extension + docs

# ---------------------------------------------------------------- VS Code CLI
find_code() {
  [ -n "$CODE_CLI" ] && { printf '%s\n' "$CODE_CLI"; return; }
  local c
  for c in code code-insiders codium vscodium; do
    have "$c" && { command -v "$c"; return; }
  done
  # Remote-SSH: the server's CLI only works inside a VS Code terminal.
  [ -n "${VSCODE_IPC_HOOK_CLI:-}" ] || return 0
  ls -td "$HOME"/.vscode-server/cli/servers/*/server/bin/remote-cli/code \
         "$HOME"/.vscode-server/bin/*/bin/remote-cli/code \
         "$HOME"/.vscode-server-insiders/bin/*/bin/remote-cli/code 2>/dev/null | head -1
}

default_settings_files() {
  [ ${#SETTINGS_FILES[@]} -gt 0 ] && { printf '%s\n' "${SETTINGS_FILES[@]}"; return; }
  local found=0 f
  for f in "$HOME/.vscode-server/data/Machine/settings.json" \
           "$HOME/.config/Code/User/settings.json" \
           "$HOME/.config/VSCodium/User/settings.json"; do
    [ -f "$f" ] && { printf '%s\n' "$f"; found=1; }
  done
  [ $found -eq 1 ] && return
  # Nothing exists yet: create the one matching how VS Code reaches this host.
  if [ -d "$HOME/.vscode-server" ]; then
    printf '%s\n' "$HOME/.vscode-server/data/Machine/settings.json"
  else
    printf '%s\n' "$HOME/.config/Code/User/settings.json"
  fi
}

# ---------------------------------------------------------------- uninstall
if [ "$DO_UNINSTALL" = 1 ]; then
  log "uninstalling from $PREFIX"
  rm -rf "$SHAREDIR" "$VSIXDIR" "$BINDIR/astmatcher-lsp"
  code=$(find_code || true)
  if [ -n "$code" ]; then
    "$code" --uninstall-extension ast-matchers-lab.astmatcher-dsl || \
      warn "extension was not installed"
  fi
  warn "VS Code settings left untouched (astmatcher.* keys still point here)"
  log "done"
  exit 0
fi

# ---------------------------------------------------------------- dependencies
if [ "$DO_DEPS" = 1 ]; then
  log "installing distro packages"
  SUDO=""; [ "$(id -u)" = 0 ] || SUDO=sudo
  have dnf || die "--install-deps needs dnf (RHEL/Rocky/Alma/Fedora)"
  if [ "$DO_VSIX" = 1 ] && $SUDO dnf -y module list nodejs >/dev/null 2>&1; then
    $SUDO dnf -y module reset nodejs || true
    $SUDO dnf -y module enable nodejs:20 || warn "nodejs:20 module unavailable; using the default stream"
  fi
  pkgs=(clang-tools-extra)
  $SUDO dnf -y list python3.11 >/dev/null 2>&1 && pkgs+=(python3.11)
  [ "$DO_VSIX" = 1 ] && pkgs+=(nodejs npm)
  [ "$DO_REGEN" = 1 ] && pkgs+=(clang-devel llvm-devel)
  $SUDO dnf -y install "${pkgs[@]}"
fi

# ---------------------------------------------------------------- toolchain
log "checking the toolchain"

pick_python() {
  [ -n "$PYTHON" ] && { printf '%s\n' "$PYTHON"; return; }
  local p
  for p in python3.13 python3.12 python3.11 python3.10 python3; do
    have "$p" || continue
    "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null \
      && { command -v "$p"; return; }
  done
  return 1
}
PYTHON=$(pick_python) || die "no Python 3.10+ found (dnf install python3.11, or pass --python)"
step "python       $PYTHON ($("$PYTHON" -c 'import platform;print(platform.python_version())'))"

if [ -z "$CLANG_QUERY" ]; then
  if [ -x "$LLVM_PREFIX/bin/clang-query" ]; then CLANG_QUERY=$LLVM_PREFIX/bin/clang-query
  elif have clang-query; then CLANG_QUERY=$(command -v clang-query)
  fi
fi
if [ -n "$CLANG_QUERY" ]; then
  step "clang-query  $CLANG_QUERY ($("$CLANG_QUERY" --version 2>/dev/null | sed -n 's/.*version \([0-9.]*\).*/\1/p' | head -1))"
else
  warn "clang-query not found (dnf install clang-tools-extra) — analysis works, Run Query will not"
fi

if [ "$DO_VSIX" = 1 ]; then
  have npm || die "npm not found (dnf install nodejs npm, or pass --vsix)"
  NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  step "node         $(node --version 2>/dev/null || echo '?')  npm $(npm --version)"
  if [ -z "$VSCE_SPEC" ]; then
    if [ "$NODE_MAJOR" -ge 20 ]; then VSCE_SPEC='@vscode/vsce@^3'; else VSCE_SPEC='@vscode/vsce@2.32.0'; fi
  fi
fi

# ---------------------------------------------------------------- regenerate
if [ "$DO_REGEN" = 1 ]; then
  log "regenerating data/ and grammars from $LLVM_PREFIX"
  [ -f "$LLVM_PREFIX/include/clang/AST/DeclNodes.inc" ] || \
    die "clang headers not under $LLVM_PREFIX/include (dnf install clang-devel llvm-devel)"
  LLVM=$LLVM_PREFIX "$PYTHON" "$SRC/generate.py"
fi

# ---------------------------------------------------------------- tests
if [ "$DO_TESTS" = 1 ]; then
  # Not check.sh: it hardcodes python3 (3.6/3.9 on RHEL), always needs node,
  # and its generate.py --check diffs against LLVM 22 headers the distro lacks.
  log "running tests"
  if [ "$DO_REGEN" = 1 ]; then
    ( cd "$SRC" && LLVM=$LLVM_PREFIX "$PYTHON" generate.py --check )
  fi
  ( cd "$SRC/astmatcher-lsp" && "$PYTHON" -m unittest discover -s tests -q )
  if [ "$DO_VSIX" = 1 ] && have node; then
    ( cd "$SRC" && node --test vscode/tests/*.test.js )
  fi
  ( cd "$SRC" && "$PYTHON" corpus_check.py )
fi

# ---------------------------------------------------------------- build vsix
if [ "$DO_VSIX" = 1 ]; then
  log "building the VS Code extension"
  cd "$SRC/vscode"
  if [ -f package-lock.json ]; then
    if [ "$OFFLINE" = 1 ]; then npm ci --offline; else npm ci; fi
  else
    npm install
  fi
  VERSION=$("$PYTHON" -c 'import json;print(json.load(open("package.json"))["version"])')
  rm -f "astmatcher-dsl-$VERSION.vsix"
  if [ "$OFFLINE" = 1 ] && [ -x node_modules/.bin/vsce ]; then
    node_modules/.bin/vsce package --allow-missing-repository
  else
    npx --yes "$VSCE_SPEC" package --allow-missing-repository
  fi
  VSIX=$SRC/vscode/astmatcher-dsl-$VERSION.vsix
  [ -f "$VSIX" ] || die "packaging produced no vsix"
  cd "$SRC"
fi
[ -z "$VSIX" ] || step "vsix         $VSIX"

# ---------------------------------------------------------------- install
log "installing into $PREFIX"
mkdir -p "$SHAREDIR/data" "$BINDIR" "$VSIXDIR"

if have rsync; then
  rsync -a --delete --exclude __pycache__ --exclude '*.pyc' \
    "$SRC/astmatcher-lsp/astmatcher_lsp" "$SHAREDIR/"
else
  rm -rf "$SHAREDIR/astmatcher_lsp"
  cp -R "$SRC/astmatcher-lsp/astmatcher_lsp" "$SHAREDIR/"
  find "$SHAREDIR/astmatcher_lsp" -name __pycache__ -type d -prune -exec rm -rf {} +
fi
cp "$SRC"/data/*.json "$SHAREDIR/data/"
cp "$SRC/astmatcher-lsp/README.md" "$SHAREDIR/README.md"
step "server       $SHAREDIR"

cat > "$BINDIR/astmatcher-lsp" <<EOF
#!/bin/sh
# GENERATED by deploy-rhel.sh — AST matcher DSL language server launcher.
#   astmatcher-lsp --stdio            speak LSP over stdin/stdout
#   astmatcher-lsp --check f.query    type-check a script
ASTMATCHER_DATA="\${ASTMATCHER_DATA:-$SHAREDIR/data}" \\
PYTHONPATH="$SHAREDIR\${PYTHONPATH:+:\$PYTHONPATH}" \\
  exec "\${ASTMATCHER_PYTHON:-$PYTHON}" -m astmatcher_lsp "\$@"
EOF
chmod 0755 "$BINDIR/astmatcher-lsp"
step "launcher     $BINDIR/astmatcher-lsp"

if [ -n "$VSIX" ]; then
  cp "$VSIX" "$VSIXDIR/"
  VSIX=$VSIXDIR/$(basename -- "$VSIX")
  step "vsix         $VSIX"
fi

# ---------------------------------------------------------------- vim files
if [ "$DO_VIM" = 1 ]; then
  log "installing Vim files"
  for target in "$HOME/.vim" "$HOME/.config/nvim"; do
    [ -d "$target" ] || [ "$target" = "$HOME/.vim" ] || continue
    for d in syntax ftdetect ftplugin autoload dict; do
      mkdir -p "$target/$d"
      cp "$SRC/vim/$d/"* "$target/$d/"
    done
    step "vim          $target"
  done
  cat <<EOF

  Add to your vimrc / init.vim:
      let g:astmatcher_lsp = '$BINDIR/astmatcher-lsp'
$([ -n "$CLANG_QUERY" ] && printf "      let g:astmatcher_clang_query = '%s'\n" "$CLANG_QUERY")
EOF
fi

# ---------------------------------------------------------------- extension
CODE=""
if [ "$DO_EXT" = 1 ] || [ "$DO_CONFIG" = 1 ]; then
  CODE=$(find_code || true)
  [ -n "$CODE" ] && step "code CLI     $CODE" || warn "no VS Code CLI found (pass --code, or use --server-only)"
fi

if [ "$DO_EXT" = 1 ] && [ -n "$CODE" ] && [ -n "$VSIX" ]; then
  log "installing the extension"
  "$CODE" --install-extension "$VSIX" --force || \
    warn "extension install failed; run: code --install-extension $VSIX"
elif [ "$DO_EXT" = 1 ]; then
  [ -n "$VSIX" ] || warn "no vsix to install"
fi

# ---------------------------------------------------------------- settings
if [ "$DO_CONFIG" = 1 ]; then
  log "configuring VS Code"
  while read -r settings; do
    [ -n "$settings" ] || continue
    mkdir -p "$(dirname -- "$settings")"
    ASTM_SERVER=$BINDIR/astmatcher-lsp \
    ASTM_PYTHON=$PYTHON \
    ASTM_CLANG_QUERY=$CLANG_QUERY \
    ASTM_SAMPLE=$SAMPLE \
    ASTM_FLAGS=$FLAGS \
    "$PYTHON" - "$settings" <<'PY'
import json, os, re, sys

path = sys.argv[1]
try:
    raw = open(path, encoding="utf-8").read()
except FileNotFoundError:
    raw = ""
if raw.strip():
    # settings.json allows comments and trailing commas; strip enough to load.
    no_str = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: " " * len(m.group()), raw)
    keep, i = [], 0
    for m in re.finditer(r"//[^\n]*|/\*.*?\*/", no_str, re.S):
        keep.append(raw[i:m.start()]); i = m.end()
    keep.append(raw[i:])
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(keep))
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        sys.exit(f"cannot parse {path}: {exc} — fix it or pass --skip-config")
    if not isinstance(data, dict):
        sys.exit(f"{path} is not a JSON object")
else:
    data = {}

env = os.environ
new = {
    "astmatcher.server.enabled": True,
    "astmatcher.server.path": env["ASTM_SERVER"],
    "astmatcher.server.python": env["ASTM_PYTHON"],
    "astmatcher.sample": env["ASTM_SAMPLE"],
    "astmatcher.flags": env["ASTM_FLAGS"].split(),
}
if env.get("ASTM_CLANG_QUERY"):
    new["astmatcher.clangQueryPath"] = env["ASTM_CLANG_QUERY"]

changed = {k: v for k, v in new.items() if data.get(k) != v}
if not changed:
    print(f"   unchanged {path}")
    raise SystemExit(0)
if raw.strip():
    import shutil
    shutil.copyfile(path, path + ".bak")
    if re.search(r"//[^\n]*|/\*.*?\*/", no_str, re.S):
        print(f"   note: comments dropped, original kept as {path}.bak")
data.update(new)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(f"   wrote {path} ({', '.join(sorted(changed))})")
PY
  done <<EOF
$(default_settings_files)
EOF
  [ "$DO_EXT" = 1 ] && [ -n "$CODE" ] && \
    warn "reload the VS Code window (or run 'AST Matcher: Restart Language Server')"
fi

# ---------------------------------------------------------------- verify
log "verifying"
tmpd=$(mktemp -d); trap 'rm -rf "$tmpd"' EXIT
q=$tmpd/verify.query
printf 'match functionDecl(hasName("main"))\n' > "$q"
if "$BINDIR/astmatcher-lsp" --check "$q" >/dev/null; then
  step "analyzer     ok"
else
  die "the installed server failed to type-check a trivial query"
fi
if [ -n "$CLANG_QUERY" ] && [ -f "$LAB/manifests/intro.cpp" ]; then
  # shellcheck disable=SC2086  # FLAGS is a flag list, split on purpose
  if "$BINDIR/astmatcher-lsp" --run "$q" --sample "$LAB/manifests/intro.cpp" \
       --clang-query "$CLANG_QUERY" -- $FLAGS >/dev/null 2>&1; then
    step "clang-query  ok"
  else
    warn "the server could not run clang-query — check --clang-query and the flags"
  fi
fi

cat <<EOF

$(log "installed")
  server      $BINDIR/astmatcher-lsp
  data        $SHAREDIR/data
  extension   ${VSIX:-(not built)}
  PATH        export PATH="$BINDIR:\$PATH"
EOF
