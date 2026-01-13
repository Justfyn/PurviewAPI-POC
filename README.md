# Microsoft Purview API - Sensitive Text Classification POC

A Proof of Concept demonstrating how to integrate custom applications with **Microsoft Purview** for real-time sensitive data classification using Data Loss Prevention (DLP) policies.

## What This POC Does

- **Classifies text** against your organization's DLP policies in real-time
- **Returns BLOCK or ALLOW** decisions based on sensitive information detection
- **Demonstrates contextual detection** - how Microsoft Purview intelligently identifies sensitive data

---

## Prerequisites

### 1. Licensing

- **Microsoft 365 E5** license (required for Purview DLP and DSPM for AI)

### 2. Entra ID App Registration

Create an app registration in [Entra ID](https://entra.microsoft.com):

1. Go to **App registrations** → **New registration**
2. Name: `PurviewAPI POC`
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
| `Content.Process.User` | Process content for DLP evaluation |
| `ProtectionScopes.Compute.User` | Retrieve protection scope settings |
| `User.Read` | Basic user profile |

Click **Grant admin consent** (requires admin privileges).

#### Note Your IDs

From the **Overview** page, copy:
- **Application (client) ID**
- **Directory (tenant) ID**

### 3. Microsoft Purview Configuration

#### A. Enable Audit (if not already enabled)

1. Go to [Microsoft Purview Portal](https://purview.microsoft.com)
2. Navigate to **DSPM for AI** → **Overview**
3. Click **Activate Microsoft Purview Audit**

#### B. Enable DSPM for AI Policies

1. Go to **DSPM for AI** → **Recommendations**
2. Enable: **Secure interactions from enterprise apps (preview)**

#### C. Create DLP Policy with Entra Enforcement

Connect to Security & Compliance PowerShell:

```powershell
# Install module if needed
Install-Module -Name ExchangeOnlineManagement -Force

# Connect
Connect-IPPSSession
```

Create the DLP policy targeting your app:

```powershell
# Replace with your app details
$appId = "YOUR-APP-CLIENT-ID"
$appName = "PurviewAPI POC"

# Create Locations JSON
$locations = "[{`"Workload`":`"Applications`",`"Location`":`"$appId`",`"LocationDisplayName`":`"$appName`",`"LocationSource`":`"Entra`",`"LocationType`":`"Individual`",`"Inclusions`":[{`"Type`":`"Tenant`",`"Identity`":`"All`",`"DisplayName`":`"All`",`"Name`":`"All`"}]}]"

# Create DLP Policy with Entra enforcement
New-DlpCompliancePolicy -Name "Entra AI App DLP" `
    -Mode Enable `
    -Locations $locations `
    -EnforcementPlanes @("Entra")

# Create DLP Rule to block SSN
New-DlpComplianceRule -Name "Block SSN in Entra Apps" `
    -Policy "Entra AI App DLP" `
    -ContentContainsSensitiveInformation @{Name = "U.S. Social Security Number (SSN)"} `
    -RestrictAccess @(@{setting="UploadText";value="Block"}) `
    -GenerateAlert $true
```

> **Note:** DLP policies take 15-60 minutes to sync. Check status in the Purview portal under **Data Loss Prevention** → **Policies**.

---

## Installation

### 1. Set Up Python Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure the Application

Edit `config.py` with your Entra app details:

```python
CLIENT_ID = "your-client-id-here"
TENANT_ID = "your-tenant-id-here"
```

---

## Usage

```bash
python classify_text.py
```

1. A browser window opens for Microsoft 365 sign-in
2. The POC runs sample text classifications
3. Enter custom text in interactive mode to test

### Example Output

```
======================================================================
📊 CLASSIFICATION SUMMARY
======================================================================
   🛑 ssn_with_context: BLOCKED
   ✅ ssn_no_context: ALLOWED
   ✅ safe: ALLOWED
   🛑 mixed_sensitive: BLOCKED
```

---

## Understanding Detection Behavior

Microsoft Purview uses **contextual detection** - sensitive information types require corroborating evidence to trigger:

| Input | Result | Why |
|-------|--------|-----|
| `Customer SSN: 120-98-1437` | 🛑 BLOCKED | "SSN" keyword provides context |
| `Reference number: 120-98-1437` | ✅ ALLOWED | No context - could be any number |
| `SSN 120-98-1437 for account` | 🛑 BLOCKED | Business context with keyword |

This prevents false positives while catching real sensitive data sharing.

---

## API Reference

### Endpoint

```
POST https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent
```

### Response

```json
{
  "protectionScopeState": "modified",
  "policyActions": [
    {
      "@odata.type": "#microsoft.graph.restrictAccessAction",
      "action": "restrictAccess",
      "restrictionAction": "block"
    }
  ]
}
```

- **Empty `policyActions`** = Content ALLOWED
- **`restrictionAction: block`** = Content BLOCKED

---

## File Structure

```
PurviewAPI_POC/
├── README.md           # This file
├── requirements.txt    # Python dependencies
├── config.py           # Configuration (Client ID, Tenant ID, samples)
└── classify_text.py    # Main POC script
```

---

## Resources

| Resource | Link |
|----------|------|
| Purview Developer Docs | https://learn.microsoft.com/en-us/purview/developer/ |
| processContent API | https://learn.microsoft.com/en-us/graph/api/userdatasecurityandgovernance-processcontent |
| Configure DSPM for AI | https://learn.microsoft.com/en-us/purview/developer/configurepurview |
| DLP Policy PowerShell | https://learn.microsoft.com/en-us/powershell/module/exchange/new-dlpcompliancerule |
