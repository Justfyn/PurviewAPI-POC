"""Offline regression tests for the raw API demo's fail-closed boundary."""

import asyncio
import io
import time
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from rich.console import Console

import classify_text as raw


ALLOW = {"policyActions": [], "processingErrors": []}
BLOCK = {
    "policyActions": [{
        "@odata.type": "#microsoft.graph.restrictAccessAction",
        "action": "restrictAccess",
        "restrictionAction": "block",
    }],
    "processingErrors": [],
}
INCOMPLETE = "EVALUATION_INCOMPLETE"
NO_COVERAGE = "NO_POLICY_COVERAGE"
SCOPES = [{
    "activities": "uploadText",
    "executionMode": "evaluateInline",
    "policyActions": [],
    "locations": [],
}]
PRIVATE_DIAGNOSTIC = "do-not-print-private-server-diagnostic"


class CapturedConsole:
    def setUp(self):
        super().setUp()
        self.output = io.StringIO()
        self.console_patch = patch.object(
            raw, "console", Console(file=self.output, width=180, color_system=None),
        )
        self.console_patch.start()
        self.addCleanup(self.console_patch.stop)

    def reset_output(self):
        self.output.seek(0)
        self.output.truncate(0)


class VerdictTests(CapturedConsole, unittest.TestCase):
    def test_legacy_allow_and_block(self):
        for result, expected in (
            (ALLOW, "ALLOWED"),
            ({"policyActions": []}, "ALLOWED"),
            (BLOCK, "BLOCKED"),
            ({"policyActions": [{"restrictionAction": "BLOCK"}]}, "BLOCKED"),
        ):
            with self.subTest(result=result):
                self.assertEqual(raw.verdict_from_result(result), expected)
                self.assertEqual(raw.render_result(result), expected)

    def test_explicit_block_wins_over_partial_errors_and_unknown_siblings(self):
        result = {
            "policyActions": BLOCK["policyActions"] + [None, {"action": "futureAction"}],
            "processingErrors": [{"message": PRIVATE_DIAGNOSTIC}],
            "_error": {"status": 503},
        }
        self.assertEqual(raw.verdict_from_result(result), "BLOCKED")
        self.assertEqual(raw.render_result(result), "BLOCKED")
        self.assertIn("processingErrors", self.output.getvalue())
        self.assertNotIn(PRIVATE_DIAGNOSTIC, self.output.getvalue())

    def test_absent_malformed_and_unsupported_results_fail_closed(self):
        results = [
            None, {}, [], "bad response", 1,
            {"_error": {}, "policyActions": []},
            {"error": {}, "policyActions": []},
            {"policyActions": None},
            {"policyActions": False},
            {"policyActions": {}},
            {"policyActions": "block"},
            {"policyActions": [None]},
            {"policyActions": [1]},
            {"policyActions": ["block"]},
            {"policyActions": [{}]},
            {"policyActions": [{"restrictionAction": 1}]},
            {"policyActions": [{"action": "unknownAction"}]},
            {"policyActions": [{"action": "futureAction", "restrictionAction": "block"}]},
            {"policyActions": [{"restrictionAction": "block", "@odata.type": "#futureAction"}]},
            {"policyActions": [{"action": "restrictAccess", "restrictionAction": "blockWithOverride"}]},
            {"policyActions": [{"action": "restrictAccess", "restrictionAction": "allow"}]},
            {"policyActions": [], "processingErrors": None},
            {"policyActions": [], "processingErrors": {}},
            {"policyActions": [], "processingErrors": False},
            {"policyActions": [], "processingErrors": "bad response"},
        ]
        for result in results:
            with self.subTest(result=result):
                self.assertEqual(raw.verdict_from_result(result), INCOMPLETE)
                self.assertEqual(raw.render_result(result), INCOMPLETE)

    def test_processing_errors_cannot_render_allow(self):
        result = {"policyActions": [], "processingErrors": [{"message": PRIVATE_DIAGNOSTIC}]}
        self.assertEqual(raw.render_result(result), INCOMPLETE)
        output = self.output.getvalue()
        self.assertIn("processingErrors", output)
        self.assertIn(INCOMPLETE, output)
        self.assertNotIn("ALLOWED", output)
        self.assertNotIn(PRIVATE_DIAGNOSTIC, output)

    def test_no_policy_coverage_is_not_failed_discovery_or_allow(self):
        self.assertEqual(raw.verdict_from_result({"_coverage": []}), NO_COVERAGE)
        self.assertEqual(raw.render_result({"_coverage": []}), NO_COVERAGE)
        output = self.output.getvalue()
        self.assertIn("Scope discovery succeeded", output)
        self.assertNotIn(INCOMPLETE, output)
        self.assertNotIn("ALLOWED", output)
        self.assertEqual(raw.verdict_from_result({"_coverage": None}), INCOMPLETE)
        self.assertEqual(raw.verdict_from_result({"_coverage": [], "_error": {}}), INCOMPLETE)
        self.assertEqual(raw.verdict_from_result({**BLOCK, "_coverage": []}), "BLOCKED")
        self.reset_output()
        raw.render_audit_result({"_coverage": []})
        self.assertIn(NO_COVERAGE, self.output.getvalue())
        self.assertNotIn("acknowledged", self.output.getvalue())

    def test_render_keeps_full_trace_identifiers(self):
        correlation_id, request_id = str(uuid.uuid4()), str(uuid.uuid4())
        timestamp = "2026-09-24T06:00:00+00:00"
        raw.render_result({
            **ALLOW,
            "_demo": {"correlation_id": correlation_id, "request_id": request_id, "timestamp": timestamp},
        })
        for value in (correlation_id, request_id, timestamp):
            self.assertIn(value, self.output.getvalue())

    def test_failed_scopes_are_not_labeled_no_policies(self):
        raw.display_protection_scopes(None)
        output = self.output.getvalue()
        self.assertIn(INCOMPLETE, output)
        self.assertNotIn("No policies apply", output)
        self.reset_output()
        raw.display_protection_scopes([])
        self.assertIn("No policies apply", self.output.getvalue())

    def test_audit_errors_are_not_success_or_raw_error_details(self):
        for result in (
            None,
            {"_error": {"message": PRIVATE_DIAGNOSTIC}},
            {"processingErrors": [{"message": PRIVATE_DIAGNOSTIC}], "policyActions": []},
            {},
            {"policyActions": [None]},
        ):
            with self.subTest(result=result):
                self.reset_output()
                raw.render_audit_result(result)
                output = self.output.getvalue()
                self.assertIn(INCOMPLETE, output)
                self.assertNotIn("acknowledged", output)
                self.assertNotIn("audited in Purview", output)
                self.assertNotIn(PRIVATE_DIAGNOSTIC, output)

    def test_audit_acknowledgement_does_not_claim_portal_arrival(self):
        for result in (ALLOW, {"_demo": {"http_status": 202}}, {"_demo": {"http_status": 204}}):
            with self.subTest(result=result):
                self.reset_output()
                raw.render_audit_result(result)
                self.assertIn("acknowledged", self.output.getvalue())
                self.assertIn("Portal arrival not verified", self.output.getvalue())

    def test_offline_failure_demo_uses_live_verdict_path_without_io(self):
        with (
            patch.object(raw, "get_token", side_effect=AssertionError("Unexpected authentication")),
            patch.object(raw.aiohttp, "ClientSession", side_effect=AssertionError("Unexpected network")),
            patch("random.choice", side_effect=AssertionError("Unexpected mock generation")),
            patch.object(raw, "verdict_from_result", wraps=raw.verdict_from_result) as verdict,
        ):
            results = raw.run_failure_demo()
        self.assertEqual(len(results), 5)
        self.assertEqual(sum(value == INCOMPLETE for _, value in results), 4)
        self.assertEqual(dict(results)["No policy coverage (valid empty scopes)"], NO_COVERAGE)
        self.assertEqual(dict(results)["Failed protection scope discovery"], INCOMPLETE)
        self.assertEqual(verdict.call_count, 5)
        output = self.output.getvalue()
        for text in ("SYNTHETIC ONLY", "503", "429", "processingErrors", "valid empty scopes",
                     "Failed protection scope discovery", NO_COVERAGE,
                     "Model calls: 0", "External actions: 0", "No live Purview events"):
            self.assertIn(text, output)


class RequestTests(CapturedConsole, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        state = patch.multiple(
            raw,
            _cached_etag="cached-scope-etag",
            _etag_timestamp=time.time(),
            _protection_scopes=SCOPES,
            _last_scope_compute_ms=0.0,
            _sequence_number=0,
            _correlation_id=str(uuid.uuid4()),
        )
        state.start()
        self.addCleanup(state.stop)
        self.token_patch = patch.object(raw, "get_token", return_value="offline-unit-test-token")
        self.token = self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.response = MagicMock()
        self.response.status = 200
        self.response.headers = {"ETag": "fresh-scope-etag"}
        self.response.json = AsyncMock(side_effect=lambda: dict(ALLOW))
        self.response.text = AsyncMock(return_value=PRIVATE_DIAGNOSTIC)
        self.response.__aenter__.return_value = self.response
        self.session = MagicMock()
        self.session.__aenter__.return_value = self.session
        self.session.request.return_value = self.response
        self.session_patch = patch.object(raw.aiohttp, "ClientSession", return_value=self.session)
        self.session_factory = self.session_patch.start()
        self.addCleanup(self.session_patch.stop)

    async def evaluate(self, kind):
        if kind == "text":
            return await raw.process_content("synthetic input")
        if kind == "file":
            return await raw.process_file_content(b"synthetic bytes", "test.docx")
        return await raw.audit_ai_response("synthetic response")

    async def test_http_failures_fail_closed_without_reading_error_body(self):
        for kind in ("text", "file", "audit"):
            for status in (401, 429, 503):
                with self.subTest(kind=kind, status=status):
                    self.response.status = status
                    result = await self.evaluate(kind)
                    self.assertEqual(raw.verdict_from_result(result), INCOMPLETE)
                    self.assertEqual(result["_error"]["status"], status)
                    self.assertNotIn(PRIVATE_DIAGNOSTIC, str(result))
                    self.response.text.assert_not_awaited()
                    self.response.json.assert_not_awaited()
        self.assertNotIn(PRIVATE_DIAGNOSTIC, self.output.getvalue())

    async def test_transport_and_timeout_failures_are_redacted(self):
        for kind in ("text", "file", "audit"):
            for error in (aiohttp.ClientConnectionError(PRIVATE_DIAGNOSTIC),
                          asyncio.TimeoutError(PRIVATE_DIAGNOSTIC)):
                with self.subTest(kind=kind, error=type(error)):
                    self.session.request.side_effect = error
                    result = await self.evaluate(kind)
                    self.assertEqual(raw.verdict_from_result(result), INCOMPLETE)
                    self.assertNotIn(PRIVATE_DIAGNOSTIC, str(result))

    async def test_authentication_failures_are_redacted(self):
        self.token.side_effect = RuntimeError(PRIVATE_DIAGNOSTIC)
        for kind in ("text", "file", "audit"):
            self.assertEqual(raw.verdict_from_result(await self.evaluate(kind)), INCOMPLETE)
        self.assertIsNone(await raw.compute_protection_scopes())
        self.assertIsNone(await raw.authenticate())
        self.session.request.assert_not_called()
        self.assertNotIn(PRIVATE_DIAGNOSTIC, self.output.getvalue())

    async def test_malformed_http_success_fails_closed(self):
        for payload in (None, [], "bad response", {}, {"policyActions": None}):
            with self.subTest(payload=payload):
                self.response.json.side_effect = None
                self.response.json.return_value = payload
                self.assertEqual(raw.verdict_from_result(await raw.process_content("test")), INCOMPLETE)
        self.response.json.side_effect = ValueError(PRIVATE_DIAGNOSTIC)
        self.assertEqual(raw.verdict_from_result(await raw.process_content("test")), INCOMPLETE)

    async def test_success_keeps_bounded_timeout_and_full_request_trace(self):
        for kind in ("text", "file", "audit"):
            result = await self.evaluate(kind)
            self.assertEqual(raw.verdict_from_result(result), "ALLOWED")
            timeout = self.session_factory.call_args.kwargs["timeout"]
            self.assertGreater(timeout.total, 0)
            self.assertLessEqual(timeout.total, 30)
            kwargs = self.session.request.call_args.kwargs
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + self.token.return_value)
            self.assertEqual(kwargs["headers"]["If-None-Match"], "cached-scope-etag")
            trace = result["_demo"]
            self.assertEqual(str(uuid.UUID(trace["request_id"])), trace["request_id"])
            self.assertEqual(trace["correlation_id"], raw._correlation_id)
            self.assertEqual(kwargs["headers"]["client-request-id"], trace["request_id"])
            self.assertTrue(trace["timestamp"].endswith("+00:00"))

    async def test_public_conversation_reset_preserves_scopes_and_restarts_sequence(self):
        correlation_id = str(uuid.uuid4())
        raw._sequence_number = 10
        raw.begin_conversation(correlation_id)
        self.assertEqual(raw._cached_etag, "cached-scope-etag")
        self.assertEqual(raw._protection_scopes, SCOPES)
        for sequence in (0, 1):
            result = await raw.process_content("synthetic prompt")
            entry = self.session.request.call_args.kwargs["json"]["contentToProcess"]["contentEntries"][0]
            self.assertEqual(entry["correlationId"], correlation_id)
            self.assertEqual(entry["sequenceNumber"], sequence)
            self.assertEqual(result["_demo"]["sequence_number"], sequence)
            self.assertEqual(result["_demo"]["correlation_id"], correlation_id)

    async def test_prompt_requests_prefer_inline_without_changing_response_audit(self):
        await raw.process_content("synthetic prompt")
        self.assertEqual(self.session.request.call_args.kwargs["headers"]["Prefer"], "evaluateInline")
        await raw.process_content("synthetic response", activity="downloadText")
        self.assertNotIn("Prefer", self.session.request.call_args.kwargs["headers"])
        await raw.audit_ai_response("synthetic response")
        self.assertNotIn("Prefer", self.session.request.call_args.kwargs["headers"])

    async def test_scope_http_failure_is_none_and_invalidates_all_cached_state(self):
        self.response.status = 503
        scopes = await raw.compute_protection_scopes()
        self.assertIsNone(scopes)
        self.assertIsNone(raw._cached_etag)
        self.assertIsNone(raw._protection_scopes)
        self.assertEqual(raw._etag_timestamp, 0)
        self.response.text.assert_not_awaited()
        self.reset_output()
        raw.display_protection_scopes(scopes)
        self.assertNotIn("No policies apply", self.output.getvalue())

    async def test_valid_empty_scopes_are_distinct_from_failure(self):
        self.response.json.side_effect = None
        self.response.json.return_value = {"value": []}
        scopes = await raw.compute_protection_scopes()
        self.assertEqual(scopes, [])
        self.assertEqual(raw._protection_scopes, [])
        self.assertEqual(raw._cached_etag, "fresh-scope-etag")
        self.assertGreater(raw._etag_timestamp, 0)
        self.response.json.return_value = dict(ALLOW)
        for kind in ("text", "file", "audit"):
            self.assertEqual(raw.verdict_from_result(await self.evaluate(kind)), NO_COVERAGE)
        self.assertEqual(self.session.request.call_count, 1)
        self.assertTrue(self.session.request.call_args.args[1].endswith("/compute"))

    async def test_scope_missing_value_malformed_and_partial_errors_invalidate_cache(self):
        for data in ({}, {"value": None}, {"value": {}}, {"value": [None]},
                     {"value": [{"policyActions": None}]},
                     {"value": [], "processingErrors": [{"message": PRIVATE_DIAGNOSTIC}]}):
            with self.subTest(data=data):
                self.response.json.side_effect = None
                self.response.json.return_value = data
                self.assertIsNone(await raw.compute_protection_scopes())
                self.assertIsNone(raw._cached_etag)
                self.assertIsNone(raw._protection_scopes)
        self.assertNotIn(PRIVATE_DIAGNOSTIC, self.output.getvalue())

    async def test_scope_transport_failure_is_none(self):
        self.session.request.side_effect = asyncio.TimeoutError(PRIVATE_DIAGNOSTIC)
        self.assertIsNone(await raw.compute_protection_scopes())
        self.assertIsNone(raw._cached_etag)
        self.assertNotIn(PRIVATE_DIAGNOSTIC, self.output.getvalue())

    async def test_failed_stale_refresh_never_sends_content(self):
        raw._etag_timestamp = time.time() - raw.ETAG_REFRESH_SECONDS - 1
        self.response.status = 503
        result = await raw.process_content("test")
        self.assertEqual(raw.verdict_from_result(result), INCOMPLETE)
        self.assertEqual(self.session.request.call_count, 1)
        self.assertTrue(self.session.request.call_args.args[1].endswith("/compute"))
        self.assertIsNone(raw._cached_etag)

    async def test_missing_scopes_hold_text_file_and_audit_requests(self):
        raw._protection_scopes = None
        for kind in ("text", "file", "audit"):
            self.assertEqual(raw.verdict_from_result(await self.evaluate(kind)), INCOMPLETE)
        self.session.request.assert_not_called()

    async def test_failed_modified_scope_refresh_preserves_block_but_not_allow(self):
        for result, expected in ((ALLOW, INCOMPLETE), (BLOCK, "BLOCKED")):
            with self.subTest(expected=expected):
                raw._protection_scopes = SCOPES
                raw._etag_timestamp = time.time()
                self.response.json.side_effect = [
                    {**result, "protectionScopeState": "modified"},
                    {"error": {"message": PRIVATE_DIAGNOSTIC}},
                ]
                evaluated = await raw.process_content("test")
                self.assertEqual(raw.verdict_from_result(evaluated), expected)
                self.assertIsNone(raw._cached_etag)

    async def test_modified_scope_refresh_with_no_coverage_is_not_allow_or_failure(self):
        for result, expected in ((ALLOW, NO_COVERAGE), (BLOCK, "BLOCKED")):
            with self.subTest(expected=expected):
                raw._protection_scopes = SCOPES
                raw._etag_timestamp = time.time()
                self.response.json.side_effect = [
                    {**result, "protectionScopeState": "modified"},
                    {"value": []},
                ]
                evaluated = await raw.process_content("test")
                self.assertEqual(raw.verdict_from_result(evaluated), expected)
                self.assertNotIn("_error", evaluated)
                self.assertEqual(evaluated["_coverage"], [])

    async def test_audit_http_accepted_is_not_a_policy_allow(self):
        for status in (202, 204):
            with self.subTest(status=status):
                self.response.status = status
                result = await raw.audit_ai_response("test")
                self.assertEqual(raw.verdict_from_result(result), INCOMPLETE)
                self.reset_output()
                raw.render_audit_result(result)
                self.assertIn("acknowledged", self.output.getvalue())
                self.assertIn("Portal arrival not verified", self.output.getvalue())

    async def test_chat_never_generates_or_audits_after_incomplete_or_block(self):
        for result, expected in (
            (None, INCOMPLETE),
            ({}, INCOMPLETE),
            ({"policyActions": [None]}, INCOMPLETE),
            ({"policyActions": [], "processingErrors": [{"message": PRIVATE_DIAGNOSTIC}]}, INCOMPLETE),
            ({"_coverage": []}, NO_COVERAGE),
            (BLOCK, "BLOCKED"),
            ({**BLOCK, "processingErrors": [{"message": PRIVATE_DIAGNOSTIC}]}, "BLOCKED"),
        ):
            with self.subTest(result=result):
                self.reset_output()
                with (
                    patch.object(raw.Prompt, "ask", side_effect=["synthetic prompt", "quit"]),
                    patch.object(raw, "process_content", AsyncMock(return_value=result)),
                    patch("random.choice") as generate,
                    patch.object(raw, "audit_ai_response", AsyncMock()) as audit,
                ):
                    await raw.interactive_chat()
                generate.assert_not_called()
                audit.assert_not_awaited()
                self.assertIn(expected, self.output.getvalue())
                self.assertNotIn(PRIVATE_DIAGNOSTIC, self.output.getvalue())
                if isinstance(result, dict) and result.get("processingErrors"):
                    self.assertIn("processingErrors", self.output.getvalue())

    async def test_chat_legacy_allow_still_generates_and_audits(self):
        with (
            patch.object(raw.Prompt, "ask", side_effect=["synthetic prompt", "quit"]),
            patch.object(raw, "process_content", AsyncMock(return_value=ALLOW)),
            patch("random.choice", return_value="mock response") as generate,
            patch.object(raw, "audit_ai_response", AsyncMock(return_value=ALLOW)) as audit,
        ):
            await raw.interactive_chat()
        generate.assert_called_once()
        audit.assert_awaited_once_with("mock response")

    async def test_file_probe_binary_error_is_inconclusive_not_text_only(self):
        for result_b in (
            None,
            {},
            {"_error": {"status": 503, "message": PRIVATE_DIAGNOSTIC}},
            {"policyActions": [], "processingErrors": [{"message": PRIVATE_DIAGNOSTIC}]},
            {**BLOCK, "processingErrors": [{"message": PRIVATE_DIAGNOSTIC}]},
        ):
            with self.subTest(result_b=result_b):
                self.reset_output()
                with (
                    patch.object(raw, "compute_protection_scopes", AsyncMock(return_value=SCOPES)),
                    patch.object(raw, "process_content", AsyncMock(return_value=BLOCK)),
                    patch.object(raw, "process_file_content", AsyncMock(side_effect=[result_b, BLOCK])),
                ):
                    verdicts = await raw.run_file_support_probe()
                self.assertEqual(verdicts["B"], raw.verdict_from_result(result_b))
                output = self.output.getvalue()
                self.assertIn("INCONCLUSIVE", output)
                self.assertNotIn("TEXT ONLY — CONFIRMED", output)
                self.assertNotIn("TEXT-ONLY SIGNAL", output)
                self.assertNotIn(PRIVATE_DIAGNOSTIC, output)

    async def test_file_probe_scope_failure_does_not_send_variants(self):
        with (
            patch.object(raw, "compute_protection_scopes", AsyncMock(return_value=None)),
            patch.object(raw, "process_content", AsyncMock()) as text,
            patch.object(raw, "process_file_content", AsyncMock()) as file,
        ):
            verdicts = await raw.run_file_support_probe()
        self.assertEqual(verdicts, {label: INCOMPLETE for label in ("A", "B", "C")})
        text.assert_not_awaited()
        file.assert_not_awaited()
        self.assertIn("INCONCLUSIVE", self.output.getvalue())

    async def test_file_probe_empty_scopes_are_no_coverage_not_failed_discovery(self):
        with (
            patch.object(raw, "compute_protection_scopes", AsyncMock(return_value=[])),
            patch.object(raw, "process_content", AsyncMock()) as text,
            patch.object(raw, "process_file_content", AsyncMock()) as file,
        ):
            verdicts = await raw.run_file_support_probe()
        self.assertEqual(verdicts, {label: NO_COVERAGE for label in ("A", "B", "C")})
        text.assert_not_awaited()
        file.assert_not_awaited()
        self.assertNotIn(INCOMPLETE, self.output.getvalue())
        self.assertIn("scope discovery succeeded", self.output.getvalue())

    async def test_file_probe_observations_are_bounded_not_general_format_proof(self):
        for result_b, conclusion in ((BLOCK, "BINARY BLOCK OBSERVED"), (ALLOW, "TEXT-ONLY SIGNAL")):
            with self.subTest(conclusion=conclusion):
                self.reset_output()
                with (
                    patch.object(raw, "compute_protection_scopes", AsyncMock(return_value=SCOPES)),
                    patch.object(raw, "process_content", AsyncMock(return_value=BLOCK)),
                    patch.object(raw, "process_file_content", AsyncMock(side_effect=[result_b, BLOCK])),
                ):
                    await raw.run_file_support_probe()
                output = self.output.getvalue()
                self.assertIn(conclusion, output)
                self.assertIn("first-party SDK supports binary data transport", output)
                self.assertIn("tenant", output)
                self.assertNotIn("always send text", output)
                self.assertNotIn("TEXT ONLY — CONFIRMED", output)
                self.assertNotIn("You can send files directly", output)

    async def test_failure_demo_cli_skips_authentication_and_live_flow(self):
        with (
            patch.object(raw.sys, "argv", ["classify_text.py", "--failure-demo"]),
            patch.object(raw, "authenticate", AsyncMock()) as authenticate,
            patch.object(raw, "run_demo", AsyncMock()) as demo,
        ):
            await raw.main()
        authenticate.assert_not_awaited()
        demo.assert_not_awaited()
        self.session.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
