"""
captions.py — word-level captions from audio.

Pipeline:
  1. faster-whisper transcribes the MP3 with word timestamps
  2. Groups words into 2-3 word chunks
  3. Writes a styled .ass subtitle file for FFmpeg burn-in

Style: bold white text, black outline, active chunk highlighted gold.
"""
import sys
from pathlib import Path

from faster_whisper import WhisperModel

_MODEL = None

# ── Style knobs ─────────────────────────────────────────────────
FONT_NAME = "Montserrat"     # falls back to Arial if not installed
FONT_SIZE = 90               # smaller than 120 for 2-line captions
PRIMARY_COLOR = "&H00FFFFFF" # white (BGR order in ASS)
HIGHLIGHT_COLOR = "&H0000D4FF"  # gold/amber
OUTLINE_COLOR = "&H00000000" # black
OUTLINE_WIDTH = 6
SHADOW = 0
CHUNK_SIZE = 3               # words per caption
MARGIN_V = 420               # vertical position from bottom (of 1920)


def _model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        print("[captions] loading whisper base model...", file=sys.stderr)
        _MODEL = WhisperModel("base", device="cpu", compute_type="int8")
    return _MODEL


# ── Transcription ───────────────────────────────────────────────
def transcribe_words(audio_path: str) -> list:
    """Returns list of {word, start, end} dicts with word timestamps."""
    segments, info = _model().transcribe(
        audio_path,
        word_timestamps=True,
        vad_filter=True,
    )
    words = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if not text:
                continue
            words.append({
                "word": text,
                "start": float(w.start),
                "end": float(w.end),
            })
    if not words:
        raise RuntimeError(f"whisper returned no words for {audio_path}")
    return words


# ── ASS generation ──────────────────────────────────────────────
def _fmt_time(seconds: float) -> str:
    """ASS timestamp: H:MM:SS.cc (centiseconds)."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_header() -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOR},{HIGHLIGHT_COLOR},{OUTLINE_COLOR},&H80000000,-1,0,0,0,100,100,0,0,1,{OUTLINE_WIDTH},{SHADOW},2,80,80,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(words: list, out_path: str = "output/captions.ass",
              chunk_size: int = CHUNK_SIZE) -> Path:
    """Write an ASS subtitle file with word-grouped captions."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [_ass_header()]

    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        if not chunk:
            continue

        start = chunk[0]["start"]
        end = chunk[-1]["end"]

        # Slight overlap into next chunk for smoother flow
        display_end = end + 0.08

        text = " ".join(w["word"] for w in chunk)

        # Force uppercase for Shorts aesthetic; highlight the whole chunk
        text_upper = text.upper()

        # Escape ASS special characters
        text_upper = text_upper.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

        # Yellow highlight applied to whole chunk; white default
        styled = (
            f"{{\\c{HIGHLIGHT_COLOR}\\b1}}{text_upper}"
            f"{{\\c{PRIMARY_COLOR}\\b1}}"
        )

        lines.append(
            f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(display_end)},"
            f"Default,,0,0,0,,{styled}"
        )

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[captions] wrote {out} ({len(lines) - 2} chunks)", file=sys.stderr)
    return out


# ── Public API ──────────────────────────────────────────────────
def generate_captions(audio_path: str, out_path: str = "output/captions.ass") -> Path:
    words = transcribe_words(audio_path)
    print(f"[captions] transcribed {len(words)} words", file=sys.stderr)
    return build_ass(words, out_path)


if __name__ == "__main__":
    audio = sys.argv[1] if len(sys.argv) > 1 else "output/voice.mp3"
    result = generate_captions(audio)
    print(result)
