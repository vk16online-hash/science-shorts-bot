"""
oauth_setup.py — ONE-TIME local script to obtain a YouTube refresh token.

Prerequisites:
  - client_secret.json in the repo root
  - OAuth consent screen PUBLISHED to Production

Run once:
  python scripts/oauth_setup.py

Output:
  Writes state/token.json and prints the JSON to stdout.
  Copy that JSON into GitHub Secrets as YOUTUBE_TOKEN_JSON.
  Then DELETE state/token.json before committing.
"""
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET = Path("client_secret.json")
TOKEN_OUT = Path("state/token.json")


def main():
    if not CLIENT_SECRET.exists():
        raise SystemExit(
            "client_secret.json not found in repo root. "
            "Download it from Google Cloud Console → Credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET), SCOPES
    )
    creds = flow.run_local_server(port=0, prompt="consent")

    TOKEN_OUT.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_OUT.write_text(creds.to_json())

    print("\n" + "=" * 60)
    print("SUCCESS — copy this entire JSON into GitHub Secrets as")
    print("YOUTUBE_TOKEN_JSON (later, when we set up the workflow).")
    print("=" * 60 + "\n")
    print(creds.to_json())
    print("\n" + "=" * 60)
    print(f"Also saved locally to: {TOKEN_OUT}")
    print("Do NOT commit this file.")
    print("=" * 60)


if __name__ == "__main__":
    main()