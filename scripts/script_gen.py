"""
script_gen.py — topic → structured Short with per-scene b-roll queries.

Output shape:
{
  "title":      "...",
  "hashtags":   [...],
  "description":"...",
  "hook":       "...",
  "cta":        "...",
  "scenes": [
     {"text": "narration", "broll_query": "3-5 word search", "keyword": "ONE WORD"},
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
    "You split scripts into 4–6 SCENES, each matched to one strong visual. "
    "Respond with a single valid JSON object, nothing else."
)

PROMPT = """Topic: {topic}

Write a ~45-second YouTube Short, split into 4–6 SCENES.

Rules:
- Total narration: 90–130 words across all scenes
- Scene 1 must be a killer hook (<=14 words)
- Each scene: 15–30 words of narration
- Every scene must have a DIFFERENT b-roll visual
- Give a single ONE-WORD keyword per scene for a text pop-up
- broll_query: 3–5 words, concrete and filmable (what you'd type into a stock site)
- Last scene ends with a short CTA

Return EXACTLY this JSON shape:

{{
  "title":       "<YouTube title <=60 chars, ends with #Shorts>",
  "hashtags":    ["#science", "#tech", "#engineering", "#<topic>", "#shorts"],
  "description": "<2 sentences>",
  "hook":        "<the hook sentence on its own>",
  "cta":         "<the CTA sentence on its own>",
  "scenes": [
    {{
      "text":        "<narration for this scene>",
      "broll_query": "<3–5 word visual search>",
      "keyword":     "<ONE WORD pop-up>"
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
        return pool.submit(_do).result(timeout=45)


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
        raise ValueError(f"missing keys: {missing}")
    scenes = data["scenes"]
    if not isinstance(scenes, list) or not (3 <= len(scenes) <= 8):
        raise ValueError(f"scenes must be 3-8 items, got {len(scenes)}")
    for s in scenes:
        if not all(k in s for k in ("text", "broll_query", "keyword")):
            raise ValueError(f"scene missing keys: {s}")
    total = " ".join(s["text"] for s in scenes)
    wc = len(total.split())
    if not (70 <= wc <= 180):
        raise ValueError(f"script length {wc} words out of range")


def _fallback(topic: str) -> dict:
    return {
        "title": f"{topic[:50]} #Shorts",
        "hashtags": ["#science", "#tech", "#engineering", "#shorts"],
        "description": f"A 45-second breakdown of {topic}.",
        "hook": f"Here's what nobody tells you about {topic}.",
        "cta": "Follow for more.",
        "scenes": [
            {"text": f"Here's what nobody tells you about {topic}.",
             "broll_query": f"{topic} closeup",
             "keyword": "WAIT"},
            {"text": "The core idea is subtle but once you see it, you can't unsee it.",
             "broll_query": "science laboratory research",
             "keyword": "SCIENCE"},
            {"text": "Engineers spent decades refining this.",
             "broll_query": "engineering machinery working",
             "keyword": "DECADES"},
            {"text": "Follow for more science shorts.",
             "broll_query": "space galaxy nebula",
             "keyword": "FOLLOW"},
        ],
    }


def generate_script(topic: str, attempts: int = 2) -> dict:
    prompt = PROMPT.format(topic=topic)
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
    return _fallback(topic)


def narration_text(script: dict) -> str:
    """Full narration as one string for TTS."""
    return " ".join(s["text"] for s in script["scenes"])


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "How aerogel works"
    result = generate_script(topic)
    print(json.dumps(result, indent=2, ensure_ascii=False))