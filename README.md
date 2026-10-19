# 🍊 CapyBargain

**A purchasing department run by AI capybaras, built on [Band](https://band.ai).**

Small cafés overpay for supplies, because comparing quotes means phone tag, emails and spreadsheets.
CapyBargain hands that job to a herd of agents that talk to each other, and to the café's suppliers,
through Band rooms. A human owner stays in charge of the money.

🎬 **Demo video:** [`video/capybargain-demo.mp4`](video/capybargain-demo.mp4) (2 minutes)

![The Capy Onsen: every Band room is a hot spring](docs/onsen.png)

## Meet the herd

| | Agent | Job |
|---|---|---|
| 🥕 | **Tofu** | Pantry keeper. Counts the shelves and posts restock tasks to the room's task board. |
| 🍊 | **Mochi** | Head buyer. Finds suppliers, opens a quote room with each, haggles, places the orders. |
| 🪙 | **Yuzu** | Treasurer. Checks every order against the weekly budget. |
| 🐢 | **Shelly** | Supplier: Slow & Steady Farm. Cheapest, but delivery takes 4 days. |
| 🐦 | **Zippy** | Supplier: Zippy Express Pantry. Next-day delivery at premium prices. |
| 🦊 | **Foxy** | Supplier: Foxy Wholesale. 2-day delivery, and always tries an upsell. |
| ☕ | **You** | The café owner. Approves anything over budget with one reply. |

## What happens in a run (real numbers from the recorded run)

1. The owner asks **@Tofu** for a pantry check. Coffee beans run out **tomorrow**, oat milk in 3 days, flour in 6.
   Tofu puts three tasks on the HQ room's board and mentions Mochi.
2. **Mochi** calls `band_lookup_peers`, keeps the peers whose description says they're a supplier, and opens a
   separate quote room with each of Shelly, Zippy and Foxy.
3. The quotes come back. For each item Mochi picks the **cheapest supplier that arrives before the shelf runs empty**:
   Shelly is cheapest for coffee but too slow, so coffee goes to Zippy. Oat milk goes to Foxy and flour to Shelly.
4. Mochi counters with the best price it saw elsewhere, and politely declines Foxy's honey bundle 🍯.
   Final offers: **$412.80**, which is **$53.90 less than last month** (−12%).
5. **Yuzu** flags that this is **$15.10 over** the weekly budget. Mochi raises an `attention` event, and the owner
   replies "approve".
6. Purchase orders go out, all three suppliers confirm, every task on the board turns green, and Yuzu logs the spend.

The whole negotiation took **35 seconds** and produced 47 Band events across 4 rooms.

## How it uses Band

| Band feature | Where |
|---|---|
| **@mention routing.** Agents only wake up for messages that mention them; status updates mention the human, so no agent ping-pong. | [`capybargain/agents.py`](capybargain/agents.py) |
| **Dynamic discovery.** Mochi finds suppliers at runtime with `band_lookup_peers` instead of hard-coded wiring. | `Mochi.find_suppliers` |
| **Agent-created rooms.** One titled quote room per supplier, created and staffed by Mochi (`create_agent_chat`, `band_add_participant`). | `Mochi.request_quote` |
| **Room task board (beta).** Tofu creates tasks, Mochi claims them, moves them to `in_review` while waiting for approval, and completes them with the PO number. | `Tofu.handle`, `Mochi.set_task*` |
| **Attention events.** A blocking `review` event asks the owner to approve an over-budget order; a second event resolves it. | `Mochi.on_budget`, `Mochi.on_owner_reply` |
| **Thought and task events.** Mochi's reasoning ("coffee runs out in 1 day → Zippy") is in the room's audit trail, and task events link HQ to every quote room. | `Mochi.send_counters` |
| **Human API.** The owner's side (open HQ, kick off, approve) and the transcript capture for the UI. | [`capybargain/owner.py`](capybargain/owner.py), [`capybargain/transcript.py`](capybargain/transcript.py) |
| **Band Python SDK.** Every agent is a `SimpleAdapter`; all six run in one process. | [`capybargain/run.py`](capybargain/run.py) |

## Run it

You need Python 3.11+, [uv](https://docs.astral.sh/uv/) and a Band account.

```bash
uv sync
cp .env.example .env                           # paste your Band user API key
uv run python scripts/register_agents.py       # creates the 6 agents, saves their keys to agent_config.yaml
```

**Live, with you as the owner:**

```bash
uv run python -m capybargain.run               # the herd comes online
```

In the Band app, make a room with Mochi, Tofu and Yuzu and say `@Tofu pantry check please`.
Watch the quote rooms appear, then reply `@Mochi approve` when Mochi asks.

**Fully scripted** (the script plays the owner and saves a transcript):

```bash
uv run python -m capybargain.run --demo --out runs/my-run.json
```

**The Capy Onsen UI:**

```bash
uv run python -m capybargain.ui_server
# http://localhost:8000/web/          replay the recorded run (runs/demo-transcript.json)
# http://localhost:8000/web/?live     watch the newest run live, straight from Band
```

**Tests:** `uv run pytest`

## Project layout

```
capybargain/
  agents.py        the herd: Tofu, Yuzu, Mochi and the suppliers (Band SimpleAdapters)
  deal.py          shopping lists, quotes, counter-offers, budget math (pure, unit tested)
  pantry.py        the café's pantry, budget and each supplier's price list
  roster.py        names and descriptions the agents are registered with
  run.py           starts all six agents; --demo plays the owner too
  owner.py         the owner's side via Band's Human API
  transcript.py    reads a whole run back out of Band (messages, events, task board)
  ui_server.py     serves the UI and a live feed of the newest run
web/               the Capy Onsen: replay and live views, plus the video director
video/             demo video: narration script, timeline, soundtrack builder, frame renderer
runs/              the recorded demo run
tests/             negotiation tests
```

## Making the video

The video is rendered from the same UI code. `web/video.html` draws any frame `t` deterministically,
replaying the real Band transcript in sync with the narration.

```bash
# put narration.mp3 and alignment.json (per-scene start/end seconds) in video/build/
uv run --with numpy python video/soundtrack.py          # cuts the narration, adds the music-box score, writes timeline.json
python3 -m http.server 8765 --bind 127.0.0.1 &
NODE_PATH=$(npm root -g) node video/render.cjs          # frames → ffmpeg → video/capybargain-demo.mp4
```

The music is synthesized in `video/soundtrack.py`, and all the characters are original SVG in
[`web/art.js`](web/art.js).

## Honest notes

- **The agents' decisions are code, not an LLM.** The negotiation strategy lives in `capybargain/deal.py`
  (unit tested), so runs are reproducible. Every message, task and approval is still a real Band event. To
  make the suppliers chattier, swap a supplier's `SimpleAdapter` for one of Band's LLM adapters; Mochi only
  depends on the markdown tables it exchanges.
- **In this demo all six agents live in one Band account.** In production, each supplier would run in its own
  company's account and Mochi would connect with a contact request (`band_add_contact`). That cross-company
  step isn't exercised here.
- **The pantry is a fixed snapshot,** because room file uploads aren't available on Band Cloud yet. A real
  café would feed it from its point-of-sale system.
