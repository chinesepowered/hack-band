"""Build the demo video's soundtrack and timeline.

Inputs (in video/build/, not committed):
  narration.mp3     the narration recorded in one take
  alignment.json    {"scenes": [{"n", "name", "text", "start", "end"}]}, seconds into narration.mp3

Outputs:
  video/build/soundtrack.wav   narration with breathing room between scenes, over music
  video/timeline.json          when each scene's narration plays in the final video

The music is synthesized here: a little music-box loop over a soft bass and
pad, so the whole soundtrack is original.

    uv run --with numpy python video/soundtrack.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SR = 44100

LEAD_IN = 0.9  # music before the first word
TAIL = 2.6  # music after the last word
GAP = 0.45  # extra pause between scenes
GAP_BEFORE = {4: 0.9, 8: 0.8}  # longer breaths before the live run and the recap


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def assemble_narration(voice: np.ndarray, scenes: list[dict]) -> tuple[np.ndarray, list[dict]]:
    pieces, timeline, t = [], [], LEAD_IN
    pieces.append(np.zeros(int(LEAD_IN * SR), np.float32))
    for i, scene in enumerate(scenes):
        if i:
            gap = GAP_BEFORE.get(scene["n"], GAP)
            pieces.append(np.zeros(int(gap * SR), np.float32))
            t += gap
        nxt = scenes[i + 1]["start"] if i + 1 < len(scenes) else len(voice) / SR
        a = max(0.0, scene["start"] - 0.06)
        b = min(scene["end"] + 0.14, nxt - 0.03)
        clip = voice[int(a * SR) : int(b * SR)]
        fade = int(0.012 * SR)
        clip[:fade] *= np.linspace(0, 1, fade)
        clip[-fade:] *= np.linspace(1, 0, fade)
        timeline.append({**scene, "start": round(t + (scene["start"] - a), 3), "end": round(t + (scene["end"] - a), 3)})
        pieces.append(clip)
        t += len(clip) / SR
    pieces.append(np.zeros(int(TAIL * SR), np.float32))
    return np.concatenate(pieces), timeline


# --- music ----------------------------------------------------------------------------------


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def tone(freq: float, dur: float, partials: list[tuple[float, float, float]], attack: float = 0.004) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    out = np.zeros_like(t)
    for mult, amp, decay in partials:
        out += amp * np.sin(2 * np.pi * freq * mult * t) * np.exp(-t * decay)
    return (out * (1 - np.exp(-t / attack))).astype(np.float32)


def music_box(freq: float) -> np.ndarray:
    return tone(freq, 1.6, [(1, 1.0, 3.0), (2, 0.32, 6.0), (3, 0.1, 9.0), (4.18, 0.07, 14.0)])


def bass(freq: float) -> np.ndarray:
    return tone(freq, 1.0, [(1, 1.0, 4.5), (2, 0.25, 8.0)], attack=0.008)


def pad(freqs: list[float], dur: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(1, t / 0.5) * np.minimum(1, (dur - t) / 0.6)
    out = sum(np.sin(2 * np.pi * f * d * t) for f in freqs for d in (0.998, 1.002))
    return (out * env / (2 * len(freqs))).astype(np.float32)


def tok() -> np.ndarray:
    t = np.arange(int(0.08 * SR)) / SR
    rng = np.random.default_rng(7)
    return ((np.sin(2 * np.pi * 1650 * t) + 0.3 * rng.standard_normal(len(t))) * np.exp(-t * 70)).astype(np.float32)


CHORDS = [[60, 64, 67], [57, 60, 64], [53, 57, 60], [55, 59, 62]]  # C, Am, F, G
MELODY = [
    [76, 79, 84, None, 76, 79, 86, 84],
    [76, 81, 84, None, 76, 79, 81, 84],
    [77, 81, 84, None, 79, 81, 84, 86],
    [86, 83, 79, None, 86, 88, 86, 83],
]


def music(duration: float) -> np.ndarray:
    beat = 60 / 92
    out = np.zeros(int((duration + 2) * SR), np.float32)
    left = np.zeros_like(out)

    def add(sig: np.ndarray, at: float, gain: float, pan: float = 0.0) -> None:
        i = int(at * SR)
        j = min(len(out), i + len(sig))
        out[i:j] += sig[: j - i] * gain * (1 - pan)
        left[i:j] += sig[: j - i] * gain * (1 + pan)

    bar, t = 0, 0.0
    while t < duration:
        chord = CHORDS[bar % 4]
        add(pad([hz(n) for n in chord], 4 * beat + 0.4), t, 0.05)
        add(bass(hz(chord[0] - 24)), t, 0.13)
        add(bass(hz(chord[0] - 12 + (7 if bar % 2 else 0))), t + 2 * beat, 0.08)
        sparse = (bar // 4) % 2 == 1
        for k, note in enumerate(MELODY[bar % 4]):
            if note is None or (sparse and k % 2 == 1):
                continue
            add(music_box(hz(note)), t + k * beat / 2, 0.15, pan=0.25 * np.sin(k))
        for k in (1, 3):
            add(tok(), t + k * beat, 0.025, pan=-0.3)
        bar += 1
        t += 4 * beat
    return np.stack([left, out], axis=1)[: int(duration * SR)]


def duck_envelope(n: int, timeline: list[dict]) -> np.ndarray:
    env = np.ones(n, np.float32)
    for scene in timeline:
        a, b = int((scene["start"] - 0.15) * SR), int((scene["end"] + 0.2) * SR)
        env[max(0, a) : min(n, b)] = 0.32
    k = int(0.25 * SR)
    kernel = np.ones(k, np.float32) / k
    return np.convolve(env, kernel, mode="same")


def main() -> None:
    alignment = json.loads((BUILD / "alignment.json").read_text())
    voice = decode(BUILD / "narration.mp3")
    voice *= 0.89 / np.abs(voice).max()
    narration, timeline = assemble_narration(voice, alignment["scenes"])
    duration = len(narration) / SR

    bed = music(duration)
    bed *= 0.22 / np.sqrt(np.mean(bed**2)) * 0.25  # music RMS well under the voice
    bed *= duck_envelope(len(bed), timeline)[:, None]
    fade = int(1.2 * SR)
    bed[-fade:] *= np.linspace(1, 0, fade)[:, None]

    mix = bed + narration[:, None]
    mix *= 0.97 / max(1.0, np.abs(mix).max())
    pcm = (mix * 32767).astype("<i2")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "-", str(BUILD / "soundtrack.wav")],
        input=pcm.tobytes(),
        check=True,
    )
    (HERE / "timeline.json").write_text(
        json.dumps({"duration": round(duration, 3), "fps": 30, "scenes": timeline}, indent=1, ensure_ascii=False)
    )
    print(f"soundtrack {duration:.2f}s → {BUILD / 'soundtrack.wav'}")
    for s in timeline:
        print(f"  {s['n']:>2} {s['name']:<22} {s['start']:7.2f} → {s['end']:7.2f}")


if __name__ == "__main__":
    main()
