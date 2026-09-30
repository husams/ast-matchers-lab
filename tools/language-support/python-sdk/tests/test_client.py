import unittest
from pathlib import Path

from astmatcher_sdk import Definition, MatcherClient, MatcherError, MatcherQuery


ROOT = Path(__file__).resolve().parents[4]
SAMPLE = ROOT / "manifests" / "intro.cpp"


class QueryTests(unittest.TestCase):
    def test_declarative_request_orders_definitions_before_matches(self) -> None:
        query = MatcherQuery(
            source=SAMPLE,
            definitions=(Definition("named", 'functionDecl(hasName("add"))'),),
            matches=("named",),
            flags=("-std=c++23",),
        )
        request = query.request()
        self.assertEqual(request["commands"], [
            {"kind": "LET", "name": "named",
             "expression": 'functionDecl(hasName("add"))'},
            {"kind": "MATCH", "expression": "named"},
        ])
        self.assertEqual(request["workingDirectory"], str(SAMPLE.parent))

    def test_rejects_empty_matcher_and_invalid_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            MatcherQuery(source=SAMPLE, matches=())
        with self.assertRaisesRegex(ValueError, "max_matches"):
            MatcherQuery(source=SAMPLE, matches=("functionDecl()",),
                         max_matches=10001)


class NativeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_binary_reports_status(self) -> None:
        client = MatcherClient(binary="/missing/astmatcher-native")
        status = await client.status()
        self.assertEqual(status.state, "unavailable")
        with self.assertRaisesRegex(MatcherError, "unavailable"):
            await client.start()

    async def test_auto_start_query_status_and_cleanup(self) -> None:
        client = MatcherClient()
        try:
            self.assertEqual((await client.status()).state, "stopped")
            result = await client.run(MatcherQuery(
                source=SAMPLE,
                definitions=(Definition("named", 'functionDecl(hasName("add"))'),),
                matches=("named",),
                flags=("-std=c++23",),
            ))
            status = await client.status()
            self.assertTrue(status.ready)
            self.assertTrue(status.compiler_path)
            self.assertEqual(len(result.queries), 1)
            self.assertEqual(result.queries[0].command_index, 1)
            self.assertGreaterEqual(result.queries[0].count, 1)
            self.assertEqual(result.diagnostics, ())
        finally:
            await client.close()
        self.assertEqual((await client.status()).state, "stopped")

    async def test_native_matcher_diagnostic_is_structured(self) -> None:
        async with MatcherClient() as client:
            result = await client.run(MatcherQuery(
                source=SAMPLE, matches=("notRegisteredMatcher()",),
                flags=("-std=c++23",),
            ))
        self.assertTrue(result.diagnostics)
        self.assertIn("Matcher not found", result.diagnostics[0].message)
