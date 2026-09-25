"""
assets.py — topic-specific image & video extraction.

Layers (in priority order):
  1. Wikipedia media-list API   -> images/videos attached to the article
  2. arXiv source tarball       -> figures inside the paper package
  3. Stock sites (Pexels/Pixabay) -> fallback for abstract concepts

Keyless for layers 1-2. Layer 3 needs PEXELS_API_KEY / PIXABAY_API_KEY.
"""
import io
import os
import re
import sys
import tarfile
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

import requests

UA = {"User-Agent": "ScienceShortsBot/1.0 (github.com/vk16online-hash)"}
TIMEOUT = 30
ASSETS_DIR = Path("assets/scene_assets")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_str(x) -> str:
    """Convert Wikipedia-style dict captions or None safely to string."""
    if x is None:
        return ""
    if isinstance(x, dict):
        return (x.get("text") or x.get("html") or "").strip()
    return str(x)


# ============================================================
# LAYER 1: WIKIPEDIA MEDIA
# ============================================================
def _wiki_media_list(title: str) -> list:
    """Return all images/videos attached to a Wikipedia article."""
    if not title:
        return []
    try:
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/media-list/"
            + urllib.parse.quote(title),
            headers=UA, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        out = []
        for item in items:
            if item.get("type") not in ("image", "video"):
                continue
            srcset = item.get("srcset", [])
            if not srcset:
                continue
            best = max(srcset, key=lambda s: int(s.get("width") or 0))
            src = best.get("src", "")
            if src.startswith("//"):
                src = "https:" + src
            if not src:
                continue
            out.append({
                "url": src,
                "title": _safe_str(item.get("title"))[:200],
                "caption": _safe_str(item.get("caption"))[:200],
                "type": item.get("type"),
                "width": int(best.get("width") or 0),
                "height": int(best.get("height") or 0),
                "source": "wikipedia",
                "license": "CC / Wikipedia (see source)",
            })
        return out
    except Exception as e:
        print(f"[assets] wiki media-list failed: {e}", file=sys.stderr)
        return []


# ============================================================
# LAYER 2: ARXIV SOURCE FIGURES
# ============================================================
def _arxiv_id_from_url(url: str):
    m = re.search(r"arxiv\.org/abs/([0-9.]+(?:v\d+)?)", url or "")
    return m.group(1) if m else None


def _arxiv_source_figures(arxiv_id: str) -> list:
    """Download arXiv source package and extract PNG/JPG figures."""
    if not arxiv_id:
        return []
    try:
        r = requests.get(
            f"https://arxiv.org/e-print/{arxiv_id}",
            headers=UA, timeout=60, stream=True,
        )
        if r.status_code != 200:
            return []
        data = r.content
        if len(data) < 1000 or len(data) > 50_000_000:
            return []

        figures = []
        with tempfile.TemporaryDirectory() as td:
            try:
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
                    for member in tar.getmembers():
                        if not member.isfile():
                            continue
                        name_lower = member.name.lower()
                        if not name_lower.endswith((".png", ".jpg", ".jpeg")):
                            continue
                        if member.size < 20_000 or member.size > 5_000_000:
                            continue
                        f = tar.extractfile(member)
                        if not f:
                            continue
                        dest = Path(td) / Path(member.name).name
                        dest.write_bytes(f.read())
                        figures.append({
                            "url": f"arxiv://{arxiv_id}/{member.name}",
                            "path": str(dest),
                            "filename": member.name,
                            "source": "arxiv_source",
                            "type": "image",
                            "license": "arXiv (author copyright)",
                            "arxiv_id": arxiv_id,
                            "width": 0,
                            "height": 0,
                        })
            except Exception:
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        for name in z.namelist():
                            name_lower = name.lower()
                            if not name_lower.endswith((".png", ".jpg", ".jpeg")):
                                continue
                            info = z.getinfo(name)
                            if info.file_size < 20_000 or info.file_size > 5_000_000:
                                continue
                            dest = Path(td) / Path(name).name
                            dest.write_bytes(z.read(name))
                            figures.append({
                                "url": f"arxiv://{arxiv_id}/{name}",
                                "path": str(dest),
                                "filename": name,
                                "source": "arxiv_source",
                                "type": "image",
                                "license": "arXiv (author copyright)",
                                "arxiv_id": arxiv_id,
                                "width": 0,
                                "height": 0,
                            })
                except Exception:
                    pass
        return figures
    except Exception as e:
        print(f"[assets] arxiv source failed: {e}", file=sys.stderr)
        return []


# ============================================================
# LAYER 3: STOCK FALLBACK
# ============================================================
def _pexels_photos(query: str, per_page: int = 5) -> list:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": "portrait",
                    "per_page": per_page},
            headers={"Authorization": key, **UA},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        out = []
        for p in r.json().get("photos", []):
            src = p.get("src", {})
            url = src.get("large2x") or src.get("large") or src.get("original")
            if not url:
                continue
            out.append({
                "url": url,
                "caption": p.get("alt", ""),
                "source": "pexels",
                "type": "image",
                "width": int(p.get("width") or 0),
                "height": int(p.get("height") or 0),
                "license": "Pexels License (free commercial use)",
            })
        return out
    except Exception as e:
        print(f"[assets] pexels failed: {e}", file=sys.stderr)
        return []


def _pexels_videos(query: str, per_page: int = 3) -> list:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": "portrait",
                    "per_page": per_page, "size": "medium"},
            headers={"Authorization": key, **UA},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        out = []
        for v in r.json().get("videos", []):
            files = v.get("video_files", [])
            files.sort(key=lambda f: (
                0 if int(f.get("width") or 0) >= 1080 else 1,
                abs(int(f.get("width") or 0) - 1080),
            ))
            for f in files:
                link = f.get("link")
                if link and link.endswith(".mp4"):
                    out.append({
                        "url": link,
                        "caption": "",
                        "source": "pexels",
                        "type": "video",
                        "width": int(f.get("width") or 0),
                        "height": int(f.get("height") or 0),
                        "license": "Pexels License (free commercial use)",
                    })
                    break
        return out
    except Exception as e:
        print(f"[assets] pexels videos failed: {e}", file=sys.stderr)
        return []


def _pixabay(query: str, per_page: int = 5) -> list:
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        return []
    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": key,
                "q": query,
                "image_type": "photo",
                "orientation": "vertical",
                "per_page": per_page,
                "safesearch": "true",
            },
            headers=UA, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        out = []
        for hit in r.json().get("hits", []):
            url = hit.get("largeImageURL") or hit.get("webformatURL")
            if not url:
                continue
            out.append({
                "url": url,
                "caption": hit.get("tags", ""),
                "source": "pixabay",
                "type": "image",
                "width": int(hit.get("imageWidth") or 0),
                "height": int(hit.get("imageHeight") or 0),
                "license": "Pixabay License (free commercial use)",
            })
        return out
    except Exception as e:
        print(f"[assets] pixabay failed: {e}", file=sys.stderr)
        return []


# ============================================================
# SCORING
# ============================================================
def _score_candidate(c: dict, scene_keywords: list) -> float:
    score = 0.0
    text = (_safe_str(c.get("caption")) + " " + _safe_str(c.get("filename"))).lower()
    for kw in scene_keywords:
        if kw and kw.lower() in text:
            score += 3.0
    w = int(c.get("width") or 0)
    h = int(c.get("height") or 0)
    if w and h:
        short = min(w, h)
        if short >= 1080:
            score += 2.0
        elif short >= 720:
            score += 1.0
    src = c.get("source", "")
    if src == "wikipedia":
        score += 1.5
    elif src == "arxiv_source":
        score += 1.0
    elif src in ("pexels", "pixabay"):
        score += 0.5
    if c.get("type") == "video":
        score += 0.5
    return score


# ============================================================
# DOWNLOAD
# ============================================================
def _download_asset(c: dict, idx: int) -> dict:
    try:
        if c.get("source") == "arxiv_source" and c.get("path"):
            src_path = Path(c["path"])
            if not src_path.exists():
                return None
            dest = ASSETS_DIR / f"scene_{idx}_{src_path.name}"
            dest.write_bytes(src_path.read_bytes())
            c["path"] = str(dest)
            return c

        r = requests.get(c["url"], headers=UA, timeout=120, stream=True)
        r.raise_for_status()
        url_path = urllib.parse.urlparse(c["url"]).path
        ext = Path(url_path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm"):
            ext = ".mp4" if c.get("type") == "video" else ".jpg"
        path = ASSETS_DIR / f"scene_{idx}_{abs(hash(c['url'])) % 10**10}{ext}"
        written = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                written += len(chunk)
                if written > 30 * 1024 * 1024:
                    f.close()
                    path.unlink(missing_ok=True)
                    return None
                f.write(chunk)
        if path.stat().st_size < 10_000:
            path.unlink(missing_ok=True)
            return None
        c["path"] = str(path)
        return c
    except Exception as e:
        print(f"[assets] download failed: {e}", file=sys.stderr)
        return None


# ============================================================
# PUBLIC API
# ============================================================
def gather_candidates(research: dict, scene_keywords: list) -> list:
    candidates = []

    wiki_title = research.get("wikipedia_title")
    wiki_media = _wiki_media_list(wiki_title)
    candidates.extend(wiki_media[:20])

    for paper in research.get("papers", [])[:3]:
        arxiv_id = _arxiv_id_from_url(paper.get("url", ""))
        if arxiv_id:
            figs = _arxiv_source_figures(arxiv_id)
            candidates.extend(figs[:6])

    if len(candidates) < 5:
        for kw in scene_keywords[:3]:
            candidates.extend(_pexels_photos(kw, 3))
            candidates.extend(_pixabay(kw, 3))
            candidates.extend(_pexels_videos(kw, 2))

    for c in candidates:
        c["score"] = _score_candidate(c, scene_keywords)
    candidates.sort(key=lambda c: -c["score"])
    return candidates


def fetch_best_asset(research: dict, scene: dict, used_urls: set):
    keywords = list(scene.get("broll_queries", []) or [])
    if scene.get("keyword"):
        keywords.append(scene["keyword"])
    keywords = [k for k in keywords if k]
    keywords.extend(research.get("terms", [])[:5])

    candidates = gather_candidates(research, keywords)

    for c in candidates:
        if c["url"] in used_urls:
            continue
        if c["score"] < 0.5:
            continue
        downloaded = _download_asset(c, len(used_urls))
        if downloaded:
            used_urls.add(c["url"])
            label = (c.get("filename") or c.get("title")
                     or c.get("caption") or "")[:60]
            print(
                f"[assets] picked {c['source']} "
                f"(score {c['score']:.1f}, {c.get('type','image')}): {label}",
                file=sys.stderr,
            )
            return downloaded
    return None


if __name__ == "__main__":
    from research import research_topic
    topic = " ".join(sys.argv[1:]) or "Large Hadron Collider"
    r = research_topic(topic)
    cands = gather_candidates(r, ["detector", "particle collision", "CERN"])
    print(f"\nTotal candidates: {len(cands)}")
    for c in cands[:20]:
        label = (c.get("filename") or c.get("title")
                 or c.get("caption") or "")[:65]
        print(f"  {c['source']:15} score={c['score']:.1f} "
              f"{c.get('type','image'):6} {label}")