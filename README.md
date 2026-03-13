# Microsoft Purview API — Live Demo

A proof-of-concept showing how **any custom application or AI app** can integrate with **Microsoft Purview** for real-time DLP enforcement and audit using the official API flow.

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
| **Response Audit** | `downloadText` with `evaluateOffline` — audits AI response asynchronously |
| **ETag Caching** | Cached from Step 1, sent with `If-None-Match` header in Step 2 |
| **Policy Change Detection** | Detects `protectionScopeState: "modified"` and re-computes scopes |
| **60-Minute Refresh** | Automatically re-calls Step 1 if ETag is older than 60 minutes |
| **Conversation Tracking** | Persistent `correlationId` per session, incrementing `sequenceNumber` |
| **Decision Trace** | Shows cache state, timing, and conversation tracking under each result |
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

### 3. Licensing

This POC uses the **Data Security — In Transit Protection** capability in Microsoft Purview (DLP enforcement via the `processContent` API). See the [Purview pricing page](https://azure.microsoft.com/en-us/pricing/details/purview/) for current meter details.

| License | API Works? | DSPM Portal? |
|---------|------------|--------------|
| **E5** | ✅ | ✅ |
| **E3 + DLP add-on** | ✅ | ❌ |
| **E3 alone** | ❌ | ❌ |

The `processContent` and `protectionScopes/compute` APIs fall under **In Transit Protection** and require at least E3 with a DLP add-on. The full DSPM for AI portal experience requires E5.

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
7. **Interactive Chat** — live AI chat with DLP enforcement + response audit

Each scenario pauses for `[Enter]` so the presenter can explain what's about to happen.

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
- Returns `policyActions` (empty = ALLOW, `block` = BLOCKED)
- Returns `protectionScopeState: "modified"` if policies changed → must re-call Step 1
- **Must block the user flow** until result is returned (evaluateInline)

### Step 2b — Process Content (downloadText — audit)

```
POST /me/dataSecurityAndGovernance/processContent
  activity: "downloadText"
```

- Sends the AI **response** to Purview for auditing
- The response appears in Activity Explorer, DSPM for AI, eDiscovery, etc.
- Runs **asynchronously** — does not block the user (evaluateOffline)
- Also detects if the AI response itself contains sensitive data

### Step 2c — Optional `contentActivities` call (audit-only)

```http
POST /me/dataSecurityAndGovernance/activities/contentActivities
```

- Useful when **no protection scopes apply** but you still want audit/compliance visibility
- Requires `ContentActivity.Write`
- Think of it as: “don’t enforce, just log”

### Key Behaviors

| Behavior | Details |
|----------|---------|
| **ETag Caching** | Cached from Step 1, sent with every Step 2 call |
| **Policy Change** | `protectionScopeState: "modified"` → re-call Step 1 |
| **60-Min Refresh** | Re-call Step 1 if ETag is older than 60 minutes |
| **Conversation Tracking** | `correlationId` per session, `sequenceNumber` increments per message |
| **Collection Policy** | Required for auditing (Activity Explorer, DSPM for AI, eDiscovery). NOT required for DLP enforcement. |
| **compute vs processContent** | `compute` is the pre-flight hint; `processContent` is the real transaction and the final content-level decision point. |

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

“This response is allowed, but it is still audited. That’s how it lands in Activity Explorer and the other Purview experiences.”

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

---

## Validation Checklist

After running the demo, verify activity appears in these Purview locations:

| Portal | What to Check |
|--------|---------------|
| **DSPM for AI** → Activity Explorer | User prompts (uploadText) AND AI responses (downloadText) with BLOCK/ALLOW status |
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
├── config.py           # Configuration, credentials, demo scenarios
├── classify_text.py    # Main demo script — two-step flow + rich UI
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
| Configure Purview for AI Apps | https://learn.microsoft.com/en-us/purview/developer/configurepurview |
| Testing Guide | https://learn.microsoft.com/en-us/purview/developer/how-to-test-an-ai-application-integrated-with-purview-sdk |
| Purview Data Security for GenAI | https://learn.microsoft.com/en-us/purview/developer/purview-data-security-genai |
| DLP Policy PowerShell | https://learn.microsoft.com/en-us/powershell/module/exchange/new-dlpcompliancerule |
