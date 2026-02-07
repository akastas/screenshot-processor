#!/usr/bin/env python3
"""
TickTick OAuth2 Helper — Run this ONCE to get a refresh token.

Usage:
    1. Register your app at https://developer.ticktick.com/manage
    2. Set redirect URI to http://localhost:8080/callback
    3. Run: python ticktick_oauth.py --client-id YOUR_ID --client-secret YOUR_SECRET
    4. Browser opens → authorize → copy the refresh token
    5. Store refresh token in GCP Secret Manager as 'ticktick-refresh-token'
"""

import argparse
import http.server
import urllib.parse
import webbrowser
from threading import Event

import requests


def main():
    parser = argparse.ArgumentParser(description="TickTick OAuth2 token helper")
    parser.add_argument("--client-id", required=True, help="TickTick OAuth client ID")
    parser.add_argument("--client-secret", required=True, help="TickTick OAuth client secret")
    parser.add_argument("--port", type=int, default=8080, help="Local callback port")
    args = parser.parse_args()

    redirect_uri = f"http://localhost:{args.port}/callback"
    auth_code = None
    done = Event()

    # --- Local HTTP server to capture the callback ---
    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if "code" in params:
                auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h1>Success!</h1><p>Authorization code received. "
                    b"You can close this tab.</p>"
                )
                done.set()
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Error: no code parameter found")

        def log_message(self, format, *args):
            pass  # Suppress server logs

    # --- Step 1: Open browser for authorization ---
    auth_url = (
        f"https://ticktick.com/oauth/authorize"
        f"?scope=tasks:write%20tasks:read"
        f"&client_id={args.client_id}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&state=screenshot_processor"
    )

    print(f"\n{'='*60}")
    print("Opening browser for TickTick authorization...")
    print(f"If it doesn't open, visit:\n{auth_url}")
    print(f"{'='*60}\n")
    webbrowser.open(auth_url)

    # --- Step 2: Wait for callback ---
    server = http.server.HTTPServer(("localhost", args.port), CallbackHandler)
    server.timeout = 120
    while not done.is_set():
        server.handle_request()

    if not auth_code:
        print("ERROR: No authorization code received.")
        return

    print(f"Authorization code received: {auth_code[:10]}...")

    # --- Step 3: Exchange code for tokens ---
    print("\nExchanging code for tokens...")
    response = requests.post(
        "https://ticktick.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": args.client_id,
            "client_secret": args.client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    response.raise_for_status()
    tokens = response.json()

    # --- Step 4: Display results ---
    print(f"\n{'='*60}")
    print("SUCCESS! Save these values in GCP Secret Manager:")
    print(f"{'='*60}")
    print(f"\n  ticktick-client-id:      {args.client_id}")
    print(f"  ticktick-client-secret:  {args.client_secret}")
    print(f"  ticktick-refresh-token:  {tokens.get('refresh_token', 'N/A')}")
    print(f"\n  Access token (temporary): {tokens.get('access_token', 'N/A')[:30]}...")
    print(f"\n{'='*60}")
    print("\nTo store in Secret Manager, run:")
    print(f'  echo -n "{tokens.get("refresh_token", "")}" | gcloud secrets create ticktick-refresh-token --data-file=-')
    print(f'  echo -n "{args.client_id}" | gcloud secrets create ticktick-client-id --data-file=-')
    print(f'  echo -n "{args.client_secret}" | gcloud secrets create ticktick-client-secret --data-file=-')


if __name__ == "__main__":
    main()
