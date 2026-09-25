"""
script_gen.py — topic + research -> structured Short script with scenes.

Input:  topic (str), research (dict from research.py)
Output:
{
  "title":      "...",
  "hashtags":   [...],
  "description":"...",
  "hook":       "...",
  "cta":        "...",
  "scenes": [
     {"text": "...",
      "broll_queries": ["specific 1", "specific 2", "broad 3"],
      "keyword": "ONE WORD"},
     ...
  ]
}
"""
import json
import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

SYSTEM = (
    "You are a veteran science communicator writing YouTube Shorts. "
    "You split scripts into 4-6 SCENES, each with a specific visual. "
    "Respond with ONE valid JSON object, nothing else."
)

PROMPT = """Topic: {topic}

RESEARCH CONTEXT (authoritative facts — use only these for accuracy):

SUMMARY:
{summary}

KEY FACTS:
{facts}

TECHNICAL TERMS (use sparingly, explain any you use):
{terms}

Write a ~45-second YouTube Short, split into 4-6 SCENES.

RULES:
- Total narration: 95-135 words
- Scene 1 is a killer hook (<=14 words, startling fact or question)
- Each scene: 18-32 words of narration
- Every scene describes ONE concrete visual moment
- Every scene must have a DIFFERENT visual (no repeats)
- keyword: ONE WORD in CAPS that captures the scene's punch
- broll_queries: a LADDER of 3 visual search phrases for this scene:
    1. SPECIFIC  (ex: "liquid metal droplets macro slow motion")
    2. ADJACENT  (ex: "silver liquid flowing close up")
    3. BROAD     (ex: "metal surface texture")
  Prefer queries that would find real footage on Wikipedia/arXiv/Pexels
- Last scene ends with a short CTA

RETURN EXACTLY THIS JSON (no markdown, no commentary):

{{
  "title":       "<YouTube title <=60 chars, ends with #Shorts>",
  "hashtags":    ["#science", "#tech", "#engineering", "#<topic-specific>", "#shorts"],
  "description": "<2 sentences, factual, no fluff>",
  "hook":        "<hook sentence alone>",
  "cta":         "<CTA sentence alone>",
  "scenes": [
    {{
      "text":          "<narration>",
      "broll_queries": ["<specific>", "<adjacent>", "<broad>"],
      "keyword":       "CAPS"
    }}
  ]
}}"""


def _clean_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip("` \n")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON found: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def _call_gemini(prompt: str) -> str:
    import concurrent.futures
    import google.generativeai as genai

    def _do():
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel("gemini-3.6-flash")
        return model.generate_content(prompt).text

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_do).result(timeout=50)


def _call_groq(prompt: str) -> str:
    key = os.environ["GROQ_API_KEY"]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.85,
            "response_format": {"type": "json_object"},
        },
        timeout=45,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_pollinations(prompt: str) -> str:
    r = requests.post(
        "https://text.pollinations.ai/openai",
        json={
            "model": "openai",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _validate(data: dict) -> None:
    required = {"title", "hashtags", "description", "scenes"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"missing top-level keys: {missing}")
    scenes = data["scenes"]
    if not isinstance(scenes, list) or not (3 <= len(scenes) <= 8):
        raise ValueError(f"scenes must be 3-8 items, got {len(scenes)}")
    for s in scenes:
        if "text" not in s or "broll_queries" not in s:
            raise ValueError(f"scene missing text/broll_queries: {s}")
        if not isinstance(s["broll_queries"], list) or not s["broll_queries"]:
            # heal by deriving from text
            s["broll_queries"] = [s["text"][:40]]
        if "keyword" not in s:
            s["keyword"] = ""
    total = " ".join(s["text"] for s in scenes)
    wc = len(total.split())
    if not (70 <= wc <= 190):
        raise ValueError(f"script length {wc} words out of range")


def _fallback(topic: str, research: dict) -> dict:
    facts = research.get("key_facts", [])[:4] or [f"Fact about {topic}."]
    scenes = []
    for i, fact in enumerate(facts):
        scenes.append({
            "text": fact[:160],
            "broll_queries": [topic, f"{topic} close up", "science laboratory"],
            "keyword": f"FACT {i+1}",
        })
    scenes.append({
        "text": "Follow for more science shorts.",
        "broll_queries": ["space galaxy", "science abstract", "dark background"],
        "keyword": "FOLLOW",
    })
    return {
        "title": f"{topic[:50]} #Shorts",
        "hashtags": ["#science", "#tech", "#engineering", "#shorts"],
        "description": f"A 45-second breakdown of {topic}.",
        "hook": scenes[0]["text"],
        "cta": "Follow for more science shorts.",
        "scenes": scenes,
    }


def generate_script(topic: str, research: dict | None = None, attempts: int = 2) -> dict:
    research = research or {}
    summary = (research.get("summary") or "")[:1500]
    facts = research.get("key_facts", [])[:8]
    facts_str = "\n".join(f"- {f}" for f in facts) or "(none extracted)"
    terms = ", ".join(research.get("terms", [])[:10]) or "(none)"

    prompt = PROMPT.format(
        topic=topic,
        summary=summary,
        facts=facts_str,
        terms=terms,
    )

    callers = [
        (_call_gemini, "gemini"),
        (_call_groq, "groq"),
        (_call_pollinations, "pollinations"),
    ]

    for _ in range(attempts):
        for caller, name in callers:
            try:
                raw = caller(prompt)
                data = _clean_json(raw)
                _validate(data)
                print(f"[script_gen] generated via {name}", file=sys.stderr)
                return data
            except Exception as e:
                print(f"[script_gen] {name} failed: {e}", file=sys.stderr)

    print("[script_gen] all LLMs failed — using template fallback", file=sys.stderr)
    return _fallback(topic, research)


def narration_text(script: dict) -> str:
    return " ".join(s["text"] for s in script["scenes"])


if __name__ == "__main__":
    import sys as _sys
    _sys.path.insert(0, "scripts")
    from research import research_topic
    topic = " ".join(_sys.argv[1:]) or "Large Hadron Collider"
    print(f"[script_gen] researching: {topic}", file=sys.stderr)
    research = research_topic(topic)
    result = generate_script(topic, research)
    print(json.dumps(result, indent=2, ensure_ascii=False))