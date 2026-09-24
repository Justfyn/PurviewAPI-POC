"""Optional, non-streaming Agent Framework journey using synthetic data only."""

import argparse
import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import classify_text as graph_demo
from config import (
    APP_NAME, CLIENT_ID, DEMO_SCENARIOS, POLICY_LOCATION_APP_ID,
    PROTECTED_APP_CLIENT_ID, TENANT_ID,
)

PAYROLL_PROMPT = "Summarize this employee's payroll record."
SENSITIVE_RECORD = (
    "Synthetic payroll record: employee DEMO-001. "
    "Employee SSN 120-98-1437. HR payroll adjustment pending."
)
PUBLIC_RECORD = (
    "Synthetic public payroll process: adjustments are reviewed by HR "
    "before the monthly payroll closes. No employee details are included."
)
INSTRUCTIONS = "Summarize only the supplied synthetic context. Do not invent employee details."


class EvaluationStopped(Exception):
    """The application did not authorize a model invocation."""


@dataclass
class ExecutionEvidence:
    correlation_id: str
    model_invoked: bool = False
    outcome: str = "EVALUATION_INCOMPLETE"

    def display(self):
        print(f"Outcome: {self.outcome}")
        print(f"Model invoked: {'yes' if self.model_invoked else 'no'}")
        print("External action executed: no (no action tools are registered)")
        print("Model invoked records a client-call attempt, not provider acceptance.")


def scope_coverage(scopes: list | None, app_id: str) -> str:
    """Require an explicit inline upload scope for this demo's protected app."""
    if scopes is None or not isinstance(scopes, list):
        return "EVALUATION_INCOMPLETE"
    inline = False
    actions = []
    for scope in scopes:
        if not isinstance(scope, dict):
            return "EVALUATION_INCOMPLETE"
        activities = scope.get("activities")
        locations = scope.get("locations")
        if not isinstance(activities, str) or not isinstance(locations, list):
            return "EVALUATION_INCOMPLETE"
        if any(
            not isinstance(location, dict)
            or not isinstance(location.get("@odata.type"), str)
            or not isinstance(location.get("value"), str)
            for location in locations
        ):
            return "EVALUATION_INCOMPLETE"
        matches = any(
            location.get("@odata.type", "").lstrip("#")
            == "microsoft.graph.policyLocationApplication"
            and str(location.get("value", "")).lower() == app_id.lower()
            for location in locations
        )
        if "uploadText" not in {activity.strip() for activity in activities.split(",")} or not matches:
            continue
        mode = scope.get("executionMode")
        if mode not in ("evaluateInline", "evaluateOffline"):
            return "EVALUATION_INCOMPLETE"
        inline = inline or mode == "evaluateInline"
        scope_actions = scope.get("policyActions", [])
        if not isinstance(scope_actions, list):
            return "EVALUATION_INCOMPLETE"
        actions.extend(scope_actions)
    if not inline:
        return "NO_POLICY_COVERAGE"
    decision = graph_demo.verdict_from_result({"policyActions": actions, "processingErrors": []})
    return "COVERED" if decision == "ALLOWED" else decision


def validate_configuration():
    for value in (CLIENT_ID, TENANT_ID, PROTECTED_APP_CLIENT_ID, POLICY_LOCATION_APP_ID):
        uuid.UUID(value)
    if POLICY_LOCATION_APP_ID.lower() != PROTECTED_APP_CLIENT_ID.lower():
        raise ValueError("The scope filter must target the protected app for this journey.")


async def preflight() -> dict | None:
    validate_configuration()
    user = await graph_demo.authenticate()
    if not user:
        print("Identity check failed; verify delegated consent and browser registration.")
        return None
    uuid.UUID(user["id"])
    print(f"Signed-in user ID: {user['id']}")
    print(f"Protected app / policy location: {PROTECTED_APP_CLIENT_ID}")
    scopes = await graph_demo.compute_protection_scopes()
    coverage = scope_coverage(scopes, PROTECTED_APP_CLIENT_ID)
    print(f"Inline upload coverage: {coverage}")
    print("Collection policy: NOT VERIFIED by these APIs; confirm in the Purview portal.")
    print("Successful calls exercise consent; they do not inventory every permission.")
    if coverage != "COVERED":
        return None
    return user


def build_model_gate(evidence: ExecutionEvidence):
    from agent_framework import ChatMiddleware

    class ModelGate(ChatMiddleware):
        async def process(self, context, call_next):
            # The SDK's public middleware does not expose processingErrors to callers.
            # Keep a strict Graph decision at the final model boundary as well.
            scopes = await graph_demo.compute_protection_scopes()
            coverage = scope_coverage(scopes, PROTECTED_APP_CLIENT_ID)
            if coverage != "COVERED":
                evidence.outcome = coverage
                raise EvaluationStopped
            if context.stream or any(
                content.type != "text"
                for message in context.messages for content in message.contents
            ):
                raise EvaluationStopped
            instructions = context.options.get("instructions", "")
            if not isinstance(instructions, str):
                raise EvaluationStopped
            model_input = "\n\n".join([instructions, *(message.text for message in context.messages)])
            result = await graph_demo.process_content(model_input)
            decision = graph_demo.verdict_from_result(result)
            if decision != "ALLOWED":
                evidence.outcome = decision
                raise EvaluationStopped
            if result.get("protectionScopeState") == "modified":
                coverage = scope_coverage(
                    await graph_demo.compute_protection_scopes(), PROTECTED_APP_CLIENT_ID,
                )
                if coverage != "COVERED":
                    evidence.outcome = coverage
                    raise EvaluationStopped
            evidence.model_invoked = True
            await call_next()

    return ModelGate()


def build_agent(client, credential, evidence: ExecutionEvidence):
    from agent_framework import Agent
    from agent_framework_purview import (
        PurviewAppLocation, PurviewLocationType, PurviewPolicyMiddleware, PurviewSettings,
    )

    logging.getLogger("agent_framework.purview").disabled = True
    settings = PurviewSettings(
        app_name=APP_NAME,
        tenant_id=TENANT_ID,
        purview_app_location=PurviewAppLocation(
            location_type=PurviewLocationType.APPLICATION,
            location_value=PROTECTED_APP_CLIENT_ID,
        ),
        ignore_exceptions=False,
        ignore_payment_required=False,
        cache_ttl_seconds=3600,
    )
    return Agent(
        client=client,
        instructions=INSTRUCTIONS,
        middleware=[
            PurviewPolicyMiddleware(credential=credential, settings=settings),
            build_model_gate(evidence),
        ],
    )


async def run_journey(
    client, credential, user_id: str, prompt: str, record: str | None = None,
    expected: str | None = None,
):
    from agent_framework import Message

    evidence = ExecutionEvidence(str(uuid.uuid4()))
    graph_demo.begin_conversation(evidence.correlation_id)
    print(f"\nUTC start: {datetime.now(timezone.utc).isoformat()}")
    print(f"Graph correlation ID: {evidence.correlation_id}")
    print(f"SDK correlation ID: {evidence.correlation_id}@AF")
    print(f"Prompt: {prompt}")
    metadata = {"user_id": user_id, "conversation_id": evidence.correlation_id}
    messages = [Message("user", [prompt], additional_properties=metadata)]
    if record is not None:
        print("Retrieval: local synthetic fixture (not a document-authorization demonstration).")
        print("The retrieved context is included in the SDK pre-check before the first model call.")
        messages.append(Message(
            "user", [f"Retrieved synthetic context:\n{record}"], additional_properties=metadata,
        ))

    try:
        agent = build_agent(client, credential, evidence)
        response = await asyncio.wait_for(agent.run(messages, stream=False), timeout=90)
        if evidence.model_invoked:
            evidence.outcome = "MODEL_COMPLETED"
            print("Non-streaming SDK result (not proof of response DLP coverage):")
            print(response.text)
        else:
            evidence.outcome = "BLOCKED"
            print("The SDK stopped this request before the model boundary.")
    except EvaluationStopped:
        print("Application gate stopped the request; no retry or bypass.")
    except Exception as exc:
        evidence.outcome = "EVALUATION_INCOMPLETE"
        # Service exception text can include prompts, responses or credentials.
        print(f"Run incomplete ({type(exc).__name__}); response withheld.")
    finally:
        evidence.display()
        if expected:
            print(f"Expected: {expected} | Match: {'yes' if evidence.outcome == expected else 'NO'}")
            if evidence.outcome != expected:
                print("Expected protection/control was not demonstrated; inspect the actual policies.")
    return evidence


async def main(args):
    # SDK exceptions can include service response bodies; keep console evidence content-free.
    logging.getLogger("agent_framework.purview").disabled = True
    user = await preflight()
    if not user or args.preflight:
        print("Model invoked: no")
        print("External action executed: no")
        return 0 if user else 1
    if not args.collection_confirmed:
        print("Confirm collection configuration in the portal, then pass --collection-confirmed.")
        return 1

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "")
    try:
        parsed = urlparse(endpoint)
        valid_endpoint = (
            parsed.scheme == "https" and parsed.hostname
            and parsed.hostname.endswith((".services.ai.azure.com", ".openai.azure.com"))
            and parsed.port in (None, 443)
            and parsed.path in ("", "/")
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint or not deployment.strip():
        print("Set AZURE_OPENAI_ENDPOINT to your Microsoft Foundry resource endpoint "
              "(https://<resource>.services.ai.azure.com), not a project or API URL, "
              "and AZURE_OPENAI_CHAT_DEPLOYMENT_NAME to your chat deployment.")
        return 1

    from agent_framework_openai import OpenAIChatCompletionClient
    from azure.identity.aio import DefaultAzureCredential
    from openai import AsyncAzureOpenAI
    from azure.identity.aio import get_bearer_token_provider

    async with DefaultAzureCredential() as model_credential:
        token_provider = get_bearer_token_provider(
            model_credential, "https://cognitiveservices.azure.com/.default",
        )
        async with AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            timeout=30,
            max_retries=0,
        ) as openai_client:
            client = OpenAIChatCompletionClient(model=deployment, async_client=openai_client)
            scenarios = (
                [
                    (scenario["text"], None,
                     "BLOCKED" if scenario["expect"] == "BLOCK" else "MODEL_COMPLETED")
                    for scenario in DEMO_SCENARIOS
                ]
                if args.scenario == "scripted"
                else [(
                    PAYROLL_PROMPT, PUBLIC_RECORD if args.public_record else SENSITIVE_RECORD,
                    "MODEL_COMPLETED" if args.public_record else "BLOCKED",
                )]
            )
            matched = True
            for prompt, record, expected in scenarios:
                result = await run_journey(
                    client, graph_demo.get_credential(), user["id"], prompt, record, expected,
                )
                matched = matched and result.outcome == expected
    return 0 if matched else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true", help="Check identity and scopes only.")
    parser.add_argument("--scenario", choices=("payroll", "scripted"), default="payroll")
    parser.add_argument("--public-record", action="store_true", help="Use the benign payroll control.")
    parser.add_argument(
        "--collection-confirmed", action="store_true",
        help="Acknowledge administrator verification of collection; not an automated check.",
    )
    try:
        raise SystemExit(asyncio.run(main(parser.parse_args())))
    except (ImportError, ValueError) as exc:
        print(f"Setup incomplete ({type(exc).__name__}). Check config.py and requirements-sdk.txt.")
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print("Demo interrupted.")
        raise SystemExit(1)
