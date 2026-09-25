"""
tts.py — voiceover MP3 from script text, using Edge-TTS.
Neural voices, keyless, unlimited. Slightly sped up for Shorts pacing.
"""
import asyncio
import sys
from pathlib import Path

import edge_tts

VOICE = "en-US-AriaNeural"   # alternatives: en-US-GuyNeural, en-GB-RyanNeural
RATE = "+8%"                  # slightly faster than conversational
PITCH = "+2Hz"


def synthesize(text: str, out_path: str = "output/voice.mp3") -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    async def _run():
        comm = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
        await comm.save(str(out))

    asyncio.run(_run())

    if not out.exists() or out.stat().st_size < 2000:
        raise RuntimeError(f"edge-tts produced empty or tiny file: {out}")

    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = ("This is a test of the voice synthesis pipeline. "
                "If you can hear this clearly, everything works.")

    path = synthesize(text)
    size_kb = path.stat().st_size / 1024
    print(f"[tts] wrote {path} ({size_kb:.1f} KB)")