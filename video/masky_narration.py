"""Render the v2 narration on Masky: Mochi's avatar says every line, lip-synced.

Reads video/narration-v2.md. Each scene gets its own Masky conversation with
Mochi's avatar and one verbatim `speak` turn with video output (Masky splits a
long line into turns of up to three sentences), so the scenes render in
parallel. Scene 6.5 is the approval clip Mochi already rendered for the Masky
integration (docs/masky/mochi-approval.mp4).

Writes, in video/build/v2/ (not committed):
  clips/<n>.mp4     each scene's talking-head clip, chunks joined
  narration.mp3     every scene back to back, with a short pause between
  alignment.json    where each scene sits in narration.mp3, for soundtrack.py

    uv run python video/masky_narration.py         # render on Masky, write narration.mp3 + alignment.json
    uv run python video/masky_narration.py host    # after soundtrack.py --cut v2: the face-cam frames
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from capybargain import masky  # noqa: E402

OUT = HERE / "build" / "v2"
CLIPS = OUT / "clips"
PAUSE = 0.35  # silence between scenes in narration.mp3, so soundtrack.py's cuts never overlap
SPEED = 1.1  # Mochi talks a touch faster than Masky's default pace; video and voice together, so lips stay in sync
READY = {6.5: ROOT / "docs" / "masky" / "mochi-approval.mp4"}
VOICE = {"emotion": "enthusiasm"}


def scenes() -> list[dict]:
    rows = []
    for line in (HERE / "narration-v2.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"\d+(\.\d+)?", cells[0]):
            n = float(cells[0])
            rows.append({"n": int(n) if n.is_integer() else n, "name": cells[1], "text": cells[2]})
    return rows


def chunks(text: str) -> int:
    return math.ceil(len(re.split(r"(?<=[.!?])\s+", text.strip())) / 3)


def duration(path: Path, stream: str = "") -> float:
    """A clip's length; pass "a:0" for its voice track, which ends a little before the video."""
    pick = ["-select_streams", stream, "-show_entries", "stream=duration"] if stream else ["-show_entries", "format=duration"]
    out = subprocess.run(
        ["ffprobe", "-v", "error", *pick, "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout)


def speech(path: Path) -> tuple[float, float]:
    """When the voice starts and stops in a clip (Masky pads clips to whole seconds)."""
    log = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "silencedetect=noise=-38dB:d=0.12", "-f", "null", "-"],
        capture_output=True,
        text=True,
    ).stderr
    total = duration(path, "a:0")
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", log)]
    lead = ends[0] if starts and starts[0] < 0.05 and ends else 0.0
    tail = starts[-1] if starts and (len(ends) < len(starts) or ends[-1] >= total - 0.05) else total
    return max(0.0, lead - 0.04), min(total, tail + 0.08)


def join(parts: list[Path], dest: Path) -> None:
    inputs = sum((["-i", str(p)] for p in parts), [])
    streams = "".join(
        f"[{i}:v]setpts=PTS/{SPEED},fps=30,scale=960:960,setsar=1[v{i}];[{i}:a]atempo={SPEED},aresample=48000,aformat=channel_layouts=mono[a{i}];"
        for i in range(len(parts))
    )
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(parts)))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", f"{streams}{pairs}concat=n={len(parts)}:v=1:a=1[v][a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(dest)],
        check=True,
    )


async def render(scene: dict, avatar: dict) -> Path:
    dest = CLIPS / f"{scene['n']}.mp4"
    if dest.exists():
        return dest
    parts = sorted(CLIPS.glob(f"{scene['n']}_*.mp4"))
    if parts and len(parts) >= chunks(scene["text"]):  # downloaded on an earlier run
        join(parts, dest)
        return dest
    conv = await masky._call(
        "POST", "/conversations", json={"avatarOwnerUserId": avatar["avatarOwnerUserId"], "avatarId": avatar["avatarId"]}
    )
    await masky._call(
        "POST",
        f"/conversations/{conv['conversationId']}/turn",
        json={"userText": scene["text"], "output": "video", "mode": "speak", "voiceStyle": VOICE},
    )
    want = chunks(scene["text"])
    for _ in range(120):
        await asyncio.sleep(5)
        try:
            data = await masky._call("GET", f"/conversations/by-slug/{conv['shareSlug']}")
        except httpx.HTTPError:
            continue  # a network blip; the render carries on server-side
        turns = sorted((t for t in data.get("turns", []) if t.get("role") == "avatar"), key=lambda t: t.get("createdAt", 0))
        failed = [t for t in turns if t.get("status") == "error"]
        if failed:
            raise RuntimeError(f"scene {scene['n']}: {failed[0].get('errorMessage')}")
        if len(turns) >= want and all(t.get("videoUrl") for t in turns):
            break
    else:
        raise TimeoutError(f"scene {scene['n']} is still rendering")
    parts = []
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        for k, turn in enumerate(turns):
            part = CLIPS / f"{scene['n']}_{k}.mp4"
            part.write_bytes((await http.get(turn["videoUrl"])).content)
            parts.append(part)
    join(parts, dest)
    print(f"✓ scene {scene['n']}: {len(parts)} clip(s), {duration(dest):.1f}s")
    return dest


async def main() -> None:
    load_dotenv(ROOT / ".env")
    CLIPS.mkdir(parents=True, exist_ok=True)
    avatar = masky.avatars()["mochi"]
    rows = scenes()
    for n, src in READY.items():
        dest = CLIPS / f"{n}.mp4"
        if not dest.exists():
            join([src], dest)
    await asyncio.gather(*(render(s, avatar) for s in rows if s["n"] not in READY))

    # narration.mp3 + alignment.json, in scene order; "lead" is the clip's silence before the voice
    t, inputs, labels, timeline = 0.0, [], [], []
    for i, s in enumerate(rows):
        clip = CLIPS / f"{s['n']}.mp4"
        d = duration(clip, "a:0")
        lead, end = speech(clip)
        timeline.append({**s, "start": round(t + lead, 3), "end": round(t + end, 3), "lead": round(lead, 3)})
        inputs += ["-i", str(clip)]
        labels.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=pad_dur={PAUSE}[a{i}];")
        t += d + PAUSE
    mix = "".join(labels) + "".join(f"[a{i}]" for i in range(len(rows))) + f"concat=n={len(rows)}:v=0:a=1[a]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", mix, "-map", "[a]", "-b:a", "192k", str(OUT / "narration.mp3")], check=True)
    (OUT / "alignment.json").write_text(json.dumps({"scenes": timeline}, indent=2, ensure_ascii=False) + "\n")
    print(f"narration: {t:.1f}s across {len(rows)} scenes → {OUT / 'narration.mp3'}")


def host() -> None:
    """The face-cam's frames: each clip laid on video/timeline-v2.json, over Mochi's still between lines."""
    timeline = json.loads((HERE / "timeline-v2.json").read_text())
    frames = OUT / "host"
    frames.mkdir(parents=True, exist_ok=True)
    for old in frames.glob("*.jpg"):
        old.unlink()
    still = CLIPS / "still.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(CLIPS / "1.mp4"), "-frames:v", "1", str(still)], check=True)
    inputs = ["-loop", "1", "-framerate", "30", "-t", str(timeline["duration"] + 1), "-i", str(still)]
    graph = "[0:v]scale=600:600,setsar=1,format=yuv420p[b0];"
    for i, s in enumerate(timeline["scenes"], 1):
        begin = s["start"] - s["lead"]
        inputs += ["-i", str(CLIPS / f"{s['n']}.mp4")]
        graph += (
            f"[{i}:v]trim=0:{s['lead'] + s['end'] - s['start'] + 0.15:.3f},scale=600:600,setsar=1,format=yuv420p,"
            f"setpts=PTS-STARTPTS+{begin:.3f}/TB[c{i}];[b{i - 1}][c{i}]overlay=eof_action=pass[b{i}];"
        )
    last = len(timeline["scenes"])
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph.rstrip(";"), "-map", f"[b{last}]",
         "-r", "30", "-start_number", "0", "-q:v", "3", str(frames / "%05d.jpg")],
        check=True,
    )
    print(f"face-cam: {len(list(frames.glob('*.jpg')))} frames → {frames}")


if __name__ == "__main__":
    host() if sys.argv[1:] == ["host"] else asyncio.run(main())
