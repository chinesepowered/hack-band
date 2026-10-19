"""Register the Capy Café herd as remote agents on Band.

Uses your *user* API key (BAND_API_KEY in .env) to call
POST /api/v1/me/agents/register once per agent, and writes each agent's id and
one-time API key into agent_config.yaml (gitignored).

Agents that already have credentials in agent_config.yaml are skipped, so the
script is safe to re-run. Your other Band agents are never touched.

    uv run python scripts/register_agents.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from capybargain.roster import EVERYONE  # noqa: E402

CONFIG_PATH = ROOT / "agent_config.yaml"


def main() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ["BAND_API_KEY"]
    base = os.environ.get("BAND_REST_URL", "https://app.band.ai").rstrip("/")
    config = yaml.safe_load(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    config = config or {}

    with httpx.Client(base_url=base, headers={"X-API-Key": api_key}, timeout=30) as http:
        existing = http.get("/api/v1/me/agents", params={"page_size": 100}).json()["data"]
        names_taken = {a["name"] for a in existing}

        for member in EVERYONE:
            if member.key in config:
                print(f"✓ {member.name} already configured")
                continue
            if member.name in names_taken:
                sys.exit(
                    f"An agent named {member.name!r} already exists on your account but "
                    "agent_config.yaml has no key for it. Delete it in the Band app or "
                    "add its credentials to agent_config.yaml by hand."
                )
            resp = http.post(
                "/api/v1/me/agents/register",
                json={"agent": {"name": member.name, "description": member.description}},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            config[member.key] = {
                "agent_id": data["agent"]["id"],
                "api_key": data["credentials"]["api_key"],
            }
            # Save after every agent: the API key is only shown once.
            CONFIG_PATH.write_text(yaml.safe_dump(config, sort_keys=False))
            CONFIG_PATH.chmod(0o600)
            print(f"+ registered {member.emoji} {member.name} ({data['agent']['id']})")

    print(f"\nCredentials saved to {CONFIG_PATH.name} (gitignored).")


if __name__ == "__main__":
    main()
