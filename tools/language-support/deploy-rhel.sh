#!/usr/bin/env bash
# Build and install the AST Matcher DSL tooling (native matcher server, Python
# language server, VS Code extension + optional Vim files) on RHEL / Rocky / Alma / Fedora.
#
#   ./deploy-rhel.sh
#
# Everything lands under --prefix (the install root); nothing is written
# outside it except the VS Code extension and user settings, which live in the
# invoking user's VS Code directories. Run --help for all options.
set -euo pipefail

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LAB=$(CDPATH= cd -- "$SRC/../.." && pwd)

PREFIX="$HOME/.local/astmatcher"
PYTHON=""
CODE_CLI=""
LLVM_PREFIX="${LLVM:-/usr}"
NATIVE_BUILD_DIR="$SRC/native/build-rhel"
VSIX=""
VSCE_SPEC=""
SETTINGS_FILES=()
SAMPLE=""
FLAGS=""
FLAGS_SET=0
COMPILE_DB=""
DO_DEPS=1
DO_REGEN=0
DO_TESTS=1
DO_VSIX=1
DO_EXT=1
DO_CONFIG=1
DO_VIM=0
DO_UNINSTALL=0
MANUAL=auto
EXTDIR=""
OFFLINE=0
AUTO_MODE=1

log()  { printf '\033[1;32m==\033[0m %s\n' "$*"; }
step() { printf '\033[1;34m--\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options
  -p, --prefix DIR       install root (default: ~/.local/astmatcher)
      --install-deps     enable build repositories and install native build dependencies (default)
      --skip-deps        use already installed build dependencies
      --python PATH      Python 3.10+ interpreter (default: autodetect)
      --llvm DIR         LLVM prefix for the native build and --regenerate (default: $LLVM or /usr)
      --native-build-dir DIR  native CMake build directory (default: native/build-rhel)
      --code PATH        VS Code CLI (default: code, codium, remote-cli/code)
      --vsix FILE        install this prebuilt .vsix instead of building one
      --vsce SPEC        npx spec for the packager (default: picked per node major)
      --extensions-dir D VS Code extensions dir for the filesystem install
      --install-manual   always install by unpacking the vsix into that dir
      --no-manual        never do that; only use the VS Code CLI
      --settings FILE    VS Code settings.json to configure (repeatable; it is
                         rewritten as plain JSON, comments dropped, .bak kept)
      --sample PATH      astmatcher.sample default (default: <lab>/manifests/intro.cpp)
      --flags "A B"      astmatcher.flags default (default: -std=c++23)
      --compile-commands P  astmatcher.compileCommands: a compile_commands.json,
                         a build directory, or "auto" (the default: the nearest
                         one at or above each file, also under build/ or out/)
      --regenerate       generate installed catalog from --llvm headers on LLVM 22 too
      --vim              also install the Vim/Neovim files for this user
      --offline          npm ci --offline, no npx download (needs a warm cache)
      --skip-tests       skip native, Python, JavaScript and corpus tests
      --skip-extension   build the vsix but do not install it into VS Code
      --skip-config      do not touch VS Code settings.json
      --server-only      no vsix, no extension, no settings (implies the above)
      --uninstall        remove the installed tree and the extension
  -h, --help             this text

With no options, the script installs dependencies and uses the default prefix.
It installs the VS Code extension when VS Code is present on this host.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in -p|--prefix) ;; *) AUTO_MODE=0;; esac
  case "$1" in
    -p|--prefix)      PREFIX=${2:?}; shift 2;;
    --install-deps)   DO_DEPS=1; shift;;
    --skip-deps)      DO_DEPS=0; shift;;
    --python)         PYTHON=${2:?}; shift 2;;
    --llvm)           LLVM_PREFIX=${2:?}; shift 2;;
    --native-build-dir) NATIVE_BUILD_DIR=${2:?}; shift 2;;
    --code)           CODE_CLI=${2:?}; shift 2;;
    --vsix)           VSIX=${2:?}; DO_VSIX=0; shift 2;;
    --vsce)           VSCE_SPEC=${2:?}; shift 2;;
    --settings)       SETTINGS_FILES+=("${2:?}"); shift 2;;
    --extensions-dir) EXTDIR=${2:?}; shift 2;;
    --install-manual) MANUAL=always; shift;;
    --no-manual)      MANUAL=never; shift;;
    --sample)         SAMPLE=${2:?}; shift 2;;
    --flags)          [ "$#" -ge 2 ] || die "--flags needs a value"; FLAGS=$2; FLAGS_SET=1; shift 2;;
    --compile-commands) COMPILE_DB=${2:?}; shift 2;;
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

case "$PREFIX" in /*) ;; *) PREFIX=$(CDPATH= cd -- "$(dirname -- "$PREFIX")" 2>/dev/null && pwd)/$(basename -- "$PREFIX") || die "cannot resolve --prefix";; esac
case "$NATIVE_BUILD_DIR" in /*) ;; *) NATIVE_BUILD_DIR="$PWD/$NATIVE_BUILD_DIR";; esac

[ -n "$SAMPLE" ] || SAMPLE=$LAB/manifests/intro.cpp
[ "$FLAGS_SET" = 1 ] || FLAGS="-std=c++23"

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
  # Remote-SSH / devcontainer: the server ships remote-cli/code, but it drives
  # the running window through $VSCODE_IPC_HOOK_CLI and fails without it.
  [ -n "${VSCODE_IPC_HOOK_CLI:-}" ] || return 0
  find "$HOME"/.vscode-server "$HOME"/.vscode-server-insiders \
       "$HOME"/.vscode-remote -maxdepth 6 -type f -name code -path '*remote-cli*' \
       2>/dev/null | while read -r c; do
    [ -x "$c" ] || continue
    printf '%s %s\n' "$(stat -c %Y "$c" 2>/dev/null || stat -f %m "$c" 2>/dev/null)" "$c"
  done | sort -rn | head -1 | cut -d' ' -f2-
}

# Where VS Code looks for extensions on this host.
extensions_dir() {
  [ -n "$EXTDIR" ] && { printf '%s\n' "$EXTDIR"; return; }
  [ -n "${VSCODE_EXTENSIONS:-}" ] && { printf '%s\n' "$VSCODE_EXTENSIONS"; return; }
  local d
  for d in "$HOME/.vscode-server/extensions" "$HOME/.vscode-server-insiders/extensions" \
           "$HOME/.vscode-remote/extensions" "$HOME/.vscode/extensions" \
           "$HOME/.vscode-oss/extensions"; do
    [ -d "$d" ] && { printf '%s\n' "$d"; return; }
  done
  if [ -d "$HOME/.vscode-server" ]; then printf '%s\n' "$HOME/.vscode-server/extensions"
  else printf '%s\n' "$HOME/.vscode/extensions"; fi
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

has_vscode() {
  [ -n "$CODE_CLI" ] && return 0
  [ -n "${VSCODE_EXTENSIONS:-}" ] && return 0
  [ -n "$(find_code)" ] && return 0
  local d
  for d in "$HOME/.vscode-server" "$HOME/.vscode-server-insiders" \
           "$HOME/.vscode-remote" "$HOME/.vscode" "$HOME/.vscode-oss" \
           "$HOME/.config/Code" "$HOME/.config/VSCodium"; do
    [ -d "$d" ] && return 0
  done
  return 1
}

if [ "$AUTO_MODE" = 1 ] && ! has_vscode; then
  DO_VSIX=0
  DO_EXT=0
  DO_CONFIG=0
  warn "VS Code is absent; installing the native server and language server only"
fi


# Install (or remove) the extension by unpacking it into the extensions
# directory and registering it in extensions.json — what the CLI does for us
# when it is reachable. VS Code picks it up on the next window reload.
manual_extension() {
  local mode=$1 vsix=${2:-} dir
  dir=$(extensions_dir)
  mkdir -p "$dir"
  "${PYTHON:-python3}" - "$mode" "$dir" "$vsix" <<'PYX'
import json, os, pathlib, re, shutil, stat, sys, tempfile, time, zipfile

mode, extdir, vsix = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3]
EXT_ID = "ast-matchers-lab.astmatcher-dsl"
manifest = extdir / "extensions.json"

entries = []
if manifest.exists():
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        entries = []
    if not isinstance(entries, list):
        entries = []

def ident_of(entry):
    return ((entry.get("identifier") or {}).get("id") or "").lower()

def write_manifest(items):
    manifest.write_text(json.dumps(items, indent=0) + "\n", encoding="utf-8")

if mode == "remove":
    kept = [e for e in entries if ident_of(e) != EXT_ID.lower()]
    for d in extdir.glob(EXT_ID + "-*"):
        shutil.rmtree(d, ignore_errors=True)
    if len(kept) != len(entries):
        write_manifest(kept)
    print(f"   removed {EXT_ID} from {extdir}")
    raise SystemExit(0)

with zipfile.ZipFile(vsix) as z:
    seen = set()
    for info in z.infolist():
        name = info.filename
        parts = name.split("/")
        if info.is_dir():
            parts.pop()
        kind = stat.S_IFMT(info.external_attr >> 16)
        expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
        if (not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name)
                or "\\" in name or any(part in ("", ".", "..") for part in parts)
                or kind not in (0, expected) or name in seen):
            raise SystemExit(f"unsafe VSIX entry: {name!r}")
        seen.add(name)
    pkg = json.loads(z.read("extension/package.json"))
    ident = f'{pkg.get("publisher")}.{pkg.get("name")}'
    version = pkg.get("version")
    if ident != EXT_ID or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*", version):
        raise SystemExit("VSIX package identity or version is invalid")
    rel = f"{ident}-{version}"
    dest = extdir / rel
    with tempfile.TemporaryDirectory(prefix=f".{rel}-", dir=extdir) as staged:
        stage = pathlib.Path(staged)
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith("extension/"):
                continue
            target = stage / info.filename[len("extension/"):]
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            bits = (info.external_attr >> 16) & 0o7777
            if bits & 0o111:
                os.chmod(target, bits)
        if dest.is_symlink():
            raise SystemExit(f"refusing symlink extension destination: {dest}")
        if dest.exists():
            shutil.rmtree(dest)
        stage.rename(dest)

# Two copies of the same extension would both load.
for old in extdir.glob(ident + "-*"):
    if old.is_dir() and old != dest:
        shutil.rmtree(old, ignore_errors=True)

entries = [e for e in entries if ident_of(e) != ident.lower()]
entries.append({
    "identifier": {"id": ident},
    "version": version,
    "location": {"$mid": 1, "path": str(dest), "scheme": "file"},
    "relativeLocation": rel,
    "metadata": {"installedTimestamp": int(time.time() * 1000),
                 "source": "vsix", "pinned": True},
})
write_manifest(entries)
print(f"   unpacked {ident}@{version} into {dest}")
PYX
}

# ---------------------------------------------------------------- uninstall
if [ "$DO_UNINSTALL" = 1 ]; then
  log "uninstalling from $PREFIX"
  rm -rf "$SHAREDIR" "$VSIXDIR" "$BINDIR/astmatcher-lsp" "$BINDIR/astmatcher-native"
  code=$(find_code || true)
  if [ -n "$code" ]; then
    "$code" --uninstall-extension ast-matchers-lab.astmatcher-dsl || \
      warn "the VS Code CLI could not uninstall it"
  fi
  manual_extension remove || true
  warn "VS Code settings left untouched (astmatcher.* keys still point here)"
  log "done"
  exit 0
fi

# The dependency stage uses the same interpreter probe as the toolchain check.
pick_python() {
  if [ -n "$PYTHON" ]; then
    "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null || return 1
    printf '%s\n' "$PYTHON"
    return
  fi
  local p
  for p in python3.13 python3.12 python3.11 python3.10 python3; do
    have "$p" || continue
    "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null \
      && { command -v "$p"; return; }
  done
  return 1
}

# ---------------------------------------------------------------- dependencies
if [ "$DO_DEPS" = 1 ]; then
  log "installing distro packages"
  SUDO=""; [ "$(id -u)" = 0 ] || SUDO=sudo
  have dnf || die "--install-deps needs dnf (RHEL/Rocky/Alma/Fedora)"
  [ -f /etc/os-release ] || die "cannot identify the Linux distribution"
  repo_enabled() {
    dnf -q repolist --enabled | awk -v wanted="$1" \
      '$1 == wanted {found = 1} END {exit !found}'
  }
  # shellcheck disable=SC1091
  . /etc/os-release
  os_major=${VERSION_ID%%.*}
  [ -z "$PYTHON" ] || pick_python >/dev/null || die "--python must point to Python 3.10 or newer"
  pkgs=(cmake make gcc-c++ clang-devel llvm-devel grpc-devel grpc-plugins protobuf-devel protobuf-compiler)
  if ! pick_python >/dev/null; then
    if dnf -y list python3.12 >/dev/null 2>&1; then pkgs+=(python3.12)
    elif dnf -y list python3.11 >/dev/null 2>&1; then pkgs+=(python3.11)
    elif dnf -y list python3.10 >/dev/null 2>&1; then pkgs+=(python3.10)
    else pkgs+=(python3.11)
    fi
  fi
  [ "$DO_VSIX" = 1 ] && pkgs+=(nodejs npm)
  if [ "$ID" = rhel ] && have rpm && rpm -q "${pkgs[@]}" >/dev/null 2>&1; then
    step "build packages already installed"
  else
    [ -z "$SUDO" ] || have sudo || die "sudo is required to install missing dependencies; use --skip-deps if all packages are already installed"
    case "$ID" in
    rocky|almalinux)
      if ! repo_enabled crb; then
        $SUDO dnf -y install dnf-plugins-core || die "cannot install dnf config-manager"
        $SUDO dnf config-manager --set-enabled crb || die "cannot enable CRB"
      fi
      if ! repo_enabled epel; then
        $SUDO dnf -y install epel-release || die "cannot install EPEL release package"
        $SUDO dnf config-manager --set-enabled epel || die "cannot enable EPEL"
      fi
      ;;
    # RHEL installations can already have the packages through RHUI or a
    # private mirror, even when subscription-manager is absent or unregistered.
    rhel) ;;
    fedora) ;;
    *) die "unsupported distribution $ID; use RHEL, Rocky, AlmaLinux, or Fedora";;
    esac
    if [ "$DO_VSIX" = 1 ] && ! have node && \
       $SUDO dnf -y module list nodejs >/dev/null 2>&1; then
      $SUDO dnf -y module reset nodejs || true
      $SUDO dnf -y module enable nodejs:20 || warn "nodejs:20 module unavailable; using the default stream"
    fi
    if [ "$ID" = rhel ]; then
      enable_epel() {
        repo_enabled epel && return 0
        if ! rpm -q epel-release >/dev/null 2>&1; then
          $SUDO dnf -y install "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${os_major}.noarch.rpm" || \
            warn "could not install the Fedora EPEL release package"
        fi
        if ! repo_enabled epel; then
          if $SUDO dnf -y install dnf-plugins-core; then
            $SUDO dnf config-manager --set-enabled epel || warn "could not enable EPEL"
          fi
        fi
      }
      # Try the host's configured repositories first. Only bootstrap public
      # repositories when they cannot satisfy the requested packages.
      if ! $SUDO dnf -y install "${pkgs[@]}"; then
        enable_epel
        if ! $SUDO dnf -y install "${pkgs[@]}"; then
          deps_ready=0
          if have crb; then
            if $SUDO crb enable; then
              enable_epel
              $SUDO dnf -y install "${pkgs[@]}" && deps_ready=1
            else
              warn "could not enable CodeReady Builder through the crb helper"
            fi
          fi
          if [ "$deps_ready" = 0 ]; then
            crb_repo="codeready-builder-for-rhel-${os_major}-$(uname -m)-rpms"
            if ! repo_enabled "$crb_repo" && have subscription-manager; then
              $SUDO subscription-manager repos --enable "$crb_repo" >/dev/null || \
                warn "could not enable $crb_repo through subscription-manager"
            fi
            enable_epel
            $SUDO dnf -y install "${pkgs[@]}" || die \
              "dnf cannot install required build packages (including Python 3.11 if needed); configure repositories with clang-devel, llvm-devel, grpc-devel, grpc-plugins and protobuf-devel, or register this RHEL host and enable CodeReady Builder and EPEL; rerun with --skip-deps if all packages are already installed"
          fi
        fi
      fi
    else
      $SUDO dnf -y install "${pkgs[@]}" || die \
        "native build dependencies unavailable; enable CRB/CodeReady Builder and EPEL 9 for protobuf-devel, grpc-devel and grpc-plugins"
    fi
  fi
fi

# ---------------------------------------------------------------- toolchain
log "checking the toolchain"
PYTHON=$(pick_python) || die "no Python 3.10+ found (dnf install python3.11, or pass --python)"
step "python       $PYTHON ($("$PYTHON" -c 'import platform;print(platform.python_version())'))"

have cmake || die "cmake not found (dnf install cmake, or pass --install-deps)"
step "cmake        $(cmake --version | head -1)"
LLVM_CONFIG=$LLVM_PREFIX/bin/llvm-config
[ -x "$LLVM_CONFIG" ] || die "llvm-config not found at $LLVM_CONFIG (pass --llvm /path/to/llvm)"
llvm_version=$("$LLVM_CONFIG" --version)
llvm_major=${llvm_version%%.*}
[[ "$llvm_major" =~ ^[0-9]+$ ]] || die "cannot read LLVM version from $LLVM_CONFIG"
[ "$llvm_major" -ge 21 ] || die \
  "LLVM $llvm_version is too old; native queries require LLVM 21+"
LLVM_CMAKE_DIR=$("$LLVM_CONFIG" --cmakedir)
[ -f "$LLVM_CMAKE_DIR/LLVMConfig.cmake" ] || \
  die "LLVM CMake package not found at $LLVM_CMAKE_DIR (dnf install llvm-devel)"
CLANG_CMAKE_DIR=$(dirname -- "$LLVM_CMAKE_DIR")/clang
if [ ! -f "$CLANG_CMAKE_DIR/ClangConfig.cmake" ]; then
  for candidate in "$LLVM_PREFIX/lib64/cmake/clang" "$LLVM_PREFIX/lib/cmake/clang"; do
    if [ -f "$candidate/ClangConfig.cmake" ]; then
      CLANG_CMAKE_DIR=$candidate
      break
    fi
  done
fi
[ -f "$CLANG_CMAKE_DIR/ClangConfig.cmake" ] || \
  die "Clang CMake package not found beside LLVM (dnf install clang-devel)"
step "LLVM         $llvm_version ($LLVM_PREFIX)"
if [ "$llvm_major" -eq 21 ]; then
  step "catalog      generating LLVM 21 data from the installed Clang registry"
fi

if [ "$DO_VSIX" = 1 ]; then
  have npm || die "npm not found (dnf install nodejs npm, or pass --vsix)"
  NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  step "node         $(node --version 2>/dev/null || echo '?')  npm $(npm --version)"
  if [ -z "$VSCE_SPEC" ]; then
    if [ "$NODE_MAJOR" -ge 20 ]; then VSCE_SPEC='@vscode/vsce@^3'; else VSCE_SPEC='@vscode/vsce@2.32.0'; fi
  fi
fi

# ---------------------------------------------------------------- native server
log "building astmatcher-native"
NATIVE_PREFIX_PATH="$LLVM_PREFIX${CMAKE_PREFIX_PATH:+;$CMAKE_PREFIX_PATH}"
cmake -S "$SRC/native" -B "$NATIVE_BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$NATIVE_PREFIX_PATH" \
  -DLLVM_DIR="$LLVM_CMAKE_DIR" -DClang_DIR="$CLANG_CMAKE_DIR" \
  -DPython3_EXECUTABLE="$PYTHON"
cmake --build "$NATIVE_BUILD_DIR" --target astmatcher-native --parallel "${JOBS:-4}"
NATIVE_EXEC=$NATIVE_BUILD_DIR/astmatcher-native
[ -x "$NATIVE_EXEC" ] || die "native build produced no $NATIVE_EXEC"
export ASTMATCHER_NATIVE=$NATIVE_EXEC
step "native       $NATIVE_EXEC"

# The checked-in catalog is generated with LLVM 22. Generate into the build
# tree on other versions, then ask the linked Clang registry which names are
# actually registered; this keeps the source checkout and installed editor in
# sync with their respective LLVM versions.
LANGUAGE_ROOT=$SRC
if [ "$llvm_major" -ne 22 ] || [ "$DO_REGEN" = 1 ]; then
  LANGUAGE_ROOT=$NATIVE_BUILD_DIR/language-support-$llvm_major
  LLVM=$LLVM_PREFIX "$PYTHON" "$SRC/generate.py" \
    --output-dir "$LANGUAGE_ROOT" --native-binary "$NATIVE_EXEC" \
    --native-llvm-major "$llvm_major"
fi

# ---------------------------------------------------------------- tests
if [ "$DO_TESTS" = 1 ]; then
  # Not check.sh: it hardcodes python3 (3.6/3.9 on RHEL), always needs node,
  # and its generate.py --check diffs against checked-in LLVM 22 files.
  log "running tests"
  ctest --test-dir "$NATIVE_BUILD_DIR" --output-on-failure
  ( cd "$SRC/astmatcher-lsp" && "$PYTHON" -m unittest discover -s tests -q )
  if [ "$DO_VSIX" = 1 ] && have node; then
    ( cd "$SRC" && node --test vscode/tests/*.test.js )
  fi
  step "catalog corpus: static checks against the checked-in LLVM 22 examples"
  ( cd "$SRC" && "$PYTHON" corpus_check.py )
  if [ "$LANGUAGE_ROOT" != "$SRC" ]; then
    ASTMATCHER_DATA=$LANGUAGE_ROOT/data \
      PYTHONPATH="$SRC/astmatcher-lsp${PYTHONPATH:+:$PYTHONPATH}" \
      "$PYTHON" - <<'PY'
from astmatcher_lsp.catalog import load
catalog = load()
assert catalog.matchers["functionDecl"].native_available is True
assert any(m.native_available is False for m in catalog.matchers.values())
PY
  fi
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
if [ -n "$VSIX" ] && [ "$LANGUAGE_ROOT" != "$SRC" ]; then
  ALIGNED_VSIX=$NATIVE_BUILD_DIR/astmatcher-dsl-llvm$llvm_major.vsix
  "$PYTHON" "$SRC/native/align_vsix.py" "$VSIX" "$LANGUAGE_ROOT" "$ALIGNED_VSIX"
  VSIX=$ALIGNED_VSIX
  step "aligned vsix $VSIX"
fi

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
cp "$LANGUAGE_ROOT"/data/*.json "$SHAREDIR/data/"
cp "$SRC/astmatcher-lsp/README.md" "$SHAREDIR/README.md"
step "server       $SHAREDIR"
install -m 0755 "$NATIVE_EXEC" "$BINDIR/astmatcher-native"
step "native       $BINDIR/astmatcher-native"

cat > "$BINDIR/astmatcher-lsp" <<EOF
#!/bin/sh
# GENERATED by deploy-rhel.sh — AST matcher DSL language server launcher.
#   astmatcher-lsp --stdio            speak LSP over stdin/stdout
#   astmatcher-lsp --check f.query    type-check a script
ASTMATCHER_DATA="\${ASTMATCHER_DATA:-$SHAREDIR/data}" \\
ASTMATCHER_NATIVE="\${ASTMATCHER_NATIVE:-$BINDIR/astmatcher-native}" \\
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
      if [ "$LANGUAGE_ROOT" != "$SRC" ] && [ -d "$LANGUAGE_ROOT/vim/$d" ]; then
        cp "$LANGUAGE_ROOT/vim/$d/"* "$target/$d/"
      else
        cp "$SRC/vim/$d/"* "$target/$d/"
      fi
    done
    step "vim          $target"
  done
  cat <<EOF

  Add to your vimrc / init.vim:
      let g:astmatcher_lsp = '$BINDIR/astmatcher-lsp'
EOF
fi

# ---------------------------------------------------------------- extension
CODE=""
if [ "$DO_EXT" = 1 ] || [ "$DO_CONFIG" = 1 ]; then
  CODE=$(find_code || true)
  [ -n "$CODE" ] && step "code CLI     $CODE" || warn "no VS Code CLI found (pass --code, or use --server-only)"
fi

if [ "$DO_EXT" = 1 ] && [ -z "$VSIX" ]; then
  warn "no vsix to install"
elif [ "$DO_EXT" = 1 ]; then
  log "installing the extension"
  installed=0
  if [ "$MANUAL" != always ] && [ -n "$CODE" ]; then
    if "$CODE" --install-extension "$VSIX" --force; then installed=1
    else warn "the VS Code CLI could not install it"; fi
  fi
  if [ "$installed" = 0 ] && [ "$MANUAL" != never ]; then
    manual_extension install "$VSIX"
    installed=1
  fi
  [ "$installed" = 1 ] || warn "extension not installed; run: code --install-extension $VSIX"
fi

# ---------------------------------------------------------------- settings
if [ "$DO_CONFIG" = 1 ]; then
  log "configuring VS Code"
  while read -r settings; do
    [ -n "$settings" ] || continue
    mkdir -p "$(dirname -- "$settings")"
    ASTM_SERVER=$BINDIR/astmatcher-lsp \
    ASTM_NATIVE=$BINDIR/astmatcher-native \
    ASTM_PYTHON=$PYTHON \
    ASTM_SAMPLE=$SAMPLE \
    ASTM_FLAGS=$FLAGS \
    ASTM_COMPILE_DB=$COMPILE_DB \
    "$PYTHON" - "$settings" <<'PY'
import json, os, shlex, sys

def clean_jsonc(source):
    # Replace comments with spaces so commas can be checked outside strings.
    out = list(source)
    quoted = escaped = commented = False
    i = 0
    while i < len(source):
        ch = source[i]
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            i += 1
        elif ch == '"':
            quoted = True
            i += 1
        elif ch == "/" and i + 1 < len(source) and source[i + 1] == "/":
            commented = True
            while i < len(source) and source[i] not in "\r\n":
                out[i] = " "
                i += 1
        elif ch == "/" and i + 1 < len(source) and source[i + 1] == "*":
            commented = True
            out[i] = out[i + 1] = " "
            i += 2
            while i + 1 < len(source) and source[i:i + 2] != "*/":
                if source[i] not in "\r\n":
                    out[i] = " "
                i += 1
            if i + 1 >= len(source):
                raise ValueError("unterminated block comment")
            out[i] = out[i + 1] = " "
            i += 2
        else:
            i += 1

    quoted = escaped = False
    for i, ch in enumerate(out):
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == ",":
            next_nonspace = i + 1
            while next_nonspace < len(out) and out[next_nonspace].isspace():
                next_nonspace += 1
            if next_nonspace < len(out) and out[next_nonspace] in "}]":
                out[i] = " "
    return "".join(out), commented

path = sys.argv[1]
try:
    raw = open(path, encoding="utf-8").read()
except FileNotFoundError:
    raw = ""
if raw.strip():
    try:
        cleaned, had_comments = clean_jsonc(raw)
        data = json.loads(cleaned)
    except (ValueError, json.JSONDecodeError) as exc:
        sys.exit(f"cannot parse {path}: {exc} — fix it or pass --skip-config")
    if not isinstance(data, dict):
        sys.exit(f"{path} is not a JSON object")
else:
    data = {}
    had_comments = False

env = os.environ
new = {
    "astmatcher.server.enabled": True,
    "astmatcher.server.path": env["ASTM_SERVER"],
    "astmatcher.server.python": env["ASTM_PYTHON"],
    "astmatcher.nativeServerPath": env["ASTM_NATIVE"],
    "astmatcher.sample": env["ASTM_SAMPLE"],
    "astmatcher.flags": shlex.split(env["ASTM_FLAGS"]),
}
if env.get("ASTM_COMPILE_DB"):
    new["astmatcher.compileCommands"] = env["ASTM_COMPILE_DB"]

removed_legacy = "astmatcher.clangQueryPath" in data
changed = {k: v for k, v in new.items() if data.get(k) != v}
if not changed and not removed_legacy:
    print(f"   unchanged {path}")
    raise SystemExit(0)
if raw.strip():
    import shutil
    shutil.copyfile(path, path + ".bak")
    if had_comments:
        print(f"   note: comments dropped, original kept as {path}.bak")
data.update(new)
data.pop("astmatcher.clangQueryPath", None)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
keys = sorted(changed) + (["removed astmatcher.clangQueryPath"] if removed_legacy else [])
print(f"   wrote {path} ({', '.join(keys)})")
PY
  done <<EOF
$(default_settings_files)
EOF
  [ "$DO_EXT" = 1 ] && \
    warn "reload the VS Code window to load the extension (Developer: Reload Window)"
fi

# ---------------------------------------------------------------- verify
log "verifying"
tmpd=$(mktemp -d)
native_pid=""
cleanup_verify() {
  if [ -n "$native_pid" ]; then
    kill "$native_pid" 2>/dev/null || true
    wait "$native_pid" 2>/dev/null || true
  fi
  rm -rf "$tmpd"
}
trap cleanup_verify EXIT
q=$tmpd/verify.query
printf 'match functionDecl(hasName("main"))\n' > "$q"
if "$BINDIR/astmatcher-lsp" --check "$q" >/dev/null; then
  step "analyzer     ok"
else
  die "the installed language server failed to type-check a trivial query"
fi
sample_file=$tmpd/verify.cpp
printf 'int main() { return 0; }\n' > "$sample_file"
socket_file=$tmpd/native.sock
"$BINDIR/astmatcher-native" serve --socket "$socket_file" \
  >"$tmpd/native.stdout" 2>"$tmpd/native.stderr" &
native_pid=$!
for ((i=0; i<50; i++)); do
  [ -S "$socket_file" ] && break
  kill -0 "$native_pid" 2>/dev/null || die "the installed native server exited before opening its socket"
  sleep 0.1
done
[ -S "$socket_file" ] || die "the installed native server did not open its Unix socket"
"$PYTHON" - "$sample_file" "$tmpd" > "$tmpd/native-request.json" <<'PY'
import json, sys
print(json.dumps({
    "sourcePath": sys.argv[1],
    "workingDirectory": sys.argv[2],
    "flags": ["-std=c++17"],
    "commands": [{"kind": "MATCH", "expression": 'functionDecl(hasName("main"))'}],
}))
PY
"$BINDIR/astmatcher-native" query --socket "$socket_file" \
  < "$tmpd/native-request.json" > "$tmpd/native-reply.json" || \
  die "the installed native gRPC query failed"
"$PYTHON" - "$tmpd/native-reply.json" <<'PY' || die "the native reply did not contain a main() match"
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    reply = json.load(fh)
assert sum(q.get("count", 0) for q in reply.get("queries", [])) >= 1, reply
PY
step "native gRPC  ok"
ASTMATCHER_NATIVE="$BINDIR/astmatcher-native" \
  "$BINDIR/astmatcher-lsp" --run "$q" --sample "$sample_file" -- -std=c++17 \
  > "$tmpd/lsp-reply.json" || die "the installed language server could not run a native query"
"$PYTHON" - "$tmpd/lsp-reply.json" <<'PY' || die "the language server reply did not contain a main() match"
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    reply = json.load(fh)
assert sum(q.get("count", 0) for q in reply.get("queries", [])) >= 1, reply
PY
step "LSP bridge   ok"

cat <<EOF

$(log "installed")
  server      $BINDIR/astmatcher-lsp
  native      $BINDIR/astmatcher-native
  data        $SHAREDIR/data
  extension   ${VSIX:-(not built)}
  PATH        export PATH="$BINDIR:\$PATH"
EOF
