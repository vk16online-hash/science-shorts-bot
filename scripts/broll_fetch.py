"""
broll_fetch.py — downloads keyless, license-clean B-roll clips.

Keyless sources (always tried in order):
  1. NASA Image & Video Library  → public domain
  2. Wikimedia Commons           → CC-licensed
  3. Internet Archive            → public domain + CC

Optional source (only if PEXELS_API_KEY env var is set):
  4. Pexels                      → free high-quality stock video

Deduplicates against state/used_broll.json. Saves state after each success.
"""
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
BROLL_DIR = REPO / "assets" / "broll"
USED_FILE = REPO / "state" / "used_broll.json"
BROLL_DIR.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "ScienceShortsBot/1.0 (github.com/vk16online-hash)"}
TIMEOUT = 30
MAX_BYTES = 25 * 1024 * 1024   # 25 MB per clip
MIN_BYTES = 200 * 1024          # 200 KB minimum


# ── Used-clip ledger ────────────────────────────────────────────
def _load_used() -> set:
    if not USED_FILE.exists():
        return set()
    try:
        return set(json.loads(USED_FILE.read_text()))
    except json.JSONDecodeError:
        return set()


def _save_used(used: set) -> None:
    USED_FILE.write_text(json.dumps(sorted(used), indent=2))


# ── 1. NASA Image & Video Library ───────────────────────────────
def _nasa(query: str) -> dict | None:
    try:
        r = requests.get(
            "https://images-api.nasa.gov/search",
            params={"q": query, "media_type": "video"},
            headers=UA, timeout=TIMEOUT,
        )
        r.raise_for_status()
        items = r.json().get("collection", {}).get("items", [])
        random.shuffle(items)
        for item in items[:8]:
            data = item.get("data", [{}])[0]
            nasa_id = data.get("nasa_id")
            if not nasa_id:
                continue
            manifest = requests.get(
                f"https://images-api.nasa.gov/asset/{nasa_id}",
                headers=UA, timeout=TIMEOUT,
            ).json()
            for asset in manifest.get("collection", {}).get("items", []):
                href = asset.get("href", "")
                if href.lower().endswith((".mp4", ".webm")):
                    return {
                        "url": href,
                        "license": "Public Domain (NASA)",
                        "creator": data.get("center", "NASA"),
                        "source": "nasa",
                    }
    except Exception as e:
        print(f"[broll] nasa failed: {e}", file=sys.stderr)
    return None


# ── 2. Wikimedia Commons ────────────────────────────────────────
def _wikimedia(query: str) -> dict | None:
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:video {query}",
                "gsrnamespace": 6,
                "gsrlimit": 15,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|user",
            },
            headers=UA, timeout=TIMEOUT,
        )
        r.raise_for_status()
        pages = list(r.json().get("query", {}).get("pages", {}).values())
        random.shuffle(pages)
        for page in pages:
            info = page.get("imageinfo", [{}])[0]
            url = info.get("url", "")
            if not url.lower().endswith((".webm", ".ogv", ".mp4")):
                continue
            meta = info.get("extmetadata", {})
            license_name = meta.get("LicenseShortName", {}).get(
                "value", "CC (see source)"
            )
            creator = info.get("user", "Wikimedia contributor")
            return {
                "url": url,
                "license": license_name,
                "creator": creator,
                "source": "wikimedia",
            }
    except Exception as e:
        print(f"[broll] wikimedia failed: {e}", file=sys.stderr)
    return None


# ── 3. Internet Archive (keyless) ───────────────────────────────
def _internet_archive(query: str) -> dict | None:
    try:
        r = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f'({query}) AND mediatype:movies',
                "fl[]": ["identifier", "title", "creator", "licenseurl"],
                "rows": 15,
                "page": 1,
                "output": "json",
            },
            headers=UA, timeout=TIMEOUT,
        )
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        random.shuffle(docs)

        for doc in docs[:10]:
            identifier = doc.get("identifier")
            if not identifier:
                continue

            meta = requests.get(
                f"https://archive.org/metadata/{identifier}",
                headers=UA, timeout=TIMEOUT,
            ).json()
            files = meta.get("files", [])

            candidates = [
                f for f in files
                if f.get("name", "").lower().endswith(".mp4")
                and f.get("format", "").lower() in ("mpeg4", "h.264", "512kb mpeg4")
            ]
            if not candidates:
                candidates = [
                    f for f in files
                    if f.get("name", "").lower().endswith(".mp4")
                ]
            if not candidates:
                continue

            # Prefer smallest files to keep downloads fast
            candidates.sort(key=lambda f: int(f.get("size", "0") or 0))

            # Filter out obviously-too-big files
            candidates = [
                c for c in candidates
                if int(c.get("size", "0") or 0) <= MAX_BYTES
            ]
            if not candidates:
                continue

            chosen = candidates[0]
            url = f"https://archive.org/download/{identifier}/{chosen['name']}"

            license_url = doc.get("licenseurl") or ""
            if "publicdomain" in license_url.lower() or not license_url:
                license_name = "Public Domain / Archive.org"
            elif "creativecommons" in license_url.lower():
                license_name = "Creative Commons (see archive.org)"
            else:
                license_name = "See archive.org"

            creator = doc.get("creator", "Archive.org contributor")
            if isinstance(creator, list):
                creator = creator[0] if creator else "Archive.org contributor"

            return {
                "url": url,
                "license": license_name,
                "creator": str(creator),
                "source": "archive",
            }
    except Exception as e:
        print(f"[broll] archive failed: {e}", file=sys.stderr)
    return None


# ── 4. Pexels (optional, needs free key) ────────────────────────
def _pexels(query: str) -> dict | None:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={
                "query": query,
                "orientation": "portrait",
                "per_page": 10,
                "size": "medium",
            },
            headers={"Authorization": key, **UA},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        random.shuffle(videos)
        for v in videos:
            files = v.get("video_files", [])
            files.sort(
                key=lambda f: (
                    0 if (f.get("width", 0) or 0) >= 1080 else 1,
                    abs((f.get("width", 0) or 0) - 1080),
                )
            )
            for f in files:
                link = f.get("link")
                if link and link.endswith(".mp4"):
                    return {
                        "url": link,
                        "license": "Pexels License (free commercial use)",
                        "creator": v.get("user", {}).get("name", "Pexels contributor"),
                        "source": "pexels",
                    }
    except Exception as e:
        print(f"[broll] pexels failed: {e}", file=sys.stderr)
    return None


# ── Download with size cap ──────────────────────────────────────
def _download(asset: dict, idx: int) -> Path | None:
    try:
        r = requests.get(asset["url"], headers=UA, timeout=(10, 60), stream=True)
        r.raise_for_status()

        declared = int(r.headers.get("Content-Length", "0") or 0)
        if declared and declared > MAX_BYTES:
            print(f"[broll] skipping oversized ({declared // 1024 // 1024} MB)", file=sys.stderr)
            return None

        url_lower = asset["url"].lower()
        ext = ".webm" if url_lower.endswith(".webm") else \
              ".ogv"  if url_lower.endswith(".ogv")  else ".mp4"
        path = BROLL_DIR / f"clip_{idx}_{hashlib.md5(asset['url'].encode()).hexdigest()[:8]}{ext}"

        written = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                written += len(chunk)
                if written > MAX_BYTES:
                    print(f"[broll] aborted: exceeded {MAX_BYTES // 1024 // 1024} MB", file=sys.stderr)
                    f.close()
                    path.unlink(missing_ok=True)
                    return None
                f.write(chunk)

        if written < MIN_BYTES:
            path.unlink(missing_ok=True)
            print(f"[broll] rejected small file: {path.name}", file=sys.stderr)
            return None

        asset["path"] = str(path)
        asset["size_mb"] = round(written / 1024 / 1024, 1)
        return path
    except Exception as e:
        print(f"[broll] download failed: {e}", file=sys.stderr)
        try:
            if 'path' in locals() and path.exists():
                path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


# ── Public API ──────────────────────────────────────────────────
def fetch_broll(keywords: list, max_clips: int = 3) -> list:
    """Fetch up to max_clips clips. Raises RuntimeError if none found."""
    used = _load_used()
    assets = []

    fetchers = [
        (_nasa, "nasa"),
        (_wikimedia, "wikimedia"),
        (_internet_archive, "archive"),
    ]
    if os.environ.get("PEXELS_API_KEY", "").strip():
        fetchers.append((_pexels, "pexels"))

    for kw in keywords:
        if len(assets) >= max_clips:
            break
        for fetcher, fname in fetchers:
            if len(assets) >= max_clips:
                break
            asset = fetcher(kw)
            if not asset:
                continue
            if asset["url"] in used:
                print(f"[broll] skipping used clip from {fname}", file=sys.stderr)
                continue
            if _download(asset, len(assets)):
                used.add(asset["url"])
                assets.append(asset)
                _save_used(used)   # persist after every success
                print(
                    f"[broll] got {fname} :: {asset['license']} "
                    f"({asset.get('size_mb', '?')} MB)",
                    file=sys.stderr,
                )
                break

    _save_used(used)

    if not assets:
        raise RuntimeError(f"No B-roll found for keywords={keywords}")

    while len(assets) < max_clips:
        assets.append(assets[0])

    return assets[:max_clips]

def fetch_broll_for_scenes(scenes: list, keyword_fallback: str = "science") -> list:
    """
    Fetch ONE clip per scene. Returns list of {scene, asset} dicts.
    Falls back to keyword_fallback if a scene's query returns nothing.
    """
    used = _load_used()
    results = []
    fetchers = [
        (_nasa, "nasa"),
        (_wikimedia, "wikimedia"),
        (_internet_archive, "archive"),
    ]
    if os.environ.get("PEXELS_API_KEY", "").strip():
        fetchers.insert(0, (_pexels, "pexels"))

    for i, scene in enumerate(scenes):
        query = scene.get("broll_query") or keyword_fallback
        picked = None

        for attempt_query in (query, keyword_fallback):
            for fetcher, fname in fetchers:
                asset = fetcher(attempt_query)
                if not asset:
                    continue
                if asset["url"] in used:
                    continue
                if _download(asset, i):
                    used.add(asset["url"])
                    _save_used(used)
                    print(
                        f"[broll] scene {i}: {fname} :: {asset['license']} "
                        f"({asset.get('size_mb', '?')} MB)",
                        file=sys.stderr,
                    )
                    picked = asset
                    break
            if picked:
                break

        if not picked:
            # Last-resort: reuse scene 0's clip
            if results:
                picked = results[0]["asset"]
                print(f"[broll] scene {i}: falling back to scene 0 clip",
                      file=sys.stderr)
            else:
                raise RuntimeError(f"No clip found for scene {i}: {query!r}")

        results.append({"scene_index": i, "scene": scene, "asset": picked})

    return results
if __name__ == "__main__":
    kws = sys.argv[1:] or ["aerogel", "science laboratory"]
    try:
        clips = fetch_broll(kws, max_clips=3)
        for c in clips:
            print(f"- {c['source']:10} {c['license']:35} {c['path']}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)