"""Read a whole negotiation back out of Band.

Starting from the HQ room, Mochi's ``task`` events point at every quote room it
opened, so one HQ room id is enough to recover the full story: every message,
thought, task update and approval, exactly as Band recorded them. The web UI
replays these files.

    uv run python -m capybargain.transcript <hq_room_id> runs/my-run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from band.config import load_agent_config
from band_rest import AsyncRestClient

from capybargain.owner import client

ROOT = Path(__file__).resolve().parent.parent

KEEP = ("id", "content", "message_type", "sender_type", "sender_name", "sender_id", "metadata", "inserted_at")


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump())
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def room_messages(c: AsyncRestClient, room_id: str) -> list[dict[str, Any]]:
    messages, cursor = [], None
    while True:
        resp = await c.human_api_messages.list_my_chat_messages(room_id, limit=100, cursor=cursor)
        messages += [{k: _plain(getattr(m, k, None)) for k in KEEP} for m in resp.data or []]
        meta = resp.metadata
        cursor = getattr(meta, "next_cursor", None)
        if not cursor or not getattr(meta, "has_more", False):
            break
    return sorted(messages, key=lambda m: m["inserted_at"] or "")


async def room(c: AsyncRestClient, room_id: str) -> dict[str, Any]:
    info = await c.human_api_chats.get_my_chat_room(room_id)
    people = await c.human_api_participants.list_my_chat_participants(room_id)
    return {
        "id": room_id,
        "title": info.data.title,
        "participants": [
            {k: getattr(p, k, None) for k in ("id", "name", "type", "handle")} for p in people.data or []
        ],
        "messages": await room_messages(c, room_id),
    }


async def board(hq_room_id: str) -> dict[str, Any] | None:
    """The HQ task board and every task's history (Agent API, so it uses Mochi's key)."""
    config_path = ROOT / "agent_config.yaml"
    if not config_path.exists():
        return None
    _, api_key = load_agent_config("mochi", config_path=str(config_path))
    mochi = AsyncRestClient(base_url=os.environ.get("BAND_REST_URL", "https://app.band.ai"), api_key=api_key)
    goal = await mochi.agent_api_chat_tasks.get_chat_board(chat_id=hq_room_id)
    listed = await mochi.agent_api_chat_tasks.list_chat_tasks(chat_id=hq_room_id, state="all")
    tasks = []
    for task in sorted(listed.data or [], key=lambda t: t.number):
        history = await mochi.agent_api_chat_tasks.get_chat_task_history(chat_id=hq_room_id, id=task.id, limit=100)
        tasks.append(
            {
                "id": task.id,
                "number": task.number,
                "subject": task.subject,
                "history": [_plain(e) for e in history.data or []],
            }
        )
    return {
        "goal_title": getattr(goal.data, "goal_title", None),
        "goal_summary": getattr(goal.data, "goal_summary", None),
        "tasks": tasks,
    }


async def capture(c: AsyncRestClient, hq_room_id: str) -> dict[str, Any]:
    hq = await room(c, hq_room_id)
    quote_rooms = [
        m["metadata"]["quote_room_id"]
        for m in hq["messages"]
        if m["message_type"] == "task" and (m.get("metadata") or {}).get("quote_room_id")
    ]
    rooms = [hq] + [await room(c, rid) for rid in quote_rooms]
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "hq_room_id": hq_room_id,
        "rooms": rooms,
        "board": await board(hq_room_id),
    }


def save(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return path


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("hq_room_id")
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    print("saved", save(await capture(client(), args.hq_room_id), args.out))


if __name__ == "__main__":
    asyncio.run(main())
