"""
topic_research.py — picks a fresh science/tech/engineering topic.
Chain: Gemini → Groq → Pollinations (keyless) → hardcoded fallback.
"""
import json
import os
import random
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

REPO = Path(__file__).resolve().parent.parent
HISTORY_FILE = REPO / "state" / "history.json"

FALLBACK_TOPICS = [
    "How CRISPR actually edits DNA",
    "Why quantum computers need near-absolute zero",
    "The engineering behind the James Webb sunshield",
    "How neural networks learn via backpropagation",
    "Why the Falcon 9 can land itself",
    "What fusion ignition actually proved",
    "How mRNA vaccines trick your cells",
    "The physics of a black hole's event horizon",
    "How solid-state batteries work",
    "Why Moore's Law is ending",
    "How GPS satellites correct for relativity",
    "The engineering of the Burj Khalifa's foundation",
]


def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except json.JSONDecodeError:
        return []


def _build_prompt(covered: list) -> str:
    covered_str = json.dumps(covered[-40:], indent=0) if covered else "[]"
    return (
        "You are the editorial brain of a YouTube Shorts channel about "
        "science, technology, and engineering.\n\n"
        f"Already covered (do NOT repeat, even paraphrased):\n{covered_str}\n\n"
        "Propose ONE new topic. Rules:\n"
        "- Max 12 words\n"
        "- Must have a clear visual hook\n"
        "- Must be a single crisp concept\n"
        "- Must appeal to a general audience\n"
        "Return ONLY the topic as one line. No quotes. No explanation."
    )


def _clean_topic(text: str) -> str:
    return text.strip().strip('"').strip("'").split("\n")[0].strip()


def _call_gemini(prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-3.6-flash")
    return model.generate_content(prompt).text


def _call_groq(prompt: str) -> str:
    key = os.environ["GROQ_API_KEY"]
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
        },
        timeout=40,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_pollinations(prompt: str) -> str:
    r = requests.get(
        "https://text.pollinations.ai/" + requests.utils.quote(prompt),
        timeout=45,
    )
    r.raise_for_status()
    return r.text


def pick_topic() -> str:
    history = load_history()
    covered = [h["topic"] if isinstance(h, dict) else h for h in history]
    prompt = _build_prompt(covered)

    for caller, name in [
        (_call_gemini, "gemini"),
        (_call_groq, "groq"),
        (_call_pollinations, "pollinations"),
    ]:
        try:
            topic = _clean_topic(caller(prompt))
            if len(topic) < 5:
                raise ValueError(f"topic too short: {topic!r}")
            if topic.lower() in (c.lower() for c in covered):
                raise ValueError(f"duplicate topic: {topic!r}")
            print(f"[topic_research] picked via {name}: {topic}", file=sys.stderr)
            return topic
        except Exception as e:
            print(f"[topic_research] {name} failed: {e}", file=sys.stderr)

    pool = [t for t in FALLBACK_TOPICS
            if t.lower() not in (c.lower() for c in covered)]
    topic = random.choice(pool) if pool else FALLBACK_TOPICS[0]
    print(f"[topic_research] fallback pool: {topic}", file=sys.stderr)
    return topic


if __name__ == "__main__":
    print(pick_topic())