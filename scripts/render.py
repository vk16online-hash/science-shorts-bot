"""
render.py — pro-grade YouTube Short assembly.

Features:
  - Ken Burns motion on every clip (varying zoom/pan per scene)
  - xfade transitions between scenes (varied: fade/slide/wipe)
  - Cinematic color grading (film contrast curve)
  - Subtle vignette
  - Burns ASS captions on top
  - Mixed audio: narration + optional bed

Usage:
  python scripts/render.py <audio.mp3> <captions.ass> <out.mp4> <scene_start> <scene_end> <clip> [...]
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
W, H = 1080, 1920
FPS = 30
XFADE_DUR = 0.4

# Ken Burns variants — cycled by scene index for visual variety
KB_EFFECTS = [
    "zoompan=z='min(zoom+0.0008,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}",
    "zoompan=z='if(eq(on,1),1.12,max(zoom-0.0008,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}",
    "zoompan=z='min(zoom+0.0006,1.10)':x='0':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}",
    "zoompan=z='min(zoom+0.0006,1.10)':x='iw-(iw/zoom)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}",
]

# xfade transitions — cycled by scene index
XFADE_TRANSITIONS = ["fade", "slideleft", "wipeleft", "fadeblack", "smoothleft"]


def _run(cmd, cwd=None):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed:\n  {' '.join(str(c) for c in cmd)}\n"
            f"stderr tail:\n{result.stderr[-2500:]}"
        )
    return result


def probe_duration(path) -> float:
    r = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    return float(r.stdout.strip())


def _rel(p) -> str:
    abs_p = Path(p).resolve()
    try:
        return abs_p.relative_to(REPO).as_posix()
    except ValueError:
        return abs_p.as_posix()


def _prep_clip(src, dst, duration: float, kb_idx: int):
    """Trim/loop source to duration and apply Ken Burns + color grade + vignette."""
    kb = KB_EFFECTS[kb_idx % len(KB_EFFECTS)].format(W=W, H=H, FPS=FPS)
    vf = (
        f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
        f"crop={W * 2}:{H * 2},"
        f"{kb},"
        f"curves=preset=medium_contrast,"
        f"eq=saturation=1.12:brightness=0.01,"
        f"vignette=PI/5,"
        f"format=yuv420p"
    )
    _run([
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-r", str(FPS),
        str(dst),
    ])


def render(scenes, audio, ass, out_path="output/final.mp4"):
    """
    scenes: list of dicts with keys 'clip', 'start', 'end'
    audio:  voiceover MP3 path
    ass:    captions ASS path
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    audio_dur = probe_duration(audio)
    print(f"[render] voiceover: {audio_dur:.2f}s across {len(scenes)} scenes",
          file=sys.stderr)

    # Compute each scene's display duration. Overlap by XFADE_DUR for the transition.
    segs = []
    for i, s in enumerate(scenes):
        start = float(s["start"])
        end = float(s["end"])
        dur = max(1.0, end - start)
        if i < len(scenes) - 1:
            dur += XFADE_DUR   # extra for the crossfade into next
        segs.append({**s, "dur": dur})

    # Last scene extends to audio end if needed
    total_visible = sum(s["dur"] for s in segs) - XFADE_DUR * (len(segs) - 1)
    if total_visible < audio_dur:
        segs[-1]["dur"] += (audio_dur - total_visible)

    with tempfile.TemporaryDirectory(prefix="shorts_render_") as td:
        workdir = Path(td)

        # 1. Prepare each clip with motion + grade
        prepared = []
        for i, s in enumerate(segs):
            dst = workdir / f"prep_{i}.mp4"
            print(f"[render] prep {i + 1}/{len(segs)} ({s['dur']:.2f}s): "
                  f"{Path(s['clip']).name}", file=sys.stderr)
            _prep_clip(s["clip"], dst, s["dur"], kb_idx=i)
            prepared.append(dst)

        # 2. Build filter_complex with xfade chain
        if len(prepared) == 1:
            # single-clip case — no xfade
            inputs = ["-i", str(prepared[0])]
            fc = (
                f"[0:v]trim=duration={audio_dur:.3f},setpts=PTS-STARTPTS,"
                f"ass={_rel(ass)}[vout]"
            )
            vout_label = "[vout]"
        else:
            inputs = []
            for p in prepared:
                inputs += ["-i", str(p)]

            parts = []
            # First chain: xfade 0↔1
            offset = segs[0]["dur"] - XFADE_DUR
            trans = XFADE_TRANSITIONS[0 % len(XFADE_TRANSITIONS)]
            parts.append(
                f"[0:v][1:v]xfade=transition={trans}:duration={XFADE_DUR}:"
                f"offset={offset:.3f}[v01]"
            )
            last = "[v01]"
            cumulative = segs[0]["dur"] + segs[1]["dur"] - 2 * XFADE_DUR

            for i in range(2, len(prepared)):
                offset = cumulative
                trans = XFADE_TRANSITIONS[i % len(XFADE_TRANSITIONS)]
                out_label = f"[v{i:02d}]"
                parts.append(
                    f"{last}[{i}:v]xfade=transition={trans}:"
                    f"duration={XFADE_DUR}:offset={offset:.3f}{out_label}"
                )
                last = out_label
                cumulative += segs[i]["dur"] - XFADE_DUR

            parts.append(
                f"{last}trim=duration={audio_dur:.3f},setpts=PTS-STARTPTS,"
                f"ass={_rel(ass)}[vout]"
            )
            fc = ";".join(parts)
            vout_label = "[vout]"

        audio_input_idx = len(prepared)
        inputs += ["-i", str(audio)]

        cmd = (
            ["ffmpeg", "-y"] + inputs +
            ["-filter_complex", fc,
             "-map", vout_label,
             "-map", f"{audio_input_idx}:a",
             "-t", f"{audio_dur:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p",
             "-movflags", "+faststart",
             "-c:a", "aac", "-b:a", "192k",
             "-shortest",
             _rel(out)]
        )
        _run(cmd, cwd=REPO)

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"[render] wrote {out} ({size_mb:.1f} MB)", file=sys.stderr)
    return out


if __name__ == "__main__":
    # Quick CLI test using equally-spaced scenes
    if len(sys.argv) < 5:
        print("usage: render.py <audio> <ass> <out> <clip1> <clip2> [...]",
              file=sys.stderr)
        sys.exit(1)

    audio = sys.argv[1]
    ass = sys.argv[2]
    out = sys.argv[3]
    clips = sys.argv[4:]

    audio_dur = probe_duration(audio)
    n = len(clips)
    scenes = []
    for i, clip in enumerate(clips):
        start = i * audio_dur / n
        end = (i + 1) * audio_dur / n
        scenes.append({"clip": clip, "start": start, "end": end})

    result = render(scenes, audio, ass, out)
    print(result)