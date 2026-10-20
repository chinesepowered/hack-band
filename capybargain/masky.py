"""Masky avatars: the faces and voices of the herd.

Every agent has a Masky avatar (https://masky.ai): a portrait, the agent's
personality and a voice. When Mochi talks to the café owner, the moments when a
person is actually listening, it also says the line on camera through its
avatar, and the Band message links to the Masky player.

    uv run python -m capybargain.masky setup                    # create the avatars, save their ids
    uv run python -m capybargain.masky say mochi "Hi!" --wait   # one line on camera, prints the clip link

Set MASKY_API_KEY for real avatars. Without it, or for an agent that has no
avatar yet, this runs as a mock: it logs what the avatar would say and returns
no link, so a run never stalls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

log = logging.getLogger("capybargain")

ROOT = Path(__file__).resolve().parent.parent
AVATARS_FILE = ROOT / "masky_avatars.json"  # gitignored: the avatars belong to the key's account

# What each agent looks and sounds like on Masky: name, preset voice, portrait prompt.
LOOKS = {
    "mochi": ("Mochi", "Expressive Girl", "a calm, polite capybara with a small yuzu fruit balanced on its head"),
    "tofu": ("Tofu", "Sitcom Girl", "a capybara wearing a tiny white chef hat, a little dramatic"),
    "yuzu": ("Yuzu", "Mrs. Pembroke", "a careful capybara with round glasses and a gold coin on its head"),
    "shelly": ("Shelly", "Turtle Guru", "a kind old tortoise in a straw farmer's hat"),
    "zippy": ("Zippy", "Highly Reactive Guy", "an excited teal hummingbird in a tiny delivery cap"),
    "foxy": ("Foxy", "Charming Cowgirl", "a charming fox holding a small jar of honey, cheeky smile"),
}
UNSPOKEN = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D*_#]")  # emoji and markdown
PORTRAIT = (
    "head-and-shoulders portrait looking straight at the camera, cute 3D animated film style, "
    "soft warm light, cosy café background in cream and orange"
)


class MaskyError(Exception):
    pass


def enabled() -> bool:
    return bool(os.environ.get("MASKY_API_KEY"))


def avatars() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(AVATARS_FILE.read_text())
    except FileNotFoundError:
        return {}


_client: httpx.AsyncClient | None = None
_conversations: dict[str, dict[str, Any]] = {}


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=os.environ.get("MASKY_URL", "https://masky.ai/api").rstrip("/"),
            headers={"Authorization": f"Bearer {os.environ['MASKY_API_KEY']}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
    return _client


async def _call(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    resp = await _http().request(method, path, **kwargs)
    if resp.status_code >= 400:
        raise MaskyError(f"{method} {path} → {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def speak(key: str, text: str) -> str | None:
    """Say a line on camera through the agent's avatar. Returns the Masky player link, or None in mock mode."""
    text = re.sub(r"\s+", " ", UNSPOKEN.sub("", text)).strip()[:500]
    avatar = avatars().get(key)
    if not (enabled() and avatar and text):
        log.info("🎭 masky (mock) · %s would say: %s", key, text[:80])
        return None
    try:
        conv = _conversations.get(key)
        if conv is None:
            conv = await _call(
                "POST",
                "/conversations",
                json={"avatarOwnerUserId": avatar["avatarOwnerUserId"], "avatarId": avatar["avatarId"]},
            )
            _conversations[key] = conv
        turn = await _call(
            "POST",
            f"/conversations/{conv['conversationId']}/turn",
            json={"userText": text, "output": "video", "mode": "speak"},
        )
        conv["last_turn_id"] = turn["turn"]["id"]
        log.info("🎭 masky · %s is saying it on camera", avatar["displayName"])
        return conv["liveUrl"]
    except (httpx.HTTPError, MaskyError, KeyError) as exc:
        log.warning("masky: %s couldn't speak (%s)", key, exc)
        return None


async def clip(key: str, timeout: float = 240.0) -> dict[str, Any] | None:
    """Wait for the agent's last line to finish rendering; returns that turn (videoUrl, shareUrl, liveUrl)."""
    conv = _conversations.get(key)
    if not conv:
        return None
    for _ in range(int(timeout / 3)):
        data = await _call("GET", f"/conversations/by-slug/{conv['shareSlug']}")
        turn = next((t for t in data.get("turns", []) if t.get("id") == conv.get("last_turn_id")), None)
        if turn and (turn.get("videoUrl") or turn.get("status") == "error"):
            return turn
        await asyncio.sleep(3)
    return None


async def setup() -> None:
    """Create a Masky avatar for each agent that doesn't have one yet."""
    from capybargain.agents import PERSONAS

    voices = {v["name"]: v["id"] for v in (await _call("GET", "/voices"))["voices"]}
    existing = {a.get("displayName"): a for a in (await _call("GET", "/avatars"))["avatars"]}
    saved = avatars()
    for key, (name, voice, look) in LOOKS.items():
        if key in saved:
            print(f"✓ {name} already has an avatar")
            continue
        avatar = existing.get(name)
        if avatar is None:
            image = (await _call("POST", "/images/generate", json={"prompt": f"{look}, {PORTRAIT}"}))["imageUrl"]
            try:
                body = {"displayName": name, "imageUrl": image, "personalityPrompt": PERSONAS[name]}
                if voice in voices:
                    body["voiceId"] = voices[voice]
                avatar = (await _call("POST", "/avatars", json=body))["avatar"]
            except MaskyError as exc:
                print(f"✗ {name}: {exc}")
                print("  The free tier allows one avatar. Redeem the hackathon's Creator code, then run setup again.")
                break
        saved[key] = {
            "avatarId": avatar["avatarId"],
            "avatarOwnerUserId": avatar["avatarOwnerUserId"],
            "displayName": name,
            "voice": voice,
            "imageUrl": avatar.get("imageUrl") or avatar.get("primaryImageUrl"),
        }
        AVATARS_FILE.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n")
        print(f"✓ {name} is on Masky ({voice})")


async def _say(key: str, text: str, wait: bool) -> None:
    link = await speak(key, text)
    if not link:
        print("(mock: no MASKY_API_KEY, or no avatar for that agent yet)")
        return
    print("player:", link)
    if wait:
        turn = await clip(key)
        print("clip:", (turn or {}).get("shareUrl") or (turn or {}).get("errorMessage") or "still rendering")


def cli() -> None:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="The herd's Masky avatars.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="create a Masky avatar for each agent")
    say = sub.add_parser("say", help="have an agent's avatar say a line on camera")
    say.add_argument("key", choices=list(LOOKS))
    say.add_argument("text")
    say.add_argument("--wait", action="store_true", help="wait for the clip and print its share link")
    args = parser.parse_args()
    asyncio.run(setup() if args.cmd == "setup" else _say(args.key, args.text, args.wait))


if __name__ == "__main__":
    cli()
