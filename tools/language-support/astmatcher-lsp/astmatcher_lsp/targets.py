"""Target discovery and compilation database helpers for query runs."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from pathlib import PurePosixPath
import subprocess

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm", ".cu"}
def _glob_match(relative: str, pattern: str) -> bool:
    def regex(glob: str) -> str:
        out, i = ["^"], 0
        while i < len(glob):
            if glob[i:i + 2] == "**":
                if i + 2 < len(glob) and glob[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
            elif glob[i] == "*":
                out.append("[^/]*")
                i += 1
            elif glob[i] == "?":
                out.append("[^/]")
                i += 1
            elif glob[i] == "[":
                close = glob.find("]", i + 1)
                if close < 0:
                    out.append(r"\[")
                    i += 1
                else:
                    out.append(glob[i:close + 1])
                    i = close + 1
            else:
                out.append(re.escape(glob[i]))
                i += 1
        out.append("$")
        return "".join(out)
    return re.match(regex(pattern), relative) is not None


def _ignored(path: Path, base: Path) -> bool:
    ignored = False
    ancestors = list(reversed([base, *base.parents]))
    ancestors.extend(parent for parent in reversed(path.parents)
                     if parent.is_relative_to(base) and parent not in ancestors)
    for ignore_base in ancestors:
        ignore_file = ignore_base / ".gitignore"
        if not ignore_file.is_file():
            continue
        try:
            patterns = ignore_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in patterns:
            pattern = raw.strip()
            if not pattern or pattern.startswith("#"):
                continue
            negate = pattern.startswith("!")
            if negate:
                pattern = pattern[1:]
            directory_only = pattern.endswith("/")
            pattern = pattern.rstrip("/")
            anchored = pattern.startswith("/")
            if anchored:
                pattern = pattern[1:]
            rel = path.relative_to(ignore_base).as_posix()
            candidates = [rel] if anchored or "/" in pattern else list(PurePosixPath(rel).parts)
            matched = any(_glob_match(candidate, pattern) for candidate in candidates)
            if directory_only and not path.is_dir():
                parts = PurePosixPath(rel).parts
                parents = ["/".join(parts[:i]) for i in range(1, len(parts))]
                matched = any(_glob_match(candidate, pattern)
                              for parent in parents for candidate in
                              ([parent] if anchored or "/" in pattern else
                               list(PurePosixPath(parent).parts)))
            if matched:
                ignored = not negate
    return ignored


def _git_ignored(paths: list[Path], root: Path) -> set[Path] | None:
    """Use Git's own ignore implementation when a repository is available."""
    try:
        repo = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=2)
        if repo.returncode:
            return None
        top = Path(repo.stdout.strip()).resolve()
        names = [str(path.resolve().relative_to(top)) for path in paths]
        check = subprocess.run(["git", "-C", str(top), "check-ignore", "--no-index",
                                "-z", "--stdin"], input="\0".join(names) + "\0",
                               capture_output=True, text=True, timeout=5)
        return {top / name for name in check.stdout.split("\0") if name}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def discover_target(target: dict | None, sample: str, cwd: str,
                    exclusions: list[str] | None = None) -> tuple[dict, list[str]]:
    """Return normalized target metadata and sorted translation-unit paths."""
    target = dict(target or {})
    scope = target.get("scope", "file")
    if scope not in {"file", "directory", "workspace"}:
        raise ValueError("target.scope must be file, directory, or workspace")
    raw_path = target.get("path") or sample
    path = Path(raw_path if os.path.isabs(raw_path) else os.path.join(cwd, raw_path)).absolute()
    roots = target.get("roots") or ([str(path)] if scope != "workspace" else [str(path)])
    roots = [str(Path(p if os.path.isabs(p) else os.path.join(cwd, p)).absolute())
             for p in roots]
    if scope == "file":
        files = ([str(path)] if path.is_file() and not _ignored(path, path.parent) and not any(
            _glob_match(path.name, glob) or _glob_match(path.as_posix(), glob)
            for glob in exclusions or []) else [])
        base = path.parent
    else:
        scan_roots = roots if scope == "workspace" else [str(path)]
        base = Path(scan_roots[0])
        files = []
        for root_name in scan_roots:
            root = Path(root_name)
            if not root.is_dir():
                continue
            candidates: list[Path] = []
            for current, dirs, names in os.walk(root):
                current_path = Path(current)
                dirs[:] = [name for name in dirs if name != ".git" and
                           not any((_glob_match((current_path / name).relative_to(root).as_posix(), glob)
                                    or ("/" not in glob and _glob_match(name, glob)))
                                   for glob in exclusions or [])]
                candidates.extend(current_path / name for name in names
                                  if (current_path / name).suffix.lower() in SOURCE_SUFFIXES)
            ignored_by_git = _git_ignored(candidates + [p for c in candidates for p in c.parents
                                                        if p.is_dir() and p.is_relative_to(root)], root)
            for candidate in candidates:
                if not candidate.is_file() or candidate.suffix.lower() not in SOURCE_SUFFIXES:
                    continue
                rel = candidate.relative_to(root)
                if any((_glob_match(rel.as_posix(), glob) or
                        ("/" not in glob and _glob_match(candidate.name, glob)))
                       for glob in exclusions or []):
                    continue
                if (".git" in rel.parts or
                        (ignored_by_git is not None and candidate.resolve() in ignored_by_git) or
                        (ignored_by_git is None and _ignored(candidate, root))):
                    continue
                files.append(str(candidate.absolute()))
    files = sorted(set(files))
    return {"scope": scope, "path": str(path), "roots": roots}, files


# Build directories a compilation database is conventionally written to.
DATABASE_DIRECTORIES = ("", "build", "out", "cmake-build-debug", "cmake-build-release")

_DISCOVERED: dict[str, str | None] = {}


def find_compile_database(source: str) -> str | None:
    """The nearest compile_commands.json at or above `source`, if any."""
    start = Path(source).resolve()
    if not start.is_dir():
        start = start.parent
    key = str(start)
    if key in _DISCOVERED:
        return _DISCOVERED[key]
    found = None
    for directory in (start, *start.parents):
        for build in DATABASE_DIRECTORIES:
            candidate = (directory / build / "compile_commands.json") if build \
                else directory / "compile_commands.json"
            if candidate.is_file():
                found = str(candidate)
                break
        if found:
            break
    _DISCOVERED[key] = found
    return found


def _entry_file(entry: dict) -> Path:
    directory = Path(entry["directory"])
    file = Path(entry["file"])
    return (file if file.is_absolute() else directory / file).resolve()


def _relatedness(entry_file: Path, target: Path) -> int | None:
    """How close an entry's TU is to `target`; lower is better, None unrelated."""
    if entry_file.parent == target.parent:
        return 0 if entry_file.stem == target.stem else 1
    common = 0
    for a, b in zip(entry_file.parent.parts, target.parent.parts):
        if a != b:
            break
        common += 1
    if common <= 1:                 # only "/" (or a drive) in common
        return None
    return 2 + (len(target.parent.parts) - common)


def _merge_flags(database: list[str], explicit: list[str]) -> list[str]:
    """Database flags win: an explicit -std= or repeated flag would override them."""
    out = list(database)
    has_std = any(flag.startswith(("-std=", "--std=")) for flag in database)
    for flag in explicit:
        if has_std and flag.startswith(("-std=", "--std=")):
            continue
        if flag in out:
            continue
        out.append(flag)
    return out


def compile_flags(database: str | None, source: str, explicit: list[str], cwd: str
                  ) -> tuple[list[str], str | None]:
    """Get flags and working directory for a source from compile_commands.json.

    `database` is a file, a build directory, `"auto"` (find the nearest
    compile_commands.json at or above the source), or empty (flags as given).

    A header is never its own entry in the database, so when `source` has none
    the flags of the closest related translation unit are used: the same-stem
    source next to it first, then any TU in that directory, then the nearest
    enclosing one. Without a database, or with no related entry at all, the
    caller's explicit flags are used as they are.
    """
    if not database:
        return list(explicit), None
    if database == "auto":
        database = find_compile_database(source)
        if not database:
            return list(explicit), None
    db_path = Path(database if os.path.isabs(database) else os.path.join(cwd, database))
    if db_path.is_dir():
        db_path = db_path / "compile_commands.json"
    entries = json.loads(db_path.read_text(encoding="utf-8"))
    target = Path(source).resolve()

    chosen: dict | None = None
    best_rank: int | None = None
    for entry in entries:
        try:
            resolved = _entry_file(entry)
        except KeyError:
            continue
        if resolved == target:
            chosen, best_rank = entry, -1
            break
        rank = _relatedness(resolved, target)
        if rank is not None and (best_rank is None or rank < best_rank):
            chosen, best_rank = entry, rank

    if chosen is None:
        if explicit:
            return list(explicit), None
        raise ValueError(f"no compile_commands.json entry for {source}")

    directory = Path(chosen["directory"])
    entry_file = _entry_file(chosen)
    args = chosen.get("arguments") or shlex.split(chosen.get("command", ""))
    args = list(args)
    if args:
        args.pop(0)
    out: list[str] = []
    skip_operand = False
    option_operand = False
    operand_options = {"-include", "-include-pch", "-imacros", "-I", "-isystem",
                       "-iquote", "-idirafter", "-isysroot", "-D", "-U", "-x",
                       "-std", "-target", "--target", "-stdlib", "-Xclang",
                       "-resource-dir", "-fmodule-map-file"}
    for arg in args:
        if skip_operand:
            skip_operand = False
            continue
        if option_operand:
            out.append(arg)
            option_operand = False
            continue
        if arg in {"-o", "-MF", "-MT", "-MQ"}:
            skip_operand = True
        elif arg in {"-c", "-MMD", "-MD", "-MP"}:
            continue
        else:
            out.append(arg)
            if arg in operand_options:
                option_operand = True
                continue
            if not arg.startswith("-"):
                candidate = Path(arg)
                if not candidate.is_absolute():
                    candidate = directory / candidate
                if candidate.resolve() == entry_file:
                    out.pop()
    return _merge_flags(out, explicit), str(directory)


def translation_unit_dependencies(source: str, flags: list[str], cwd: str,
                                  compiler: str | None = None) -> list[str] | None:
    """Ask Clang for the full include dependency set; None means caching is unsafe."""
    import shutil
    import subprocess

    compiler = compiler or shutil.which("clang") or shutil.which("clang++")
    if not compiler:
        return None
    cmd = [compiler, "-M", "-MT", "astmatcher-cache", *flags, source]
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                                timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    dep_text = result.stdout.replace("\\\n", " ")
    _, _, deps = dep_text.partition(":")
    paths = []
    for dep in shlex.split(deps):
        path = Path(dep)
        if not path.is_absolute():
            path = Path(cwd) / path
        if path.is_file():
            paths.append(str(path.resolve()))
    return paths
