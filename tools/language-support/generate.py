#!/usr/bin/env python3
"""Generate the matcher-DSL language-support data files.

Single source of truth in, three consumers out:

  in   scripts/catalog.json              726 AST Matcher Reference rows
       $LLVM/include/clang/AST/*.inc     real AST class hierarchies
       $LLVM/include/clang/**/*.def      cast kinds, operators, attributes

  out  data/matchers.json                name -> overloads, params, docs
       data/hierarchy.json               AST class -> base class
       data/enums.json                   string-argument value sets
       vscode/syntaxes/astmatcher.tmLanguage.json
       vscode/snippets/astmatcher.json
       vim/syntax/astmatcher.vim
       vim/dict/astmatcher.txt

Run after a brew LLVM bump or any edit to scripts/catalog.json:

    python3 tools/language-support/generate.py

`--check` regenerates into a temp dir and diffs, for CI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent.parent
CATALOG = LAB / "scripts" / "catalog.json"

# Roots and one-offs that have no x-macro database in the clang headers.
EXTRA_NODES: dict[str, str | None] = {
    "Decl": None,
    "Stmt": None,
    "Type": None,
    "TypeLoc": None,
    "QualType": None,
    "Attr": None,
    "CXXBaseSpecifier": None,
    "CXXCtorInitializer": None,
    "LambdaCapture": None,
    "NestedNameSpecifier": None,
    "NestedNameSpecifierLoc": None,
    "TemplateArgument": None,
    "TemplateArgumentLoc": None,
    "TemplateName": None,
    "OMPClause": None,
    # OpenMP clause nodes: no header database ships with the release.
    "OMPDefaultClause": "OMPClause",
    "OMPToClause": "OMPClause",
    "OMPFromClause": "OMPClause",
    "OMPCountsClause": "OMPClause",
    # Not registered in clang-query 22, but referenced by the reference rows.
    "OMPSplitDirective": "OMPExecutableDirective",
}

# clang-query session commands.
COMMANDS = {
    "match": "Match the loaded ASTs against the given matcher.",
    "m": "Alias for `match`.",
    "let": "Give a matcher expression a name, to be used later as part of other expressions.",
    "l": "Alias for `let`.",
    "set": "Change a session setting.",
    "enable": "Enable an output feature non-exclusively (`enable output <feature>`).",
    "disable": "Disable an output feature non-exclusively (`disable output <feature>`).",
    "quit": "Terminate the query session.",
    "q": "Alias for `quit`.",
    "help": "List the available commands.",
}

SET_OPTIONS = {
    "bind-root": ("bool", "Bind the root matcher to \"root\" (default true)."),
    "print-matcher": ("bool", "Print the matcher before its results."),
    "enable-profile": ("bool", "Print matcher profiling information."),
    "traversal": ("TraversalKind", "Traversal kind of the session."),
    "output": ("OutputFeature", "Output only <feature> content."),
}

OUTPUT_FEATURES = {
    "print": "Pretty-print bound nodes.",
    "diag": "Diagnostic location for bound nodes.",
    "detailed-ast": "Detailed AST output for bound nodes.",
    "dump": "Detailed AST output for bound nodes (alias of detailed-ast).",
}

TRAVERSAL_KINDS = {
    "AsIs": "Print and match the AST as clang sees it. This mode is the default.",
    "IgnoreUnlessSpelledInSource": "Omit AST nodes unless spelled in the source.",
}

# String parameters whose values come from a fixed set clang validates.
VALUE_SETS: dict[str, str] = {
    "hasOperatorName": "OperatorName",
    "hasAnyOperatorName": "OperatorName",
    "hasOverloadedOperatorName": "OverloadedOperatorName",
    "hasAnyOverloadedOperatorName": "OverloadedOperatorName",
}

# Matcher<*> helpers that still produce a node, so `match` accepts them.
TOP_LEVEL_POLYMORPHIC = {"binaryOperation", "invocation", "mapAnyOf"}

# Matchers whose string argument names a node bound earlier in the same match.
BOUND_ID_ARGS = {"equalsBoundNode", "hasBinding", "hasAnyBinding"}


# --------------------------------------------------------------------------
# clang header mining
# --------------------------------------------------------------------------

def llvm_prefix() -> Path:
    env = os.environ.get("LLVM")
    if env:
        return Path(env)
    out = subprocess.run(["brew", "--prefix", "llvm"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("cannot find LLVM: set $LLVM or install Homebrew llvm")
    return Path(out.stdout.strip())


def expand(include_dir: Path, source: str) -> list[tuple[str, str]]:
    """Run the C preprocessor over an x-macro database and collect NODE() pairs."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "nodes.c"
        src.write_text(source)
        cc = os.environ.get("CC") or str(include_dir.parent / "bin" / "clang")
        if not Path(cc).exists():
            cc = "cc"
        out = subprocess.run(
            [cc, "-E", "-P", "-nostdinc", f"-I{include_dir}", str(src)],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            sys.exit(f"preprocessing failed:\n{out.stderr}")
    return re.findall(r"NODE\(\s*([A-Za-z_][\w]*)\s*,\s*([A-Za-z_][\w]*)\s*\)", out.stdout)


def build_hierarchy(include_dir: Path) -> dict[str, str | None]:
    bases: dict[str, str | None] = {}
    databases = [
        """
        #define ABSTRACT_DECL(D) D
        #define DECL(Type, Base) NODE(Type##Decl, Base)
        #include "clang/AST/DeclNodes.inc"
        """,
        """
        #define ABSTRACT_STMT(S) S
        #define STMT(Type, Base) NODE(Type, Base)
        #include "clang/AST/StmtNodes.inc"
        """,
        """
        #define ABSTRACT_TYPE(Class, Base) NODE(Class##Type, Base)
        #define TYPE(Class, Base) NODE(Class##Type, Base)
        #include "clang/AST/TypeNodes.inc"
        """,
        """
        #define TYPELOC(Class, Base) NODE(Class##TypeLoc, Base)
        #define UNQUAL_TYPELOC(Class, Base) NODE(Class##TypeLoc, Base)
        #define ABSTRACT_TYPELOC(Class, Base) NODE(Class##TypeLoc, Base)
        #include "clang/AST/TypeLocNodes.def"
        """,
    ]
    for db in databases:
        for node, base in expand(include_dir, db):
            bases.setdefault(node, base)
    for node, base in EXTRA_NODES.items():
        bases.setdefault(node, base)
    # Every named base must exist so that walks terminate.
    for base in list(bases.values()):
        if base and base not in bases:
            bases[base] = None
    return bases


def build_enums(include_dir: Path) -> dict[str, dict[str, str]]:
    def read(rel: str) -> str:
        path = include_dir / rel
        return path.read_text() if path.exists() else ""

    ops = read("clang/AST/OperationKinds.def")
    cast_kinds = {f"CK_{n}": "" for n in re.findall(r"^CAST_OPERATION\((\w+)\)", ops, re.M)}

    binary = re.findall(r"^BINARY_OPERATION\((\w+),\s*\"?([^)\"]+)\"?\)", ops, re.M)
    unary = re.findall(r"^UNARY_OPERATION\((\w+),\s*\"?([^)\"]+)\"?\)", ops, re.M)
    operator_names: dict[str, str] = {}
    for name, spelling in binary:
        operator_names[spelling] = f"binary operator (BO_{name})"
    for name, spelling in unary:
        operator_names.setdefault(spelling, f"unary operator (UO_{name})")

    okinds = read("clang/Basic/OperatorKinds.def")
    overloaded = {}
    for _, spelling in re.findall(
        r"^OVERLOADED_OPERATOR(?:_MULTI)?\(\s*(\w+)\s*,\s*\"([^\"]*)\"", okinds, re.M
    ):
        overloaded[spelling] = "overloadable operator"

    attrs = read("clang/Basic/AttrList.inc")
    attr_kinds = {
        f"attr::{n}": ""
        for n in re.findall(r"^[A-Z_]*ATTR\((\w+)\)$", attrs, re.M)
    }

    toks = read("clang/Basic/TokenKinds.def")
    uett = {}
    for spelling, name in re.findall(
        r"^(?:CXX11_)?UNARY_EXPR_OR_TYPE_TRAIT\((\S+?),\s*(\w+),", toks, re.M
    ):
        uett[f"UETT_{name}"] = f"`{spelling}`"

    omp_src = read("llvm/Frontend/OpenMP/OMP.h.inc") or read("clang/Basic/OpenMPKinds.h")
    omp = {k: "" for k in sorted(set(re.findall(r"\bOMPC_[a-z][\w]*", omp_src)))}

    return {
        "CastKind": cast_kinds,
        "attr::Kind": attr_kinds,
        "UnaryExprOrTypeTrait": uett,
        "OpenMPClauseKind": omp,
        "OperatorName": operator_names,
        "OverloadedOperatorName": overloaded,
        "TraversalKind": dict(TRAVERSAL_KINDS),
        "OutputFeature": dict(OUTPUT_FEATURES),
    }


# --------------------------------------------------------------------------
# catalog -> matcher model
# --------------------------------------------------------------------------

def split_args(text: str) -> list[str]:
    depth, cur, out = 0, "", []
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [a.strip() for a in out if a.strip()]


def parse_param(raw: str) -> dict:
    """Turn one reference parameter spelling into a typed slot."""
    raw = raw.strip()
    default = None
    if "=" in raw:
        raw, default = (p.strip() for p in raw.split("=", 1))

    m = re.match(r"^Matcher<([^>]*)>\s*(\w+)?$", raw)
    if m:
        node = m.group(1).strip()
        return {
            "kind": "matcher",
            "node": None if node == "*" else node,
            "name": m.group(2) or "",
        }
    m = re.match(r"^const\s+(\w+)\s*\*\s*(\w+)?$", raw)
    if m:
        return {"kind": "node-pointer", "node": m.group(1), "name": m.group(2) or "Other"}
    if raw.startswith("nodeMatcherFunction"):
        return {"kind": "matcher-name", "name": "nodeMatcherFunction"}

    parts = raw.split()
    name = parts[-1] if len(parts) > 1 else ""
    type_ = " ".join(parts[:-1]) if len(parts) > 1 else raw
    if type_ in ("std::string", "StringRef") and not name:
        name = ""
    type_ = type_.replace("const ", "").strip()

    if type_ in ("std::string", "StringRef"):
        kind = "string"
    elif type_ == "unsigned":
        kind = "unsigned"
    elif type_ == "bool":
        kind = "bool"
    elif type_ == "double":
        kind = "double"
    elif type_ == "ValueT":
        kind = "value"
    elif type_ in ("CastKind", "attr::Kind", "UnaryExprOrTypeTrait",
                   "OpenMPClauseKind", "TraversalKind"):
        return {"kind": "enum", "enum": type_, "name": name or type_,
                **({"default": default} if default else {})}
    elif type_.startswith("Regex::RegexFlags"):
        return {"kind": "regex-flags", "name": name or "Flags",
                **({"default": default} if default else {})}
    else:  # unknown spelling: accept anything, do not invent a diagnostic
        kind = "value"
    slot = {"kind": kind, "name": name}
    if default:
        slot["default"] = default
    return slot


def parse_params(params: str, matcher: str) -> tuple[list[dict], bool, int, int | None]:
    """-> (slots, variadic, min_args, max_args)."""
    text = params.strip()
    if not text:
        return [], False, 0, 0

    if "..." in text:
        # Three spellings appear in the reference:
        #   Matcher<X>...            variadic node matcher
        #   Matcher<*>, ..., Matcher<*>   and   Matcher<*>...Matcher<*>
        #   StringRef, ..., StringRef
        head = text.split("...", 1)[0].rstrip().rstrip(",").strip()
        args = [a for a in split_args(head) if a != "..."]
        slots = [parse_param(a) for a in args] if args else []
        if not slots:
            slots = [{"kind": "matcher", "node": None, "name": "InnerMatcher"}]
        if matcher in ("allOf", "anyOf", "eachOf"):
            min_args = 2
        elif slots[0]["kind"] == "matcher-name":
            min_args = 1
        else:
            min_args = 0
        return slots, True, min_args, None

    args = split_args(text)
    slots = [parse_param(a) for a in args]
    # An unnamed `Matcher<ConcreteType>` marks clang's TypeTraverseMatcher, which
    # is variadic even though the reference prints a single parameter
    # (`pointee(isConstQualified(), isInteger())` is legal).
    if (len(slots) == 1 and slots[0]["kind"] == "matcher"
            and slots[0]["node"] is not None and not slots[0]["name"]):
        return slots, True, 0, None
    required = sum(1 for s in slots if "default" not in s)
    return slots, False, required, len(slots)


def render_signature(name: str, slots: list[dict], variadic: bool) -> str:
    def one(s: dict) -> str:
        if s["kind"] == "matcher":
            node = s["node"] or "*"
            return f"Matcher<{node}> {s['name']}".strip()
        if s["kind"] == "node-pointer":
            return f"const {s['node']}* {s['name']}"
        if s["kind"] == "matcher-name":
            return "nodeMatcherFunction"
        if s["kind"] == "enum":
            return f"{s['enum']} {s['name']}"
        if s["kind"] == "regex-flags":
            return f"Regex::RegexFlags {s['name']}"
        return f"{s['kind']} {s['name']}".strip()

    rendered = [one(s) for s in slots]
    if variadic:
        rendered = rendered + ["..."] if rendered else ["..."]
    return f"{name}({', '.join(rendered)})"


def is_node_shaped(overload: dict, bases: dict[str, str | None]) -> bool:
    """True for `Matcher<Stmt> sizeOfExpr(Matcher<UnaryExprOrTypeTraitExpr>)`.

    The reference files a few node-producing matchers under "traversal", but
    clang-query accepts them at top level.  What marks them is the shape: they
    convert through a hierarchy root and take a matcher for a class derived
    from it.
    """
    ret, params = overload["ret"], overload["params"]
    if ret is None or bases.get(ret, "missing") is not None:
        return False                     # not a root of its hierarchy
    if not params or params[0]["kind"] != "matcher":
        return False
    node = params[0]["node"]
    if node == ret:
        return False                     # `hasCanonicalType(Matcher<QualType>)` narrows
    while node:
        if node == ret:
            return True
        node = bases.get(node)
    return False


def build_matchers(rows: list[dict], bases: dict[str, str | None]) -> dict[str, dict]:
    matchers: dict[str, dict] = {}
    for row in rows:
        name = row["name"]
        ret_raw = row["ret"]
        m = re.match(r"^Matcher<(.+)>$", ret_raw)
        ret = m.group(1) if m else None          # None: mapAnyOf ("unspecified")
        if ret == "*":
            ret = None
        slots, variadic, min_args, max_args = parse_params(row["params"], name)
        node = ret
        if row["section"] == "node" and slots and slots[0]["kind"] == "matcher":
            node = slots[0]["node"] or ret
        overload = {
            "ret": ret,
            "node": node,
            "ret_raw": ret_raw,
            "section": row["section"],
            "params": slots,
            "variadic": variadic,
            "min_args": min_args,
            "max_args": max_args,
            "signature": render_signature(name, slots, variadic),
            "doc": row["doc"],
        }
        entry = matchers.setdefault(name, {
            "name": name,
            "sections": [],
            "parts": [],
            "in_clang_query": bool(row.get("in_clang_query_22", True)),
            "overloads": [],
        })
        if row["section"] not in entry["sections"]:
            entry["sections"].append(row["section"])
        if row["part"] not in entry["parts"]:
            entry["parts"].append(row["part"])
        entry["in_clang_query"] = (entry["in_clang_query"]
                                   and bool(row.get("in_clang_query_22", True)))
        entry["overloads"].append(overload)

    for name, entry in matchers.items():
        # Kind drives completion ordering: node matchers can stand at top level.
        entry["kind"] = ("node" if "node" in entry["sections"]
                         else "narrowing" if "narrowing" in entry["sections"]
                         else "traversal")
        entry["polymorphic"] = any(o["ret"] is None for o in entry["overloads"])
        entry["top_level"] = ("node" in entry["sections"]
                             or name in TOP_LEVEL_POLYMORPHIC
                             or any(is_node_shaped(o, bases) for o in entry["overloads"]))
        entry["ret_kinds"] = sorted({o["ret"] for o in entry["overloads"] if o["ret"]})
        entry["node_kinds"] = sorted({o["node"] for o in entry["overloads"] if o["node"]})
        docs, seen = [], set()
        for o in entry["overloads"]:
            d = o["doc"].strip()
            if d and d not in seen:
                seen.add(d)
                docs.append(d)
        entry["doc"] = "\n\n---\n\n".join(docs)
        entry["parts"].sort()
        if name in VALUE_SETS:
            entry["value_set"] = VALUE_SETS[name]
        if name in BOUND_ID_ARGS:
            entry["bound_id_arg"] = True
    return matchers


def check_coverage(matchers: dict[str, dict], bases: dict[str, str | None]) -> list[str]:
    missing = set()
    for entry in matchers.values():
        for o in entry["overloads"]:
            for key in ("ret", "node"):
                if o[key] and o[key] not in bases:
                    missing.add(o[key])
            for s in o["params"]:
                node = s.get("node")
                if node and node not in bases:
                    missing.add(node)
    return sorted(missing)


# --------------------------------------------------------------------------
# consumers
# --------------------------------------------------------------------------

def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def by_kind(matchers: dict[str, dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"node": [], "narrowing": [], "traversal": []}
    for name, entry in sorted(matchers.items()):
        if entry.get("native_available") is False:
            continue
        out[entry["kind"]].append(name)
    return out


def alt(names: list[str]) -> str:
    return "|".join(sorted(names, key=lambda n: (-len(n), n)))


def write_tmlanguage(path: Path, matchers: dict[str, dict], enums: dict) -> None:
    kinds = by_kind(matchers)
    enum_values = sorted(
        set(enums["CastKind"]) | set(enums["attr::Kind"])
        | set(enums["UnaryExprOrTypeTrait"]) | set(enums["OpenMPClauseKind"])
    )
    grammar = {
        "$schema": "https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json",
        "name": "AST Matcher DSL",
        "scopeName": "source.astmatcher",
        "fileTypes": ["query"],
        "patterns": [{"include": f"#{p}"} for p in (
            "comment", "command", "setting", "bind", "matcher-node",
            "matcher-narrowing", "matcher-traversal", "matcher-unknown",
            "string", "number", "boolean", "punctuation")],
        "repository": {
            "comment": {
                "match": r"#.*$",
                "name": "comment.line.number-sign.astmatcher",
            },
            "command": {
                "match": r"^\s*\b(" + alt(list(COMMANDS)) + r")\b",
                "captures": {"1": {"name": "keyword.control.astmatcher"}},
            },
            "setting": {
                "patterns": [
                    {"match": r"\b(" + alt(list(SET_OPTIONS)) + r")\b",
                     "name": "variable.parameter.setting.astmatcher"},
                    {"match": r"\b(" + alt(list(OUTPUT_FEATURES) + list(TRAVERSAL_KINDS)) + r")\b",
                     "name": "support.constant.astmatcher"},
                ],
            },
            "bind": {
                "begin": r"\.\s*(bind)\s*\(",
                "beginCaptures": {"1": {"name": "support.function.bind.astmatcher"}},
                "end": r"\)",
                "patterns": [{"include": "#bind-id"}],
            },
            "bind-id": {
                "begin": '"',
                "beginCaptures": {"0": {"name": "punctuation.definition.string.begin.astmatcher"}},
                "end": '"',
                "endCaptures": {"0": {"name": "punctuation.definition.string.end.astmatcher"}},
                "name": "entity.name.tag.bind-id.astmatcher",
            },
            "matcher-node": {
                "match": r"\b(" + alt(kinds["node"]) + r")\b(?=\s*\()",
                "captures": {"1": {"name": "support.class.matcher.node.astmatcher"}},
            },
            "matcher-narrowing": {
                "match": r"\b(" + alt(kinds["narrowing"]) + r")\b(?=\s*\()",
                "captures": {"1": {"name": "support.function.matcher.narrowing.astmatcher"}},
            },
            "matcher-traversal": {
                "match": r"\b(" + alt(kinds["traversal"]) + r")\b(?=\s*\()",
                "captures": {"1": {"name": "support.function.matcher.traversal.astmatcher"}},
            },
            "matcher-unknown": {
                "match": r"\b([A-Za-z_]\w*)\b(?=\s*\()",
                "captures": {"1": {"name": "entity.name.function.astmatcher"}},
            },
            "string": {
                "begin": '"',
                "beginCaptures": {"0": {"name": "punctuation.definition.string.begin.astmatcher"}},
                "end": '"',
                "endCaptures": {"0": {"name": "punctuation.definition.string.end.astmatcher"}},
                "name": "string.quoted.double.astmatcher",
                "patterns": [
                    {"match": r"\\.", "name": "constant.character.escape.astmatcher"},
                    {"match": r"\b(" + alt(enum_values) + r")\b",
                     "name": "constant.language.enum.astmatcher"},
                ],
            },
            "number": {
                "match": r"\b\d+(\.\d+)?\b",
                "name": "constant.numeric.astmatcher",
            },
            "boolean": {
                "match": r"\b(true|false)\b",
                "name": "constant.language.boolean.astmatcher",
            },
            "punctuation": {
                "patterns": [
                    {"match": r"[()]", "name": "meta.brace.round.astmatcher"},
                    {"match": r",", "name": "punctuation.separator.comma.astmatcher"},
                ],
            },
        },
    }
    write_json(path, grammar)


def write_snippets(path: Path, matchers: dict[str, dict]) -> None:
    snippets = {
        "match": {"prefix": "match", "body": ["match ${1:functionDecl}(${2}).bind(\"${3:m}\")"],
                  "description": "Match the loaded ASTs against a matcher."},
        "let": {"prefix": "let", "body": ["let ${1:name} ${2:matcher}()"],
                "description": "Name a matcher expression for reuse."},
        "set output diag": {"prefix": "setdiag", "body": ["set output diag"],
                            "description": "Report only the source location of bound nodes."},
        "set traversal": {"prefix": "settraversal",
                          "body": ["set traversal ${1|AsIs,IgnoreUnlessSpelledInSource|}"],
                          "description": "Change the session traversal kind."},
        "query file header": {
            "prefix": "queryheader",
            "body": [
                "# ${1:name}.query — ${2:what this check finds}.",
                "# Run:  \\$LLVM/bin/clang-query -f ${3:manifests/queries/$1.query} "
                "${4:manifests/capstone.cpp} -- -std=c++23",
                "set output diag",
                "",
                "match ${5:functionDecl}().bind(\"${6:m}\")",
            ],
            "description": "Skeleton for a clang-query -f script.",
        },
    }
    # One snippet per matcher, so the editor offers the shape of its arguments.
    for name, entry in sorted(matchers.items()):
        if not entry["in_clang_query"] or entry.get("native_available") is False:
            continue
        o = entry["overloads"][0]
        slots = o["params"]
        if not slots:
            body = f"{name}()"
        else:
            placeholders = []
            for i, s in enumerate(slots, start=1):
                if s["kind"] == "matcher":
                    placeholders.append(f"${{{i}:{s['node'] or 'anything()'}}}")
                elif s["kind"] in ("string", "enum"):
                    placeholders.append(f'"${{{i}:{s.get("enum", s["name"])}}}"')
                else:
                    placeholders.append(f"${{{i}:{s['name']}}}")
            body = f"{name}({', '.join(placeholders)})"
        snippets[name] = {
            "prefix": name,
            "body": [body],
            "description": (entry["doc"].splitlines() or [""])[0][:200],
        }
    write_json(path, snippets)


VIM_HEADER = '''" astmatcher.vim — syntax for the Clang AST Matcher DSL (clang-query files).
" GENERATED by tools/language-support/generate.py — do not edit by hand.
"
" Language:   Clang AST Matcher DSL
" Maintainer: ast-matchers-lab

if exists("b:current_syntax")
  finish
endif

let s:cpo_save = &cpo
set cpo&vim

syn case match
syn iskeyword @,48-57,_,:
'''

VIM_FOOTER = '''
" `let NAME …` introduces a named matcher.
syn match   astmatcherLetName      "\\%(^\\s*\\%(let\\|l\\)\\s\\+\\)\\@<=\\h\\w*"

syn match   astmatcherComment      "#.*$" contains=astmatcherTodo
syn keyword astmatcherTodo         contained TODO FIXME XXX NOTE
syn match   astmatcherBind         "\\.\\s*bind\\>"
syn region  astmatcherString       start=+"+ skip=+\\\\.+ end=+"+
      \\ contains=astmatcherEnumValue,astmatcherEscape
syn match   astmatcherEscape       contained "\\\\."
syn match   astmatcherNumber       "\\<\\d\\+\\(\\.\\d\\+\\)\\?\\>"
syn keyword astmatcherBoolean      true false
syn match   astmatcherDelimiter    "[(),]"

" A name that is followed by "(" but is in none of the keyword lists above is
" almost always a typo or a `let` reference; leave it neutral rather than red.
syn match   astmatcherUserMatcher  "\\<\\h\\w*\\>\\ze\\s*("

hi def link astmatcherComment      Comment
hi def link astmatcherTodo         Todo
hi def link astmatcherCommand      Statement
hi def link astmatcherSetting      Identifier
hi def link astmatcherSettingValue Constant
hi def link astmatcherNodeMatcher  Structure
hi def link astmatcherNarrowing    Function
hi def link astmatcherTraversal    Keyword
hi def link astmatcherBind         Special
hi def link astmatcherString       String
hi def link astmatcherEscape       SpecialChar
hi def link astmatcherEnumValue    Constant
hi def link astmatcherNumber       Number
hi def link astmatcherBoolean      Boolean
hi def link astmatcherDelimiter    Delimiter
hi def link astmatcherUserMatcher  Identifier
hi def link astmatcherLetName      Define

let b:current_syntax = "astmatcher"

let &cpo = s:cpo_save
unlet s:cpo_save
'''


def vim_alt(names: list[str], no_hyphen: bool = False) -> str:
    """A vim regex alternation with word boundaries: \\<\\%(a\\|b\\)\\>.

    `no_hyphen` refuses a match that is only the head of a hyphenated word, so
    that `print` does not light up inside `print-matcher`.
    """
    joined = "\\|".join(sorted(names, key=lambda n: (-len(n), n)))
    tail = "\\%(-\\)\\@!" if no_hyphen else ""
    return "\\<\\%(" + joined + "\\)\\>" + tail


def vim_keyword_lines(group: str, names: list[str], width: int = 78) -> list[str]:
    lines, cur = [], f"syn keyword {group}"
    for name in names:
        if len(cur) + 1 + len(name) > width:
            lines.append(cur)
            cur = f"syn keyword {group}"
        cur += " " + name
    if cur.strip() != f"syn keyword {group}":
        lines.append(cur)
    return lines


def write_vim_syntax(path: Path, matchers: dict[str, dict], enums: dict) -> None:
    kinds = by_kind(matchers)
    enum_values = sorted(
        set(enums["CastKind"]) | set(enums["attr::Kind"])
        | set(enums["UnaryExprOrTypeTrait"]) | set(enums["OpenMPClauseKind"])
    )
    out = [VIM_HEADER]
    out += vim_keyword_lines("astmatcherCommand", sorted(COMMANDS))
    out.append("")
    out.append(f'syn match astmatcherSetting "{vim_alt(list(SET_OPTIONS))}"')
    out.append('syn match astmatcherSettingValue '
               f'"{vim_alt(list(OUTPUT_FEATURES) + list(TRAVERSAL_KINDS), True)}"')
    out.append("")
    out.append(f'" {len(kinds["node"])} node matchers')
    out += vim_keyword_lines("astmatcherNodeMatcher", kinds["node"])
    out.append("")
    out.append(f'" {len(kinds["narrowing"])} narrowing matchers')
    out += vim_keyword_lines("astmatcherNarrowing", kinds["narrowing"])
    out.append("")
    out.append(f'" {len(kinds["traversal"])} traversal matchers')
    out += vim_keyword_lines("astmatcherTraversal", kinds["traversal"])
    out.append("")
    out.append('" values clang validates inside string arguments')
    out += vim_keyword_lines("astmatcherEnumValue contained", enum_values)
    out.append(VIM_FOOTER)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))


def write_dictionary(path: Path, matchers: dict[str, dict], enums: dict) -> None:
    words = {name for name, entry in matchers.items()
             if entry.get("native_available") is not False}
    words |= set(COMMANDS) | set(SET_OPTIONS) | set(OUTPUT_FEATURES)
    words |= set(TRAVERSAL_KINDS) | {"bind"}
    for key in ("CastKind", "attr::Kind", "UnaryExprOrTypeTrait", "OpenMPClauseKind"):
        words |= set(enums[key])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(words)) + "\n")


# --------------------------------------------------------------------------

def native_capabilities(binary: Path, names: list[str]) -> set[str]:
    result = subprocess.run([str(binary), "capabilities"],
                            input="\n".join(names) + "\n", text=True,
                            capture_output=True, check=True)
    available = set(result.stdout.splitlines())
    if not available or "functionDecl" not in available or not available <= set(names):
        sys.exit("native matcher capability scan returned an invalid matcher set")
    return available


def generate(root: Path, verbose: bool = True,
             native_binary: Path | None = None,
             native_llvm_major: int | None = None) -> None:
    include_dir = llvm_prefix() / "include"
    if not (include_dir / "clang" / "AST" / "DeclNodes.inc").exists():
        sys.exit(f"clang headers not found under {include_dir}")

    rows = json.loads(CATALOG.read_text())
    bases = build_hierarchy(include_dir)
    enums = build_enums(include_dir)
    matchers = build_matchers(rows, bases)
    if native_binary is not None:
        available = native_capabilities(native_binary, list(matchers))
        for name, entry in matchers.items():
            entry["native_available"] = name in available

    missing = check_coverage(matchers, bases)
    if missing:
        print(f"warning: {len(missing)} node kinds have no hierarchy entry: "
              f"{', '.join(missing)}", file=sys.stderr)

    write_json(root / "data" / "hierarchy.json", {
        "bases": bases,
        "roots": sorted(k for k, v in bases.items() if v is None),
    })
    part_docs = {}
    for doc in sorted((LAB / "docs").glob("part_*.md")):
        m = re.match(r"part_(\d+)_", doc.name)
        if m:
            part_docs[m.group(1)] = f"docs/{doc.name}"
    write_json(root / "data" / "enums.json", {
        "values": enums,
        "part_docs": part_docs,
        "commands": COMMANDS,
        "set_options": {k: {"type": v[0], "doc": v[1]} for k, v in SET_OPTIONS.items()},
        "bound_id_args": sorted(BOUND_ID_ARGS),
    })
    matcher_data = {
        "source": "scripts/catalog.json",
        "rows": len(rows),
        "matchers": matchers,
    }
    if native_llvm_major is not None:
        matcher_data["native_llvm_major"] = native_llvm_major
    write_json(root / "data" / "matchers.json", matcher_data)
    write_tmlanguage(root / "vscode" / "syntaxes" / "astmatcher.tmLanguage.json", matchers, enums)
    write_snippets(root / "vscode" / "snippets" / "astmatcher.json", matchers)
    write_vim_syntax(root / "vim" / "syntax" / "astmatcher.vim", matchers, enums)
    write_dictionary(root / "vim" / "dict" / "astmatcher.txt", matchers, enums)

    if verbose:
        kinds = by_kind(matchers)
        print(f"{len(rows)} reference rows -> {len(matchers)} matcher names "
              f"({len(kinds['node'])} node, {len(kinds['narrowing'])} narrowing, "
              f"{len(kinds['traversal'])} traversal)")
        print(f"{len(bases)} AST classes, "
              f"{sum(len(v) for v in enums.values())} enum values")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    output = ap.add_mutually_exclusive_group()
    output.add_argument("--check", action="store_true",
                        help="regenerate into a temp tree and diff against the committed files")
    output.add_argument("--output-dir", type=Path,
                        help="write generated files into this separate tree")
    ap.add_argument("--native-binary", type=Path,
                    help="filter generated completion with this binary's registered matchers")
    ap.add_argument("--native-llvm-major", type=int,
                    help="linked LLVM major for version-specific diagnostics")
    args = ap.parse_args()
    if args.native_binary is not None and args.output_dir is None:
        ap.error("--native-binary requires --output-dir")
    if args.native_binary is not None and args.native_llvm_major is None:
        ap.error("--native-binary requires --native-llvm-major")

    if args.output_dir is not None:
        generate(args.output_dir, native_binary=args.native_binary,
                 native_llvm_major=args.native_llvm_major)
        return 0
    if not args.check:
        generate(HERE)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        generate(Path(tmp), verbose=False)
        failed = []
        for rel in ("data/matchers.json", "data/hierarchy.json", "data/enums.json",
                    "vscode/syntaxes/astmatcher.tmLanguage.json",
                    "vscode/snippets/astmatcher.json",
                    "vim/syntax/astmatcher.vim", "vim/dict/astmatcher.txt"):
            want, have = Path(tmp) / rel, HERE / rel
            if not have.exists() or have.read_text() != want.read_text():
                failed.append(rel)
        if failed:
            print("stale generated files (run tools/language-support/generate.py):",
                  file=sys.stderr)
            for rel in failed:
                print(f"  {rel}", file=sys.stderr)
            return 1
    print("generated files are up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
