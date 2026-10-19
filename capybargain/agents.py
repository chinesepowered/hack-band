"""The Capy Café herd. Each agent is a Band ``SimpleAdapter``.

The agents never call each other directly. Everything goes through Band chat
rooms: @mentions route work, markdown tables carry the numbers, the room's
task board tracks progress, and an ``attention`` event asks the human owner
for approval.

Every message has two parts: a line in the agent's own voice, written by the
LLM when one is configured (see llm.py), and a payload written by code: the
tables and marker lines the other agents parse. The model can be as chatty as
it likes without breaking a handoff. It also makes the real negotiation moves,
Mochi's asks and each supplier's concessions, inside limits enforced by
deal.py.

Rooms:
  ☕ Capy Café HQ          owner + Mochi + Tofu + Yuzu (task board lives here)
  🐢 Shelly × Capy Café    Mochi + Shelly (+ owner, watching)
  🐦 Zippy × Capy Café     Mochi + Zippy  (+ owner, watching)
  🦊 Foxy × Capy Café      Mochi + Foxy   (+ owner, watching)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from band.core import AgentToolsProtocol, SimpleAdapter
from band.core.types import PlatformMessage
from band.runtime.tools.agent import AgentTools
from band_rest import ChatRoomRequest

from capybargain import deal, llm
from capybargain.deal import money, plural
from capybargain.pantry import (
    PANTRY,
    PANTRY_BY_NAME,
    SPENT_THIS_WEEK,
    SUPPLIER_PROFILES,
    WEEKLY_BUDGET,
    SupplierProfile,
)
from capybargain.roster import MOCHI, SUPPLIER_PREFIX, TOFU, YUZU, Member

log = logging.getLogger("capybargain")

HQ_TITLE = "☕ Capy Café HQ"

CAPY_EMOJI = (
    " There is no capybara emoji, so never use 🦫, 🐹, 🐿️ or 🐭 for yourself; 🍊, 🌿 and ☕ suit you."
)

PERSONAS = {
    "Tofu": (
        "You are Tofu, the pantry keeper at Capy Café: a capybara in a tiny chef hat who counts "
        "everything twice and gets a little dramatic when something runs low." + CAPY_EMOJI
    ),
    "Mochi": (
        "You are Mochi, head buyer at Capy Café: a calm, polite capybara with a yuzu on your head. "
        "You haggle gently but firmly, thank everyone, and never buy extras that aren't on the list." + CAPY_EMOJI
    ),
    "Yuzu": (
        "You are Yuzu, Capy Café's treasurer: a careful capybara with round glasses and a gold coin "
        "on your head. You love a balanced budget and say things plainly." + CAPY_EMOJI
    ),
    "Shelly": (
        "You are Shelly, a slow and steady tortoise who runs Slow & Steady Farm. Your prices are the "
        "lowest around, but deliveries take 4 days. You speak slowly and kindly, with farm and tortoise jokes."
    ),
    "Zippy": (
        "You are Zippy, a speedy hummingbird who runs Zippy Express Pantry: next-day delivery at "
        "premium prices. You talk fast and excited, with zoom and wing jokes."
    ),
    "Foxy": (
        "You are Foxy, a charming fox who runs Foxy Wholesale: 2-day delivery, fair prices, and you "
        "always try to upsell your honey bundle. Smooth, flattering and a little cheeky."
    ),
}

# How each supplier haggles. The model decides; deal.concession_bounds keeps it honest.
HAGGLE = {
    "Shelly": "You rarely move far: shave a few cents at most. Slow and steady.",
    "Zippy": "Speed is worth paying for, but for a polite customer you'll meet them partway.",
    "Foxy": "You'll sweeten the price, especially once your honey bundle is declined.",
}

MENTION_TOKEN = re.compile(r"@\[\[[0-9a-f-]{36}\]\]\s*")


def pace() -> float:
    """Multiplier for the agents' "thinking" pauses (CAPY_PACE). 0 makes the herd instant."""
    return float(os.environ.get("CAPY_PACE", "1"))


def when(days: int) -> str:
    if days == 1:
        return "tomorrow"
    return "on " + (date.today() + timedelta(days=days)).strftime("%A")


def plain(content: str) -> str:
    """A message without Band's mention tokens, for the model to read."""
    return MENTION_TOKEN.sub("", content).strip()


def compose(voice: str, payload: str) -> str:
    return f"{voice}\n\n{payload}" if voice else payload


def by_item(raw: Any, items: list[str]) -> dict[str, Any]:
    """Match the model's item keys ("Coffee Beans", "coffee") to our item names."""
    if not isinstance(raw, Mapping):
        return {}
    out = {}
    for key, value in raw.items():
        k = str(key).strip().lower()
        for item in items:
            if k == item or k in item or item in k:
                out[item] = value
    return out


async def quietly(what: str, call: Awaitable[Any]) -> Any:
    """Run a nice-to-have platform call (board, events) without derailing the deal."""
    try:
        return await call
    except Exception as exc:  # noqa: BLE001
        log.warning("%s failed: %s", what, exc)
        return None


class CapyAgent(SimpleAdapter[Any]):
    """Shared plumbing: voice, pacing, error reporting, and always settling the turn."""

    idle_line = "Hi! 🍊"

    def __init__(self, member: Member) -> None:
        super().__init__()
        self.member = member
        self.persona = PERSONAS[member.name]

    async def nap(self, seconds: float) -> None:
        await asyncio.sleep(seconds * pace())

    async def say(self, task: str, fallback: str, facts: str = "", prices: bool = True) -> str:
        return await llm.line(self.persona, task, fallback=fallback, facts=facts, prices=prices)

    def context(self) -> str:
        """What this agent knows right now, for answering people."""
        return ""

    async def chat(self, msg: PlatformMessage, tools: AgentToolsProtocol) -> None:
        """Answer a person who talks to this agent outside the restock flow."""
        reply = await self.say(
            f'The café owner says to you: "{plain(msg.content)}". Answer them helpfully, in character.',
            fallback=self.idle_line,
            facts=self.context(),
        )
        await tools.send_message(reply, mentions=[self.human(tools) or msg.sender_name])

    async def on_message(
        self,
        msg: PlatformMessage,
        tools: AgentToolsProtocol,
        history: Any,
        participants_msg: str | None,
        contacts_msg: str | None,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        try:
            await self.handle(msg, tools, room_id)
        except Exception as exc:  # noqa: BLE001
            # Report instead of raising: a raised error makes Band retry the
            # message, and a retried negotiation step would run twice.
            log.exception("%s failed on message %s", self.member.name, msg.id)
            await quietly("error event", tools.send_event(f"{self.member.name} tripped: {exc}", "error"))
        if not tools.turn.replied:
            await tools.no_reply("nothing to add")

    async def handle(self, msg: PlatformMessage, tools: AgentToolsProtocol, room_id: str) -> None:
        raise NotImplementedError

    @staticmethod
    def human(tools: AgentToolsProtocol) -> str | None:
        """Handle of a person in the room.

        Band requires every message to @mention someone. Mentioning a person
        keeps them in the loop without waking another agent, which is how
        status updates avoid agent-to-agent ping-pong.
        """
        person = next((p for p in tools.participants if p.get("type") == "User"), None)
        return (person.get("handle") or person.get("name")) if person else None


# --- Tofu: pantry keeper ---------------------------------------------------------------------

PANTRY_REQUEST = re.compile(r"pantry\s*check|check (the )?pantry|restock", re.IGNORECASE)


class Tofu(CapyAgent):
    idle_line = "🥕 I count the pantry! Ask me for a *pantry check*."

    def __init__(self) -> None:
        super().__init__(TOFU)

    def context(self) -> str:
        return "The pantry right now: " + "; ".join(
            f"{i.name}: {plural(int(i.on_hand), i.unit)} on the shelf, runs out in {plural(i.deadline_days, 'day')}"
            for i in PANTRY
        )

    async def handle(self, msg, tools, room_id):
        if not PANTRY_REQUEST.search(msg.content):
            if msg.sender_type == "User":
                await self.chat(msg, tools)
            return
        await self.nap(1.5)
        counted = ", ".join(f"{item.name} {plural(int(item.on_hand), item.unit)}" for item in PANTRY)
        await quietly("thought", tools.send_event(f"Counting the shelves… {counted}", "thought"))

        low = deal.restock_list(PANTRY)
        if not low:
            await tools.send_message("All stocked up! 🥕 Nothing to order today.", mentions=[self.human(tools)])
            return
        for item in low:
            await quietly(
                "create task",
                tools.create_task(
                    subject=f"Restock {item.name} · {plural(item.qty, item.unit)}",
                    detail=f"Runs out in {plural(item.deadline_days, 'day')}. Found by Tofu's pantry check.",
                ),
            )

        urgent = low[0]
        runs_out = "tomorrow" if urgent.deadline_days == 1 else f"in {plural(urgent.deadline_days, 'day')}"
        verb = "run" if urgent.name.endswith("s") else "runs"
        fine = " and ".join(item.name for item in PANTRY if not item.is_low)
        voice = await self.say(
            "Tell Mochi what is running low and ask Mochi to restock it. Make the most urgent item sound urgent.",
            fallback=f"Morning pantry check is done! {urgent.name.capitalize()} {verb} out **{runs_out}** 😱 Could you restock everything?",
            facts="Running low: "
            + "; ".join(f"{i.name}, runs out in {plural(i.deadline_days, 'day')}" for i in low)
            + f". These are fine: {fine}.",
        )
        payload = (
            f"🥕 **Pantry check: running low**\n\n{deal.format_restock_table(PANTRY)}\n\n"
            f"⏰ Most urgent: {urgent.name} ({verb} out {runs_out}) · 👍 Fine: {fine}"
        )
        await tools.send_message(compose(voice, payload), mentions=[MOCHI.name])


# --- Yuzu: treasurer ---------------------------------------------------------------------------


class Yuzu(CapyAgent):
    idle_line = "🪙 I keep the café's budget! Mochi asks me before anything is ordered."

    def __init__(self) -> None:
        super().__init__(YUZU)
        self.spent = SPENT_THIS_WEEK

    def context(self) -> str:
        return (
            f"Weekly purchasing budget {money(WEEKLY_BUDGET)}; spent so far this week {money(self.spent)}; "
            f"left {money(WEEKLY_BUDGET - self.spent)}."
        )

    async def handle(self, msg, tools, room_id):
        await self.nap(1.2)
        if logged := re.search(r"log\s+(\$[0-9,]+\.[0-9]{2})", msg.content, re.IGNORECASE):
            amount = deal.parse_money(logged.group(1))
            self.spent += amount
            extra = self.spent - WEEKLY_BUDGET
            note = f" (owner-approved +{money(extra)})" if extra > 0 else ""
            voice = await self.say(
                "Confirm that you logged the spend in the books.",
                fallback="Logged! 🪙",
                facts=f"Logged {money(amount)}. This week: {money(self.spent)} of {money(WEEKLY_BUDGET)}{note}.",
            )
            payload = f"📒 **Logged** {money(amount)} for the pantry restock · this week {money(self.spent)} of {money(WEEKLY_BUDGET)}{note}"
            await tools.send_message(compose(voice, payload), mentions=[self.human(tools)])
        elif planned := re.search(r"Planned order \**(\$[0-9,]+\.[0-9]{2})", msg.content):
            check = deal.BudgetCheck(WEEKLY_BUDGET, self.spent, deal.parse_money(planned.group(1)))
            verdict = (
                "✅ **Within budget** · go for it!"
                if check.within
                else f"⚠️ **Over budget by {money(check.over_by)}** · this one needs the boss's OK"
            )
            voice = await self.say(
                "Tell Mochi the result of your budget check. If it is over budget, say the boss (the café "
                "owner, a person) must approve it; Mochi will ask them.",
                fallback="🪙 Budget check done!",
                facts=(
                    f"Weekly budget {money(check.budget)}, spent {money(check.spent)}, left {money(check.left)}, "
                    f"this order {money(check.order)}. "
                    + ("It fits the budget." if check.within else f"It is {money(check.over_by)} over, so the owner must approve it.")
                ),
            )
            table = deal.md_table(
                ["weekly budget", "spent so far", "left", "this order"],
                [[money(check.budget), money(check.spent), money(check.left), money(check.order)]],
            )
            await tools.send_message(compose(voice, f"{table}\n\n{verdict}"), mentions=[msg.sender_name])
        elif msg.sender_type == "User":
            await self.chat(msg, tools)


# --- Suppliers: Shelly, Zippy, Foxy ---------------------------------------------------------------


@dataclass(frozen=True)
class Voice:
    """Built-in lines, used when no model is configured or a call fails."""

    hello: str
    final: str
    confirm: str
    no_deal: str
    upsell_declined: str = ""


VOICES = {
    "Shelly": Voice(
        hello="Hello hello, friend! 🐢🌿 Here's my quote.",
        final="Mmm… I can shave a little off. Slow and steady wins the race 🐢",
        confirm="Packing it up nice and steady 🐢💚",
        no_deal="No worries at all! Maybe next time 🐢🌿",
    ),
    "Zippy": Voice(
        hello="Zip zip! 🐦⚡ Quote, hot off the wing!",
        final="For a capybara this polite? I'll flap a little harder 🐦",
        confirm="Zooming over by 8am! 🐦⚡",
        no_deal="Zip! Next time then 🐦",
    ),
    "Foxy": Voice(
        hello="Well hello there, darling capybara 🦊✨ A deal just for you.",
        final="Fine, fine 🦊",
        upsell_declined="Okay, okay, no honey 🦊 Here's my very best.",
        confirm="Pleasure doing business 🦊 (The honey offer stands forever 😉)",
        no_deal="Your loss, sweetie 🦊 …kidding! Next time ✨",
    ),
}

# Slower animals think slower. It's a tortoise.
THINKING_SECONDS = {"Shelly": 3.5, "Zippy": 1.0, "Foxy": 2.0}


class Supplier(CapyAgent):
    def __init__(self, member: Member) -> None:
        super().__init__(member)
        self.profile: SupplierProfile = SUPPLIER_PROFILES[member.name]
        self.voice = VOICES[member.name]
        self.idle_line = self.voice.hello

    def context(self) -> str:
        prices = ", ".join(f"{item} {money(price)}" for item, price in self.profile.prices.items())
        upsell = self.profile.upsell
        extra = f" You also sell a {upsell.name} ({upsell.blurb}) for {money(upsell.price)}." if upsell else ""
        return f"Your price list: {prices}. Delivery takes {plural(self.profile.delivery_days, 'day')}.{extra}"

    async def handle(self, msg, tools, room_id):
        text = msg.content
        lowered = text.lower()
        buyer = msg.sender_name or MOCHI.name
        days = self.profile.delivery_days
        name = self.member.name
        await self.nap(THINKING_SECONDS[name] * (0.5 if llm.enabled() else 1))

        if "needed within" in lowered:
            quote = deal.build_quote(self.profile, deal.parse_rfq_table(text))
            voice = await self.say(
                "Mochi from Capy Café asked you for a quote. Reply with a short, in-character pitch. "
                "Don't state prices: the table under your message shows them."
                + (" Tease your honey bundle." if self.profile.upsell else ""),
                fallback=self.voice.hello,
                facts=f"You deliver in {plural(days, 'day')}. Items asked for: {', '.join(line.item for line in quote.lines)}.",
                prices=False,
            )
            payload = (
                f"{deal.format_quote_table(quote)}\n\n"
                f"**Total: {money(quote.total)}** · 🚚 delivery in **{plural(days, 'day')}**"
            )
            if upsell := self.profile.upsell:
                payload += f"\n\n🍯 Psst… add our **{upsell.name}** ({upsell.blurb}) for just **{money(upsell.price)}**?"
            await tools.send_message(compose(voice, payload), mentions=[buyer])
        elif "could you do" in lowered:
            counters = deal.parse_counter_table(text)
            declined = bool(self.profile.upsell) and "no honey" in lowered
            facts = ["Mochi from Capy Café is haggling."]
            for c in counters:
                low, high = deal.concession_bounds(self.profile, c)
                facts.append(
                    f"{c.line.item} ({plural(c.line.qty, c.line.unit)}): you quoted {money(high)} each, "
                    f"Mochi asks {money(c.target)}. You can't go below {money(low)}."
                )
            if declined:
                facts.append("Mochi politely declined your honey bundle.")
            decision = await llm.decide(
                self.persona,
                f"{HAGGLE[name]} Decide your final unit price for each item, then write your reply. "
                'Return JSON: {"prices": {"<item>": <number>}, "line": "<one or two short sentences in '
                'character; do not state any numbers or mention your limits>"}',
                facts="\n".join(facts),
                fallback={},
            )
            prices = by_item(decision.get("prices"), [c.line.item for c in counters])
            final = deal.respond_to_counters(self.profile, counters, prices=prices or None)
            voice = llm.without_prices(llm.tidy(str(decision.get("line") or ""))) or (
                self.voice.upsell_declined if declined else self.voice.final
            )
            payload = (
                f"**Final offer**\n\n{deal.format_quote_table(final)}\n\n"
                f"**Total: {money(final.total)}** · 🚚 delivery in **{plural(days, 'day')}**"
            )
            await tools.send_message(compose(voice, payload), mentions=[buyer])
        elif "purchase order" in lowered:
            po = re.search(r"CAPY-[0-9A-Z-]+", text)
            number = po.group(0) if po else "the order"
            voice = await self.say(
                f"Mochi just placed the order. Thank Mochi and confirm it arrives {when(days)}.",
                fallback=self.voice.confirm,
                prices=False,
            )
            payload = f"📦 Order **{number}** confirmed · arriving **{when(days)}**"
            await tools.send_message(compose(voice, payload), mentions=[buyer])
        elif "not this time" in lowered:
            await tools.send_message(self.voice.no_deal, mentions=[self.human(tools) or buyer])
        elif msg.sender_type == "User":
            await self.chat(msg, tools)


# --- Mochi: head buyer -------------------------------------------------------------------------------


@dataclass
class Deal:
    hq_room: str
    hq: AgentTools
    owner: dict[str, Any] | None
    items: list[deal.LineItem]
    expected: int = 0  # suppliers we asked for a quote
    expected_finals: int = 0  # suppliers we sent a counter-offer
    rooms: dict[str, AgentTools] = field(default_factory=dict)  # supplier -> quote room tools
    room_ids: dict[str, str] = field(default_factory=dict)  # quote room id -> supplier
    quotes: dict[str, deal.Quote] = field(default_factory=dict)
    awards: dict[str, deal.Award] = field(default_factory=dict)
    counters: dict[str, list[deal.Counter]] = field(default_factory=dict)
    finals: dict[str, deal.Quote] = field(default_factory=dict)
    orders: dict[str, str] = field(default_factory=dict)  # supplier -> PO number
    confirmed: set[str] = field(default_factory=set)
    tasks: dict[str, str] = field(default_factory=dict)  # item -> task id
    attention_id: str | None = None
    stage: str = "quoting"

    @property
    def total(self) -> Decimal:
        return deal.order_total(self.finals.values())

    def savings(self) -> tuple[Decimal, Decimal, int]:
        last_paid = {name: item.last_paid for name, item in PANTRY_BY_NAME.items()}
        before = deal.last_month_cost(self.finals.values(), last_paid)
        saved = before - self.total
        return before, saved, round(saved / before * 100) if before else 0


ApprovalHook = Callable[[str], Awaitable[None]]


class Mochi(CapyAgent):
    idle_line = "Hi boss! 🍊 Ask Tofu for a pantry check (`@Tofu pantry check`) and I'll take it from there."

    def __init__(self, on_approval_requested: ApprovalHook | None = None) -> None:
        super().__init__(MOCHI)
        self.deal: Deal | None = None
        self.lock = asyncio.Lock()
        self.on_approval_requested = on_approval_requested
        self.finished = asyncio.Event()
        self.rest: Any = None

    async def on_started(self, agent_name: str, agent_description: str) -> None:
        await super().on_started(agent_name, agent_description)
        self.rest = self.build_rest_client()
        self.agent_id = self.require_platform().agent_id

    def tools_for(self, room_id: str, participants: list[dict[str, Any]] | None = None) -> AgentTools:
        """Tools bound to a room, usable outside the turn that is running now."""
        return AgentTools(room_id, self.rest, participants or [], agent_id=self.agent_id)

    def context(self) -> str:
        d = self.deal
        if not d:
            return "No restock is in progress. Tofu does the pantry check, then you buy what's low."
        parts = [f"A restock is in progress (stage: {d.stage})."]
        parts.append("Shopping list: " + ", ".join(f"{i.name} {plural(i.qty, i.unit)}" for i in d.items) + ".")
        if d.quotes:
            parts.append(
                "Quotes: "
                + "; ".join(f"{q.supplier} {money(q.total)} total, {plural(q.delivery_days, 'day')} delivery" for q in d.quotes.values())
                + "."
            )
        if d.awards:
            parts.append(
                "You picked the cheapest supplier that arrives before each shelf runs empty: "
                + ", ".join(f"{a.item.name} from {a.supplier}" for a in d.awards.values())
                + "."
            )
        if d.finals:
            before, saved, pct = d.savings()
            parts.append(f"Final offers total {money(d.total)}, {money(saved)} less than last month.")
        if d.orders:
            parts.append("Orders placed: " + ", ".join(f"{po} with {s}" for s, po in d.orders.items()) + ".")
        return " ".join(parts)

    # -- routing --

    async def handle(self, msg, tools, room_id):
        d = self.deal
        if msg.sender_name == TOFU.name and "running low" in msg.content:
            await self.start_deal(msg, tools, room_id)
        elif msg.sender_type == "User":
            if d and d.stage == "approval" and room_id == d.hq_room:
                await self.on_owner_reply(d, msg, tools)
            else:
                await self.chat(msg, tools)
        elif d and room_id in d.room_ids:
            await self.on_supplier_message(d, msg, tools)
        elif d and msg.sender_name == YUZU.name and d.stage == "budget":
            await self.on_budget(d, msg)

    # -- step 1: find suppliers and ask for quotes --

    async def start_deal(self, msg, tools, hq_room):
        items = deal.parse_restock_table(msg.content)
        hq = self.tools_for(hq_room, list(tools.participants))
        owner = next((p for p in tools.participants if p.get("type") == "User"), None)
        self.deal = d = Deal(hq_room=hq_room, hq=hq, owner=owner, items=items)
        self.finished.clear()
        await self.nap(1.0)

        await quietly(
            "set board",
            hq.set_board(
                goal_title="Restock Capy Café's pantry 🍊",
                goal_summary="Best price, delivered before the shelf runs empty, within budget.",
            ),
        )
        listed = await quietly("list tasks", hq.list_tasks())
        for task in getattr(listed, "data", None) or []:
            for item in items:
                if task.subject.startswith(f"Restock {item.name}"):
                    d.tasks[item.name] = task.id

        suppliers = await self.find_suppliers(tools)
        names = ", ".join(f"{s['name']} {self.emoji(s)}" for s in suppliers)
        await quietly(
            "thought",
            tools.send_event(
                f"band_lookup_peers → {len(suppliers)} suppliers ({names}) out of all my peers",
                "thought",
                {"suppliers": [s["name"] for s in suppliers]},
            ),
        )
        if not suppliers:
            await tools.send_message(
                "Hmm 🍊 I couldn't find any suppliers on Band. Are they online?", mentions=[self.human(tools)]
            )
            return
        d.expected = len(suppliers)
        log.info("🍊 Mochi found %d suppliers: %s", len(suppliers), names)
        await self.set_tasks(d, status="in_progress", active_form=f"Collecting quotes from {len(suppliers)} suppliers")
        voice = await self.say(
            "Tell Tofu and the boss you're on it: you found suppliers on Band and are opening a quote room with each.",
            fallback="On it, Tofu! 🍊 Back soon with the best deal!",
            facts=f"Suppliers found: {names}.",
        )
        payload = f"**On it!** Found **{len(suppliers)} suppliers** on Band: {self.oxford(suppliers)} · opening a quote room with each"
        await tools.send_message(compose(voice, payload), mentions=[self.human(tools)])
        await asyncio.gather(*(self.request_quote(d, s) for s in suppliers))

    async def find_suppliers(self, tools) -> list[dict[str, Any]]:
        peers, page = [], 1
        while True:
            resp = await tools.lookup_peers(page=page, page_size=100)
            batch = [p.model_dump() if hasattr(p, "model_dump") else dict(p) for p in resp.data or []]
            peers += batch
            meta = getattr(resp, "metadata", None)
            if not batch or not meta or page >= (getattr(meta, "total_pages", 1) or 1):
                break
            page += 1
        return [p for p in peers if (p.get("description") or "").startswith(SUPPLIER_PREFIX)]

    @staticmethod
    def emoji(peer: dict[str, Any]) -> str:
        found = re.search(r"([🐢🐦🦊🐝🐻🦉🐸🐧🦆🐰])", peer.get("description") or "")
        return found.group(1) if found else "🛒"

    def oxford(self, peers: list[dict[str, Any]]) -> str:
        names = [f"{p['name']} {self.emoji(p)}" for p in peers]
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]

    async def request_quote(self, d: Deal, supplier: dict[str, Any]) -> None:
        name = supplier["name"]
        created = await self.rest.agent_api_chats.create_agent_chat(
            chat=ChatRoomRequest(title=f"{self.emoji(supplier)} {name} × Capy Café")
        )
        room = self.tools_for(created.data.id)
        await room.add_participant(supplier.get("handle") or name)
        if d.owner:  # the owner can watch every negotiation live
            await quietly("add owner", room.add_participant(d.owner.get("handle") or d.owner["id"]))
        d.rooms[name] = room
        d.room_ids[created.data.id] = name
        await quietly(
            "link room",
            d.hq.send_event(
                f"Opened a quote room with {name} {self.emoji(supplier)}",
                "task",
                {"quote_room_id": created.data.id, "supplier": name},
            ),
        )
        voice = await self.say(
            f"Greet {name}, a supplier, warmly and ask for their best price and delivery time on the list.",
            fallback="Hi friend! 🍊 Capy Café would love a quote.",
            facts="Capy Café needs: " + ", ".join(f"{i.name} ({plural(i.qty, i.unit)})" for i in d.items) + ".",
        )
        await self.nap(0.5)
        await room.send_message(
            compose(voice, f"{deal.format_rfq_table(d.items)}\n\nWhat's your best price and delivery time?"),
            mentions=[name],
        )

    # -- steps 2 and 3: quotes in, counter-offers out; final offers in, budget check --

    async def on_supplier_message(self, d: Deal, msg, tools):
        supplier = msg.sender_name
        if supplier not in d.rooms:
            return
        async with self.lock:
            if d.stage == "quoting" and supplier not in d.quotes:
                d.quotes[supplier] = deal.parse_quote(supplier, msg.content)
                log.info("📨 quote from %s: %s", supplier, money(d.quotes[supplier].total))
                await quietly(
                    "thought",
                    tools.send_event(f"Got {supplier}'s quote ({len(d.quotes)}/{d.expected})", "thought"),
                )
                if len(d.quotes) < d.expected:
                    return
                d.stage = "haggling"
                ready = "counter"
            elif d.stage == "haggling" and supplier in d.counters and supplier not in d.finals:
                d.finals[supplier] = deal.parse_quote(supplier, msg.content)
                log.info("🤝 final offer from %s: %s", supplier, money(d.finals[supplier].total))
                if len(d.finals) < d.expected_finals:
                    return
                d.stage = "budget"
                ready = "budget"
            elif d.stage == "ordering" and supplier in d.orders and "confirmed" in msg.content.lower():
                d.confirmed.add(supplier)
                log.info("📦 %s confirmed %s", supplier, d.orders[supplier])
                await self.set_task_for(
                    d,
                    supplier,
                    status="completed",
                    active_form=f"{d.orders[supplier]} confirmed, arriving {when(d.finals[supplier].delivery_days)}",
                    comment=f"{d.orders[supplier]} · {supplier} · {money(d.finals[supplier].total)} · "
                    f"arrives {when(d.finals[supplier].delivery_days)}",
                )
                if d.confirmed != set(d.orders):
                    return
                d.stage = "done"
                ready = "receipt"
            else:
                return

        if ready == "counter":
            await self.send_counters(d)
        elif ready == "budget":
            await self.ask_budget(d)
        else:
            await self.post_receipt(d)

    async def send_counters(self, d: Deal) -> None:
        await self.nap(1.0)
        d.awards = deal.choose_winners(d.items, d.quotes)
        winners = {a.supplier for a in d.awards.values()}
        d.expected_finals = len(winners)

        reasons = []
        for award in d.awards.values():
            item, slower = award.item, []
            for q in d.quotes.values():
                line = q.line(item.name)
                if line and q.delivery_days > item.deadline_days and line.unit_price < award.line.unit_price:
                    slower.append(f"{q.supplier} is cheaper but takes {plural(q.delivery_days, 'day')}")
            why = f"{item.name}: runs out in {plural(item.deadline_days, 'day')} → {award.supplier}"
            reasons.append(why + (f" ({'; '.join(slower)})" if slower else " (cheapest that arrives in time)"))
        await quietly("thought", d.hq.send_event("Picking winners: " + " · ".join(reasons), "thought"))
        for award in d.awards.values():
            await self.set_task(d, award.item.name, active_form=f"Haggling with {award.supplier}")
        await asyncio.gather(*(self.counter_one(d, supplier, supplier in winners) for supplier in d.rooms))

    async def counter_one(self, d: Deal, supplier: str, won: bool) -> None:
        room = d.rooms[supplier]
        if not won:
            voice = await self.say(
                f"Thank {supplier} for the quote and say kindly that it's not this time.",
                fallback="Thank you so much for the quote! 🍊",
            )
            await room.send_message(compose(voice, "Not this time, but we'll be back 🍊"), mentions=[supplier])
            return
        awards = {k: a for k, a in d.awards.items() if a.supplier == supplier}
        planned = deal.counter_offers(awards, d.quotes)[supplier]  # the built-in policy, also the fallback
        upsell = d.quotes[supplier].upsell
        facts = [f"You are haggling with {supplier}."]
        for c in planned:
            low, high = deal.ask_bounds(c.line.unit_price)
            elsewhere = (
                f"another supplier offered {money(c.seen_elsewhere)} but delivers too slowly"
                if c.seen_elsewhere
                else f"{supplier} is already the cheapest"
            )
            facts.append(
                f"{c.line.item} ({plural(c.line.qty, c.line.unit)}): {supplier} quoted {money(c.line.unit_price)}; "
                f"{elsewhere}. Ask for something between {money(low)} and {money(high)}."
            )
        if upsell:
            facts.append(f"{supplier} also tried to upsell a honey bundle. Café policy: never buy extras.")
        ask = "thank them and gently ask for a better price" + (", and politely decline the honey bundle" if upsell else "")
        decision = await llm.decide(
            self.persona,
            "Decide the unit price to ask for each item, then write your message. Return JSON: "
            f'{{"asks": {{"<item>": <number>}}, "line": "<one or two short, warm sentences to {supplier}: {ask}; '
            'do not state any numbers>"}',
            facts="\n".join(facts),
            fallback={},
        )
        asks = by_item(decision.get("asks"), [c.line.item for c in planned])
        counters = deal.counter_offers(awards, d.quotes, asks=asks or None)[supplier]
        voice = llm.without_prices(llm.tidy(str(decision.get("line") or ""))) or "Thank you! 🍊 Could you meet me here?"
        lines = []
        if upsell:
            lines.append("🍯 No honey today, thanks, just the list.")
        leverage = [c for c in counters if c.seen_elsewhere is not None]
        for c in leverage:
            lines.append(f"Best price I've seen elsewhere: {c.line.item} at **{money(c.seen_elsewhere)}/{c.line.unit}**.")
        if not leverage:
            lines.append("You're already the cheapest ✨ any wiggle room for a regular customer?")
        d.counters[supplier] = counters
        await room.send_message(
            compose(voice, "\n".join(lines) + f"\n\n{deal.format_counter_table(counters)}"),
            mentions=[supplier],
        )

    async def ask_budget(self, d: Deal) -> None:
        await self.nap(1.0)
        parts = " · ".join(
            f"{line.item} {money(line.subtotal)} ({q.supplier})" for q in d.finals.values() for line in q.lines
        )
        await self.set_tasks(d, active_form="Final offers are in, checking the budget with Yuzu")
        voice = await self.say(
            "Final offers are in. Ask Yuzu, the treasurer, to check this order against the weekly budget. "
            "Only ask; you don't approve anything yourself.",
            fallback="Final offers are in! 🍊",
            facts=f"Order total {money(d.total)}: {parts}.",
        )
        await d.hq.send_message(
            compose(voice, f"🪙 **Budget check:** Planned order **{money(d.total)}**\n{parts}"),
            mentions=[YUZU.name],
        )

    # -- step 4: budget verdict, maybe ask the owner --

    async def on_budget(self, d: Deal, msg) -> None:
        over_match = re.search(r"Over budget by \**(\$[0-9,]+\.[0-9]{2})", msg.content)
        if not over_match and "**Within budget**" in msg.content:
            await d.hq.send_message("Within budget, placing the orders now 🍊", mentions=[self.human(d.hq)])
            await self.place_orders(d)
            return
        d.stage = "approval"
        await self.nap(1.0)
        before, saved, pct = d.savings()
        over = deal.parse_money(over_match.group(1)) if over_match else d.total
        summary = deal.md_table(
            ["item", "from", "price", "arrives"],
            [
                [line.item, q.supplier, money(line.subtotal), when(q.delivery_days)]
                for q in d.finals.values()
                for line in q.lines
            ],
        )
        event = await quietly(
            "attention",
            d.hq.send_event(
                f"Approve pantry order: {money(d.total)} ({money(over)} over this week's budget)",
                "attention",
                {"kind": "review", "blocking": True, "amount": str(d.total), "over_budget_by": str(over)},
            ),
        )
        d.attention_id = getattr(event, "id", None) or getattr(getattr(event, "data", None), "id", None)
        log.info("🙋 Mochi asks the owner to approve %s (%s over budget)", money(d.total), money(over))
        await self.set_tasks(d, status="in_review", active_form="Waiting for the boss's OK")
        voice = await self.say(
            "You are talking to the boss, the café owner. Ask them to approve your order: mention the savings "
            "versus last month and that it is a little over this week's budget.",
            fallback="Boss! 🍊 I found a deal:",
            facts=f"Total {money(d.total)}, which is {money(saved)} less than last month. It is {money(over)} over this week's budget.",
        )
        payload = (
            f"{summary}\n\n**Total {money(d.total)}** · **{money(saved)} less** than last month (−{pct}%) · "
            f"**{money(over)} over** this week's budget\n\nReply **@{MOCHI.name} approve** or **@{MOCHI.name} no**."
        )
        owner = d.owner or {}
        handle = owner.get("handle") or owner.get("name")
        await d.hq.send_message(compose(voice, payload), mentions=[handle] if handle else None)
        if self.on_approval_requested:
            asyncio.create_task(self.on_approval_requested(d.hq_room))

    async def on_owner_reply(self, d: Deal, msg, tools) -> None:
        text = msg.content.lower()
        if re.search(r"\b(approve|approved|yes|ok|okay|go)\b", text):
            d.stage = "ordering"
            log.info("✅ owner approved")
            if d.attention_id:
                await quietly(
                    "resolve attention",
                    tools.send_event(
                        "Approved by the owner ✅",
                        "attention",
                        {"kind": "review", "resolves": d.attention_id, "resolution": "approved"},
                    ),
                )
            voice = await self.say(
                "The boss approved the order. Thank them and say you're placing the orders now.",
                fallback="Yay, thank you boss! 🎉",
            )
            await tools.send_message(compose(voice, "📤 Placing the orders now."), mentions=[self.human(tools)])
            await self.place_orders(d)
        elif re.search(r"\b(no|nope|cancel|decline)\b", text):
            d.stage = "cancelled"
            for supplier, room in d.rooms.items():
                await room.send_message(
                    "So sorry, not this time after all 🍊 Thank you for your patience!", mentions=[supplier]
                )
            await self.set_tasks(d, state="cancelled")
            await tools.send_message(
                "Okay boss, I cancelled everything 🍊 Nothing was ordered.", mentions=[self.human(tools)]
            )
            self.finished.set()
        else:
            voice = await self.say(
                f'The boss replied "{plain(msg.content)}" while you wait for an approve or no. Answer them, then ask again.',
                fallback="I just need a yes or no 🍊",
                facts=self.context(),
            )
            await tools.send_message(
                compose(voice, f"Reply **@{MOCHI.name} approve** or **@{MOCHI.name} no**."), mentions=[self.human(tools)]
            )

    # -- step 5: purchase orders and the receipt --

    async def place_orders(self, d: Deal) -> None:
        d.stage = "ordering"
        stamp = date.today().strftime("%m%d")
        for n, supplier in enumerate(d.finals, start=1):
            d.orders[supplier] = f"CAPY-{stamp}-{n}"
        await asyncio.gather(*(self.send_order(d, supplier) for supplier in d.finals))

    async def send_order(self, d: Deal, supplier: str) -> None:
        final, po = d.finals[supplier], d.orders[supplier]
        await self.set_task_for(d, supplier, status="in_progress", active_form=f"{po} sent to {supplier}")
        voice = await self.say(
            f"Tell {supplier} you accept their final offer and ask them to deliver {when(final.delivery_days)}.",
            fallback="Deal! ✅ Thank you, friend! 🍊",
            prices=False,
        )
        await d.rooms[supplier].send_message(
            compose(
                voice,
                f"✅ **Purchase order {po}**\n\n{deal.format_quote_table(final)}\n\n"
                f"**Total {money(final.total)}**, please deliver {when(final.delivery_days)}.",
            ),
            mentions=[supplier],
        )

    async def post_receipt(self, d: Deal) -> None:
        await self.nap(1.0)
        before, saved, pct = d.savings()
        rows = [
            [d.orders[s], s, ", ".join(line.item for line in q.lines), money(q.total), when(q.delivery_days)]
            for s, q in d.finals.items()
        ]
        table = deal.md_table(["order", "supplier", "items", "total", "arrives"], rows)
        voice = await self.say(
            "Celebrate with the team: every order is confirmed. Mention how much you saved versus last month.",
            fallback="Yay! 🍊🎉",
            facts=f"Total {money(d.total)}; {money(saved)} less than last month; coffee arrives tomorrow, before it runs out.",
        )
        payload = (
            f"🎉 **All done!** {len(rows)} orders placed and confirmed:\n\n{table}\n\n"
            f"**Total {money(d.total)}** · saved **{money(saved)}** vs last month (−{pct}%)\n\n"
            f"Yuzu, please log {money(d.total)} (approved by the boss) 🪙"
        )
        await d.hq.send_message(compose(voice, payload), mentions=[YUZU.name, self.human(d.hq)])
        log.info("🎉 done: %s total, saved %s", money(d.total), money(saved))
        self.finished.set()

    # -- task board helpers --

    async def set_task(self, d: Deal, item: str, **fields: Any) -> None:
        task_id = d.tasks.get(item)
        if task_id:
            await quietly("update task", d.hq.update_task(task_id, **fields))

    async def set_tasks(self, d: Deal, **fields: Any) -> None:
        for item in d.tasks:
            await self.set_task(d, item, **fields)

    async def set_task_for(self, d: Deal, supplier: str, **fields: Any) -> None:
        for line in d.finals[supplier].lines:
            await self.set_task(d, line.item, **fields)
