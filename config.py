"""
Configuration for Microsoft Purview API POC
"""

# Azure Entra ID (formerly Azure AD) App Registration
CLIENT_ID = "clientid"
TENANT_ID = "tenantid"

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

# Sample sensitive data for testing DLP policies
# NOTE: Microsoft Purview uses contextual detection - sensitive info types require
# corroborating keywords nearby to trigger detection (e.g., "SSN" near the number).
# Test patterns like 123-45-6789 are excluded as known examples.
SAMPLE_TEXTS = {
    "ssn_with_context": "Customer SSN: 120-98-1437 for the new account application",
    "ssn_no_context": "The reference number is 120-98-1437",
    "credit_card": "Credit card number 4532667785213500 expiring 12/2027",
    "safe": "Hello, this is a normal message without any sensitive information.",
    "mixed_sensitive": "Write an acceptance letter for Alex Wilber with SSN 120-98-1437 and credit card 4532667785213500 at One Microsoft Way, Redmond, WA 98052"
}
