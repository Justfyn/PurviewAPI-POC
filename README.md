# Microsoft Purview API — Live Demo

A proof-of-concept showing how **any custom application or AI app** can integrate with **Microsoft Purview** for real-time DLP enforcement and audit using the official API flow.

**Choose your journey:**

- **Understand the API:** `classify_text.py` uses live Graph calls and simulated AI responses.
- **Protect an agent:** [SDK companion](#sdk-companion-protect-a-payroll-assistant) uses the supported **preview** Purview Agent Framework middleware and a real Azure OpenAI deployment.
- **Understand failure behavior:** `python classify_text.py --failure-demo` is an offline, synthetic demonstration; no authentication or cloud calls.

Use synthetic data only. Purview receives content for evaluation even when the application subsequently blocks it from reaching the model. An **ALLOW** result means no blocking action was returned for that evaluation—not that the content is universally safe.

```
    User                 Your App                  Purview API              AI Model
     │                     │                          │                       │
     │                     │  Step 1                  │                       │
     │                     │  protectionScopes/compute│                       │
     │                     │ ────────────────────────>│                       │
     │                     │         ETag + scopes    │                       │
     │                     │ <────────────────────────│                       │
     │                     │                          │                       │
     │  prompt             │  Step 2a                 │                       │
     │ ───────────────────>│  processContent          │                       │
     │                     │  activity: uploadText    │                       │
     │                     │ ────────────────────────>│                       │
     │                     │                          │                       │
     │                     │    BLOCK or ALLOW        │                       │
     │                     │ <────────────────────────│                       │
     │                     │                          │                       │
     │                     │── if BLOCKED ──> return error to user            │
     │                     │                          │                       │
     │                     │── if ALLOWED ───────────────────────────────────>│
     │                     │                          │          AI response  │
     │                     │<────────────────────────────────────────────────-│
     │                     │                          │                       │
     │                     │  Step 2b                 │                       │
     │                     │  processContent          │                       │
     │                     │  activity: downloadText  │                       │
     │                     │ ────────────────────────>│                       │
     │                     │        (async audit)     │                       │
     │  response           │                          │                       │
     │ <───────────────────│                          │                       │
     │                     │                          │                       │
```

## Key Concepts

| Term | Description | Where it appears |
|------|-----------------------|------------------|
| **Integrated app** | The app that calls the Purview APIs. Think of it as the **orchestrator** or **messenger**. | `integratedAppMetadata` in `processContent`; optional `integratedAppMetadata` in `protectionScopes/compute` |
| **Protected app** | The app whose prompts/responses are being governed by Purview policy. Think of it as the **thing being protected**. | `protectedAppMetadata.applicationLocation` in `processContent` |
| **Policy location** | The location identifier used by Purview policy scoping. For app scenarios, this is usually an Entra app ID wrapped in `policyLocationApplication`. | DLP policy locations; `locations` filter in `protectionScopes/compute`; `protectedAppMetadata.applicationLocation` in `processContent` |
| **Collection Policy (KYD)** | Captures prompts/responses for audit, DSPM for AI, eDiscovery, Insider Risk, and Communication Compliance. | Purview portal / DSPM for AI |
| **DLP Policy** | Decides whether content should be blocked or allowed. | `processContent` result |

## Mental Model

If you only remember one thing, remember this:

- **Integrated app = who is calling Purview**
- **Protected app = what app/location Purview should protect**
- **Policy location = the ID Purview uses to match policy scope**

### In a simple one-app demo

All three can point to the same app:

- Your app calls Purview
- The same app is also the protected app
- The same app ID is also the policy location

This is the easiest setup and works well for a demo.

### In a real orchestrator pattern

They can be different:

- The **orchestrator** calls Purview
- A **downstream business app** is the protected app
- The **policy location** is the protected app’s app ID

That is why `protectionScopes/compute` and `processContent` can feel different:

- `protectionScopes/compute` is a **pre-flight / control-plane** call. It tells you what kind of evaluation is needed for a user and (optionally) for a specific policy location.
- `processContent` is the **real transaction**. It carries the actual content plus both identities: who is calling and what app/location is being protected.

### Practical rule of thumb

If your orchestrator protects content **for itself**, use the same app ID everywhere.

If your orchestrator protects content **for another app**, use:

- orchestrator details in `integratedAppMetadata`
- downstream app ID in `protectedAppMetadata.applicationLocation`
- that same downstream app ID in the `locations` filter when you want to scope `protectionScopes/compute`

## What This Demo Shows

| Feature | Description |
|---------|-------------|
| **Full API Flow** | `protectionScopes/compute` → `processContent(uploadText)` → `processContent(downloadText)` |
| **Prompt DLP Check** | `uploadText` with `evaluateInline` — blocks the thread until DLP decision |
| **Response Audit** | `downloadText` submission after displaying the response; offline service evaluation is not response blocking |
| **ETag Caching** | Cached from Step 1, sent with `If-None-Match` header in Step 2 |
| **Policy Change Detection** | Detects `protectionScopeState: "modified"` and re-computes scopes |
| **60-Minute Refresh** | Automatically re-calls Step 1 if ETag is older than 60 minutes |
| **Conversation Tracking** | Persistent `correlationId` per session, incrementing `sequenceNumber` |
| **Decision Trace** | Shows cache state, timing, and conversation tracking under each result |
| **File Support Probe** | Compares text, raw `.docx` bytes and extracted text for one fixture in your tenant; not a general file-format certification |
| **Interactive AI Chat** | Simulates a real AI assistant with live DLP enforcement + audit |

---

## Demo Scenarios

The scripted demo runs 4 scenarios:

| # | Scenario | Expected | Why |
|---|----------|----------|-----|
| 1 | Hidden SSN (No Context) | ✅ ALLOW | `120-98-1437` without business keywords — could be any number |
| 2 | SSN with Context | 🛑 BLOCK | The same number with HR/SSN context is now clearly sensitive |
| 3 | Credit Card Number | 🛑 BLOCK | Payment card data with payment context |
| 4 | Data Exfiltration Attempt | 🛑 BLOCK | Multiple sensitive data types in one suspicious prompt |

> **Scenario 1→2** highlights contextual intelligence: same number, different context, different decision. Purview goes beyond simple pattern matching.

---

## Prerequisites

### 1. Entra ID App Registration

Create an app registration in [Entra ID](https://entra.microsoft.com):

1. Go to **App registrations** → **New registration**
2. Name: `Contoso AI Assistant`
3. Supported account types: **Single tenant**
4. Click **Register**

#### Configure Authentication

1. Go to **Authentication** → **Add a platform** → **Mobile and desktop applications**
2. Add Custom redirect URI: `http://localhost:8000`
3. Save

#### Add API Permissions

Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:

| Permission | Purpose |
|------------|---------|
| `Content.Process.User` | Evaluate text against DLP policies (Step 2) |
| `ProtectionScopes.Compute.User` | Discover applicable policies (Step 1) |
| `ContentActivity.Write` | Optional. Log audit-only activity via `contentActivities` when no scopes apply |
| `User.Read` | Display authenticated user identity |

Click **Grant admin consent** (requires admin privileges).

#### Note Your IDs

From the **Overview** page, copy:
- **Application (client) ID**
- **Directory (tenant) ID**

### 2. Microsoft Purview Configuration

#### A. Enable Audit (Required)

1. Go to [Microsoft Purview Portal](https://purview.microsoft.com)
2. Navigate to **DSPM for AI** → **Overview**
3. Click **Activate Microsoft Purview Audit**

#### B. Enable DSPM for AI Policies (Recommended)

1. Go to **DSPM for AI** → **Recommendations**
2. Enable: **Secure interactions from enterprise apps**

#### C. Create DLP Policies with Entra Enforcement (Required)

Connect to Security & Compliance PowerShell:

```powershell
Install-Module -Name ExchangeOnlineManagement -Force
Connect-IPPSSession
```

**Policy 1 — Block SSN:**

```powershell
$appId = "YOUR-APP-CLIENT-ID"
$appName = "Contoso AI Assistant"

$locations = "[{`"Workload`":`"Applications`",`"Location`":`"$appId`",`"LocationDisplayName`":`"$appName`",`"LocationSource`":`"Entra`",`"LocationType`":`"Individual`",`"Inclusions`":[{`"Type`":`"Tenant`",`"Identity`":`"All`",`"DisplayName`":`"All`",`"Name`":`"All`"}]}]"

New-DlpCompliancePolicy -Name "Entra AI App DLP - SSN" `
    -Mode Enable `
    -Locations $locations `
    -EnforcementPlanes @("Entra")

New-DlpComplianceRule -Name "Block SSN in AI Apps" `
    -Policy "Entra AI App DLP - SSN" `
    -ContentContainsSensitiveInformation @{Name = "U.S. Social Security Number (SSN)"} `
    -RestrictAccess @(@{setting="UploadText";value="Block"}) `
    -GenerateAlert $true
```

**Policy 2 — Block Credit Cards:**

```powershell
New-DlpCompliancePolicy -Name "Entra AI App DLP - Credit Card" `
    -Mode Enable `
    -Locations $locations `
    -EnforcementPlanes @("Entra")

New-DlpComplianceRule -Name "Block Credit Cards in AI Apps" `
    -Policy "Entra AI App DLP - Credit Card" `
    -ContentContainsSensitiveInformation @{Name = "Credit Card Number"} `
    -RestrictAccess @(@{setting="UploadText";value="Block"}) `
    -GenerateAlert $true
```

> **Note:** DLP policies take 15-60 minutes to sync. Check status in the Purview portal under **Data Loss Prevention** → **Policies**.

> **Running the file support probe?** Add the file activity to the rule so file uploads are also restricted:
> `-RestrictAccess @(@{setting="UploadText";value="Block"}, @{setting="UploadFile";value="Block"})`

### 3. Licensing

Licensing and consumption billing are separate setup checks. As verified on
**2026-09-24**, the [official SDK prerequisites](https://github.com/microsoft/agent-framework/blob/703fbce285ee0f026e5effcadfb9e65aab7f5d84/python/packages/purview/README.md#prerequisites)
list an Azure subscription, Microsoft 365 **E5**, and **pay-as-you-go billing**
setup. That is the documented baseline for this SDK walkthrough, not an
exhaustive entitlement matrix for every Purview capability.

Before running, have your administrator verify:

- Entitlement for the API and each intended investigation/portal experience.
- Required Azure subscription/billing association and active meters using the
  [Purview billing guidance](https://learn.microsoft.com/en-us/purview/purview-billing-models)
  and [current pricing](https://azure.microsoft.com/en-us/pricing/details/purview/).
- The tenant configuration in [Configure Microsoft Purview](https://learn.microsoft.com/en-us/purview/developer/configurepurview).
- Separate Azure OpenAI model charges for the companion's allowed requests.

The earlier E3/E5 yes/no table has been removed: neither E3-plus-add-on eligibility
nor current meter prices were independently verified. Live Learn/pricing pages
were unavailable during implementation; the dated SDK source above is the
verified prerequisite reference. A successful sign-in is not licensing proof,
and a 402 response must not be treated as permission to bypass evaluation.

---

## Installation

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configure

Edit `config.py` with your Entra app details:

```python
CLIENT_ID = "your-client-id-here"
TENANT_ID = "your-tenant-id-here"
PROTECTED_APP_CLIENT_ID = CLIENT_ID  # keep same for a simple one-app demo
POLICY_LOCATION_APP_ID = PROTECTED_APP_CLIENT_ID
```

If your orchestrator protects a different downstream app, set `PROTECTED_APP_CLIENT_ID` to that downstream app’s Entra app ID. The demo now supports both models.

---

## Usage

```bash
python classify_text.py
```

### Demo Flow

1. **Banner** — intro screen
2. **Authentication** — browser sign-in, shows user identity
3. **Step 1** — `protectionScopes/compute` — discovers policies, caches ETag
4. **Step 2a** — `processContent(uploadText)` — 4 scripted scenarios with DLP decisions
5. **Step 2b** — `processContent(downloadText)` — audits simulated AI responses for ALLOWED scenarios
6. **Summary Table** — expected vs actual results with match indicators
7. **File Support Probe** *(optional)* — does Purview classify Office binaries, or text only?
8. **Interactive Chat** — live AI chat with DLP enforcement + response audit

Each scenario pauses for `[Enter]` so the presenter can explain what's about to happen.

---

## SDK Companion: Protect a Payroll Assistant

### What the customer should learn

“Summarize this employee's payroll record” contains no sensitive number. The
retrieved **synthetic** record does. The companion puts both messages through
`PurviewPolicyMiddleware` **before the first model invocation**, so a matching
inline SSN policy can stop the retrieved information from reaching Azure OpenAI.
Retrieval is a local fixture, not a real HR connector or an authorization system.

The public-record control reaches a real model when policy evaluation succeeds.
No email, HTTP action, MCP, or other action tools are registered in either case.

### Install and configure

Keep the existing raw demo and follow its [prerequisites](#prerequisites) first.
The companion requires Python 3.10+ and an Azure OpenAI chat deployment:

```bash
pip install -r requirements-sdk.txt
python agent_demo.py --preflight
```

Configure the app IDs in `config.py`. For this journey,
`POLICY_LOCATION_APP_ID` must equal `PROTECTED_APP_CLIENT_ID`. Preflight checks
the signed-in identity and exercises Graph access, then requires an explicit
`uploadText` / `evaluateInline` scope matching that application location.
Empty or offline-only scopes produce **NO_POLICY_COVERAGE**; failed scope
discovery produces **EVALUATION_INCOMPLETE**. Neither permits a model invocation.

Successful API access is evidence of usable consent for those calls, **not** a
complete permission inventory. The SDK can also use `contentActivities`;
grant the documented `ContentActivity.Write` permission with admin consent for
that path. Preflight cannot confirm a collection policy, licensing entitlement,
portal ingestion, or every SDK permission.

Set these environment variables in your shell:

| Variable | Value |
|----------|-------|
| `AZURE_OPENAI_ENDPOINT` | Your commercial Azure OpenAI endpoint, `https://<resource>.openai.azure.com` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | An existing chat-completions deployment name |
| `AZURE_OPENAI_API_VERSION` | Optional; defaults to `2024-10-21`, must be supported by your deployment |

The model connection uses `DefaultAzureCredential` (for example, your local
Azure CLI sign-in) and requires appropriate Azure OpenAI data-plane access,
such as **Cognitive Services OpenAI User**. This is separate from the browser
sign-in and delegated Graph permissions used for Purview. No API key is needed.
Model calls and Purview consumption can incur charges.

Have the administrator verify the collection policy for the test user/app and
the audit configuration in the Purview portal. Then run:

```bash
# Harmless prompt + sensitive retrieved record; expected to block with the SSN policy
python agent_demo.py --collection-confirmed

# Benign control; expected to invoke the real model
python agent_demo.py --collection-confirmed --public-record

# Reuse all four original prompts through the SDK, with real model responses when allowed
python agent_demo.py --collection-confirmed --scenario scripted
```

`--collection-confirmed` records a human prerequisite acknowledgment; it does
**not** enable collection or claim to have verified it automatically. Expected
decisions depend on your tenant policies, their scope, and propagation.

### Where enforcement happens

1. **Application preflight:** verify identity and inline policy coverage.
2. **Local retrieval:** select a synthetic sensitive record or public control.
3. **SDK agent middleware:** evaluate prompt and retrieved context; an explicit
   block terminates the run before the chat client is called.
4. **Application model gate:** recheck coverage and evaluate the complete
   text input, including instructions, via Graph. Only **ALLOWED** continues.
5. **Real model:** non-streaming Azure OpenAI chat completion, without tools.
6. **SDK post-check:** process the response according to applicable scopes.
   Offline collection is not output blocking or proof of portal arrival.

Why retain a Graph gate in an SDK sample? The pinned SDK's public middleware
does not expose per-entry `processingErrors` to the application, and its
no-applicable-scopes behavior can fall back to background activity collection.
The additional gate deliberately prioritizes an explicit, fail-closed teaching
example over minimal API calls. **This duplicates evaluations, latency, records,
and potentially cost.** Do not interpret it as a required Microsoft integration
pattern. Reassess it when upgrading the SDK.

The gate supports text-only, non-streaming calls. It rejects unsupported content
instead of silently dropping it. Its evidence prints:

- UTC start, full Graph correlation ID, and the SDK's corresponding `<ID>@AF`.
- **Model invoked: no** when the SDK or application gate stops the request.
- **Model invoked: yes** once the model client is called (an attempt, not proof
  that the provider accepted or completed it).
- **External action executed: no**, because this example registers no action
  tools—not because it demonstrates interception of an email or HTTP tool.

### Protection coverage and responsibilities

| Boundary | Raw API demo | SDK companion | Still your responsibility |
|----------|--------------|---------------|---------------------------|
| User prompt | Inline decision enforced by app | SDK pre-check plus strict Graph gate | Configure policies and enforce the decision |
| Retrieved context | Not part of scripted chat | Synthetic text checked before first model call | Authorize retrieval; integrate real connectors; check every later tool-result/model boundary |
| Model response | **Audit-only**, displayed before submission | Non-streaming SDK post-check; behavior depends on scopes | Verify supported inline output policies before claiming output prevention |
| External actions | None | No action tools registered | Tool permissions, destination controls, approval and pre-action checks |
| Audit / investigations | Submission shown, not ingestion proof | SDK may schedule background work | Collection policy, roles, retention, ingestion verification and durable delivery |
| Labels / encrypted files | Experimental file probe, not label enforcement | Text-only journey | Validate supported formats and label/rights handling separately |
| Prompt injection / access control | Not implemented | Not implemented | Identity, document ACLs, tool authorization and separate attack defenses |

Purview supplies policy signals; application and middleware control execution.
Neither integrating an SDK nor an empty action list makes an entire agent secure.
The SDK's streaming response post-check is not supported in this pinned version;
the companion deliberately disables streaming. Background SDK audit work may
not complete before a short-lived CLI exits; never treat a console result as an
audit-delivery guarantee.

### Supported integration and deployment boundaries

Verified against published packages on **2026-09-24**:

- [`agent-framework-purview` 1.0.0b260918](https://pypi.org/project/agent-framework-purview/1.0.0b260918/): **preview**, public `PurviewPolicyMiddleware`, `PurviewSettings` and `PurviewAppLocation`.
- [`agent-framework-core` 1.19.0](https://pypi.org/project/agent-framework-core/1.19.0/) and [`agent-framework-openai` 1.14.4](https://pypi.org/project/agent-framework-openai/1.14.4/): public `Agent`, chat middleware and model-client integration.
- [Microsoft integration source](https://github.com/microsoft/agent-framework/tree/703fbce285ee0f026e5effcadfb9e65aab7f5d84/python/packages/purview): scope caching, inline/offline handling, message correlation and middleware behavior. The pinned wheel, rather than the evolving main branch, is the compatibility baseline.

The SDK handles request mapping, scope caching, policy actions, pre/post hooks
and background collection. The application owns correct user/app identity,
coverage requirements, failure handling, downstream actions, and verification.
`ignore_exceptions` and `ignore_payment_required` are explicitly **false**.

The CLI uses an authenticated browser user and a user ID obtained from Graph,
not an ID supplied by an untrusted prompt. In a deployed web application, use
a supported on-behalf-of flow for delegated user calls, or the documented
application-permission flow for the SDK's `/users/{id}` endpoints. Do not use
an app-only token with `/me`, assume a managed identity is the end user, or copy
the CLI's single-user global cache into a multi-user service. Bind identity to
the authenticated request; isolate caches and correlations by tenant/user/app;
use least privilege and separate model credentials. Review supported permission
types in the [compute](https://learn.microsoft.com/en-us/graph/api/userprotectionscopecontainer-compute)
and [processContent](https://learn.microsoft.com/en-us/graph/api/userdatasecurityandgovernance-processcontent)
references before choosing a deployment flow.

### Prove it worked in Purview

1. Run the sensitive case and save the printed **UTC start**, signed-in user ID,
   protected app ID, correlation ID and execution evidence. A block should show
   no model call. Do not save access tokens or real employee information.
2. In **Activity Explorer**, filter by the test user, app and time window.
   Inspect the detailed prompt/retrieved-content events and the matching policy
   action. SDK content correlation uses the printed **`<ID>@AF`** value.
   Depending on portal fields, export/open event details to find correlation.
3. If the SDK blocks first, the supplemental Graph gate does not run, so there
   may be **no unsuffixed Graph content event** for that journey. If it runs,
   the gate's record uses `<ID>` and contains the combined model-bound text.
   Scope discovery itself is not evidence of content evaluation.
4. Run the public control. Confirm a real model-call attempt and, after
   ingestion, the configured response collection activity. Check **Audit**
   for applicable rule-match events; a benign allow need not create a
   `DLPRuleMatch` event. Other investigation surfaces require their own
   policies, licenses, permissions and processing time.
5. If evidence is missing, investigate collection setup, user/app scoping,
   role access, ingestion delay and failed/background submissions. **Do not
   report “audited” solely because an API accepted a request.**

Follow Microsoft's [AI app validation guide](https://learn.microsoft.com/en-us/purview/developer/how-to-test-an-ai-application-integrated-with-purview-sdk)
alongside the existing [validation checklist](#validation-checklist).

### Failure behavior and troubleshooting

| Observation | Meaning / next step |
|-------------|---------------------|
| `NO_POLICY_COVERAGE` | Discovery succeeded but no explicit matching inline upload scope was found. Check app location, test user, activity, execution mode and propagation; not an ALLOW result. |
| `EVALUATION_INCOMPLETE` | No trustworthy complete decision. Stop rather than forwarding to the model. |
| 401 / 403 | Verify tenant, sign-in, endpoint permission type and admin consent; authentication alone is insufficient. |
| 402 | Verify licensing and pay-as-you-go setup; do not enable payment-error bypass. |
| 429 | Throttled, not cleared. This demo stops; production retries should respect `Retry-After` with bounded backoff. |
| 503 / timeout | Service unavailable or decision incomplete. No automatic bypass or model call. |
| HTTP 200 with `processingErrors` | Partial processing is not successful clearance. An explicit block remains BLOCKED; otherwise stop as incomplete. |
| Benign control blocked | Inspect the actual policy and sensitive-information matches rather than hard-coding an ALLOW expectation. |
| Expected block allowed | Check scopes/rules and test data; a model call in this case means the expected protection was **not demonstrated**. |

Run `python classify_text.py --failure-demo` to show synthetic 503, 429, partial
processing and missing-coverage cases without a tenant. These are application
failure-policy demonstrations, **not live Purview results or audit records**.
The SDK companion additionally has a 90-second run deadline and disables model
transport retries. Model and service exception bodies are not printed.

### Local validation

No live tenant or model credentials are required for these standard-library tests:

```bash
python -m unittest test_raw_safety -v
python -m unittest test_agent_demo -v
```

Install `requirements-sdk.txt` to run the SDK integration tests rather than
skip them. They exercise the actual pinned middleware and model-client pipeline
with mocked HTTP services; tenant enforcement and portal ingestion still require
the live walkthrough above.

---

## API Flow Explained

### Step 1 — Compute Protection Scopes

```
POST /me/dataSecurityAndGovernance/protectionScopes/compute
```

- Discovers which DLP policies apply to the current user + app
- Returns **ETag** in the response header (must be cached)
- Returns **execution mode** per activity:
  - `uploadText` → `evaluateInline` (block thread, wait for decision)
  - `downloadText` → `evaluateOffline` (audit async, don't block user)
- `integratedAppMetadata` = who is calling Purview
- `locations` = optional policy-location filter (usually the protected app’s app ID)
- With a one-app demo you often get the same result with or without the filter; it becomes more useful when one orchestrator protects multiple downstream apps

### Step 2a — Process Content (uploadText — DLP check)

```
POST /me/dataSecurityAndGovernance/processContent
  activity: "uploadText"
```

- Evaluates user **prompt** against DLP policies
- Sends cached ETag via `If-None-Match` header
- Carries both identities:
  - `integratedAppMetadata` = caller / orchestrator
  - `protectedAppMetadata.applicationLocation` = protected app / policy location
- Returns `policyActions` (a complete successful evaluation with no actions = ALLOW, explicit block = BLOCKED); processing failures are not clearance
- Returns `protectionScopeState: "modified"` if policies changed → must re-call Step 1
- **Must block the user flow** until result is returned (evaluateInline)

### Step 2b — Process Content (downloadText — audit)

```
POST /me/dataSecurityAndGovernance/processContent
  activity: "downloadText"
```

- Sends the AI **response** to Purview for auditing
- The raw demo displays the response before submitting it; it **does not enforce response blocking**.
- The CLI awaits submission, while `evaluateOffline` refers to asynchronous **service evaluation**, not a background Python task.
- Visibility and classification in Activity Explorer and other investigation surfaces depend on collection/policy configuration and ingestion. Successful submission is not proof of arrival.

### Step 2c — Optional `contentActivities` call (audit-only)

```http
POST /me/dataSecurityAndGovernance/activities/contentActivities
```

- Useful when **no protection scopes apply** but you still want audit/compliance visibility
- Requires `ContentActivity.Write`
- Think of it as: “don’t enforce, just log”

### Step 3 — Files (`uploadFile` / `downloadFile`)

```http
POST /me/dataSecurityAndGovernance/processContent
  activity: "uploadFile"
```

The Graph v1.0 schema contains file-shaped entries as well as conversation text:

| Type | Purpose |
|------|---------|
| `microsoft.graph.processConversationMetadata` | Prompts and responses — used by Steps 2a/2b |
| `microsoft.graph.processFileMetadata` | Files — adds `ownerId` and `customProperties` |
| `microsoft.graph.textContent` | Content as a plain string |
| `microsoft.graph.binaryContent` | Content as a Base64-encoded byte stream |

The `userActivityType` enum includes `uploadText`, `uploadFile`, `downloadText`, `downloadFile`. Request the file activities in Step 1 (`activities: "uploadText,uploadFile,downloadText,downloadFile"`) or `uploadFile` may fall outside the computed scope.

**Important caveat:** accepting `binaryContent` does not prove that the service
parses every file format. Check the current API limits and supported formats
before designing a file pipeline; this probe only exercises one generated
`.docx` and the policies configured in your tenant.

- The v1.0 "Network provider app with file content" example uses `processFileMetadata` and `activity: uploadFile` — but its content block is `textContent` with a `"Base64 encoded content"` placeholder, contradicting the `processFileMetadata` schema, which shows `binaryContent`.
- [`microsoft/PurviewIntegrations`](https://github.com/microsoft/PurviewIntegrations) (the Purview GitHub Action that scans repository files) explicitly **skips binary files** and always builds `microsoft.graph.textContent`.
- The pinned [`agent-framework-purview`](https://pypi.org/project/agent-framework-purview/1.0.0b260918/) processor **does** construct binary content for base64 data URIs. Older statements that all first-party integrations send only text are no longer accurate. Binary transport still does not establish format-specific parsing or sensitivity-label enforcement.

The practical guidance today: **extract text from files client-side**, send it as `textContent` **inside** `processFileMetadata` so the file name, size, and owner still land correctly in Activity Explorer and DSPM for AI. Use the file support probe below to verify this for your own tenant.

### Key Behaviors

| Behavior | Details |
|----------|---------|
| **ETag Caching** | Cached from Step 1, sent with every Step 2 call |
| **Policy Change** | `protectionScopeState: "modified"` → re-call Step 1 |
| **60-Min Refresh** | Re-call Step 1 if ETag is older than 60 minutes |
| **Conversation Tracking** | `correlationId` per session, `sequenceNumber` increments per message |
| **Collection Policy** | Required for auditing (Activity Explorer, DSPM for AI, eDiscovery). NOT required for DLP enforcement. |
| **compute vs processContent** | `compute` is the pre-flight hint; `processContent` is the real transaction and the final content-level decision point. |
| **Files vs text** | `processFileMetadata` + `binaryContent` exist in the schema, but no file format list is documented. Verify with the file support probe before relying on binary parsing. |

---

## File Support Probe

Answers empirically, for **your** tenant: *does Purview classify Office file binaries, or only text?*

```bash
python classify_text.py
# ... then answer "y" at: Run the file support probe?
```

The probe sends the **same sensitive string three ways** and compares the DLP verdicts:

| # | Content entry | Content type | Activity | What it proves |
|---|---------------|--------------|----------|----------------|
| **A** | `processConversationMetadata` | `textContent` | `uploadText` | Control — the policy really does block this string |
| **B** | `processFileMetadata` | `binaryContent` (raw `.docx` bytes, Base64) | `uploadFile` | Whether the service parses Office binaries |
| **C** | `processFileMetadata` | `textContent` (text extracted locally from the same `.docx`) | `uploadFile` | Whether the file path works once you extract text yourself |

The `.docx` is generated in memory with the standard library (`zipfile` + minimal OOXML parts), so the demo gains no new dependencies and the file content is known exactly.

**Reading the result:**

| A | B | C | Conclusion |
|---|---|---|------------|
| BLOCKED | BLOCKED | — | The tested binary was blocked; validate why and test other formats separately |
| BLOCKED | ALLOWED | BLOCKED | The tested binary did not produce the same block; use extracted text for this path and investigate parsing/policy differences |
| BLOCKED | EVALUATION_INCOMPLETE | — | Inconclusive; fix the failed evaluation before comparing formats |
| BLOCKED | ALLOWED | ALLOWED | Inconclusive — the policy likely doesn't cover the `uploadFile` activity |
| ALLOWED | — | — | Inconclusive — the control failed; your policy isn't matching the test string |

**Configuration** (`config.py`):

| Setting | Purpose |
|---------|---------|
| `FILE_PROBE_TEXT` | Sensitive string used by all three variants. Must be something your DLP policy actually blocks. |
| `FILE_PROBE_FILE_NAME` | File name reported in `processFileMetadata.name` |
| `FILE_PROBE_ACTIVITIES` | Activities requested in Step 1 for the probe (includes `uploadFile` / `downloadFile`) |
| `PROTECTION_SCOPE_ACTIVITIES` | Activities requested in Step 1 for the standard text demo |

For a BLOCK verdict on the file variants, the DLP policy must also restrict the file activity — add `UploadFile` alongside `UploadText` in `-RestrictAccess`.

The three submissions share a `correlationId`. Verify resulting records in
Activity Explorer after collection configuration and ingestion; a failed request
is not a confirmed audit record.

---

## Raw HTTP Samples (Demo-Ready)

These samples are simplified on purpose so you can explain them live.

### 1. `protectionScopes/compute` — “What kind of checks do I need to do?”

```http
POST https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/protectionScopes/compute
Authorization: Bearer <token>
Content-Type: application/json
Client-Request-Id: 11111111-1111-1111-1111-111111111111

{
  "activities": "uploadText,downloadText",
  "integratedAppMetadata": {
    "name": "Contoso Orchestrator",
    "version": "1.0"
  },
  "locations": [
    {
      "@odata.type": "microsoft.graph.policyLocationApplication",
      "value": "<protected-app-id>"
    }
  ]
}
```

**What matters here**

- `integratedAppMetadata` = who is calling Purview
- `locations` = which app/location you want scopes for
- This is a **pre-flight** call, not the final decision

**Sample response**

```http
HTTP/1.1 200 OK
ETag: "W/\"scope-state-123\""
Content-Type: application/json

{
  "value": [
    {
      "activities": "uploadText",
      "executionMode": "evaluateInline",
      "locations": [
        {
          "value": "<protected-app-id>"
        }
      ],
      "policyActions": []
    },
    {
      "activities": "downloadText",
      "executionMode": "evaluateOffline",
      "locations": [
        {
          "value": "<protected-app-id>"
        }
      ],
      "policyActions": []
    }
  ]
}
```

**How to explain it**

“Purview is telling my app: for prompts, wait for a decision; for responses, audit asynchronously.”

### 2. `processContent` with `uploadText` — “Can I let this prompt through?”

```http
POST https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent
Authorization: Bearer <token>
Content-Type: application/json
If-None-Match: "W/\"scope-state-123\""
Client-Request-Id: 22222222-2222-2222-2222-222222222222

{
  "contentToProcess": {
    "contentEntries": [
      {
        "@odata.type": "microsoft.graph.processConversationMetadata",
        "identifier": "msg-001",
        "name": "User prompt",
        "correlationId": "thread-001",
        "sequenceNumber": 0,
        "isTruncated": false,
        "createdDateTime": "2026-03-13T12:00:00Z",
        "modifiedDateTime": "2026-03-13T12:00:00Z",
        "content": {
          "@odata.type": "microsoft.graph.textContent",
          "data": "Please update the HR record for employee SSN 120-98-1437 before payroll closes."
        }
      }
    ],
    "activityMetadata": {
      "activity": "uploadText"
    },
    "deviceMetadata": {
      "deviceType": "Unmanaged",
      "operatingSystemSpecifications": {
        "operatingSystemPlatform": "Windows 11",
        "operatingSystemVersion": "10.0.26100.0"
      },
      "ipAddress": "127.0.0.1"
    },
    "integratedAppMetadata": {
      "name": "Contoso Orchestrator",
      "version": "1.0"
    },
    "protectedAppMetadata": {
      "name": "Contoso HR App",
      "version": "1.0",
      "applicationLocation": {
        "@odata.type": "microsoft.graph.policyLocationApplication",
        "value": "<protected-app-id>"
      }
    }
  }
}
```

**Sample response**

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "protectionScopeState": "notModified",
  "policyActions": [
    {
      "@odata.type": "#microsoft.graph.restrictAccessAction",
      "action": "restrictAccess",
      "restrictionAction": "block"
    }
  ],
  "processingErrors": []
}
```

**How to explain it**

“Now I’m sending the actual prompt. This is the real decision call. Purview says: block it.”

### 3. `processContent` with `downloadText` — “Audit the AI response”

```http
POST https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent
Authorization: Bearer <token>
Content-Type: application/json
If-None-Match: "W/\"scope-state-123\""
Client-Request-Id: 33333333-3333-3333-3333-333333333333

{
  "contentToProcess": {
    "contentEntries": [
      {
        "@odata.type": "microsoft.graph.processConversationMetadata",
        "identifier": "msg-002",
        "name": "AI response",
        "correlationId": "thread-001",
        "sequenceNumber": 1,
        "isTruncated": false,
        "createdDateTime": "2026-03-13T12:00:02Z",
        "modifiedDateTime": "2026-03-13T12:00:02Z",
        "content": {
          "@odata.type": "microsoft.graph.textContent",
          "data": "Thank you. I have updated the reference number for the project."
        }
      }
    ],
    "activityMetadata": {
      "activity": "downloadText"
    },
    "deviceMetadata": {
      "deviceType": "Unmanaged",
      "operatingSystemSpecifications": {
        "operatingSystemPlatform": "Windows 11",
        "operatingSystemVersion": "10.0.26100.0"
      },
      "ipAddress": "127.0.0.1"
    },
    "integratedAppMetadata": {
      "name": "Contoso Orchestrator",
      "version": "1.0"
    },
    "protectedAppMetadata": {
      "name": "Contoso HR App",
      "version": "1.0",
      "applicationLocation": {
        "@odata.type": "microsoft.graph.policyLocationApplication",
        "value": "<protected-app-id>"
      }
    }
  }
}
```

**Sample response**

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "protectionScopeState": "notModified",
  "policyActions": [],
  "processingErrors": []
}
```

**How to explain it**

“This response was submitted for offline auditing. We must verify its arrival in the configured Purview experiences; this is not an inline output-clearance decision.”

### 4. Optional `contentActivities` — “No enforcement, just log it”

Use this when **no protection scopes apply** but you still want audit/compliance visibility.

```http
POST https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/activities/contentActivities
Authorization: Bearer <token>
Content-Type: application/json

{
  "contentToProcess": {
    "contentEntries": [
      {
        "@odata.type": "microsoft.graph.processConversationMetadata",
        "identifier": "msg-003",
        "name": "Audit-only prompt",
        "correlationId": "thread-002",
        "sequenceNumber": 0,
        "isTruncated": false,
        "createdDateTime": "2026-03-13T12:05:00Z",
        "modifiedDateTime": "2026-03-13T12:05:00Z"
      }
    ],
    "activityMetadata": {
      "activity": "uploadText"
    },
    "deviceMetadata": {
      "operatingSystemSpecifications": {
        "operatingSystemPlatform": "Windows 11",
        "operatingSystemVersion": "10.0.26100.0"
      },
      "ipAddress": "127.0.0.1"
    },
    "integratedAppMetadata": {
      "name": "Contoso Orchestrator",
      "version": "1.0"
    },
    "protectedAppMetadata": {
      "name": "Contoso HR App",
      "version": "1.0",
      "applicationLocation": {
        "@odata.type": "microsoft.graph.policyLocationApplication",
        "value": "<protected-app-id>"
      }
    }
  }
}
```

**Sample response**

```http
HTTP/1.1 201 Created
Content-Type: application/json

{
  "id": "<activity-id>",
  "userId": "<user-id>",
  "contentMetadata": {
    "activityMetadata": {
      "activity": "uploadText"
    }
  }
}
```

### 5. `processContent` with `uploadFile` — “Can I let this file through?”

Same endpoint, different content entry type. `processFileMetadata` adds file-shaped
metadata (`ownerId`, `customProperties`, `length`) so the activity shows up as a file
in Activity Explorer.

```http
POST https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent
Authorization: ******
Content-Type: application/json
If-None-Match: "<etag-from-compute>"

{
  "contentToProcess": {
    "contentEntries": [
      {
        "@odata.type": "microsoft.graph.processFileMetadata",
        "identifier": "file-001",
        "content": {
          "@odata.type": "microsoft.graph.binaryContent",
          "data": "<Base64-encoded file bytes>"
        },
        "name": "payroll-update.docx",
        "correlationId": "thread-003",
        "sequenceNumber": 0,
        "length": 17352,
        "isTruncated": false,
        "ownerId": "<entra-user-id>",
        "customProperties": {
          "Department": "Finance"
        },
        "createdDateTime": "2026-03-13T12:10:00Z",
        "modifiedDateTime": "2026-03-13T12:10:00Z"
      }
    ],
    "activityMetadata": {
      "activity": "uploadFile"
    },
    "deviceMetadata": {
      "deviceType": "Unmanaged",
      "operatingSystemSpecifications": {
        "operatingSystemPlatform": "Windows 11",
        "operatingSystemVersion": "10.0.26100.0"
      },
      "ipAddress": "127.0.0.1"
    },
    "integratedAppMetadata": {
      "name": "Contoso Orchestrator",
      "version": "1.0"
    },
    "protectedAppMetadata": {
      "name": "Contoso HR App",
      "version": "1.0",
      "applicationLocation": {
        "@odata.type": "microsoft.graph.policyLocationApplication",
        "value": "<protected-app-id>"
      }
    }
  }
}
```

> Swap `binaryContent` for `textContent` (with text you extracted from the file) if the
> file support probe shows that binaries are not classified in your tenant. Everything
> else in the payload stays the same.

## FAQ — Latest Customer Confusion

### What exactly is a policy location?

A policy location is just the thing a Purview policy targets. For app scenarios, that is typically an app ID inside `policyLocationApplication`.

### What exactly is an integrated app?

The integrated app is the app that calls Purview. It has the Graph permissions and sends the API requests.

### What exactly is a protected app?

The protected app is the app/location whose prompts or responses are being evaluated and audited.

### Can the integrated app and protected app be different?

Yes. In a simple demo they are often the same. In a real orchestrator pattern they can be different.

The API shape itself reflects this: `processContent` has separate fields for `integratedAppMetadata` and `protectedAppMetadata`, indicating these are distinct concepts even if many demos use the same app for both.

### Why can `protectionScopes/compute` feel different from `processContent`?

Because they do different jobs:

- `compute` = “What kind of checks should I do?”
- `processContent` = “Here is the actual content. Should I block it or allow it?”

`processContent` carries the concrete protected app metadata, so it is the stronger signal for the real content transaction.

### Why can `compute` return empty while `processContent` still evaluates content?

Treat `compute` as the pre-flight hint and `processContent` as the source of truth for the actual transaction. If your `compute` filter does not line up with how Purview resolves policy location, you can still see `processContent` evaluate the concrete protected app metadata you sent.

### What is the purpose of `policyActions` in `compute` if it is often empty?

At a high level, it tells you whether a scope already carries actions/restrictions at the scope level.

The important practical point is this: in the public Enterprise AI app examples, `compute.policyActions` is usually empty, and Microsoft’s enforcement examples rely on `processContent.policyActions` for the real allow/block action.

So for demos and customer conversations, treat `processContent.policyActions` as the actionable result.

### Should the DLP policy target the orchestrator or the protected app?

Target the app/location you actually want to govern. If the orchestrator is protecting content on behalf of a downstream app, target the downstream protected app location.

### Why do I sometimes see `Entra` and sometimes `Application`?

That is mostly terminology. The enforcement plane is being renamed from **Entra** to **Application**. For the purposes of this POC, treat them as the same concept unless Microsoft documentation explicitly tells you otherwise.

### Are files supported, or is it text only?

Structurally, files are supported: `processFileMetadata`, `binaryContent`, and the `uploadFile` / `downloadFile` activities are all in the Graph **v1.0** schema.

Binary transport and file parsing are different capabilities. The pinned SDK
can send binary data, but this text-only companion does not demonstrate Office/PDF
parsing or sensitivity-label enforcement. Validate formats and policies in your
tenant, using the **File Support Probe** as a narrow diagnostic, and extract text
client-side where required rather than treating an unevaluated file as cleared.

---

## Validation Checklist

After running the demo, verify activity appears in these Purview locations:

| Portal | What to Check |
|--------|---------------|
| **DSPM for AI** → Activity Explorer | User prompts (uploadText) AND AI responses (downloadText) with BLOCK/ALLOW status |
| **DSPM for AI** → Activity Explorer | File activity (uploadFile) if you ran the file support probe |
| **Audit** → Search | `DLPRuleMatch` events for your app |
| **Insider Risk Management** | Policy triggers if configured |
| **Communication Compliance** | Chat messages if policy is set |
| **eDiscovery** | Content items from AI interactions |
| **Data Lifecycle Management** | Retention of AI interaction records |

For detailed validation guidance, see [How to Test an AI Application Integrated with Purview](https://learn.microsoft.com/en-us/purview/developer/how-to-test-an-ai-application-integrated-with-purview-sdk).

---

## File Structure

```
PurviewAPI_POC/
├── README.md           # This file — demo guide and documentation
├── requirements.txt    # Python dependencies (rich, aiohttp, azure-identity)
├── config.py           # Configuration, credentials, demo scenarios, file probe settings
├── classify_text.py    # Main demo script — two-step flow + file support probe + rich UI
├── agent_demo.py       # Optional SDK payroll journey + real Azure OpenAI client
├── requirements-sdk.txt # Pinned optional SDK/model dependencies
├── test_raw_safety.py  # Offline raw decision/failure regression tests
├── test_agent_demo.py  # SDK pipeline tests with mocked Graph and model transports
└── .gitignore          # Excludes .venv, __pycache__, etc.
```

---

## Resources

| Resource | Link |
|----------|------|
| Purview Developer Integration Guide | https://learn.microsoft.com/en-us/purview/developer/use-the-api |
| protectionScopes/compute API Reference | https://learn.microsoft.com/en-us/graph/api/userprotectionscopecontainer-compute |
| processContent API Reference | https://learn.microsoft.com/en-us/graph/api/userdatasecurityandgovernance-processcontent |
| contentActivities API Reference | https://learn.microsoft.com/en-us/graph/api/activitiescontainer-post-contentactivities |
| integratedApplicationMetadata | https://learn.microsoft.com/en-us/graph/api/resources/integratedapplicationmetadata |
| protectedApplicationMetadata | https://learn.microsoft.com/en-us/graph/api/resources/protectedapplicationmetadata |
| policyLocationApplication | https://learn.microsoft.com/en-us/graph/api/resources/policylocationapplication |
| processFileMetadata (file content entries) | https://learn.microsoft.com/en-us/graph/api/resources/processfilemetadata |
| binaryContent (Base64 file bytes) | https://learn.microsoft.com/en-us/graph/api/resources/binarycontent |
| Configure Purview for AI Apps | https://learn.microsoft.com/en-us/purview/developer/configurepurview |
| Testing Guide | https://learn.microsoft.com/en-us/purview/developer/how-to-test-an-ai-application-integrated-with-purview-sdk |
| Purview Data Security for GenAI | https://learn.microsoft.com/en-us/purview/developer/purview-data-security-genai |
| DLP Policy PowerShell | https://learn.microsoft.com/en-us/powershell/module/exchange/new-dlpcompliancerule |
