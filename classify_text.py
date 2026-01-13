"""
Microsoft Purview API POC - Sensitive Text Classification

This script demonstrates how to use the Microsoft Graph API to classify
text content against DLP (Data Loss Prevention) policies configured in
Microsoft Purview.

Prerequisites:
1. Microsoft 365 E5 license
2. Entra app registration with required permissions
3. DLP policies configured in Microsoft Purview portal
4. Redirect URI (http://localhost:8000) added to app registration

Usage:
    python classify_text.py
"""

import asyncio
import uuid
import json
from datetime import datetime, timezone

from azure.identity import InteractiveBrowserCredential
from msgraph import GraphServiceClient
from kiota_abstractions.base_request_configuration import RequestConfiguration

from config import CLIENT_ID, TENANT_ID, REDIRECT_URI, SCOPES, SAMPLE_TEXTS


def create_credential():
    """Create interactive browser credential for authentication."""
    print("\n🔐 Initializing authentication...")
    print(f"   Client ID: {CLIENT_ID}")
    print(f"   Tenant ID: {TENANT_ID}")
    print(f"   Redirect URI: {REDIRECT_URI}")
    
    credential = InteractiveBrowserCredential(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI
    )
    return credential


def create_graph_client(credential):
    """Create Microsoft Graph client with the credential."""
    print("\n📊 Creating Microsoft Graph client...")
    client = GraphServiceClient(credential, scopes=SCOPES)
    return client


async def get_current_user(client: GraphServiceClient):
    """Get the current authenticated user's info."""
    try:
        user = await client.me.get()
        if user:
            print(f"\n✅ Authenticated as: {user.display_name} ({user.user_principal_name})")
            return user
    except Exception as e:
        print(f"\n⚠️  Could not get user info: {e}")
    return None


async def classify_text_with_purview(client: GraphServiceClient, text: str, text_name: str = "Test"):
    """
    Classify text content using Microsoft Purview DLP policies.
    
    This calls the processContent API endpoint to evaluate text against
    configured DLP policies and returns the policy action (block/allow).
    
    Args:
        client: Microsoft Graph client
        text: The text content to classify
        text_name: A friendly name for the text being classified
        
    Returns:
        dict: The API response containing policy actions
    """
    print(f"\n{'='*60}")
    print(f"📝 Classifying: {text_name}")
    print(f"   Text: {text[:80]}{'...' if len(text) > 80 else ''}")
    print(f"{'='*60}")
    
    # Generate unique identifiers for this request
    request_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    
    # Build the request body for processContent API
    # Following the exact format from Microsoft documentation examples
    request_body = {
        "contentToProcess": {
            "contentEntries": [
                {
                    "@odata.type": "microsoft.graph.processConversationMetadata",
                    "identifier": request_id,
                    "content": {
                        "@odata.type": "microsoft.graph.textContent",
                        "data": text
                    },
                    "name": "PC Purview API Explorer message",
                    "correlationId": correlation_id,
                    "sequenceNumber": 0,
                    "isTruncated": False,
                    "createdDateTime": current_time,
                    "modifiedDateTime": current_time
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
            "protectedAppMetadata": {
                "name": "PurviewAPI POC",
                "version": "1.0",
                "applicationLocation": {
                    "@odata.type": "#microsoft.graph.policyLocationApplication",
                    "value": CLIENT_ID
                }
            },
            "integratedAppMetadata": {
                "name": "PurviewAPI POC",
                "version": "1.0"
            }
        }
    }
    
    try:
        # Make the API call using raw HTTP request since the SDK may not have
        # full support for the dataSecurityAndGovernance endpoints yet
        import aiohttp
        
        # Get access token
        token = credential.get_token("https://graph.microsoft.com/.default")
        
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json"
        }
        
        url = "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=request_body) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    result = json.loads(response_text)
                    return parse_classification_result(result, text_name)
                elif response.status == 401:
                    print(f"\n❌ Authentication error (401)")
                    print("   Make sure you have the required API permissions:")
                    print("   - Content.Process.User")
                    print("   - ProtectionScopes.Compute.User")
                    return None
                elif response.status == 403:
                    print(f"\n❌ Authorization error (403)")
                    print("   Your account may not have access to Purview APIs.")
                    print("   Ensure you have an E5 license and proper permissions.")
                    return None
                elif response.status == 404:
                    print(f"\n❌ Endpoint not found (404)")
                    print("   The dataSecurityAndGovernance API may not be available in your tenant.")
                    return None
                else:
                    print(f"\n❌ API Error: {response.status}")
                    print(f"   Response: {response_text[:500]}")
                    return None
                    
    except Exception as e:
        print(f"\n❌ Error classifying text: {e}")
        return None


def parse_classification_result(result: dict, text_name: str):
    """Parse and display the classification result."""
    print(f"\n📋 Classification Result for '{text_name}':")
    print(f"   Protection Scope State: {result.get('protectionScopeState', 'N/A')}")
    
    policy_actions = result.get('policyActions', [])
    processing_errors = result.get('processingErrors', [])
    
    if processing_errors:
        print(f"\n   ⚠️  Processing Errors:")
        for error in processing_errors:
            print(f"      - {error}")
    
    if not policy_actions:
        print(f"\n   ✅ ALLOWED - No DLP policy violations detected")
        return {"status": "allowed", "actions": [], "result": result}
    
    print(f"\n   🚫 Policy Actions Triggered:")
    blocked = False
    for action in policy_actions:
        action_type = action.get('@odata.type', 'Unknown')
        action_name = action.get('action', 'Unknown')
        restriction = action.get('restrictionAction', '')
        
        print(f"      - Type: {action_type}")
        print(f"        Action: {action_name}")
        if restriction:
            print(f"        Restriction: {restriction}")
            if restriction.lower() == 'block':
                blocked = True
    
    if blocked:
        print(f"\n   🛑 BLOCKED - Content violates DLP policies")
        return {"status": "blocked", "actions": policy_actions, "result": result}
    else:
        print(f"\n   ⚠️  WARNING - Policy actions triggered but not blocked")
        return {"status": "warning", "actions": policy_actions, "result": result}


async def run_classification_demo(client: GraphServiceClient):
    """Run classification on all sample texts."""
    print("\n" + "="*70)
    print("🔍 MICROSOFT PURVIEW API - SENSITIVE TEXT CLASSIFICATION DEMO")
    print("="*70)
    
    results = {}
    
    for name, text in SAMPLE_TEXTS.items():
        result = await classify_text_with_purview(client, text, name)
        results[name] = result
        # Small delay between requests
        await asyncio.sleep(1)
    
    # Summary
    print("\n" + "="*70)
    print("📊 CLASSIFICATION SUMMARY")
    print("="*70)
    
    for name, result in results.items():
        if result:
            status = result.get('status', 'unknown')
            emoji = "✅" if status == "allowed" else "🛑" if status == "blocked" else "⚠️"
            print(f"   {emoji} {name}: {status.upper()}")
        else:
            print(f"   ❓ {name}: ERROR (could not classify)")
    
    return results


async def classify_custom_text(client: GraphServiceClient, text: str):
    """Classify a custom text input."""
    return await classify_text_with_purview(client, text, "Custom Input")


# Global credential for reuse
credential = None


async def main():
    """Main entry point for the POC."""
    global credential
    
    print("\n" + "="*70)
    print("🚀 MICROSOFT PURVIEW API POC - STARTING")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    # Create credential and client
    credential = create_credential()
    client = create_graph_client(credential)
    
    # Authenticate and get user info
    print("\n🌐 Opening browser for authentication...")
    print("   Please sign in with your Microsoft 365 account.")
    user = await get_current_user(client)
    
    if not user:
        print("\n❌ Authentication failed. Please check your credentials and try again.")
        return
    
    # Run the demo
    await run_classification_demo(client)
    
    # Interactive mode
    print("\n" + "="*70)
    print("💬 INTERACTIVE MODE")
    print("   Enter text to classify, or 'quit' to exit")
    print("="*70)
    
    while True:
        try:
            user_input = input("\n📝 Enter text to classify: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                break
            if user_input:
                await classify_custom_text(client, user_input)
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            break


if __name__ == "__main__":
    asyncio.run(main())
