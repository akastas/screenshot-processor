"""
TickTick OAuth2 Token Helper
Guides you through the TickTick OAuth flow to get an access token.

Usage:
    pip install requests
    python scripts/get_ticktick_token.py
"""

import webbrowser
import urllib.parse
import requests

# TickTick OAuth credentials
CLIENT_ID = "dZFOtH8a0WHCJnfn10"
CLIENT_SECRET = "n4ahoWCVRi481NamnKfN2U3WBqCkj6Ul"
REDIRECT_URI = "http://localhost:8080/callback"
SCOPE = "tasks:read tasks:write"

AUTH_URL = "https://ticktick.com/oauth/authorize"
TOKEN_URL = "https://ticktick.com/oauth/token"


def main():
    # Step 1: Build authorization URL
    params = {
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": "screenshot-processor",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\n=== TickTick OAuth2 Setup ===\n")
    print("Opening browser for TickTick login...")
    print(f"\nIf browser doesn't open, go to:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("After authorizing, you'll be redirected to a localhost URL.")
    print("Copy the FULL URL from the browser address bar and paste here.\n")

    redirect_url = input("Paste the redirect URL: ").strip()

    # Step 2: Extract authorization code
    parsed = urllib.parse.urlparse(redirect_url)
    query_params = urllib.parse.parse_qs(parsed.query)
    code = query_params.get("code", [None])[0]

    if not code:
        print("ERROR: Could not find 'code' parameter in URL.")
        print(f"URL received: {redirect_url}")
        return

    print(f"\nAuthorization code: {code}")

    # Step 3: Exchange code for access token
    print("\nExchanging code for access token...")
    response = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        print(f"ERROR: Token exchange failed ({response.status_code})")
        print(response.text)
        return

    token_data = response.json()
    access_token = token_data.get("access_token")

    print("\n✅ SUCCESS! Here's your access token:\n")
    print(f"TICKTICK_ACCESS_TOKEN={access_token}\n")
    print("Add this to your .env.deploy file.")
    print("\nNote: TickTick tokens don't expire unless revoked.")


if __name__ == "__main__":
    main()
