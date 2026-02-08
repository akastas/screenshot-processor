"""
One-time script to get an OAuth2 refresh token for akastas@gmail.com.

Usage:
    pip install google-auth-oauthlib
    python scripts/get_oauth_token.py

You'll need your OAuth Client ID and Client Secret from the GCP Console.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]


def main():
    print("=== Screenshot Processor — OAuth2 Token Setup ===\n")

    client_id = input("Paste your OAuth Client ID: ").strip()
    client_secret = input("Paste your OAuth Client Secret: ").strip()

    if not client_id or not client_secret:
        print("Error: Both Client ID and Client Secret are required.")
        return

    # Build the OAuth flow from client config
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    print("\nA browser window will open. Log in with akastas@gmail.com")
    print("and grant Google Drive access.\n")

    credentials = flow.run_local_server(port=8090)

    print("\n=== SUCCESS ===\n")
    print(f"Refresh Token:\n{credentials.refresh_token}\n")
    print("Now store this in GCP Secret Manager as 'oauth-refresh-token'")
    print("Also store your Client ID as 'oauth-client-id'")
    print("And your Client Secret as 'oauth-client-secret'")


if __name__ == "__main__":
    main()
