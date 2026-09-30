"""Find source-specific Clang flags in a compilation database.

The search order and related-header selection follow the lab's LSP target
resolver; this module lives in the wheel so applications need no LSP install.
"""

import json
import shlex
from pathlib import Path

DATABASE_DIRECTORIES = ("", "build", "out", "cmake-build-debug",
                        "cmake-build-release")
_OPERAND_OPTIONS = {
    "-include", "-include-pch", "-imacros", "-I", "-isystem", "-iquote",
    "-idirafter", "-isysroot", "-D", "-U", "-x", "-std", "-target",
    "--target", "-stdlib", "-Xclang", "-resource-dir", "-fmodule-map-file",
}
_OUTPUT_OPTIONS = {"-o", "-MF", "-MT", "-MQ"}
_BUILD_ONLY_OPTIONS = {"-c", "-MMD", "-MD", "-MP"}


def find_compile_database(source: Path) -> Path | None:
    """Find the nearest database beside or above the source, including build dirs."""
    for directory in (source.parent, *source.parent.parents):
        for build in DATABASE_DIRECTORIES:
            candidate = directory / build / "compile_commands.json"
            if candidate.is_file():
                return candidate
    return None


def _entry_file(entry: dict) -> Path:
    directory = Path(entry["directory"])
    file = Path(entry["file"])
    return (file if file.is_absolute() else directory / file).resolve()


def _relatedness(entry_file: Path, source: Path) -> int | None:
    if entry_file.parent == source.parent:
        return 0 if entry_file.stem == source.stem else 1
    common = 0
    for left, right in zip(entry_file.parent.parts, source.parent.parts):
        if left != right:
            break
        common += 1
    if common <= 1:
        return None
    return 2 + len(source.parent.parts) - common


def _entry_flags(entry: dict) -> list[str]:
    args = entry.get("arguments")
    if args is None:
        command = entry.get("command")
        if not isinstance(command, str):
            raise ValueError("compilation database entry needs arguments or command")
        args = shlex.split(command)
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("compilation database arguments must be strings")
    args = args[1:]  # The compiler executable is not a ClangTool flag.
    directory = Path(entry["directory"])
    out: list[str] = []
    skip_operand = False
    option_operand = False
    entry_file = _entry_file(entry)
    for arg in args:
        if skip_operand:
            skip_operand = False
            continue
        if option_operand:
            out.append(arg)
            option_operand = False
            continue
        if arg in _OUTPUT_OPTIONS:
            skip_operand = True
        elif arg in _BUILD_ONLY_OPTIONS:
            continue
        else:
            out.append(arg)
            if arg in _OPERAND_OPTIONS:
                option_operand = True
                continue
            candidate = Path(arg)
            if not arg.startswith("-") and (
                candidate if candidate.is_absolute() else directory / candidate
            ).resolve() == entry_file:
                out.pop()
    return out


def compile_flags(
    database: str | Path | None,
    source: Path,
    explicit: tuple[str, ...],
    working_directory: Path,
) -> tuple[list[str], Path]:
    """Resolve the database entry and preserve its directory for relative flags."""
    if database is None:
        return list(explicit), working_directory
    if database == "auto":
        path = find_compile_database(source)
        if path is None:
            return list(explicit), working_directory
    else:
        raw = Path(database)
        path = (raw if raw.is_absolute() else working_directory / raw).resolve()
        if path.is_dir():
            path /= "compile_commands.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read compilation database {path}: {exc}") from exc
    if not isinstance(entries, list):
        raise ValueError(f"compilation database must be a JSON array: {path}")

    chosen: dict | None = None
    best_rank: int | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            entry_path = _entry_file(entry)
        except (KeyError, TypeError, ValueError):
            continue
        if entry_path == source:
            chosen = entry
            break
        rank = _relatedness(entry_path, source)
        if rank is not None and (best_rank is None or rank < best_rank):
            chosen, best_rank = entry, rank
    if chosen is None:
        if explicit:
            return list(explicit), working_directory
        raise ValueError(f"no compile_commands.json entry for {source}")

    database_flags = _entry_flags(chosen)
    has_std = any(flag.startswith(("-std=", "--std=")) for flag in database_flags)
    for flag in explicit:
        if has_std and flag.startswith(("-std=", "--std=")):
            continue
        if flag not in database_flags:
            database_flags.append(flag)
    return database_flags, Path(chosen["directory"]).resolve()
