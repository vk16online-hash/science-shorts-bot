"""
orchestrator.py — full pipeline for one YouTube Short.

Flow:
  1. Pick a fresh topic (deduped against history)
  2. Research the topic (Wikipedia + arXiv + OpenAlex)
  3. Generate a script grounded in research facts (per-scene visual queries)
  4. Fetch topic-specific assets per scene (Wikipedia/arXiv first, stock fallback)
  5. Synthesize the voiceover from the script
  6. Transcribe + build ASS captions
  7. Align scenes to voiceover timestamps
  8. Render with Ken Burns + varied transitions
  9. Upload to YouTube
 10. Append topic to history
"""
import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from topic_research import pick_topic, load_history, save_history
from research import research_topic
from script_gen import generate_script, narration_text
from assets import fetch_best_asset
from broll_fetch import fetch_broll_for_scenes
from tts import synthesize
from captions import generate_captions
from scene_align import align_scenes
from render import render
from upload import upload_video


def _notify(msg: str) -> None:
    url = os.environ.get("DISCORD_WEBHOOK", "").strip()
    print(f"[notify] {msg}", file=sys.stderr)
    if not url:
        return
    try:
        import requests
        requests.post(url, json={"content": msg}, timeout=10)
    except Exception as e:
        print(f"[notify] webhook failed: {e}", file=sys.stderr)


def _resolve_scene_clips(script: dict, research: dict) -> list:
    """
    For each scene, prefer topic-specific assets (Wikipedia/arXiv) and
    fall back to stock b-roll (Pexels/Pixabay/Archive) when nothing matches.
    Returns a list of clip paths (may include images and videos).
    """
    clips = []
    used_urls = set()

    for i, scene in enumerate(script["scenes"]):
        print(f"[orchestrator] resolving assets for scene {i + 1}/{len(script['scenes'])}",
              file=sys.stderr)

        # Try topic-specific asset first (Wikipedia/arXiv)
        asset = fetch_best_asset(research, scene, used_urls)

        if asset and asset.get("path"):
            clips.append({
                "path": asset["path"],
                "source": asset.get("source", "unknown"),
                "type": asset.get("type", "image"),
            })
            continue

        # Fallback: stock b-roll for this scene's queries
        try:
            print(f"[orchestrator] scene {i}: falling back to stock b-roll",
                  file=sys.stderr)
            fallback = fetch_broll_for_scenes([scene])
            if fallback:
                clips.append({
                    "path": fallback[0]["asset"]["path"],
                    "source": fallback[0]["asset"].get("source", "stock"),
                    "type": "video",
                })
                continue
        except Exception as e:
            print(f"[orchestrator] scene {i} stock fallback failed: {e}",
                  file=sys.stderr)

        # Final fallback: reuse the previous clip
        if clips:
            print(f"[orchestrator] scene {i}: reusing previous clip",
                  file=sys.stderr)
            clips.append(clips[-1])
        else:
            raise RuntimeError(f"No asset could be found for any scene")

    return clips


def main(privacy: str = "public") -> None:
    print("[orchestrator] === starting pipeline ===", file=sys.stderr)

    # 1. Topic
    history = load_history()
    topic = pick_topic()
    print(f"[orchestrator] topic: {topic}", file=sys.stderr)

    # 2. Research
    research = research_topic(topic)

    # 3. Script grounded in research
    script = generate_script(topic, research)
    print(f"[orchestrator] title: {script['title']}", file=sys.stderr)
    print(f"[orchestrator] scenes: {len(script['scenes'])}", file=sys.stderr)

    # 4. Resolve clips per scene
    clips = _resolve_scene_clips(script, research)
    for i, c in enumerate(clips):
        print(f"[orchestrator] scene {i}: {c['source']} ({c['type']})",
              file=sys.stderr)

    # 5. Voiceover (full narration)
    narration = narration_text(script)
    voice = synthesize(narration, "output/voice.mp3")

    # 6. Captions
    ass = generate_captions(str(voice), "output/captions.ass")

    # 7. Align scenes to timestamps
    aligned = align_scenes(script["scenes"], str(voice))

    # 8. Render
    scenes = []
    for i, s in enumerate(aligned):
        scenes.append({
            "clip": clips[i]["path"],
            "start": s["start"],
            "end": s["end"],
        })

    final = render(scenes, str(voice), str(ass), "output/final.mp4")

    # 9. Upload
    vid = upload_video(
        str(final),
        title=script["title"],
        description=script.get("description", ""),
        tags=script.get("hashtags", []),
        privacy=privacy,
    )
    print(f"[orchestrator] uploaded: https://youtube.com/shorts/{vid}",
          file=sys.stderr)

    # 10. History
    history.append({
        "topic": topic,
        "video_id": vid,
        "title": script["title"],
    })
    save_history(history[-500:])

    _notify(f"✅ Uploaded: {script['title']} — https://youtube.com/shorts/{vid}")


if __name__ == "__main__":
    privacy = os.environ.get("PRIVACY", "public")
    try:
        main(privacy=privacy)
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        _notify(f"❌ Pipeline failed: {e}\n```{tb[:1200]}```")
        sys.exit(1)