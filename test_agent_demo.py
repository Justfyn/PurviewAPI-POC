"""Offline tests exercising the pinned SDK middleware with fake Graph/model services."""

import base64
import asyncio
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import agent_demo

try:
    import httpx
    from agent_framework_openai import OpenAIChatCompletionClient
    from openai import AsyncOpenAI
    import agent_framework_purview
except ImportError:
    agent_framework_purview = None

APP_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
TENANT_ID = "33333333-3333-4333-8333-333333333333"
SCOPES = [{
    "activities": "uploadText",
    "executionMode": "evaluateInline",
    "locations": [{
        "@odata.type": "microsoft.graph.policyLocationApplication",
        "value": APP_ID,
    }],
}]


class CoverageTests(unittest.TestCase):
    def test_scope_states_are_distinct(self):
        for scopes, expected in [
            (None, "EVALUATION_INCOMPLETE"),
            ([], "NO_POLICY_COVERAGE"),
            ([{}], "EVALUATION_INCOMPLETE"),
            (SCOPES, "COVERED"),
            ([dict(SCOPES[0], executionMode="evaluateOffline")], "NO_POLICY_COVERAGE"),
            ([dict(SCOPES[0], activities="downloadText")], "NO_POLICY_COVERAGE"),
        ]:
            with self.subTest(scopes=scopes):
                self.assertEqual(agent_demo.scope_coverage(scopes, APP_ID), expected)

    def test_wrong_location_is_not_coverage(self):
        self.assertEqual(agent_demo.scope_coverage(SCOPES, USER_ID), "NO_POLICY_COVERAGE")

    def test_malformed_location_is_incomplete(self):
        self.assertEqual(
            agent_demo.scope_coverage([dict(SCOPES[0], locations=[{"@odata.type": None}])], APP_ID),
            "EVALUATION_INCOMPLETE",
        )

    def test_known_scope_block_is_not_ignored(self):
        scopes = [dict(SCOPES[0], policyActions=[{
            "action": "restrictAccess", "restrictionAction": "block",
        }])]
        self.assertEqual(agent_demo.scope_coverage(scopes, APP_ID), "BLOCKED")


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_distinguishes_empty_scopes_from_failure(self):
        for scopes, expected in [(None, "EVALUATION_INCOMPLETE"), ([], "NO_POLICY_COVERAGE")]:
            with self.subTest(scopes=scopes):
                output = io.StringIO()
                with (
                    patch.object(agent_demo, "validate_configuration"),
                    patch.object(agent_demo.graph_demo, "authenticate", AsyncMock(return_value={"id": USER_ID})),
                    patch.object(agent_demo.graph_demo, "compute_protection_scopes", AsyncMock(return_value=scopes)),
                    redirect_stdout(output),
                ):
                    self.assertIsNone(await agent_demo.preflight())
                self.assertIn(expected, output.getvalue())
                self.assertIn("Collection policy: NOT VERIFIED", output.getvalue())

    async def test_collection_acknowledgment_is_required_before_model_setup(self):
        with (
            patch.object(agent_demo, "preflight", AsyncMock(return_value={"id": USER_ID})),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                await agent_demo.main(SimpleNamespace(preflight=False, collection_confirmed=False)), 1,
            )


@unittest.skipUnless(agent_framework_purview, "Install requirements-sdk.txt for SDK integration tests")
class JourneyTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, *, block=False, graph_status=200, coverage=SCOPES,
                       gate_verdict="ALLOWED", gate_exception=None, sdk_processing_errors=None):
        requests = []
        model_calls = []

        def graph_handler(request):
            body = json.loads(request.content)
            if request.url.host == "model.invalid":
                model_calls.append(body)
                return httpx.Response(200, json={
                    "id": "completion-1", "object": "chat.completion", "created": 0,
                    "model": "test-model",
                    "choices": [{
                        "index": 0, "message": {"role": "assistant", "content": "Synthetic summary."},
                        "finish_reason": "stop",
                    }],
                })
            requests.append(body)
            if request.url.path.endswith("/compute"):
                return httpx.Response(200, json={"value": SCOPES})
            if graph_status != 200:
                return httpx.Response(graph_status, json={"error": {"message": "DO NOT LOG BODY"}})
            sensitive = agent_demo.SENSITIVE_RECORD in json.dumps(body)
            actions = (
                [{"action": "restrictAccess", "restrictionAction": "block"}]
                if block and sensitive else []
            )
            return httpx.Response(200, json={
                "id": "test-response", "policyActions": actions,
                "processingErrors": sdk_processing_errors or [],
            })

        async def token_provider():
            payload = base64.urlsafe_b64encode(json.dumps({
                "idtyp": "user", "oid": USER_ID, "tid": TENANT_ID, "appid": APP_ID,
            }).encode()).decode().rstrip("=")
            return f"not-a-real-token.{payload}.not-a-signature"

        evaluate = AsyncMock(
            return_value={"policyActions": [], "processingErrors": []},
            side_effect=gate_exception,
        )
        output = io.StringIO()
        async with httpx.AsyncClient(transport=httpx.MockTransport(graph_handler)) as http_client:
            model = OpenAIChatCompletionClient(
                model="test-model",
                async_client=AsyncOpenAI(
                    api_key="unused-test-value", base_url="https://model.invalid/v1",
                    http_client=http_client, max_retries=0,
                ),
            )
            with (
                patch(
                    "agent_framework_purview._client.httpx",
                    SimpleNamespace(AsyncClient=lambda **kwargs: http_client),
                ),
                patch.object(agent_demo, "PROTECTED_APP_CLIENT_ID", APP_ID),
                patch.object(agent_demo, "TENANT_ID", TENANT_ID),
                patch.object(agent_demo.graph_demo, "compute_protection_scopes", AsyncMock(return_value=coverage)),
                patch.object(agent_demo.graph_demo, "process_content", evaluate),
                patch.object(
                    agent_demo.graph_demo, "verdict_from_result",
                    side_effect=["ALLOWED", gate_verdict] if coverage else [gate_verdict],
                ),
                redirect_stdout(output),
            ):
                evidence = await agent_demo.run_journey(
                    model, token_provider, USER_ID,
                    agent_demo.PAYROLL_PROMPT, agent_demo.SENSITIVE_RECORD,
                )
                await asyncio.sleep(0)  # Let mocked SDK background requests finish before closing transport.
        return evidence, model_calls, requests, evaluate, output.getvalue()

    async def test_sdk_block_never_reaches_model_or_fallback_gate(self):
        evidence, calls, requests, evaluate, output = await self.run_case(block=True)
        self.assertEqual(evidence.outcome, "BLOCKED")
        self.assertFalse(evidence.model_invoked)
        self.assertEqual(calls, [])
        evaluate.assert_not_awaited()
        self.assertIn("External action executed: no", output)
        self.assertIn(evidence.correlation_id + "@AF", json.dumps(requests))
        self.assertIn(agent_demo.PAYROLL_PROMPT, json.dumps(requests))
        self.assertIn(agent_demo.SENSITIVE_RECORD, json.dumps(requests))

    async def test_allow_evaluates_full_context_before_real_model_boundary(self):
        evidence, calls, requests, evaluate, _ = await self.run_case()
        self.assertEqual(evidence.outcome, "MODEL_COMPLETED")
        self.assertTrue(evidence.model_invoked)
        self.assertEqual(len(calls), 1)
        checked_text = evaluate.await_args.args[0]
        self.assertIn(agent_demo.SENSITIVE_RECORD, checked_text)
        self.assertIn(agent_demo.INSTRUCTIONS, checked_text)
        self.assertIn(agent_demo.SENSITIVE_RECORD, json.dumps(requests))

    async def test_missing_coverage_stops_even_when_sdk_allows(self):
        evidence, calls, _, evaluate, _ = await self.run_case(coverage=[])
        self.assertEqual(evidence.outcome, "NO_POLICY_COVERAGE")
        self.assertEqual(calls, [])
        evaluate.assert_not_awaited()

    async def test_incomplete_graph_guard_stops_even_when_sdk_allows(self):
        evidence, calls, _, evaluate, _ = await self.run_case(
            gate_verdict="EVALUATION_INCOMPLETE",
            sdk_processing_errors=[{"error": {"code": "syntheticProcessingFailure"}}],
        )
        self.assertEqual(evidence.outcome, "EVALUATION_INCOMPLETE")
        self.assertFalse(evidence.model_invoked)
        self.assertEqual(calls, [])
        evaluate.assert_awaited_once()

    async def test_sdk_service_failures_never_reach_model(self):
        for status in (402, 403, 429, 503):
            with self.subTest(status=status):
                evidence, calls, _, _, output = await self.run_case(graph_status=status)
                self.assertEqual(evidence.outcome, "EVALUATION_INCOMPLETE")
                self.assertEqual(calls, [])
                self.assertNotIn("DO NOT LOG BODY", output)

    async def test_guard_timeout_does_not_invoke_model(self):
        evidence, calls, _, _, _ = await self.run_case(gate_exception=TimeoutError())
        self.assertEqual(evidence.outcome, "EVALUATION_INCOMPLETE")
        self.assertFalse(evidence.model_invoked)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
