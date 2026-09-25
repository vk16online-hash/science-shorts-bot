"""
upload.py — uploads a rendered MP4 to YouTube via Data API v3.
Reads OAuth from YOUTUBE_TOKEN_JSON env var or state/token.json.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

CATEGORY_SCIENCE = "28"


def _load_credentials() -> Credentials:
    raw = os.environ.get("YOUTUBE_TOKEN_JSON", "").strip()
    if raw:
        info = json.loads(raw)
    elif Path("state/token.json").exists():
        info = json.loads(Path("state/token.json").read_text())
    else:
        raise RuntimeError(
            "No YouTube credentials. Set YOUTUBE_TOKEN_JSON or run "
            "scripts/oauth_setup.py to create state/token.json."
        )
    creds = Credentials.from_authorized_user_info(info)
    if creds.expired and creds.refresh_token:
        print("[upload] refreshing access token...", file=sys.stderr)
        creds.refresh(Request())
        try:
            Path("state/token.json").write_text(creds.to_json())
        except Exception:
            pass
    return creds


def _youtube():
    return build("youtube", "v3", credentials=_load_credentials(),
                 cache_discovery=False)


def upload_video(video_path, title, description, tags, privacy="public"):
    if not Path(video_path).exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    if len(title) > 100:
        title = title[:97] + "..."

    clean_tags = []
    for t in (tags or []):
        t = str(t).lstrip("#").strip()
        if t and t not in clean_tags:
            clean_tags.append(t)
    clean_tags = clean_tags[:15]

    body = {
        "snippet": {
            "title": title,
            "description": description or "",
            "tags": clean_tags,
            "categoryId": CATEGORY_SCIENCE,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path, chunksize=-1, resumable=True, mimetype="video/mp4"
    )

    print(f"[upload] uploading {video_path} as '{title}' ({privacy})",
          file=sys.stderr)
    request = _youtube().videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"[upload] {pct}%", file=sys.stderr)

    vid = response["id"]
    print(f"[upload] done: https://youtube.com/shorts/{vid}", file=sys.stderr)
    return vid


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--privacy", default="public",
                    choices=["public", "unlisted", "private"])
    args = ap.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    vid = upload_video(args.video, args.title, args.description, tags,
                       privacy=args.privacy)
    print(vid)


if __name__ == "__main__":
    _cli()