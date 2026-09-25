"""
research.py — academic-grade research on a topic.

Sources (all keyless):
  - Wikipedia REST API   -> concept summary + full article sections
  - Wikipedia media-list -> images & videos attached to the article
  - arXiv API            -> recent papers with abstracts
  - OpenAlex API         -> high-citation works

Output:
{
  "topic": "...",
  "wikipedia_title": "...",
  "summary": "...",
  "sections": [{"title": "...", "text": "..."}],
  "key_facts": ["..."],
  "papers": [{"title": "...", "abstract": "...", "year": ..., "url": "..."}],
  "terms": ["..."]
}
"""
import re
import sys
import xml.etree.ElementTree as ET
from typing import Optional

import requests

UA = {"User-Agent": "ScienceShortsBot/1.0 (github.com/vk16online-hash)"}
TIMEOUT = 20


# -- Wikipedia ----------------------------------------------------
def _wiki_search(topic: str) -> Optional[str]:
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": topic,
                "format": "json",
                "srlimit": 1,
            },
            headers=UA, timeout=TIMEOUT,
        )
        r.raise_for_status()
        hits = r.json().get("query", {}).get("search", [])
        return hits[0]["title"] if hits else None
    except Exception as e:
        print(f"[research] wiki search failed: {e}", file=sys.stderr)
        return None


def _wiki_fetch(title: str) -> dict:
    out = {"summary": "", "sections": []}
    try:
        r = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/"
            f"{requests.utils.quote(title)}",
            headers=UA, timeout=TIMEOUT,
        )
        if r.status_code == 200:
            out["summary"] = r.json().get("extract", "")

        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "exsectionformat": "plain",
                "titles": title,
                "format": "json",
                "redirects": 1,
            },
            headers=UA, timeout=TIMEOUT,
        )
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        for _, page in pages.items():
            text = page.get("extract", "")
            if not text:
                continue
            parts = re.split(r"\n==+\s*([^=]+?)\s*==+\n", text)
            if parts:
                out["sections"].append(
                    {"title": "Introduction", "text": parts[0].strip()}
                )
            for i in range(1, len(parts) - 1, 2):
                stitle = parts[i].strip()
                sbody = parts[i + 1].strip()
                if stitle and sbody:
                    out["sections"].append(
                        {"title": stitle, "text": sbody[:2000]}
                    )
    except Exception as e:
        print(f"[research] wiki fetch failed: {e}", file=sys.stderr)
    return out


# -- arXiv --------------------------------------------------------
def _arxiv(topic: str, max_results: int = 5) -> list:
    try:
        r = requests.get(
            "http://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{topic}",
                "sortBy": "relevance",
                "sortOrder": "descending",
                "max_results": max_results,
            },
            headers=UA, timeout=TIMEOUT,
        )
        r.raise_for_status()
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.text)
        out = []
        for entry in root.findall("a:entry", ns):
            title_el = entry.find("a:title", ns)
            summary_el = entry.find("a:summary", ns)
            published_el = entry.find("a:published", ns)
            id_el = entry.find("a:id", ns)
            if title_el is None or summary_el is None:
                continue
            year = None
            if published_el is not None and published_el.text:
                year = int(published_el.text[:4])
            out.append({
                "title": " ".join(title_el.text.split()) if title_el.text else "",
                "abstract": " ".join(summary_el.text.split())[:800]
                            if summary_el.text else "",
                "year": year,
                "url": id_el.text if id_el is not None else "",
            })
        return out
    except Exception as e:
        print(f"[research] arxiv failed: {e}", file=sys.stderr)
        return []


# -- OpenAlex -----------------------------------------------------
def _openalex(topic: str, max_results: int = 5) -> list:
    try:
        r = requests.get(
            "https://api.openalex.org/works",
            params={
                "search": topic,
                "per-page": max_results,
                "sort": "cited_by_count:desc",
            },
            headers=UA, timeout=TIMEOUT,
        )
        r.raise_for_status()
        out = []
        for w in r.json().get("results", []):
            abstract = ""
            inv = w.get("abstract_inverted_index")
            if inv:
                positions = []
                for word, idxs in inv.items():
                    for i in idxs:
                        positions.append((i, word))
                positions.sort()
                abstract = " ".join(w for _, w in positions)
            out.append({
                "title": w.get("title", ""),
                "abstract": abstract[:800],
                "year": w.get("publication_year"),
                "citations": w.get("cited_by_count", 0),
                "url": w.get("doi", "") or w.get("id", ""),
            })
        return out
    except Exception as e:
        print(f"[research] openalex failed: {e}", file=sys.stderr)
        return []


# -- Fact & term extraction --------------------------------------
def _extract_key_facts(texts: list, limit: int = 12) -> list:
    markers = [
        "most", "only", "never", "always", "first", "last",
        "smallest", "largest", "fastest", "slowest", "strongest",
        "weaker", "stronger", "unlike", "surprisingly", "actually",
        "however", "but", "discovered", "invented",
    ]
    facts = []
    seen = set()
    for text in texts:
        for sent in re.split(r"(?<=[.!?])\s+", text):
            s = sent.strip()
            if len(s) < 40 or len(s) > 260:
                continue
            lower = s.lower()
            score = 0
            if re.search(r"\d", s):
                score += 2
            if any(m in lower for m in markers):
                score += 1
            if score >= 2:
                key = s[:80].lower()
                if key not in seen:
                    seen.add(key)
                    facts.append({"text": s, "score": score})
    facts.sort(key=lambda f: -f["score"])
    return [f["text"] for f in facts[:limit]]


def _extract_terms(texts: list, limit: int = 15) -> list:
    counts = {}
    for text in texts:
        for term in re.findall(
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text
        ):
            counts[term] = counts.get(term, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [t for t, c in ranked[:limit] if c >= 2]


# -- Public API ---------------------------------------------------
def research_topic(topic: str) -> dict:
    print(f"[research] researching: {topic}", file=sys.stderr)

    title = _wiki_search(topic)
    wiki = _wiki_fetch(title) if title else {"summary": "", "sections": []}

    papers = _arxiv(topic, 4) + _openalex(topic, 4)
    seen, deduped = set(), []
    for p in papers:
        key = (p.get("title") or "").lower()[:60]
        if key and key not in seen:
            seen.add(key)
            deduped.append(p)

    all_text = [
        wiki.get("summary", ""),
        *[s["text"] for s in wiki.get("sections", [])],
        *[p.get("abstract", "") for p in deduped],
    ]

    result = {
        "topic": topic,
        "wikipedia_title": title,
        "summary": wiki.get("summary", ""),
        "sections": wiki.get("sections", [])[:6],
        "key_facts": _extract_key_facts(all_text),
        "papers": deduped[:6],
        "terms": _extract_terms(all_text),
    }

    print(
        f"[research] summary: {len(result['summary'])} chars, "
        f"sections: {len(result['sections'])}, "
        f"papers: {len(result['papers'])}, "
        f"facts: {len(result['key_facts'])}",
        file=sys.stderr,
    )
    return result


if __name__ == "__main__":
    import json
    topic = " ".join(sys.argv[1:]) or "aerogel"
    result = research_topic(topic)
    print(json.dumps(result, indent=2, ensure_ascii=False)[:4000])