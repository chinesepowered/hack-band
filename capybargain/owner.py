"""The café owner's side of the story, through Band's Human API.

The owner is a person, so in a live demo they simply type in the Band app.
These helpers do the same thing from a script, with your user key, for
recorded runs and for kicking things off quickly:

    uv run python -m capybargain.owner kickoff     # open HQ and ask Tofu for a pantry check
    uv run python -m capybargain.owner approve     # approve Mochi's order in the latest HQ room
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from dotenv import load_dotenv
from band_rest import AsyncRestClient, ChatMessageRequest, ChatMessageRequestMentionsItem, ParticipantRequest
from band_rest.human_api_chats import CreateMyChatRoomRequestChat

from capybargain.agents import HQ_TITLE
from capybargain.roster import CAFE_STAFF, MOCHI, TOFU


def client() -> AsyncRestClient:
    return AsyncRestClient(
        base_url=os.environ.get("BAND_REST_URL", "https://app.band.ai"),
        api_key=os.environ["BAND_API_KEY"],
    )


async def find_agents(c: AsyncRestClient, names: list[str]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    page = 1
    while len(found) < len(names):
        resp = await c.human_api_peers.list_my_peers(type="Agent", page=page, page_size=100)
        for peer in resp.data or []:
            if peer.name in names:
                found[peer.name] = peer
        if not resp.data or page >= (resp.metadata.total_pages or 1):
            break
        page += 1
    missing = set(names) - set(found)
    if missing:
        raise SystemExit(f"Can't find {', '.join(sorted(missing))}. Run scripts/register_agents.py first.")
    return found


async def say(c: AsyncRestClient, room_id: str, content: str, mention: list[Any]) -> None:
    await c.human_api_messages.send_my_chat_message(
        room_id,
        message=ChatMessageRequest(
            content=content,
            mentions=[ChatMessageRequestMentionsItem(id=p.id, handle=p.handle) for p in mention],
        ),
    )


async def kickoff(c: AsyncRestClient) -> str:
    """Open a fresh HQ room with the café staff and ask Tofu for a pantry check."""
    staff = await find_agents(c, [m.name for m in CAFE_STAFF])
    room = await c.human_api_chats.create_my_chat_room(chat=CreateMyChatRoomRequestChat(title=HQ_TITLE))
    room_id = room.data.id
    for agent in staff.values():
        await c.human_api_participants.add_my_chat_participant(
            room_id, participant=ParticipantRequest(participant_id=agent.id, role="member")
        )
    await say(c, room_id, "Good morning! ☀️ Pantry check, please 🍊", [staff[TOFU.name]])
    return room_id


async def latest_hq(c: AsyncRestClient) -> str:
    resp = await c.human_api_chats.list_my_chats(page_size=50)
    rooms = [r for r in resp.data or [] if (r.title or "") == HQ_TITLE]
    if not rooms:
        raise SystemExit("No HQ room yet. Run: uv run python -m capybargain.owner kickoff")
    return max(rooms, key=lambda r: r.inserted_at).id


async def approve(c: AsyncRestClient, room_id: str | None = None) -> None:
    room_id = room_id or await latest_hq(c)
    mochi = (await find_agents(c, [MOCHI.name]))[MOCHI.name]
    await say(c, room_id, "Approve ✅ Great haggling!", [mochi])


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["kickoff", "approve"])
    parser.add_argument("--room", help="HQ room id (default: the latest HQ room)")
    args = parser.parse_args()
    c = client()
    if args.action == "kickoff":
        print("☕ HQ room:", await kickoff(c))
    else:
        await approve(c, args.room)
        print("✅ Approved")


if __name__ == "__main__":
    asyncio.run(main())
