"""
orchestrator.py — end-to-end pipeline for one YouTube Short.
"""
import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from topic_research import pick_topic, load_history, save_history
from script_gen import generate_script, narration_text
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


def main(privacy: str = "public") -> None:
    print("[orchestrator] === starting pipeline ===", file=sys.stderr)

    history = load_history()
    topic = pick_topic()
    print(f"[orchestrator] topic: {topic}", file=sys.stderr)

    script = generate_script(topic)
    print(f"[orchestrator] title: {script['title']}", file=sys.stderr)
    print(f"[orchestrator] scenes: {len(script['scenes'])}", file=sys.stderr)

    scene_clips = fetch_broll_for_scenes(script["scenes"])

    narration = narration_text(script)
    voice = synthesize(narration, "output/voice.mp3")

    ass = generate_captions(str(voice), "output/captions.ass")

    aligned = align_scenes(script["scenes"], str(voice))

    scenes = []
    for i, s in enumerate(aligned):
        clip = scene_clips[i]["asset"]["path"]
        scenes.append({
            "clip": clip,
            "start": s["start"],
            "end": s["end"],
        })

    final = render(scenes, str(voice), str(ass), "output/final.mp4")

    vid = upload_video(
        str(final),
        title=script["title"],
        description=script.get("description", ""),
        tags=script.get("hashtags", []),
        privacy=privacy,
    )
    print(f"[orchestrator] uploaded: https://youtube.com/shorts/{vid}",
          file=sys.stderr)

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