"""
scene_align.py — aligns each scene's narration to its time range in the audio.

Uses word timestamps from captions.transcribe_words() to find the
start of the first word and the end of the last word of each scene.
"""
from captions import transcribe_words


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for matching."""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s']", "", text)
    return re.sub(r"\s+", " ", text).strip()


def align_scenes(scenes: list, audio_path: str) -> list:
    """
    Returns the same scenes with .start/.end (seconds) added.
    """
    words = transcribe_words(audio_path)
    norm_words = [_normalize(w["word"]) for w in words]

    aligned = []
    cursor = 0

    for idx, scene in enumerate(scenes):
        target_words = _normalize(scene["text"]).split()
        target_len = len(target_words)

        if cursor + target_len > len(words):
            # Not enough words left — assign remaining time to this scene
            start = words[cursor]["start"] if cursor < len(words) else words[-1]["end"]
            end = words[-1]["end"]
        else:
            start = words[cursor]["start"]
            end = words[cursor + target_len - 1]["end"]
            cursor += target_len

        aligned.append({
            **scene,
            "start": float(start),
            "end": float(end),
        })

    return aligned


if __name__ == "__main__":
    import json
    import sys

    audio = sys.argv[1] if len(sys.argv) > 1 else "output/voice.mp3"
    # Read scenes from stdin (JSON) for quick testing
    script = json.loads(sys.stdin.read())
    aligned = align_scenes(script["scenes"], audio)
    for i, s in enumerate(aligned):
        print(f"scene {i}: {s['start']:.2f}s – {s['end']:.2f}s  |  {s['text'][:60]}")