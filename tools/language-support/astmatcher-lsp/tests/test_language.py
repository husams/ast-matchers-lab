"""Tests for the matcher-DSL language support.

    python3 -m unittest discover -s tools/language-support/astmatcher-lsp/tests

The interesting cases are the ones checked against the real clang-query 22
behaviour; each is noted where it is not obvious.
"""

from __future__ import annotations

from dataclasses import replace
import io
import json
import sys
import tempfile
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
from astmatcher_lsp.native_client import (NativeClientError, native_binary_path)  # noqa: E402
from astmatcher_lsp.run import group_bindings, native_commands, run_query  # noqa: E402
from astmatcher_lsp.server import Server                            # noqa: E402
from astmatcher_lsp.targets import (compile_flags,                   # noqa: E402
                                    find_compile_database)

CAT = load()
LAB = HERE.parent.parent.parent.parent


def native_available() -> bool:
    try:
        return Path(native_binary_path()).is_file()
    except NativeClientError:
        return False


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

    def test_linked_clang_capability_filters_completion_and_reports_error(self):
        unavailable = replace(CAT.matchers["arrayTypeLoc"],
                              native_available=False, native_llvm_major=21)
        cat = replace(CAT, matchers={**CAT.matchers,
                                     "arrayTypeLoc": unavailable})
        query = parse("match arrayTypeLoc()")
        diags = analyze(cat, query)[0]
        self.assertEqual(diags[0].severity, ERROR)
        self.assertEqual(diags[0].code, "unavailable-matcher")
        self.assertIn("linked Clang 21", diags[0].message)
        names = {item["label"] for item in completions(cat, parse("match "), 6)}
        self.assertNotIn("arrayTypeLoc", names)
        self.assertIn("functionDecl", names)
        markdown = hover(cat, query, 9)["contents"]["value"]
        self.assertIn("linked Clang 21", markdown)

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


class TestRun(unittest.TestCase):
    def test_native_commands_preserve_expression_and_settings(self):
        text = ('# sample: a.cpp\nset output print\n'
                'let chosen integerLiteral(equals(42))\n'
                'set traversal IgnoreUnlessSpelledInSource\n'
                'set bind-root false\n'
                'match varDecl(hasInitializer(chosen)).bind("v")\n')
        commands, originals, error = native_commands(parse(text))
        self.assertIsNone(error)
        self.assertEqual([c["kind"] for c in commands],
                         ["LET", "SET_TRAVERSAL", "SET_BIND_ROOT", "MATCH"])
        self.assertEqual(commands[0]["name"], "chosen")
        self.assertEqual(commands[0]["expression"], "integerLiteral(equals(42))")
        self.assertEqual(commands[-1]["expression"],
                         'varDecl(hasInitializer(chosen)).bind("v")')
        self.assertEqual([c.name for c in originals], ["let", "set", "set", "match"])

    def test_incomplete_native_setting_is_sent_for_diagnostics(self):
        commands, _, error = native_commands(parse("set traversal\nset bind-root\n"))
        self.assertIsNone(error)
        self.assertEqual(commands, [{"kind": "SET_TRAVERSAL", "value": ""},
                                    {"kind": "SET_BIND_ROOT", "value": ""}])

    @unittest.skipUnless(native_available(), "native matcher server not built")
    def test_same_node_in_two_matches_is_one_binding(self):
        query = ('match cxxRecordDecl(hasName("Pair"),\n'
                 '  eachOf(has(fieldDecl(hasName("first")).bind("v")),\n'
                 '         has(fieldDecl(hasName("second")).bind("v")))).bind("d")\n')
        result = run_query(query, str(LAB / "manifests" / "trav_decls.cpp"), ["-std=c++23"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["queries"][0]["count"], 2)
        bindings = result["bindings"]
        self.assertEqual(list(bindings), ["root", "d", "v"])
        self.assertEqual(len(bindings["d"]), 1)
        self.assertEqual([m["index"] for m in bindings["d"][0]["matches"]], [1, 2])
        self.assertEqual([n["text"] for n in bindings["v"]], ["int first", "int second"])
        self.assertEqual(bindings, group_bindings(result["queries"]))

    @unittest.skipUnless(native_available(), "native matcher server not built")
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


class TestCompileFlags(unittest.TestCase):
    """compile_commands.json lookup, including the header fallback."""

    def database(self, root: Path, *entries: dict) -> str:
        path = root / "compile_commands.json"
        path.write_text(json.dumps(list(entries)))
        return str(path)

    def entry(self, root: Path, name: str, *args: str) -> dict:
        return {"directory": str(root), "file": name,
                "arguments": ["clang++", *args, "-c", name]}

    def test_no_database_keeps_the_explicit_flags(self):
        self.assertEqual(compile_flags(None, "/x/a.cpp", ["-std=c++23"], "/x"),
                         (["-std=c++23"], None))

    def test_exact_entry_drops_the_source_and_the_output_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.cpp").write_text("")
            db = self.database(root, {
                "directory": str(root), "file": "a.cpp",
                "arguments": ["clang++", "-std=c++17", "-Iinc", "-DX=1",
                              "-o", "a.o", "-c", "a.cpp"]})
            flags, directory = compile_flags(db, str(root / "a.cpp"), [], str(root))
            self.assertEqual(flags, ["-std=c++17", "-Iinc", "-DX=1"])
            self.assertEqual(directory, str(root))

    def test_database_std_wins_over_the_configured_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = self.database(root, self.entry(root, "a.cpp", "-std=c++17", "-Iinc"))
            flags, _ = compile_flags(db, str(root / "a.cpp"), ["-std=c++23", "-Wall"], str(root))
            self.assertEqual(flags, ["-std=c++17", "-Iinc", "-Wall"])

    def test_header_uses_the_same_stem_translation_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = self.database(root,
                               self.entry(root, "other.cpp", "-DOTHER=1"),
                               self.entry(root, "widget.cpp", "-DWIDGET=1"))
            flags, directory = compile_flags(db, str(root / "widget.hpp"), [], str(root))
            self.assertEqual(flags, ["-DWIDGET=1"])
            self.assertEqual(directory, str(root))

    def test_header_falls_back_to_the_nearest_enclosing_translation_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "include" / "deep").mkdir(parents=True)
            db = self.database(root, self.entry(root / "src", "main.cpp", "-I../include"))
            flags, directory = compile_flags(
                db, str(root / "include" / "deep" / "model.hpp"), ["-std=c++23"], str(root))
            self.assertEqual(flags, ["-I../include", "-std=c++23"])
            self.assertEqual(directory, str(root / "src"))

    def test_auto_finds_the_database_in_a_build_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "build").mkdir()
            (root / "build" / "compile_commands.json").write_text(json.dumps([
                self.entry(root / "src", "main.cpp", "-std=c++20", "-Iinc")]))
            header = root / "src" / "main.hpp"
            self.assertEqual(Path(find_compile_database(str(header))),
                             (root / "build" / "compile_commands.json").resolve())
            flags, directory = compile_flags("auto", str(header), ["-std=c++23"], str(root))
            self.assertEqual(flags, ["-std=c++20", "-Iinc"])
            self.assertEqual(directory, str(root / "src"))

    def test_auto_without_a_database_keeps_the_explicit_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.cpp").write_text("")
            self.assertEqual(compile_flags("auto", str(root / "a.cpp"), ["-std=c++23"], str(root)),
                             (["-std=c++23"], None))

    def test_unrelated_database_keeps_the_explicit_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = self.database(root, {"directory": "/elsewhere/build",
                                      "file": "/elsewhere/src/a.cpp",
                                      "arguments": ["clang++", "-c", "/elsewhere/src/a.cpp"]})
            self.assertEqual(compile_flags(db, str(root / "b.hpp"), ["-std=c++23"], str(root)),
                             (["-std=c++23"], None))

    def test_unrelated_database_without_flags_reports_the_gap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = self.database(root, {"directory": "/elsewhere/build",
                                      "file": "/elsewhere/src/a.cpp",
                                      "arguments": ["clang++", "-c", "/elsewhere/src/a.cpp"]})
            with self.assertRaises(ValueError):
                compile_flags(db, str(root / "b.hpp"), [], str(root))


if __name__ == "__main__":
    unittest.main()
