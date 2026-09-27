"""Regression coverage for unmatched DSL delimiters."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from astmatcher_lsp.analyze import ERROR, analyze  # noqa: E402
from astmatcher_lsp.catalog import load             # noqa: E402
from astmatcher_lsp.parser import calls_at, parse   # noqa: E402

CAT = load()


class TestSyntaxDiagnostics(unittest.TestCase):
    def diagnostics(self, source: str):
        return analyze(CAT, parse(source))[0]

    def test_extra_brace_after_multiline_matcher_is_a_syntax_error(self):
        source = (
            'match cxxRecordDecl(\n'
            '  hasName("Pair"),\n'
            '  anyOf(\n'
            '    has(fieldDecl(hasName("first")).bind("v")),\n'
            '    has(fieldDecl(hasName("second")).bind("v"))\n'
            '  )\n'
            ')\n'
            '}\n'
        )
        diags = self.diagnostics(source)
        brace = source.rindex("}")
        syntax = [d for d in diags if d.code == "stray"]
        self.assertEqual(len(syntax), 1)
        self.assertEqual((syntax[0].start, syntax[0].end), (brace, brace + 1))
        self.assertEqual(syntax[0].severity, ERROR)
        self.assertEqual(syntax[0].message, "unexpected input: '}'")

    def test_extra_brace_nested_before_expected_closers_is_reported(self):
        source = "match cxxRecordDecl(anyOf(, } ))"
        diags = self.diagnostics(source)
        self.assertEqual([d.code for d in diags], ["arity", "stray"])
        self.assertEqual(diags[1].message, "unexpected input: '}'")

    def test_extra_parenthesis_is_reported(self):
        diags = self.diagnostics("match cxxRecordDecl(anything()))")
        self.assertEqual([(d.code, d.message) for d in diags],
                         [("stray", "unexpected input: ')'")])

    def test_delimiter_characters_in_strings_and_comments_are_ignored(self):
        source = 'match cxxRecordDecl(hasName("}")) # ] }\n'
        self.assertEqual(self.diagnostics(source), [])

    def test_incomplete_call_remains_available_for_completion(self):
        doc = parse('match cxxRecordDecl(\n  hasName("Pair"),\n  anyOf(')
        chain = calls_at(doc, len(doc.text))
        self.assertEqual([call.name for call in chain], ["cxxRecordDecl", "anyOf"])
        self.assertTrue(any(d.code == "unclosed" and d.severity == ERROR
                            for d in self.diagnostics(doc.text)))


if __name__ == "__main__":
    unittest.main()
