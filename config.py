"""
Configuration for Microsoft Purview API — Live Demo
=====================================================
Update CLIENT_ID and TENANT_ID with your Entra app registration values.
"""

# ──────────────────────────────────────────────────────────────────────
# Azure Entra ID App Registration
# ──────────────────────────────────────────────────────────────────────
# This is the "Integrated App" / "IntegratorApp" — the orchestrator that
# calls the Purview APIs to check compliance BEFORE routing user input to
# an AI model.
# An app becomes an IntegratorApp by:
#   1. Registering in Entra ID
#   2. Being granted ProtectionScopes.Compute.User and Content.Process.User
#   3. Having admin consent granted for those permissions
# Purview recognises it automatically — no separate registration needed.
CLIENT_ID = "Your-Application(Client)-ID-Here"
TENANT_ID = "Your-Tenant-ID-Here"

# Redirect URI for interactive browser authentication
# IMPORTANT: Add this URI to your Entra app registration under:
# Authentication > Platform configurations > Add a platform > Mobile and desktop applications
REDIRECT_URI = "http://localhost:8000"

# Microsoft Graph API scopes required for Purview content processing
SCOPES = [
    "https://graph.microsoft.com/Content.Process.User",
    "https://graph.microsoft.com/ProtectionScopes.Compute.User",
    "https://graph.microsoft.com/User.Read",  # Basic profile access
]

# ──────────────────────────────────────────────────────────────────────
# Demo Scenarios — ordered for maximum storytelling impact
#
# Each scenario includes:
#   - text: the user prompt sent to the AI (evaluated via uploadText)
#   - ai_response: simulated AI reply (audited via downloadText)
#   - expect: expected DLP decision for the prompt
#
# The downloadText call sends the AI response to Purview for auditing.
# This ensures both prompts AND responses appear in Activity Explorer,
# DSPM for AI, eDiscovery, Insider Risk, etc.
# ──────────────────────────────────────────────────────────────────────
DEMO_SCENARIOS = [
    {
        "title": "Hidden SSN (No Context)",
        "text": "The reference number is 120-98-1437 for that project.",
        "ai_response": "Thank you! I've noted reference number 120-98-1437 for the project. I'll use this to track the relevant documentation. Is there anything else you'd like me to help with?",
        "description": "A number that looks like an SSN but has no business context. This shows Purview is not just using a naive pattern match.",
        "expect": "ALLOW",
    },
    {
        "title": "SSN with Context",
        "text": "Please update the HR record for employee SSN 120-98-1437 before payroll closes.",
        "ai_response": None,  # blocked — no AI response
        "description": "The same number, now with explicit HR and SSN context. This is the core contextual-intelligence moment in the demo.",
        "expect": "BLOCK",
    },
    {
        "title": "Credit Card Number",
        "text": "Process payment with credit card number 4532-6677-8521-3500 expiring 12/2027.",
        "ai_response": None,  # blocked — no AI response
        "description": "A credit card number with contextual payment keywords.",
        "expect": "BLOCK",
    },
    {
        "title": "Data Exfiltration Attempt",
        "text": "Write an acceptance letter for Alex Wilber with SSN 120-98-1437 and credit card 4532667785213500 at One Microsoft Way, Redmond, WA 98052",
        "ai_response": None,  # blocked — no AI response
        "description": "A prompt trying to exfiltrate multiple PII types through an AI app — the nightmare scenario.",
        "expect": "BLOCK",
    },
]

# ──────────────────────────────────────────────────────────────────────
# App metadata sent to Purview
# ──────────────────────────────────────────────────────────────────────
# UI / demo branding
APP_NAME = "Contoso AI Assistant"
APP_VERSION = "2.0"

# The application integrated with the Purview APIs (the caller / orchestrator).
# This is represented in processContent as integratedAppMetadata.
INTEGRATED_APP_NAME = APP_NAME
INTEGRATED_APP_VERSION = APP_VERSION

# The application whose activity is being governed by DLP policy.
# This is represented in processContent as protectedAppMetadata.applicationLocation.
#
# For the SIMPLEST demo, keep this equal to the calling app.
# If your orchestrator protects downstream apps, point this to the actual
# protected application's Entra app ID instead.
PROTECTED_APP_NAME = APP_NAME
PROTECTED_APP_VERSION = APP_VERSION
PROTECTED_APP_CLIENT_ID = CLIENT_ID

# Optional filter used in protectionScopes/compute.
# This is a POLICY LOCATION filter, not the identity of the caller.
# In most demos, use the protected app's application ID here.
POLICY_LOCATION_APP_ID = PROTECTED_APP_CLIENT_ID

# Simulated AI responses for the interactive chat (when prompt is allowed)
CHAT_AI_RESPONSES = [
    "I'd be happy to help with that! Based on the information you provided, here's what I can do...",
    "That's a great question. Let me look into that for you and provide a detailed answer.",
    "I've processed your request. Here's the summary of what I found...",
    "Sure! I can assist with that. Here are the key points to consider...",
]
