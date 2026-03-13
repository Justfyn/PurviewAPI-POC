"""
╔══════════════════════════════════════════════════════════════════════╗
║  Microsoft Purview API — Live Demo                                  ║
║  Real-time DLP enforcement for custom AI applications               ║
╚══════════════════════════════════════════════════════════════════════╝

Demonstrates the two-step Purview API integration:
  Step 1 → Compute Protection Scopes (what policies apply?)
  Step 2 → Process Content (evaluate text against DLP policies)

Usage:
    pip install -r requirements.txt
    python classify_text.py
"""

import asyncio
import uuid
import time
import sys
import io
from datetime import datetime, timezone

import aiohttp
from azure.identity import InteractiveBrowserCredential
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.rule import Rule
from rich.prompt import Prompt
from rich import box

from config import (
    CLIENT_ID, TENANT_ID, REDIRECT_URI, SCOPES,
    DEMO_SCENARIOS, APP_NAME, CHAT_AI_RESPONSES,
    INTEGRATED_APP_NAME, INTEGRATED_APP_VERSION,
    PROTECTED_APP_NAME, PROTECTED_APP_VERSION, PROTECTED_APP_CLIENT_ID,
    POLICY_LOCATION_APP_ID,
)

# Force UTF-8 output on Windows to support emojis and box-drawing characters
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console()

# ──────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────
_credential: InteractiveBrowserCredential | None = None
_cached_etag: str | None = None
_etag_timestamp: float = 0
_protection_scopes: list = []
_sequence_number: int = 0
_correlation_id: str = str(uuid.uuid4())
_last_scope_compute_ms: float = 0.0

ETAG_REFRESH_SECONDS = 3600  # 60 minutes


def format_duration_ms(duration_ms: float) -> str:
    return f"{duration_ms:.0f} ms"


def get_etag_age_seconds() -> float | None:
    if not _cached_etag or _etag_timestamp == 0:
        return None
    return max(0.0, time.time() - _etag_timestamp)


def format_etag_state(etag_used: bool, etag_age_seconds: float | None) -> str:
    if not etag_used:
        return "MISS"
    if etag_age_seconds is None:
        return "HIT"
    return f"HIT ({etag_age_seconds / 60:.1f} min old)"


def build_policy_location_application(app_id: str) -> dict:
    return {
        "@odata.type": "microsoft.graph.policyLocationApplication",
        "value": app_id,
    }


def get_integrated_app_metadata() -> dict:
    """Metadata about the app calling the Purview APIs."""
    return {
        "name": INTEGRATED_APP_NAME,
        "version": INTEGRATED_APP_VERSION,
    }


def get_protected_app_metadata() -> dict:
    """Metadata about the app/location whose activity is being governed."""
    return {
        "name": PROTECTED_APP_NAME,
        "version": PROTECTED_APP_VERSION,
        "applicationLocation": build_policy_location_application(PROTECTED_APP_CLIENT_ID),
    }


# ═══════════════════════════════════════════════════════════════════════
# BANNER
# ═══════════════════════════════════════════════════════════════════════
def show_banner():
    console.print()
    console.print(
        Panel(
            Align.center(
                Text.assemble(
                    ("Microsoft Purview API\n", "bold cyan"),
                    ("Data Loss Prevention for Custom Applications\n\n", "bold white"),
                    ("Real-time policy enforcement via Microsoft Graph API", "dim"),
                )
            ),
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()


def show_architecture():
    """Display the integration architecture."""
    arch = (
        "[bold cyan]Integration Architecture[/]\n\n"
        "  [bold white]User[/]  \u2192  [bold blue]Your AI App (Orchestrator)[/]  \u2192  [bold magenta]Purview API[/]  \u2192  [bold blue]Your AI App[/]  \u2192  [bold green]AI Model[/]\n"
        "                          \u2502                          \u2502\n"
        "                   [dim]1. protectionScopes/compute[/]    \u2502\n"
        "                   [dim]   (what policies apply?)[/]      \u2502\n"
        "                          \u2502                          \u2502\n"
        "                   [dim]2a. processContent[/]             \u2502\n"
        "                   [dim]    activity: uploadText[/]       \u2502\n"
        "                   [dim]    (check user prompt)[/]        \u2502\n"
        "                          \u2502                          \u2502\n"
        "                   [dim]If ALLOWED \u2192 forward to AI[/]    \u2502\n"
        "                          \u2502                          \u2502\n"
        "                   [dim]2b. processContent[/]             \u2502\n"
        "                   [dim]    activity: downloadText[/]     \u2502\n"
        "                   [dim]    (audit AI response)[/]        \u2502\n"
        "                          \u2502                          \u2502\n"
        "                          \u25bc                          \u25bc\n"
        "                   [bold red]\ud83d\uded1 BLOCK[/]              [bold green]\u2705 ALLOW \u2192 AI[/]\n\n"
        "  [dim]uploadText  = evaluateInline  (block thread, wait for decision)[/]\n"
        "  [dim]downloadText = evaluateOffline (async audit, don't block the user)[/]\n"
        "  [dim]Both calls go through Microsoft Graph v1.0 \u2014 /me endpoint[/]"
    )
    console.print(Panel(arch, border_style="cyan", padding=(1, 2)))


# ═══════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════
def get_credential() -> InteractiveBrowserCredential:
    global _credential
    if _credential is None:
        _credential = InteractiveBrowserCredential(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            redirect_uri=REDIRECT_URI,
        )
    return _credential


def get_token() -> str:
    cred = get_credential()
    token = cred.get_token("https://graph.microsoft.com/.default")
    return token.token


async def authenticate() -> dict | None:
    """Authenticate and return user profile."""
    console.print()
    with console.status("[bold green]Opening browser for sign-in...", spinner="dots"):
        try:
            token = get_token()
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        body = await resp.text()
                        console.print(f"[bold red]Failed to get user profile ({resp.status}):[/] {body[:200]}")
        except Exception as e:
            console.print(f"[bold red]Authentication failed:[/] {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════
# STEP 1 — COMPUTE PROTECTION SCOPES
# ═══════════════════════════════════════════════════════════════════════
async def compute_protection_scopes() -> list:
    """
    Call protectionScopes/compute to discover which policies apply.
    Caches the ETag for subsequent processContent calls.

    The 'locations' parameter is an OPTIONAL policy-location filter.
    It is NOT the identity of the caller.

    - integratedAppMetadata = who is calling Purview
    - locations             = which app/location we want scopes for

    If omitted, all applicable policies are returned. With a single-app demo
    you'll often see the same result either way. The filter becomes most
    useful when one orchestrator protects multiple downstream apps.
    """
    global _cached_etag, _etag_timestamp, _protection_scopes, _last_scope_compute_ms

    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "activities": "uploadText,downloadText",
        "integratedAppMetadata": get_integrated_app_metadata(),
        "locations": [build_policy_location_application(POLICY_LOCATION_APP_ID)],
    }
    url = "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/protectionScopes/compute"

    started_at = time.perf_counter()

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body) as resp:
            _last_scope_compute_ms = (time.perf_counter() - started_at) * 1000
            etag = resp.headers.get("ETag")
            if etag:
                _cached_etag = etag
                _etag_timestamp = time.time()

            if resp.status == 200:
                data = await resp.json()
                _protection_scopes = data.get("value", [])
                return _protection_scopes
            else:
                text = await resp.text()
                console.print(f"[yellow]protectionScopes/compute returned {resp.status}[/]")
                console.print(f"[dim]{text[:300]}[/dim]")
                return []


def display_protection_scopes(scopes: list):
    """Render protection scopes in a rich table."""
    table = Table(
        title="Protection Scopes for Current User",
        box=box.HEAVY_EDGE,
        title_style="bold cyan",
        header_style="bold white on dark_blue",
        show_lines=True,
    )
    table.add_column("Activity", style="bold")
    table.add_column("Execution Mode", justify="center")
    table.add_column("Policy Actions", justify="center")
    table.add_column("Locations")

    if not scopes:
        table.add_row(
            "—", "—",
            Text("No policies apply", style="dim italic"),
            "—",
        )
    else:
        for scope in scopes:
            activities = scope.get("activities", "—")
            mode = scope.get("executionMode", "—")
            actions = scope.get("policyActions", [])
            locations = scope.get("locations", [])

            mode_style = (
                "bold red" if mode == "evaluateInline"
                else "bold yellow" if mode == "evaluateOffline"
                else "dim"
            )
            mode_text = Text(mode, style=mode_style)

            if actions:
                action_parts = []
                for a in actions:
                    action_parts.append(
                        f"{a.get('action', '?')} -> {a.get('restrictionAction', '?')}"
                    )
                action_text = Text("\n".join(action_parts), style="bold red")
            else:
                action_text = Text("evaluate on processContent", style="dim italic")

            location_text = Text(
                "\n".join(str(loc.get("value", "—")) for loc in locations) if locations else "—",
                style="dim",
            )

            table.add_row(activities, mode_text, action_text, location_text)

    console.print()
    console.print(table)

    # ETag info
    if _cached_etag:
        console.print(
            f"\n  [dim]ETag cached:[/] [bold green]{_cached_etag[:50]}...[/]"
        )
        console.print(
            "  [dim]This ETag will be sent with every processContent call to detect policy changes.[/]\n"
        )
        console.print(
            f"  [dim]Scope compute latency:[/] [bold]{format_duration_ms(_last_scope_compute_ms)}[/]"
        )
        etag_age_seconds = get_etag_age_seconds()
        if etag_age_seconds is not None:
            console.print(
                f"  [dim]Current cache age:[/] [bold]{etag_age_seconds / 60:.1f} min[/]\n"
            )


# ═══════════════════════════════════════════════════════════════════════
# STEP 2 — PROCESS CONTENT
# ═══════════════════════════════════════════════════════════════════════
async def process_content(text: str, activity: str = "uploadText") -> dict | None:
    """
    Evaluate text against DLP policies via processContent.
    Uses cached ETag from protectionScopes/compute.
    """
    global _cached_etag, _etag_timestamp, _sequence_number

    etag_used = bool(_cached_etag)
    etag_age_seconds = get_etag_age_seconds()
    scope_refresh_reason: str | None = None

    # Refresh scopes if stale (> 60 min)
    if _etag_timestamp > 0 and (time.time() - _etag_timestamp > ETAG_REFRESH_SECONDS):
        console.print("[yellow]  ↻ ETag expired (>60 min) — refreshing protection scopes...[/]")
        scope_refresh_reason = "ETag expired"
        await compute_protection_scopes()
        etag_used = bool(_cached_etag)
        etag_age_seconds = get_etag_age_seconds()

    request_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    body = {
        "contentToProcess": {
            "contentEntries": [
                {
                    "@odata.type": "microsoft.graph.processConversationMetadata",
                    "identifier": request_id,
                    "content": {
                        "@odata.type": "microsoft.graph.textContent",
                        "data": text,
                    },
                    "name": f"{APP_NAME} message",
                    "correlationId": _correlation_id,
                    "sequenceNumber": _sequence_number,
                    "isTruncated": False,
                    "createdDateTime": current_time,
                    "modifiedDateTime": current_time,
                }
            ],
            "activityMetadata": {"activity": activity},
            "deviceMetadata": {
                "deviceType": "Unmanaged",
                "operatingSystemSpecifications": {
                    "operatingSystemPlatform": "Windows 11",
                    "operatingSystemVersion": "10.0.26100.0",
                },
                "ipAddress": "127.0.0.1",
            },
            "protectedAppMetadata": get_protected_app_metadata(),
            "integratedAppMetadata": get_integrated_app_metadata(),
        }
    }

    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if _cached_etag:
        headers["If-None-Match"] = _cached_etag

    url = "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent"

    started_at = time.perf_counter()

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body) as resp:
            _sequence_number += 1
            process_duration_ms = (time.perf_counter() - started_at) * 1000

            if resp.status == 200:
                result = await resp.json()

                # Check if policies changed
                scope_state = result.get("protectionScopeState", "")
                if scope_state == "modified":
                    console.print(
                        "[yellow]  ⚡ Policy state changed — refreshing protection scopes...[/]"
                    )
                    scope_refresh_reason = "Purview reported modified protection scope"
                    await compute_protection_scopes()

                result["_demo"] = {
                    "etag_used": etag_used,
                    "etag_age_seconds": etag_age_seconds,
                    "process_duration_ms": process_duration_ms,
                    "scope_refresh_reason": scope_refresh_reason,
                    "correlation_id": _correlation_id,
                    "sequence_number": _sequence_number - 1,
                }

                return result
            else:
                text_resp = await resp.text()
                console.print(f"[red]  processContent returned {resp.status}[/]")
                console.print(f"[dim]  {text_resp[:300]}[/]")
                return None


# ═══════════════════════════════════════════════════════════════════════
# STEP 2b — AUDIT AI RESPONSE (downloadText)
# ═══════════════════════════════════════════════════════════════════════
async def audit_ai_response(ai_text: str) -> dict | None:
    """
    Send the AI-generated response to Purview via processContent with
    activity='downloadText'. This audits the response so it appears in
    Activity Explorer, DSPM for AI, eDiscovery, Insider Risk, etc.

    Per the protection scopes, downloadText uses evaluateOffline — meaning
    we fire this asynchronously and do NOT block the user while waiting.
    """
    global _sequence_number

    request_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    body = {
        "contentToProcess": {
            "contentEntries": [
                {
                    "@odata.type": "microsoft.graph.processConversationMetadata",
                    "identifier": request_id,
                    "content": {
                        "@odata.type": "microsoft.graph.textContent",
                        "data": ai_text,
                    },
                    "name": f"{APP_NAME} AI response",
                    "correlationId": _correlation_id,
                    "sequenceNumber": _sequence_number,
                    "isTruncated": False,
                    "createdDateTime": current_time,
                    "modifiedDateTime": current_time,
                }
            ],
            "activityMetadata": {"activity": "downloadText"},
            "deviceMetadata": {
                "deviceType": "Unmanaged",
                "operatingSystemSpecifications": {
                    "operatingSystemPlatform": "Windows 11",
                    "operatingSystemVersion": "10.0.26100.0",
                },
                "ipAddress": "127.0.0.1",
            },
            "protectedAppMetadata": get_protected_app_metadata(),
            "integratedAppMetadata": get_integrated_app_metadata(),
        }
    }

    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if _cached_etag:
        headers["If-None-Match"] = _cached_etag

    url = "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent"

    started_at = time.perf_counter()

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body) as resp:
            _sequence_number += 1
            duration_ms = (time.perf_counter() - started_at) * 1000

            if resp.status in (200, 202, 204):
                result = await resp.json() if resp.status == 200 else {}
                result["_demo"] = {
                    "activity": "downloadText",
                    "audit_duration_ms": duration_ms,
                }
                return result
            else:
                text_resp = await resp.text()
                console.print(f"[yellow]  downloadText audit returned {resp.status}[/]")
                console.print(f"[dim]  {text_resp[:300]}[/]")
                return None


def render_audit_result(result: dict | None):
    """Show a compact audit confirmation for the downloadText call."""
    if result is None:
        console.print("    [yellow]\u26a0 AI response audit: failed to send[/]")
        return

    demo = result.get("_demo", {})
    duration = demo.get("audit_duration_ms", 0)
    console.print(
        f"    [dim]\u2713 AI response audited in Purview[/] "
        f"[dim]({duration:.0f} ms, activity: downloadText)[/]"
    )


# ═══════════════════════════════════════════════════════════════════════
# RESULT RENDERING
# ═══════════════════════════════════════════════════════════════════════
def render_result(result: dict | None, scenario_title: str = "") -> str:
    """Pretty-print a processContent result. Returns 'BLOCKED' or 'ALLOWED'."""
    if result is None:
        console.print(Panel("  [bold red]ERROR[/] — Could not evaluate", border_style="red"))
        return "ERROR"

    actions = result.get("policyActions", [])
    errors = result.get("processingErrors", [])
    demo_metadata = result.get("_demo", {})

    blocked = any(
        a.get("restrictionAction", "").lower() == "block" for a in actions
    )

    trace_table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )
    trace_table.add_column("Signal", style="dim", no_wrap=True)
    trace_table.add_column("Value")
    trace_table.add_row("ETag cache", format_etag_state(
        demo_metadata.get("etag_used", False),
        demo_metadata.get("etag_age_seconds"),
    ))
    trace_table.add_row(
        "processContent",
        format_duration_ms(demo_metadata.get("process_duration_ms", 0.0)),
    )
    trace_table.add_row(
        "sequence",
        str(demo_metadata.get("sequence_number", "?")),
    )
    trace_table.add_row(
        "correlation",
        str(demo_metadata.get("correlation_id", "n/a"))[:12],
    )
    if demo_metadata.get("scope_refresh_reason"):
        trace_table.add_row("scope refresh", str(demo_metadata["scope_refresh_reason"]))

    if blocked:
        block_content = Text()
        block_content.append("  🛑  BLOCKED  🛑\n\n", style="bold red")
        block_content.append("  DLP policy violation detected.\n", style="red")
        block_content.append("  Content blocked by Microsoft Purview.\n", style="red")
        block_content.append("  Next: stop the request before it reaches the AI model.", style="bold red")

        block_panel = Panel(
            Align.center(block_content),
            border_style="bold red",
            title=f"[bold red]🛑 {scenario_title}[/]" if scenario_title else "[bold red]🛑 BLOCKED[/]",
            padding=(1, 2),
        )
        console.print(block_panel)
        console.print(trace_table)

        # Show which actions triggered
        for a in actions:
            console.print(
                f"    [red]►[/] Action: [bold]{a.get('action', '?')}[/] → "
                f"[bold red]{a.get('restrictionAction', '?')}[/]"
            )
        return "BLOCKED"
    else:
        allow_content = Text()
        allow_content.append("  ✅  ALLOWED  ✅\n\n", style="bold green")
        allow_content.append("  No DLP policy violations detected.\n", style="green")
        allow_content.append("  Next: the app can safely forward the prompt to the AI model.", style="bold green")

        allow_panel = Panel(
            Align.center(allow_content),
            border_style="bold green",
            title=f"[bold green]✅ {scenario_title}[/]" if scenario_title else "[bold green]✅ ALLOWED[/]",
            padding=(1, 2),
        )
        console.print(allow_panel)
        console.print(trace_table)

        if errors:
            for e in errors:
                console.print(f"    [yellow]⚠ Error:[/] {e}")

        return "ALLOWED"


# ═══════════════════════════════════════════════════════════════════════
# DEMO FLOW
# ═══════════════════════════════════════════════════════════════════════
async def run_demo(user: dict):
    """Run the full scripted demo."""
    display_name = user.get("displayName", "User")

    show_architecture()
    Prompt.ask("\n  [bold dim]Press Enter to begin[/]")

    # ── Step 1 ────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold cyan] STEP 1 — Compute Protection Scopes [/]", style="cyan"))
    console.print()
    console.print(
        "  [dim]Calling[/] [bold]POST /me/dataSecurityAndGovernance/protectionScopes/compute[/]"
    )
    console.print(
        f"  [dim]Caller / integrated app:[/] [bold]{INTEGRATED_APP_NAME}[/]\n"
        f"  [dim]Policy location filter:[/] [bold]{PROTECTED_APP_NAME}[/] "
        f"[dim]({POLICY_LOCATION_APP_ID})[/]\n"
        f"  [dim]User:[/] [bold]{display_name}[/]\n"
    )

    with console.status("[bold cyan]Computing protection scopes...", spinner="dots"):
        scopes = await compute_protection_scopes()

    display_protection_scopes(scopes)

    console.print(
        Panel(
            "[dim]The protection scopes tell us:[/]\n"
            "  \u2022 [bold]uploadText  \u2192 evaluateInline[/]  \u2014 BLOCK the thread, wait for DLP decision before forwarding to AI\n"
            "  \u2022 [bold]downloadText \u2192 evaluateOffline[/] \u2014 audit AI response async, don't block the user\n\n"
            "[dim]Vocabulary shortcut:[/]\n"
            "  \u2022 [bold]Integrated app[/] = who is calling Purview\n"
            "  \u2022 [bold]Protected app / policy location[/] = what app/location the policy applies to\n\n"
            "[dim]The ETag is cached and sent with every processContent call.\n"
            "If Purview detects that policies changed, it tells us to re-compute scopes.\n"
            "Both uploadText and downloadText calls create audit records in Purview.[/]",
            title="[bold cyan]What does this mean?[/]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    # Pause for presenter to explain
    Prompt.ask("\n  [bold dim]Press Enter to continue to Step 2[/]")

    # ── Step 2 ────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold magenta] STEP 2 — Process Content (DLP Evaluation) [/]", style="magenta"))
    console.print()
    console.print(
        "  [dim]For each user prompt, we call[/] [bold]processContent[/] [dim]with[/] [bold]activity: uploadText[/]"
    )
    console.print(
        f"  [dim]Caller:[/] [bold]{INTEGRATED_APP_NAME}[/]  "
        f"[dim]| Protected app:[/] [bold]{PROTECTED_APP_NAME}[/]"
    )
    console.print(
        "  [dim]If ALLOWED, we also call[/] [bold]processContent[/] [dim]with[/] [bold]activity: downloadText[/] [dim]to audit the AI response[/]\n"
    )

    results = []
    for i, scenario in enumerate(DEMO_SCENARIOS, 1):
        console.print()
        console.print(
            Rule(f"[bold] Scenario {i}/{len(DEMO_SCENARIOS)}: {scenario['title']} [/]", style="white")
        )
        console.print()

        # Show what we're sending
        prompt_panel = Panel(
            f"[white]{scenario['text']}[/]",
            title=f"[bold]User Prompt → {APP_NAME}[/]",
            border_style="blue",
            padding=(1, 2),
        )
        console.print(prompt_panel)
        console.print(f"  [dim italic]{scenario['description']}[/]\n")

        # Call the API (uploadText — evaluateInline, blocks until result)
        with console.status("[bold magenta]Evaluating prompt against DLP policies...", spinner="dots"):
            result = await process_content(scenario["text"])

        status = render_result(result, scenario["title"])
        results.append((scenario, status))

        # If ALLOWED and we have a simulated AI response, audit it (downloadText)
        ai_response = scenario.get("ai_response")
        if status == "ALLOWED" and ai_response:
            console.print()
            console.print(
                Panel(
                    f"[green]{ai_response}[/]",
                    title=f"[bold green]\U0001f916 {APP_NAME} Response[/]",
                    border_style="green",
                    padding=(1, 2),
                )
            )
            with console.status("[dim]Auditing AI response in Purview (downloadText)...", spinner="dots"):
                audit_result = await audit_ai_response(ai_response)
            render_audit_result(audit_result)

        # Pause between scenarios for live demo
        if i < len(DEMO_SCENARIOS):
            Prompt.ask("\n  [bold dim]Press Enter for next scenario[/]")

    # ── Summary ───────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold yellow] RESULTS SUMMARY [/]", style="yellow"))
    console.print()

    summary_table = Table(
        box=box.DOUBLE_EDGE,
        title="Demo Classification Results",
        title_style="bold yellow",
        header_style="bold white on dark_blue",
        show_lines=True,
        padding=(0, 2),
    )
    summary_table.add_column("#", style="dim", width=3, justify="center")
    summary_table.add_column("Scenario", style="bold", min_width=25)
    summary_table.add_column("Expected", justify="center", width=10)
    summary_table.add_column("Result", justify="center", width=10)
    summary_table.add_column("Match", justify="center", width=6)

    for i, (scenario, status) in enumerate(results, 1):
        expected = scenario["expect"]
        result_style = "bold red" if status == "BLOCKED" else "bold green" if status == "ALLOWED" else "bold yellow"
        expected_style = "red" if expected == "BLOCK" else "green"
        match = (
            (expected == "BLOCK" and status == "BLOCKED")
            or (expected == "ALLOW" and status == "ALLOWED")
        )
        match_text = Text("✅" if match else "❌")

        summary_table.add_row(
            str(i),
            scenario["title"],
            Text(expected, style=expected_style),
            Text(status, style=result_style),
            match_text,
        )

    console.print(summary_table)
    console.print()

    # Key takeaways panel
    console.print(
        Panel(
            "[bold]Key Takeaways:[/]\n\n"
            "  [cyan]1.[/] [bold]protectionScopes/compute[/] \u2014 discover policies + cache ETag\n"
            "  [cyan]2.[/] [bold]processContent (uploadText)[/] \u2014 check user prompt, block inline if needed\n"
            "  [cyan]3.[/] [bold]processContent (downloadText)[/] \u2014 audit AI response asynchronously\n"
            "  [cyan]4.[/] [bold]Contextual intelligence[/] \u2014 same data, different context, different decision\n"
            "  [cyan]5.[/] [bold]Full audit trail[/] \u2014 both prompts and responses visible in Purview\n"
            "  [cyan]6.[/] [bold]Central governance[/] \u2014 admins own policy, developers enforce via Graph API\n",
            title="[bold yellow]\U0001f4a1 Key Takeaways[/]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    return results


# ═══════════════════════════════════════════════════════════════════════
# INTERACTIVE AI CHAT MODE
# ═══════════════════════════════════════════════════════════════════════
async def interactive_chat():
    """Simulate an AI chat with real-time DLP enforcement."""
    global _sequence_number, _correlation_id
    _sequence_number = 0
    _correlation_id = str(uuid.uuid4())

    console.print()
    console.print(Rule("[bold green] LIVE AI CHAT — with Purview DLP [/]", style="green"))
    console.print()

    chat_header = Panel(
        f"[bold white]{APP_NAME}[/]\n"
        "[dim]Every message is checked via uploadText (DLP) and responses are audited via downloadText.\n"
        f"Caller: {INTEGRATED_APP_NAME} | Protected app: {PROTECTED_APP_NAME}\n"
        "Try typing something with sensitive data (SSN, credit card, etc.)\n"
        "Type 'quit' to exit.[/]",
        border_style="green",
        title="[bold green]\U0001f4ac Interactive Mode[/]",
        padding=(1, 2),
    )
    console.print(chat_header)
    console.print()

    import random

    while True:
        try:
            user_input = Prompt.ask("[bold blue]  You[/]")
            if user_input.strip().lower() in ("quit", "exit", "q"):
                console.print("\n  [dim]Chat session ended.[/]\n")
                break
            if not user_input.strip():
                continue

            # Step 2a: Evaluate the prompt (uploadText — evaluateInline)
            with console.status("[magenta]Purview is evaluating prompt...", spinner="dots"):
                result = await process_content(user_input.strip())

            if result:
                actions = result.get("policyActions", [])
                blocked = any(
                    a.get("restrictionAction", "").lower() == "block" for a in actions
                )

                if blocked:
                    console.print(
                        f"  [bold red]\U0001f6d1 {APP_NAME}:[/] "
                        "[red]I cannot process this request. Sensitive content was detected "
                        "and blocked by your organization's DLP policies.[/]\n"
                    )
                else:
                    # Simulate AI response
                    ai_text = random.choice(CHAT_AI_RESPONSES)
                    console.print(
                        f"  [bold green]\U0001f916 {APP_NAME}:[/] "
                        f"[green]{ai_text}[/]"
                    )

                    # Step 2b: Audit the AI response (downloadText — evaluateOffline)
                    with console.status("[dim]Auditing response in Purview...", spinner="dots"):
                        audit_result = await audit_ai_response(ai_text)
                    render_audit_result(audit_result)
                    console.print()
            else:
                console.print(
                    f"  [bold yellow]\u26a0\ufe0f  {APP_NAME}:[/] "
                    "[yellow]Could not evaluate content.[/]\n"
                )

        except KeyboardInterrupt:
            console.print("\n  [dim]Chat session ended.[/]\n")
            break
        except EOFError:
            break


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
async def main():
    show_banner()

    console.print(Rule("[bold] Authentication [/]", style="blue"))

    user = await authenticate()
    if not user:
        console.print("[bold red]Cannot continue without authentication.[/]")
        return

    # Show authenticated user
    user_panel = Panel(
        f"  [bold]{user.get('displayName', '?')}[/]\n"
        f"  [dim]{user.get('userPrincipalName', '?')}[/]\n"
        f"  [dim]ID: {user.get('id', '?')}[/]\n\n"
        f"  [dim]Integrated app:[/] [bold]{INTEGRATED_APP_NAME}[/]\n"
        f"  [dim]Protected app:[/] [bold]{PROTECTED_APP_NAME}[/]\n"
        f"  [dim]Policy location ID:[/] [bold]{PROTECTED_APP_CLIENT_ID}[/]",
        title="[bold green]✅ Authenticated[/]",
        border_style="green",
        padding=(0, 2),
    )
    console.print(user_panel)

    # Run the scripted demo
    await run_demo(user)

    # Offer interactive mode
    try:
        choice = Prompt.ask(
            "\n  [bold]Launch interactive AI chat demo?[/]",
            choices=["y", "n"],
            default="y",
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Demo interrupted by user.[/]")
        return

    if choice == "y":
        await interactive_chat()

    # Farewell
    console.print()
    console.print(
        Panel(
            Align.center(
                Text.assemble(
                    ("Thank you!\n\n", "bold white"),
                    ("Microsoft Purview API\n", "bold cyan"),
                    ("Protecting sensitive data in AI applications\n\n", "dim"),
                    ("learn.microsoft.com/purview/developer", "underline blue"),
                )
            ),
            border_style="blue",
            padding=(1, 4),
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Demo interrupted by user.[/]")
