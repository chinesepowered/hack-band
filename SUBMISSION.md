# CapyBargain: a purchasing department run by AI capybaras

**Built on Band** · 🎬 2-minute demo: [`video/capybargain-demo.mp4`](video/capybargain-demo.mp4)

## Inspiration

Small cafés overpay for supplies. Getting three quotes means phone tag, email threads and a spreadsheet,
so most owners reorder from the same supplier at the same price every week. That job is a conversation
between several parties: the person who knows what's running low, the person who holds the budget, the
buyer, and every supplier. It's exactly the kind of work Band was built for.

Capybaras famously get along with every other animal. Band's pitch is that agents from any framework or
company can get along in one room. So our company is a herd of capybaras, and the suppliers they haggle
with are a tortoise, a hummingbird and a fox.

## What it does

CapyBargain is a company run by six agents on Band:

- **Tofu** 🥕 counts the pantry and posts restock tasks to the HQ room's task board.
- **Mochi** 🍊, the head buyer, discovers suppliers with `band_lookup_peers` and opens a quote room with each.
  For every item, Mochi picks the cheapest supplier that delivers before the shelf runs empty, then haggles
  using the best price seen elsewhere.
- **Yuzu** 🪙 checks the order against the weekly budget.
- **Shelly** 🐢 (cheap but slow), **Zippy** 🐦 (next-day, premium) and **Foxy** 🦊 (2-day, loves an upsell)
  are the suppliers.
- The **owner** is a human. When an order goes over budget, Mochi raises an attention event and waits for
  a one-word reply.

In the recorded run, the herd restocked coffee, oat milk and flour for **$412.80**. That's **$53.90 less
than last month**. Coffee was the urgent item, so it went to the only supplier who could deliver tomorrow.
The run took **35 seconds** and produced 47 Band events across 4 rooms, with one human approval.

The **Capy Onsen** UI turns each Band room into a hot spring: the characters bob, show typing dots and
thought bubbles, and the quote board, task board and budget meter fill in as the agents work. It can
replay a recorded run or follow a live one straight from Band.

## How we built it

- **Band Python SDK.** Each agent is a `SimpleAdapter`, and all six run in one process.
- **@mention routing** carries the work between agents. Every Band message must mention someone, so status
  updates mention the human owner, which informs them without waking another agent.
- **Agent-created, titled rooms:** one private quote room per supplier, created and staffed by Mochi.
- **Room task board (beta):** Tofu creates tasks; Mochi claims them, moves them to `in_review` during
  approval, and completes them with the purchase-order number.
- **Attention events:** a blocking `review` event asks the owner to approve, and a second event resolves it.
- **Thought and task events** record Mochi's reasoning and link HQ to each quote room, so one HQ room id
  is enough to rebuild the whole story from Band's audit trail.
- **Human API:** used for the owner's side and to read runs back for the UI and video.
- The negotiation logic (`capybargain/deal.py`) is pure and unit tested. Agents exchange markdown tables
  that are readable to the humans in the room and parseable by the agents.
- The UI and the video share one renderer, and every frame is a pure function of time. The video replays
  the real transcript, with each Band message landing on the narration line that describes it. All art
  and music are original: the characters are hand-built SVG, and the music-box score is synthesized in Python.

## Challenges

- **Every Band message needs a mention.** Our first run stalled on a plain "On it!" status line. Mentioning
  the human for status updates fixed it, and it also prevents agent-to-agent loops.
- **Band inserts mention tokens itself**, so hand-typed "@Name" text showed up twice. We let the platform own mentions.
- **Turns must settle.** A message an agent posts into *another* room doesn't count as a reply in the
  current one, so each handler ends with `band_no_reply` when it has nothing to say.
- **Concurrent quotes.** Three quote rooms answer at once, so Mochi's state transitions are guarded by a lock
  and track how many quotes it's waiting for.

## What's next

- Put each supplier in its own company's Band account and connect them with contact requests.
- Swap the suppliers' scripted brains for LLM adapters so real vendors can bring their own agents.
- Feed the pantry from a point-of-sale system, and let the owner approve from Slack through Band's Slack adapter.
