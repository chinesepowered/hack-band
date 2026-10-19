"""Bring the whole herd online.

    uv run python -m capybargain.run                    # agents online; drive it from the Band app
    uv run python -m capybargain.run --demo             # also play the owner: kick off, approve, save transcript

In the Band app: make a room with Mochi, Tofu and Yuzu, then say
"@Tofu pantry check please". When Mochi asks, reply "@Mochi approve".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from band import Agent, configure_logging
from band.config import load_agent_config

from capybargain import owner, transcript
from capybargain.agents import Mochi, Supplier, Tofu, Yuzu, pace
from capybargain.roster import FOXY, SHELLY, ZIPPY

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("capybargain")


async def main(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")
    configure_logging(level="WARNING", root_level="WARNING")
    logging.getLogger("band.client.streaming").setLevel(logging.ERROR)  # presence-event chatter
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    c = owner.client()

    async def owner_approves(room_id: str) -> None:
        await asyncio.sleep(args.approve_after)
        log.info("👩‍🍳 owner approves")
        await owner.approve(c, room_id)

    mochi = Mochi(on_approval_requested=owner_approves if args.demo else None)
    herd = {"mochi": mochi, "tofu": Tofu(), "yuzu": Yuzu()}
    herd |= {m.key: Supplier(m) for m in (SHELLY, ZIPPY, FOXY)}

    agents = []
    for key, adapter in herd.items():
        agent_id, api_key = load_agent_config(key, config_path=str(ROOT / "agent_config.yaml"))
        agent = Agent.create(adapter=adapter, agent_id=agent_id, api_key=api_key)
        await agent.start()
        agents.append(agent)
        log.info("%s %s is online", adapter.member.emoji, adapter.member.name)

    try:
        if not args.demo:
            log.info("🍊 The herd is soaking in the onsen. Ctrl+C to stop.")
            await asyncio.Event().wait()
        hq = await owner.kickoff(c)
        log.info("☕ HQ room %s, asked Tofu for a pantry check", hq)
        await asyncio.wait_for(mochi.finished.wait(), timeout=args.timeout)
        await asyncio.sleep(max(4.0, 4 * pace()))  # let Yuzu log the spend
        out = args.out or ROOT / "runs" / f"run-{datetime.now():%Y%m%d-%H%M%S}.json"
        log.info("📜 transcript saved to %s", transcript.save(await transcript.capture(c, hq), out))
    finally:
        for agent in agents:
            await agent.stop(timeout=5)


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="play the owner: kick off, approve, save transcript")
    parser.add_argument("--approve-after", type=float, default=5.0, help="seconds the owner takes to approve")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--out", type=Path, help="transcript path (default runs/run-<time>.json)")
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
