"""Tests for the matcher-DSL language support.

    python3 -m unittest discover -s tools/language-support/astmatcher-lsp/tests

The interesting cases are the ones checked against the real clang-query 22
behaviour; each is noted where it is not obvious.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from astmatcher_lsp.analyze import ERROR, WARNING, analyze          # noqa: E402
from astmatcher_lsp.catalog import load                             # noqa: E402
from astmatcher_lsp.features import (completions, context_at, hover,  # noqa: E402
                                    semantic_tokens, signature_help)
from astmatcher_lsp.lexer import LineIndex, tokenize                # noqa: E402
from astmatcher_lsp.parser import bound_ids, calls_at, parse        # noqa: E402
from astmatcher_lsp.run import (OutputParser, attach_query_ranges,     # noqa: E402
                                build_script, clang_query_path, group_bindings,
                                parse_dump_header, run_query)
from astmatcher_lsp.server import Server                            # noqa: E402

CAT = load()
LAB = HERE.parent.parent.parent.parent


def codes(src: str) -> list[str]:
    return [d.code for d in analyze(CAT, parse(src))[0]]


def labels(src: str, offset: int | None = None) -> list[str]:
    doc = parse(src)
    items = completions(CAT, doc, len(src) if offset is None else offset)
    items.sort(key=lambda i: (i.get("sortText", ""), i["label"]))
    return [i["label"] for i in items]


class TestLexer(unittest.TestCase):
    def test_settings_are_single_words(self):
        kinds = [(t.kind, t.text) for t in tokenize("set print-matcher true")[:3]]
        self.assertEqual(kinds, [("ident", "set"), ("ident", "print-matcher"),
                                 ("ident", "true")])

    def test_comment_runs_to_end_of_line(self):
        toks = tokenize("# note\nmatch decl()")
        self.assertEqual(toks[0].kind, "comment")
        self.assertEqual(toks[1].text, "match")

    def test_string_escapes_and_unterminated(self):
        tok = tokenize(r'"a\"b"')[0]
        self.assertEqual(tok.value, 'a"b')
        self.assertTrue(tok.terminated)
        self.assertFalse(tokenize('"open')[0].terminated)

    def test_exponent_and_negative_numbers(self):
        self.assertEqual([t.text for t in tokenize("314e-2 -1")[:2]], ["314e-2", "-1"])

    def test_line_index_roundtrip(self):
        text = "match a()\nmatch b()\n"
        index = LineIndex(text)
        self.assertEqual(index.position(text.index("b")), (1, 6))
        self.assertEqual(index.offset(1, 6), text.index("b"))


class TestParser(unittest.TestCase):
    def test_multi_line_matcher_is_one_command(self):
        doc = parse("match functionDecl(\n    hasName(\"a\"),\n    isDefinition())")
        self.assertEqual(len(doc.commands), 1)
        self.assertEqual(doc.commands[0].expr.name, "functionDecl")

    def test_let_then_match(self):
        doc = parse('let zero integerLiteral(equals(0))\nmatch expr(zero)')
        self.assertEqual(list(doc.lets), ["zero"])
        self.assertEqual(doc.commands[1].expr.name, "expr")

    def test_unclosed_paren_still_parses(self):
        doc = parse("match functionDecl(hasName(")
        self.assertIsNone(doc.commands[0].expr.rparen)
        self.assertEqual([c.name for c in calls_at(doc, 27)],
                         ["functionDecl", "hasName"])

    def test_bound_ids(self):
        doc = parse('match varDecl(hasInitializer(expr().bind("init"))).bind("v")')
        self.assertEqual(sorted(bound_ids(doc.commands[0])), ["init", "v"])


class TestDiagnostics(unittest.TestCase):
    """Each expectation below matches what clang-query 22 actually reports."""

    def test_accepts_real_queries(self):
        for path in sorted((LAB / "manifests").rglob("*.query")):
            with self.subTest(query=path.name):
                self.assertEqual([d for d in analyze(CAT, parse(path.read_text()))[0]
                                  if d.severity == ERROR], [])

    def test_unknown_matcher_suggests(self):
        diags = analyze(CAT, parse("match functionDecl(hasNamex())"))[0]
        self.assertEqual(diags[0].code, "unknown-matcher")
        self.assertIn("hasName", diags[0].message)

    def test_cross_hierarchy_argument_is_rejected(self):
        self.assertIn("arg-type", codes("match functionDecl(integerLiteral())"))
        self.assertIn("arg-type", codes("match varDecl(hasBody(compoundStmt()))"))

    def test_sibling_kinds_build_but_cannot_match(self):
        # clang-query accepts this and reports 0 matches, so it is a warning.
        self.assertEqual(codes("match functionDecl(varDecl())"), ["dead-restriction"])

    def test_base_matchers_are_accepted_inside_derived(self):
        self.assertEqual(codes("match functionDecl(isPublic())"), [])
        self.assertEqual(codes("match decl(functionDecl())"), [])

    def test_qualtype_and_type_convert(self):
        self.assertEqual(codes("match varDecl(hasType(pointerType()))"), [])
        self.assertEqual(
            codes("match varDecl(hasType(pointerType(pointee(isConstQualified()))))"), [])

    def test_overloads_are_tried_in_turn(self):
        # hasType takes a Matcher<Decl> or a Matcher<QualType>; both are legal.
        self.assertEqual(codes("match varDecl(hasType(recordDecl()))"), [])
        self.assertEqual(codes('match varDecl(hasType(asString("int")))'), [])

    def test_top_level_must_name_a_node(self):
        self.assertEqual(codes('match hasName("x")'), ["top-level"])
        self.assertEqual(codes("match unless(functionDecl())"), ["top-level"])
        self.assertEqual(codes("match mapAnyOf(ifStmt, forStmt)"), [])
        self.assertEqual(codes('match sizeOfExpr(hasArgumentOfType(asString("int")))'), [])

    def test_bare_let_name_shadows_builtin(self):
        # clang-query resolves a bare name to the `let` first (27 matches on intro.cpp).
        self.assertEqual(codes("let hasName functionDecl()\nmatch hasName"), ["shadow"])

    def test_deep_overload_nesting_is_not_exponential(self):
        import time
        q = "cxxRecordDecl()"
        for _ in range(12):
            q = f"hasType(hasDeclaration(hasType({q})))"
        start = time.monotonic()
        self.assertNotIn("arg-type", codes(f"match varDecl({q})"))
        self.assertLess(time.monotonic() - start, 2.0)

    def test_let_body_may_be_a_narrowing_matcher(self):
        self.assertEqual(codes("let fixable allOf(isPublic(), isDefinition())"), [])

    def test_arity(self):
        self.assertEqual(codes('match functionDecl(hasName("a", "b"))'), ["arity"])
        self.assertEqual(codes("match allOf(functionDecl())"), ["top-level", "arity"])
        # pointee is variadic even though the reference prints one parameter.
        self.assertEqual(
            codes("match varDecl(hasType(pointerType(pointee(isConstQualified(), "
                  "isInteger()))))"), [])

    def test_literal_types(self):
        self.assertEqual(codes("match functionDecl(hasName(3))"), ["arg-type"])
        self.assertEqual(codes("match integerLiteral(equals(-1))"), ["negative-literal"])
        self.assertEqual(codes("match floatLiteral(equals(314e-2))"), [])

    def test_enum_values(self):
        self.assertEqual(codes('match functionDecl(hasAttr("attr::Nope"))'), ["enum-value"])
        self.assertEqual(codes('match cxxMethodDecl(hasAttr("attr::Override"))'), [])
        self.assertEqual(codes('match binaryOperator(hasOperatorName("=?="))'),
                         ["enum-value"])
        self.assertEqual(codes('match binaryOperator(hasOperatorName("+="))'), [])

    def test_bound_ids_must_exist(self):
        self.assertEqual(codes('match varDecl(equalsBoundNode("v"))'), ["unbound-id"])
        self.assertEqual(
            codes('match binaryOperator(hasLHS(declRefExpr(to(varDecl().bind("v")))), '
                  'hasRHS(declRefExpr(to(varDecl(equalsBoundNode("v"))))))'), [])

    def test_settings(self):
        self.assertEqual(codes("set output diag"), [])
        self.assertEqual(codes("set output diags"), ["set-value"])
        self.assertEqual(codes("set print-matcher yes"), ["set-value"])
        self.assertEqual(codes("set traversal IgnoreUnlessSpelledInSource"), [])
        self.assertEqual(codes("set bogus true"), ["set-option"])
        self.assertEqual(codes("enable output print"), [])

    def test_members(self):
        self.assertEqual(codes('match functionDecl().bind("f")'), [])
        self.assertEqual(codes('match functionDecl().bnd("f")'), ["unknown-member"])
        self.assertEqual(codes("match mapAnyOf(ifStmt, forStmt).with(hasCondition(expr()))"),
                         [])
        self.assertEqual(codes("match functionDecl().with(isPublic())"), ["with-owner"])

    def test_unregistered_matcher_warns(self):
        diags = analyze(CAT, parse("match cxxRecordDecl(requiresExpr())"))[0]
        self.assertEqual(diags[0].severity, WARNING)
        self.assertEqual(diags[0].code, "not-registered")

    def test_unterminated_string(self):
        self.assertIn("unterminated-string", codes('match functionDecl(hasName("x'))


class TestCompletion(unittest.TestCase):
    def test_commands_at_start_of_line(self):
        self.assertEqual(context_at(CAT, parse(""), 0).kind, "command")
        self.assertIn("match", labels(""))

    def test_top_level_offers_only_node_matchers(self):
        names = labels("match ")
        self.assertIn("functionDecl", names)
        self.assertNotIn("hasName", names)
        self.assertLess(names.index("decl"), names.index("functionDecl"))  # roots first

    def test_argument_slot_is_type_filtered(self):
        names = labels("match functionDecl(")
        self.assertIn("hasName", names)
        self.assertIn("isDefinition", names)
        self.assertNotIn("hasCastKind", names)      # Matcher<CastExpr>
        self.assertNotIn("hasOperatorName", names)  # Matcher<BinaryOperator>

    def test_specific_matchers_rank_first(self):
        names = labels("match cxxRecordDecl(hasMethod(")
        self.assertLess(names.index("isConst"), names.index("hasName"))

    def test_statement_slot_offers_statements(self):
        names = labels("match functionDecl(hasBody(")
        self.assertEqual(names[0], "stmt")
        self.assertIn("compoundStmt", names)
        self.assertNotIn("functionDecl", names)

    def test_string_argument_offers_enum_values(self):
        names = labels('match functionDecl(hasAttr("')
        self.assertIn("attr::Override", names)
        names = labels("match implicitCastExpr(hasCastKind(")
        self.assertIn("CK_NullToPointer", names)
        src = "match implicitCastExpr(hasCastKind("
        item = next(i for i in completions(CAT, parse(src), len(src))
                    if i["label"] == "CK_NoOp")
        self.assertEqual(item["insertText"], '"CK_NoOp"')

    def test_bound_ids_are_offered(self):
        src = 'match varDecl(hasInitializer(expr().bind("init")), equalsBoundNode("'
        self.assertEqual(labels(src), ["init"])

    def test_let_names_are_offered_after_definition(self):
        src = "let inner functionDecl()\nmatch decl("
        self.assertEqual(labels(src)[0], "inner")
        self.assertNotIn("inner", labels("match decl(\nlet inner functionDecl()", 11))

    def test_settings(self):
        self.assertEqual(labels("set "), ["bind-root", "enable-profile", "output",
                                         "print-matcher", "traversal"])
        self.assertEqual(labels("set output "), ["detailed-ast", "diag", "dump", "print"])
        self.assertEqual(labels("set print-matcher "), ["false", "true"])
        self.assertEqual(labels("set traversal "),
                         ["AsIs", "IgnoreUnlessSpelledInSource"])
        self.assertEqual(labels("enable "), ["output"])

    def test_members_after_dot(self):
        self.assertEqual(labels("match functionDecl()."), ["bind", "with"])

    def test_mapanyof_takes_bare_names(self):
        names = labels("match mapAnyOf(")
        self.assertIn("ifStmt", names)
        item = next(i for i in completions(CAT, parse("match mapAnyOf("), 15)
                    if i["label"] == "ifStmt")
        self.assertNotIn("insertText", item)


class TestHoverAndSignature(unittest.TestCase):
    def test_hover_matcher(self):
        text = hover(CAT, parse('match functionDecl(hasName("main"))'), 22)
        self.assertIn("hasName(string Name)", text["contents"]["value"])
        self.assertIn("Part 5", text["contents"]["value"])

    def test_hover_enum_value_in_string(self):
        src = 'match implicitCastExpr(hasCastKind("CK_NullToPointer"))'
        text = hover(CAT, parse(src), src.index("CK_") + 2)
        self.assertIn("CastKind", text["contents"]["value"])

    def test_hover_reports_unregistered(self):
        text = hover(CAT, parse("match requiresExpr()"), 8)
        self.assertIn("Not in clang-query 22", text["contents"]["value"])

    def test_signature_help_tracks_the_argument(self):
        src = "match functionDecl(hasParameter(0, parmVarDecl()))"
        help_ = signature_help(CAT, parse(src), src.index("0") + 1)
        self.assertEqual(help_["activeParameter"], 0)
        help_ = signature_help(CAT, parse(src), src.index("parmVarDecl"))
        self.assertEqual(help_["activeParameter"], 1)
        self.assertIn("hasParameter", help_["signatures"][help_["activeSignature"]]["label"])


class TestSemanticTokens(unittest.TestCase):
    def test_tokens_are_deltas_of_five(self):
        text = '# c\nmatch functionDecl(hasName("a")).bind("f")\n'
        doc = parse(text)
        data = semantic_tokens(CAT, doc, LineIndex(text))
        self.assertEqual(len(data) % 5, 0)
        self.assertEqual(data[:5], [0, 0, 3, 1, 0])          # comment on line 0
        self.assertEqual(data[5:7], [1, 0])                  # `match` on line 1

    def test_each_matcher_kind_and_every_literal_has_its_own_type(self):
        from astmatcher_lsp.features import SEMANTIC_TOKEN_TYPES as TYPES
        text = 'match cxxRecordDecl(has(fieldDecl(hasName("a"), isBitField(), true, 3)))'
        data = semantic_tokens(CAT, parse(text), LineIndex(text))
        kinds, char = {}, 0
        for i in range(0, len(data), 5):
            char += data[i + 1]
            kinds[text[char:char + data[i + 2]]] = TYPES[data[i + 3]]
        self.assertEqual(kinds["cxxRecordDecl"], "nodeMatcher")
        self.assertEqual(kinds["fieldDecl"], "nodeMatcher")
        self.assertEqual(kinds["hasName"], "narrowingMatcher")
        self.assertEqual(kinds["has"], "traversalMatcher")
        for lit in ('"a"', "true", "3"):
            self.assertEqual(kinds[lit], "literal", lit)


PAIR_OUTPUT = """
  Matcher: cxxRecordDecl(hasName("Pair"),
              has(fieldDecl().bind("v")))
  ==================================


Match #1:

/src/p.cpp:2:1: note: "root" binds here
    2 | struct Pair { int first; };
      | ^~~~~~~~~~~~~~~~~~~~~~~~~~
Binding for "root":
CXXRecordDecl 0x1 </src/p.cpp:2:1, col:26> col:8 struct Pair definition
`-FieldDecl 0x2 <col:15, col:19> col:19 first 'int'

/src/p.cpp:2:15: note: "v" binds here
    2 | struct Pair { int first; };
      |               ^~~~~~~~~
Binding for "v":
FieldDecl 0x2 </src/p.cpp:2:15, col:19> col:19 first 'int'

Binding for "t":
BuiltinType 0x3 'int'

1 match.
1:2: Error parsing argument 1 for matcher varDecl.
1:10: Matcher not found: hasNamex
"""


class TestRun(unittest.TestCase):
    """Parsing clang-query 22's text output into the runQuery JSON."""

    def test_dump_header_ranges(self):
        info = parse_dump_header(
            "CXXRecordDecl 0x9 </a/b.cpp:47:1, line:49:2> col:8 struct Pair definition")
        self.assertEqual(info["begin"], ("/a/b.cpp", 47, 1))
        self.assertEqual(info["end"], ("/a/b.cpp", 49, 2))
        self.assertEqual(info["summary"], "struct Pair definition")
        info = parse_dump_header("IntegerLiteral 0x9 </a/b.cpp:39:7> 'int' 42")
        self.assertEqual(info["end"], ("/a/b.cpp", 39, 7))
        self.assertEqual(info["summary"], "'int' 42")
        info = parse_dump_header("BuiltinType 0x9 'int'")
        self.assertIsNone(info["begin"])
        self.assertEqual(info["summary"], "'int'")

    def test_output_is_parsed_and_mapped_back_to_the_script(self):
        parser = OutputParser()
        for line in PAIR_OUTPUT.splitlines():
            parser.feed(line)
        state = parser.result()
        (query,) = state.queries
        self.assertEqual(query["count"], 1)
        self.assertIn("has(fieldDecl", query["matcher"])
        root, v, t = query["matches"][0]["bindings"]
        self.assertEqual((root["id"], root["kind"], root["location"]),
                         ("root", "CXXRecordDecl", "p.cpp:2:1"))
        self.assertEqual(root["range"]["start"], {"line": 1, "character": 0})
        self.assertEqual(root["range"]["end"]["line"], 1)
        self.assertEqual((v["id"], v["summary"]), ("v", "first 'int'"))
        self.assertIsNone(t["range"])                    # types have no location

        script = ('match cxxRecordDecl(hasName("Pair"),\n'
                  '              has(fieldDecl().bind("v")))\nlet v varDecl(hasNamex())\n')
        attach_query_ranges(state, parse(script))
        self.assertEqual(query["range"]["start"], {"line": 0, "character": 0})
        # clang-query counts a failing `let` from just after its name
        self.assertEqual([e["range"]["start"] for e in state.errors],
                         [{"line": 2, "character": 6}, {"line": 2, "character": 14}])

    def test_type_names_are_not_ranges(self):
        info = parse_dump_header("TemplateSpecializationType 0x7 'vector<int>' sugar")
        self.assertEqual((info["node"], info["begin"]), ("0x7", None))

    @unittest.skipUnless(Path(clang_query_path()).is_file(), "clang-query not installed")
    def test_same_node_in_two_matches_is_one_binding(self):
        query = ('match cxxRecordDecl(hasName("Pair"),\n'
                 '  eachOf(has(fieldDecl(hasName("first")).bind("v")),\n'
                 '         has(fieldDecl(hasName("second")).bind("v")))).bind("d")\n')
        result = run_query(query, str(LAB / "manifests" / "trav_decls.cpp"), ["-std=c++23"])
        self.assertEqual(result["queries"][0]["count"], 2)
        b = result["bindings"]
        self.assertEqual(list(b), ["root", "d", "v"])
        self.assertEqual(len(b["d"]), 1)                     # one record ...
        self.assertEqual([m["index"] for m in b["d"][0]["matches"]], [1, 2])   # ... twice
        self.assertEqual([n["text"] for n in b["v"]], ["int first", "int second"])
        self.assertEqual([[m["index"] for m in n["matches"]] for n in b["v"]], [[1], [2]])
        self.assertEqual(b, group_bindings(result["queries"]))

    def test_output_settings_in_the_script_are_blanked(self):
        text = "set output print\nenable output dump\nset bind-root false\nmatch decl()\n"
        script = build_script(text)
        body = script.split("\n", 3)[3]
        self.assertEqual(len(body), len(text))
        self.assertNotIn("print", body)
        self.assertIn("set bind-root false", body)

    @unittest.skipUnless(Path(clang_query_path()).is_file(), "clang-query not installed")
    def test_real_run(self):
        result = run_query('match integerLiteral(equals(42))\n',
                           str(LAB / "manifests" / "narrow_types.cpp"), ["-std=c++23"])
        self.assertTrue(result["ok"], result)
        (query,) = result["queries"]
        self.assertGreaterEqual(query["count"], 1)
        binding = query["matches"][0]["bindings"][0]
        self.assertEqual(binding["kind"], "IntegerLiteral")
        self.assertEqual(binding["text"], "42")

    def test_missing_sample_is_an_error_not_a_crash(self):
        result = run_query("match decl()\n", "/nonexistent/x.cpp")
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["errors"][0]["message"])


class TestServer(unittest.TestCase):
    def _session(self, messages: list[dict]) -> list[dict]:
        payload = b""
        for message in messages:
            body = json.dumps(message).encode()
            payload += b"Content-Length: %d\r\n\r\n" % len(body) + body
        out = io.BytesIO()
        Server(stdin=io.BytesIO(payload), stdout=out).run()
        raw, replies = out.getvalue(), []
        while raw:
            header, _, rest = raw.partition(b"\r\n\r\n")
            length = int(header.split(b":")[1])
            replies.append(json.loads(rest[:length]))
            raw = rest[length:]
        return replies

    def test_full_round_trip(self):
        uri = "file:///tmp/x.query"
        text = "match functionDecl(hasNamex())"
        replies = self._session([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "textDocument/didOpen",
             "params": {"textDocument": {"uri": uri, "languageId": "astmatcher",
                                         "version": 1, "text": text}}},
            {"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion",
             "params": {"textDocument": {"uri": uri},
                        "position": {"line": 0, "character": 19}}},
            {"jsonrpc": "2.0", "id": 3, "method": "textDocument/hover",
             "params": {"textDocument": {"uri": uri},
                        "position": {"line": 0, "character": 8}}},
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": {}},
            {"jsonrpc": "2.0", "method": "exit", "params": {}},
        ])
        initialize = next(r for r in replies if r.get("id") == 1)
        self.assertIn("completionProvider", initialize["result"]["capabilities"])

        published = next(r for r in replies
                         if r.get("method") == "textDocument/publishDiagnostics")
        self.assertEqual(published["params"]["diagnostics"][0]["code"], "unknown-matcher")
        self.assertEqual(published["params"]["diagnostics"][0]["range"]["start"],
                         {"line": 0, "character": 19})

        completion = next(r for r in replies if r.get("id") == 2)
        self.assertTrue(any(i["label"] == "hasName"
                            for i in completion["result"]["items"]))
        hover_reply = next(r for r in replies if r.get("id") == 3)
        self.assertIn("functionDecl", hover_reply["result"]["contents"]["value"])


class TestGeneratedData(unittest.TestCase):
    def test_every_reference_row_is_present(self):
        catalog = json.loads((LAB / "scripts" / "catalog.json").read_text())
        names = {row["name"] for row in catalog}
        self.assertEqual(names - set(CAT.matchers), set())

    def test_hierarchy_is_acyclic_and_rooted(self):
        for kind in CAT.matchers:
            for ret in CAT.matchers[kind].ret_kinds:
                self.assertTrue(CAT.ancestors(ret), f"{ret} missing from the hierarchy")
        for root in CAT.roots:
            self.assertIsNone(CAT.bases[root])

    def test_vim_syntax_and_grammar_mention_every_matcher(self):
        base = LAB / "tools" / "language-support"
        vim = (base / "vim" / "syntax" / "astmatcher.vim").read_text()
        grammar = (base / "vscode" / "syntaxes" / "astmatcher.tmLanguage.json").read_text()
        for name in ("functionDecl", "hasName", "hasDescendant"):
            self.assertIn(name, vim)
            self.assertIn(name, grammar)


if __name__ == "__main__":
    unittest.main()
