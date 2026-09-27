"""Editor features: what to complete here, what this name means, what is wrong.

Everything is computed from a parsed document plus a byte offset, so the same
code serves the LSP server and the batch CLI.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analyze import Analyzer, analyze
from .catalog import SAME_NODE_COMBINATORS, Catalog, Matcher
from .lexer import COMMENT, DOT, EOF, IDENT, NUMBER, STRING, Token
from .parser import (BOOLEANS, Call, Command, Document, calls_at, command_at,
                     token_at)

# LSP CompletionItemKind
K_TEXT, K_METHOD, K_FUNCTION, K_FIELD, K_VARIABLE, K_CLASS = 1, 2, 3, 5, 6, 7
K_PROPERTY, K_VALUE, K_ENUM, K_KEYWORD, K_SNIPPET = 10, 12, 13, 14, 15
K_CONSTANT, K_ENUM_MEMBER = 21, 20

SEMANTIC_TOKEN_TYPES = [
    "keyword", "comment", "string", "number", "class", "function", "method",
    "variable", "property", "enumMember",
]
SEMANTIC_TOKEN_MODIFIERS = ["defaultLibrary", "definition", "deprecated"]
_TYPE_INDEX = {name: i for i, name in enumerate(SEMANTIC_TOKEN_TYPES)}
_MOD_INDEX = {name: 1 << i for i, name in enumerate(SEMANTIC_TOKEN_MODIFIERS)}


@dataclass
class Context:
    """What the cursor is sitting in."""
    kind: str                       # command|set-option|set-value|matcher|string|member|none
    prefix: str = ""
    replace: tuple[int, int] = (0, 0)
    expected: str | None = None     # node kind a matcher slot wants
    top_level: bool = False
    owner: Matcher | None = None    # the call whose argument list we are in
    call: Call | None = None
    index: int = 0
    slot: dict | None = None
    enum: str | None = None
    command: Command | None = None
    inside_string: bool = False


# ---------------------------------------------------------------- context

def _word_before(doc: Document, offset: int) -> tuple[str, tuple[int, int]]:
    tok = token_at(doc, offset)
    if tok is not None and tok.kind == IDENT and tok.start <= offset <= tok.end:
        return doc.text[tok.start:offset], (tok.start, tok.end)
    return "", (offset, offset)


def _slot_for(cat: Catalog, an: Analyzer, call: Call,
              index: int) -> tuple[dict | None, Matcher | None]:
    matcher = cat.get(call.name)
    if matcher is None:
        return None, None
    res = an.resolution_for(call)
    overload = res.overload or (matcher.overloads[0] if matcher.overloads else None)
    if overload is None:
        return None, matcher
    return overload.slot(index), matcher


def _expected_for(cat: Catalog, an: Analyzer, chain: list[Call], offset: int) -> Context:
    """Walk the innermost call and report what its current argument expects."""
    call = chain[-1]
    index = call.arg_index_at(offset)
    slot, matcher = _slot_for(cat, an, call, index)
    ctx = Context(kind="matcher", call=call, index=index, owner=matcher, slot=slot)
    if slot is None:
        return ctx
    if slot["kind"] == "matcher":
        node = slot["node"]
        if node is None and matcher is not None and matcher.name in SAME_NODE_COMBINATORS:
            outer = _expected_for(cat, an, chain[:-1], call.start) if len(chain) > 1 else None
            node = outer.expected if outer else None
        ctx.expected = node
    elif slot["kind"] == "matcher-name":
        ctx.expected = None
        ctx.kind = "matcher-name"
    elif slot["kind"] in ("enum", "string"):
        ctx.kind = "string"
        ctx.enum = slot.get("enum") or (matcher.value_set if matcher else None)
    else:
        ctx.kind = "literal"
    return ctx


def context_at(cat: Catalog, doc: Document, offset: int, an: Analyzer | None = None) -> Context:
    if an is None:
        _, an = analyze(cat, doc)

    tok = token_at(doc, offset)
    if tok is not None and tok.kind == STRING and tok.start < offset \
            and (offset < tok.end or not tok.terminated):
        chain = calls_at(doc, tok.start + 1)
        ctx = Context(kind="string", inside_string=True,
                      prefix=doc.text[tok.start + 1:offset],
                      replace=(tok.start + 1, tok.end - (1 if tok.terminated else 0)))
        if chain:
            inner = _expected_for(cat, an, chain, tok.start)
            ctx.owner, ctx.call, ctx.index = inner.owner, inner.call, inner.index
            ctx.enum = inner.enum
            ctx.command = command_at(doc, offset)
        return ctx

    prefix, replace = _word_before(doc, offset)
    cmd = command_at(doc, offset)
    if cmd is None:
        return Context(kind="command", prefix=prefix, replace=replace)
    in_keyword = cmd.keyword.start <= offset <= cmd.keyword.end
    if in_keyword and prefix == doc.text[cmd.keyword.start:offset]:
        return Context(kind="command", prefix=prefix, replace=replace, command=cmd)

    if cmd.name in ("set", "enable", "disable"):
        words = cmd.words
        in_word0 = bool(words) and words[0].start <= offset <= words[0].end
        if not words or in_word0:
            if cmd.name == "set":
                return Context(kind="set-option", prefix=prefix, replace=replace, command=cmd)
            return Context(kind="set-output-keyword", prefix=prefix, replace=replace, command=cmd)
        option = words[0].text
        if cmd.name in ("enable", "disable"):
            return Context(kind="set-value", prefix=prefix, replace=replace,
                           enum="OutputFeature", command=cmd)
        spec = cat.set_options.get(option)
        enum = "Boolean" if spec and spec["type"] == "bool" else (spec["type"] if spec else None)
        return Context(kind="set-value", prefix=prefix, replace=replace, enum=enum, command=cmd)

    # match / let
    if cmd.name == "let" and cmd.let_name is not None \
            and cmd.let_name.start <= offset <= cmd.let_name.end:
        return Context(kind="none", command=cmd)

    prev = _previous_significant(doc, offset)
    if prev is not None and prev.kind == DOT:
        return Context(kind="member", prefix=prefix, replace=replace, command=cmd)

    chain = calls_at(doc, offset)
    if not chain:
        return Context(kind="matcher", prefix=prefix, replace=replace, command=cmd,
                       top_level=cmd.name == "match")
    ctx = _expected_for(cat, an, chain, offset)
    ctx.prefix, ctx.replace, ctx.command = prefix, replace, cmd
    return ctx


def _previous_significant(doc: Document, offset: int) -> Token | None:
    best = None
    for tok in doc.tokens:
        if tok.kind in (COMMENT, EOF):
            continue
        if tok.end <= offset:
            if tok.kind == IDENT and tok.end == offset:
                continue            # the word being typed
            best = tok
        else:
            break
    return best


# ------------------------------------------------------------- completion

def _doc_link(cat: Catalog, matcher: Matcher) -> str:
    links = []
    for part in matcher.parts:
        path = cat.part_docs.get(str(part))
        if path:
            links.append(f"[Part {part}]({path})")
        else:
            links.append(f"Part {part}")
    return ", ".join(links)


def matcher_markdown(cat: Catalog, matcher: Matcher) -> str:
    lines = ["```astmatcher"]
    for sig in matcher.signatures[:8]:
        ret = matcher.ret_display()
        lines.append(f"{ret} {sig}")
    lines.append("```")
    tags = [matcher.kind + " matcher"]
    if matcher.parts:
        tags.append(_doc_link(cat, matcher))
    lines.append(" · ".join(tags))
    if not matcher.in_clang_query:
        lines.append("")
        lines.append("**Not in clang-query 22** — this reference row has no registered "
                     "matcher; see `docs/part_12_capstone.md` for the nearest alternative.")
    if matcher.doc:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(matcher.doc)
    return "\n".join(lines)


def _insert_text(matcher: Matcher) -> tuple[str, int]:
    overload = matcher.overloads[0]
    if overload.min_args == 0 and not overload.params:
        return f"{matcher.name}()", 2      # plain text
    return f"{matcher.name}($0)", 2        # snippet: cursor between the parens


def resolve(cat: Catalog, item: dict) -> dict:
    """Fill in the documentation for one item (completionItem/resolve)."""
    name = (item.get("data") or {}).get("matcher")
    matcher = cat.get(name) if name else None
    if matcher is not None and "documentation" not in item:
        item["documentation"] = {"kind": "markdown", "value": matcher_markdown(cat, matcher)}
    return item


def _completion_item(cat: Catalog, matcher: Matcher, group: str) -> dict:
    kind = {"node": K_CLASS, "narrowing": K_FUNCTION, "traversal": K_METHOD}[matcher.kind]
    text, fmt = _insert_text(matcher)
    item = {
        "label": matcher.name,
        "kind": kind,
        "labelDetails": {"description": matcher.kind},
        "detail": f"{matcher.ret_display()} {matcher.signatures[0]}",
        "insertText": text,
        "insertTextFormat": fmt,
        "sortText": f"{group}{matcher.name}",
        "filterText": matcher.name,
        "data": {"matcher": matcher.name},
    }
    if not matcher.in_clang_query:
        item["tags"] = [1]                  # CompletionItemTag.Deprecated
    return item


def _rank(cat: Catalog, expected: str | None, kinds: list[str]) -> tuple[int, int]:
    """(bucket, depth) for a candidate whose types are `kinds`.

    bucket 0  exactly the expected node        (hasBody on a FunctionDecl slot)
    bucket 1  a base of it, nearest first      (hasName, then isImplicit)
    bucket 2  only a subclass of it            (forEachOverridden)
    bucket 9  unrelated
    """
    best = (9, 99)
    for kind in kinds or []:
        canon = cat.canonical(kind) or kind
        if expected is None:
            best = min(best, (1, len(cat.ancestors(canon))))
            continue
        canon_expected = cat.canonical(expected) or expected
        if canon == canon_expected:
            return 0, 0
        chain = cat.ancestors(canon_expected)
        if canon in chain:
            best = min(best, (1, chain.index(canon)))
            continue
        chain = cat.ancestors(canon)
        if canon_expected in chain:
            best = min(best, (2, chain.index(canon_expected)))
    return best


def _matcher_candidates(cat: Catalog, ctx: Context, an: Analyzer) -> list[dict]:
    items: list[dict] = []
    expected = ctx.expected
    root_slot = expected is None or cat.is_root(expected)

    for matcher in cat.matchers.values():
        if ctx.top_level and not matcher.is_node_matcher:
            continue
        if not cat.applies_to(matcher, expected):
            continue
        if matcher.polymorphic and not matcher.ret_kinds:
            group, depth = ("2" if root_slot else "4"), 0
        elif matcher.kind == "node":
            bucket, depth = _rank(cat, expected, matcher.node_kinds)
            if expected is not None and bucket == 9:
                continue
            group = ("0" if root_slot else "3") if bucket != 0 else "0"
        else:
            bucket, depth = _rank(cat, expected, matcher.ret_kinds)
            if root_slot:
                group = "1"
            else:
                group = {0: "0", 1: "1", 2: "2"}.get(bucket, "3")
        # groups start at 1 so that `let` names (sortText "000…") stay on top
        items.append(_completion_item(cat, matcher, f"{int(group) + 1}{depth:02d}"))

    for name, let in _visible_lets(an, ctx).items():
        if ctx.top_level and not let.is_node_matcher:
            continue
        if expected is not None and let.ret_kinds and not any(
                cat.related(k, expected) for k in let.ret_kinds):
            continue
        items.append({
            "label": name,
            "kind": K_VARIABLE,
            "detail": f"let {name} {let.signature}",
            "documentation": {"kind": "markdown",
                              "value": f"Named matcher defined in this file:\n\n"
                                       f"```astmatcher\nlet {name} {let.signature}\n```"},
            "sortText": f"000{name}",
        })
    return items


def _visible_lets(an: Analyzer, ctx: Context) -> dict:
    """`let` names already defined above the cursor — clang-query needs order."""
    if ctx.command is None:
        return an.lets
    limit = ctx.command.keyword.start
    return {name: let for name, let in an.lets.items()
            if (an.doc.lets[name].keyword.start < limit if name in an.doc.lets else True)}


def completions(cat: Catalog, doc: Document, offset: int,
                an: Analyzer | None = None) -> list[dict]:
    if an is None:
        _, an = analyze(cat, doc)
    ctx = context_at(cat, doc, offset, an)

    if ctx.kind == "command":
        return [{
            "label": name,
            "kind": K_KEYWORD,
            "detail": _command_detail(name),
            "documentation": {"kind": "markdown", "value": cat.commands[name]},
            "insertText": _command_snippet(name),
            "insertTextFormat": 2,
            "sortText": f"{'0' if len(name) > 1 else '1'}{name}",
        } for name in sorted(cat.commands)]

    if ctx.kind == "set-option":
        return [{
            "label": name,
            "kind": K_PROPERTY,
            "detail": spec["type"],
            "documentation": {"kind": "markdown", "value": spec["doc"]},
            "sortText": f"0{name}",
        } for name, spec in sorted(cat.set_options.items())]

    if ctx.kind == "set-output-keyword":
        return [{"label": "output", "kind": K_KEYWORD, "sortText": "0output",
                 "documentation": {"kind": "markdown",
                                   "value": "`enable output <feature>` / "
                                            "`disable output <feature>`"}}]

    if ctx.kind == "set-value":
        if ctx.enum == "Boolean":
            return [{"label": v, "kind": K_KEYWORD, "sortText": f"0{v}"} for v in sorted(BOOLEANS)]
        return _enum_items(cat, ctx.enum)

    if ctx.kind == "member":
        return [
            {"label": "bind", "kind": K_METHOD, "detail": 'bind("id")',
             "insertText": 'bind("$1")', "insertTextFormat": 2, "sortText": "0bind",
             "documentation": {"kind": "markdown",
                               "value": "Name this node so the output reports it, and so "
                                        "`equalsBoundNode(\"id\")` can refer back to it."}},
            {"label": "with", "kind": K_METHOD, "detail": "with(matchers...)",
             "insertText": "with($1)", "insertTextFormat": 2, "sortText": "1with",
             "documentation": {"kind": "markdown",
                               "value": "Only after `mapAnyOf(...)`: apply matchers to "
                                        "whichever of the listed node kinds matched."}},
        ]

    if ctx.kind == "string":
        return _string_items(cat, ctx, an)

    if ctx.kind == "matcher-name":
        return [{
            "label": m.name, "kind": K_CLASS, "sortText": f"0{m.name}",
            "detail": m.ret_display(),
            "documentation": {"kind": "markdown", "value": matcher_markdown(cat, m)},
        } for m in cat.matchers.values() if m.kind == "node"]

    if ctx.kind == "matcher":
        return _matcher_candidates(cat, ctx, an)

    if ctx.kind == "literal" and ctx.slot is not None and ctx.slot["kind"] == "bool":
        return [{"label": v, "kind": K_KEYWORD, "sortText": f"0{v}"} for v in sorted(BOOLEANS)]
    return []


def _command_detail(name: str) -> str:
    return {
        "match": "match MATCHER", "m": "m MATCHER",
        "let": "let NAME MATCHER", "l": "l NAME MATCHER",
        "set": "set <option> <value>",
        "enable": "enable output <feature>", "disable": "disable output <feature>",
    }.get(name, name)


def _command_snippet(name: str) -> str:
    return {
        "match": "match $0", "m": "m $0",
        "let": "let ${1:name} $0", "l": "l ${1:name} $0",
        "set": "set ${1|bind-root,print-matcher,enable-profile,traversal,output|} $0",
        "enable": "enable output ${1|print,diag,detailed-ast,dump|}",
        "disable": "disable output ${1|print,diag,detailed-ast,dump|}",
    }.get(name, name)


def _enum_items(cat: Catalog, enum: str | None, quote: bool = False) -> list[dict]:
    """`quote` when the cursor is not already inside a string literal."""
    values = cat.enum_values(enum or "")
    items = []
    for value, note in sorted(values.items()):
        item = {"label": value, "kind": K_ENUM_MEMBER, "sortText": f"0{value}",
                "filterText": value}
        if quote:
            item["insertText"] = '"' + value + '"'
        if note:
            item["documentation"] = {"kind": "markdown", "value": note}
        if enum:
            item["detail"] = enum
        items.append(item)
    return items


def _string_items(cat: Catalog, ctx: Context, an: Analyzer) -> list[dict]:
    if ctx.enum:
        return _enum_items(cat, ctx.enum, quote=not ctx.inside_string)
    owner, call = ctx.owner, ctx.call
    if owner is not None and owner.bound_id_arg and ctx.command is not None:
        ids = an.visible_bound_ids(ctx.command)
        quote = "" if ctx.inside_string else chr(34)
        return [{"label": i, "kind": K_VALUE, "sortText": f"0{i}",
                 "insertText": quote + i + quote, "detail": "bound node id",
                 "documentation": {"kind": "markdown",
                                   "value": f"`.bind(\"{i}\")` appears in this file."}}
                for i in ids]
    if call is not None and call.name == "bind":
        return []
    return []


# ------------------------------------------------------------------ hover

def hover(cat: Catalog, doc: Document, offset: int, an: Analyzer | None = None) -> dict | None:
    if an is None:
        _, an = analyze(cat, doc)
    tok = token_at(doc, offset)
    if tok is None:
        return None

    if tok.kind == IDENT:
        matcher = cat.get(tok.text)
        if matcher is not None:
            return {"contents": {"kind": "markdown", "value": matcher_markdown(cat, matcher)},
                    "range": _range(doc, tok.start, tok.end)}
        let = an.lets.get(tok.text)
        if let is not None:
            return {"contents": {"kind": "markdown",
                                 "value": f"```astmatcher\nlet {let.name} {let.signature}\n```\n"
                                          f"Named matcher"
                                          f"{' (a node matcher)' if let.is_node_matcher else ''}."},
                    "range": _range(doc, tok.start, tok.end)}
        if tok.text in cat.commands:
            return {"contents": {"kind": "markdown",
                                 "value": f"**{tok.text}** — {cat.commands[tok.text]}"},
                    "range": _range(doc, tok.start, tok.end)}
        spec = cat.set_options.get(tok.text)
        if spec is not None:
            return {"contents": {"kind": "markdown",
                                 "value": f"**set {tok.text}** *({spec['type']})* — {spec['doc']}"},
                    "range": _range(doc, tok.start, tok.end)}
        for enum, values in cat.enums.items():
            if tok.text in values:
                note = values[tok.text]
                return {"contents": {"kind": "markdown",
                                     "value": f"`{tok.text}` — {enum}"
                                              + (f"\n\n{note}" if note else "")},
                        "range": _range(doc, tok.start, tok.end)}
        return None

    if tok.kind == STRING:
        for enum, values in cat.enums.items():
            if tok.value in values and enum not in ("OutputFeature", "TraversalKind"):
                note = values[tok.value]
                return {"contents": {"kind": "markdown",
                                     "value": f"`{tok.value}` — {enum}"
                                              + (f"\n\n{note}" if note else "")},
                        "range": _range(doc, tok.start, tok.end)}
    return None


# --------------------------------------------------------- signature help

def signature_help(cat: Catalog, doc: Document, offset: int,
                   an: Analyzer | None = None) -> dict | None:
    if an is None:
        _, an = analyze(cat, doc)
    chain = calls_at(doc, offset)
    if not chain:
        return None
    call = chain[-1]
    matcher = cat.get(call.name)
    if matcher is None:
        return None
    index = call.arg_index_at(offset)

    res = an.resolution_for(call)
    chosen = res.overload
    signatures, active = [], 0
    seen: set[str] = set()
    for overload in matcher.overloads:
        if overload.signature in seen:
            continue
        seen.add(overload.signature)
        params = []
        rendered = overload.signature[len(matcher.name) + 1:-1]
        for piece in _split_signature(rendered):
            params.append({"label": piece})
        if chosen is not None and overload.signature == chosen.signature:
            active = len(signatures)
        signatures.append({
            "label": f"{matcher.ret_display()} {overload.signature}",
            "documentation": {"kind": "markdown", "value": overload.doc or matcher.doc},
            "parameters": params,
        })
    if not signatures:
        return None
    params = signatures[active]["parameters"]
    return {
        "signatures": signatures,
        "activeSignature": active,
        "activeParameter": min(index, max(len(params) - 1, 0)),
    }


def _split_signature(rendered: str) -> list[str]:
    depth, cur, out = 0, "", []
    for ch in rendered:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# ------------------------------------------------------- symbols, tokens

# LSP SymbolKind
S_FUNCTION, S_VARIABLE, S_CONSTANT = 12, 13, 14


def document_symbols(doc: Document, index) -> list[dict]:
    """One outline entry per command, so that a long -f script is navigable."""
    out = []
    for cmd in doc.commands:
        if cmd.name == "let" and cmd.let_name:
            name, kind, detail = cmd.let_name.text, S_VARIABLE, "let"
        elif cmd.name == "match" and isinstance(cmd.expr, Call):
            name, kind, detail = cmd.expr.name, S_FUNCTION, "match"
        elif cmd.name in ("set", "enable", "disable"):
            name = f"{cmd.name} " + " ".join(w.text for w in cmd.words)
            kind, detail = S_CONSTANT, "setting"
        else:
            continue
        rng = _range(doc, cmd.start, cmd.end, index)
        out.append({"name": name, "detail": detail, "kind": kind,
                    "range": rng, "selectionRange": rng})
    return out


def definition(doc: Document, offset: int, uri: str, index) -> dict | None:
    tok = token_at(doc, offset)
    if tok is None or tok.kind != IDENT:
        return None
    cmd = doc.lets.get(tok.text)
    if cmd is None or cmd.let_name is None:
        return None
    return {"uri": uri,
            "range": _range(doc, cmd.let_name.start, cmd.let_name.end, index)}


def semantic_tokens(cat: Catalog, doc: Document, index) -> list[int]:
    entries: list[tuple[int, int, int, int, int]] = []   # line, char, len, type, mods

    def add(start: int, end: int, type_: str, mods: int = 0) -> None:
        line, char = index.position(start)
        entries.append((line, char, end - start, _TYPE_INDEX[type_], mods))

    let_names = set(doc.lets)
    for tok in doc.tokens:
        if tok.kind == COMMENT:
            add(tok.start, tok.end, "comment")
        elif tok.kind == STRING:
            add(tok.start, tok.end, "string")
        elif tok.kind == NUMBER:
            add(tok.start, tok.end, "number")

    for cmd in doc.commands:
        add(cmd.keyword.start, cmd.keyword.end, "keyword")
        if cmd.let_name is not None:
            add(cmd.let_name.start, cmd.let_name.end, "variable",
                _MOD_INDEX["definition"])
        for word in cmd.words:
            type_ = "property" if word is cmd.words[0] else "enumMember"
            add(word.start, word.end, type_)
        _token_calls(cat, cmd.expr, let_names, add)

    entries.sort()
    data: list[int] = []
    prev_line = prev_char = 0
    for line, char, length, type_, mods in entries:
        data.extend([line - prev_line,
                     char - (prev_char if line == prev_line else 0),
                     length, type_, mods])
        prev_line, prev_char = line, char
    return data


def _token_calls(cat: Catalog, expr, let_names, add) -> None:
    if isinstance(expr, Call):
        matcher = cat.get(expr.name)
        if matcher is not None:
            type_ = {"node": "class", "narrowing": "function",
                     "traversal": "method"}[matcher.kind]
            mods = _MOD_INDEX["defaultLibrary"]
            if not matcher.in_clang_query:
                mods |= _MOD_INDEX["deprecated"]
            add(expr.name_token.start, expr.name_token.end, type_, mods)
        elif expr.name in let_names:
            add(expr.name_token.start, expr.name_token.end, "variable")
        elif expr.name in BOOLEANS:
            add(expr.name_token.start, expr.name_token.end, "keyword")
        for bind in expr.binds:
            add(bind.name_token.start, bind.name_token.end, "property")
            for arg in bind.args:
                _token_calls(cat, arg, let_names, add)
        for arg in expr.args:
            _token_calls(cat, arg, let_names, add)


# ---------------------------------------------------------------- ranges

def _range(doc: Document, start: int, end: int, index=None) -> dict:
    from .lexer import LineIndex
    idx = index or LineIndex(doc.text)
    sl, sc = idx.position(start)
    el, ec = idx.position(end)
    return {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}
