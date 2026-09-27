"""Completion regressions for partial, multiline matcher expressions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from astmatcher_lsp.catalog import load  # noqa: E402
from astmatcher_lsp.features import completions, context_at  # noqa: E402
from astmatcher_lsp.parser import parse  # noqa: E402

CAT = load()


def completion_state(text: str):
    doc = parse(text)
    context = context_at(CAT, doc, len(text))
    items = completions(CAT, doc, len(text))
    return context, {item["label"] for item in items}


class TestPartialMultilineCompletion(unittest.TestCase):
    def test_newline_after_outer_comma_keeps_record_kind(self):
        text = 'match cxxRecordDecl(\n    hasName("Pair"),\n    '
        context, names = completion_state(text)
        self.assertEqual(context.expected, "CXXRecordDecl")
        self.assertIn("hasName", names)
        self.assertNotIn("functionDecl", names)

    def test_anyof_arguments_keep_the_enclosing_node_kind(self):
        text = ('match cxxRecordDecl(\n    hasName("Pair"),\n'
                '    anyOf(\n        ')
        context, names = completion_state(text)
        self.assertEqual(context.expected, "CXXRecordDecl")
        self.assertIn("has", names)
        self.assertNotIn("functionDecl", names)

    def test_nested_node_arguments_filter_unrelated_node_matchers(self):
        text = ('match cxxRecordDecl(\n    hasName("Pair"),\n'
                '    anyOf(\n        has(fieldDecl(')
        context, names = completion_state(text)
        self.assertEqual(context.expected, "FieldDecl")
        self.assertIn("isBitField", names)
        self.assertNotIn("functionDecl", names)
        self.assertNotIn("cxxRecordDecl", names)

    def test_indent_after_completed_bind_returns_to_anyof_slot(self):
        text = ('match cxxRecordDecl(\n    hasName("Pair"),\n'
                '    anyOf(\n        '
                'has(fieldDecl(hasName("first")).bind("v")),\n        ')
        context, names = completion_state(text)
        self.assertEqual(context.call.name, "anyOf")
        self.assertEqual(context.index, 1)
        self.assertEqual(context.expected, "CXXRecordDecl")
        self.assertIn("has", names)
        self.assertNotIn("functionDecl", names)

    def test_dot_and_bind_prefixes_offer_member_completion(self):
        base = ('match cxxRecordDecl(\n    hasName("Pair"),\n'
                '    anyOf(\n        has(fieldDecl(hasName("first"))')
        for suffix, prefix in ((".", ""), (".b", "b"), (".bind", "bind")):
            with self.subTest(suffix=suffix):
                text = base + suffix
                context, names = completion_state(text)
                self.assertEqual(context.kind, "member")
                self.assertEqual(context.prefix, prefix)
                self.assertIn("bind", names)

    def test_partial_matcher_names_keep_their_filter_prefix(self):
        cases = (("match cxxRecordD", "cxxRecordD", "cxxRecordDecl"),
                 ('match cxxRecordDecl(anyOf(has(fieldD', "fieldD", "fieldDecl"))
        for text, prefix, matcher_name in cases:
            with self.subTest(text=text):
                doc = parse(text)
                context = context_at(CAT, doc, len(text))
                items = completions(CAT, doc, len(text))
                self.assertEqual(context.prefix, prefix)
                self.assertEqual(context.replace, (len(text) - len(prefix), len(text)))
                item = next(item for item in items if item["label"] == matcher_name)
                self.assertEqual(item["filterText"], matcher_name)


if __name__ == "__main__":
    unittest.main()
