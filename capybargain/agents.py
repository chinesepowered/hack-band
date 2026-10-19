"""The Capy Café herd. Each agent is a Band ``SimpleAdapter``.

The agents never call each other directly. Everything goes through Band chat
rooms: @mentions route work, markdown tables carry the numbers, the room's
task board tracks progress, and an ``attention`` event asks the human owner
for approval.

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from band.core import AgentToolsProtocol, SimpleAdapter
from band.core.types import PlatformMessage
from band.runtime.tools.agent import AgentTools
from band_rest import ChatRoomRequest

from capybargain import deal
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


def pace() -> float:
    """Multiplier for the agents' "thinking" pauses (CAPY_PACE). 0 makes the herd instant."""
    return float(os.environ.get("CAPY_PACE", "1"))


HQ_TITLE = "☕ Capy Café HQ"


def when(days: int) -> str:
    if days == 1:
        return "tomorrow"
    return "on " + (date.today() + timedelta(days=days)).strftime("%A")


async def quietly(what: str, call: Awaitable[Any]) -> Any:
    """Run a nice-to-have platform call (board, events) without derailing the deal."""
    try:
        return await call
    except Exception as exc:  # noqa: BLE001
        log.warning("%s failed: %s", what, exc)
        return None


class CapyAgent(SimpleAdapter[Any]):
    """Shared plumbing: pacing, error reporting, and always settling the turn."""

    def __init__(self, member: Member) -> None:
        super().__init__()
        self.member = member

    async def nap(self, seconds: float) -> None:
        await asyncio.sleep(seconds * pace())

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


class Tofu(CapyAgent):
    def __init__(self) -> None:
        super().__init__(TOFU)

    async def handle(self, msg, tools, room_id):
        if not re.search(r"pantry|stock|shel(f|ves)", msg.content, re.IGNORECASE):
            if msg.sender_type == "User":
                await tools.send_message("🥕 I count the pantry! Ask me for a *pantry check*.", mentions=[self.human(tools)])
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
        await tools.send_message(
            f"🥕 Morning pantry check is done! These are running low:\n\n"
            f"{deal.format_restock_table(PANTRY)}\n\n"
            f"{urgent.name.capitalize()} {verb} out **{runs_out}** 😱 Could you restock everything? "
            f"({fine} are fine 👍)",
            mentions=[MOCHI.name],
        )


# --- Yuzu: treasurer ---------------------------------------------------------------------------


class Yuzu(CapyAgent):
    def __init__(self) -> None:
        super().__init__(YUZU)
        self.spent = SPENT_THIS_WEEK

    async def handle(self, msg, tools, room_id):
        text = msg.content.lower()
        await self.nap(1.2)
        if logged := re.search(r"log\s+(\$[0-9,]+\.[0-9]{2})", msg.content, re.IGNORECASE):
            amount = deal.parse_money(logged.group(1))
            self.spent += amount
            extra = self.spent - WEEKLY_BUDGET
            note = f" (owner-approved +{money(extra)})" if extra > 0 else ""
            await tools.send_message(
                f"Logged! 🪙 {money(amount)} for the pantry restock. "
                f"This week: {money(self.spent)} of {money(WEEKLY_BUDGET)}{note}.",
                mentions=[self.human(tools)],
            )
            return
        if "budget" in text:
            check = deal.BudgetCheck(WEEKLY_BUDGET, self.spent, deal.first_amount(msg.content))
            table = deal.md_table(
                ["weekly budget", "spent so far", "left", "this order"],
                [[money(check.budget), money(check.spent), money(check.left), money(check.order)]],
            )
            verdict = (
                "✅ Within budget, go for it!"
                if check.within
                else f"⚠️ That's **{money(check.over_by)} over**, so this one needs the boss's OK."
            )
            await tools.send_message(
                f"🪙 Budget check:\n\n{table}\n\n{verdict}",
                mentions=[msg.sender_name],
            )
            return
        if msg.sender_type == "User":
            await tools.send_message(
                "🪙 I keep the café's budget! Ask me for a *budget check* with an amount.",
                mentions=[self.human(tools)],
            )


# --- Suppliers: Shelly, Zippy, Foxy ---------------------------------------------------------------


@dataclass(frozen=True)
class Voice:
    hello: str
    quip: str
    final: str
    confirm: str
    no_deal: str
    upsell_declined: str = ""


VOICES = {
    "Shelly": Voice(
        hello="Hello hello, friend! 🐢🌿 Here's my quote:",
        quip="slow & steady!",
        final="Mmm… I can shave a little off. Slow and steady wins the race 🐢 **Final offer:**",
        confirm="Order **{po}** confirmed! 🐢💚 Packing it up nice and steady, arriving **{when}**.",
        no_deal="No worries at all! Maybe next time 🐢🌿",
    ),
    "Zippy": Voice(
        hello="Zip zip! 🐦⚡ Quote, hot off the wing:",
        quip="zoom zoom!",
        final="For a capybara this polite? I'll flap a little harder 🐦 **Final offer:**",
        confirm="Order **{po}** confirmed! 🐦⚡ Zooming over **{when}** by 8am!",
        no_deal="Zip! Next time then 🐦",
    ),
    "Foxy": Voice(
        hello="Well hello there, darling capybara 🦊✨ A deal just for you:",
        quip="quick and cozy",
        final="Fine, fine 🦊 **Final offer:**",
        upsell_declined="Okay, okay, no honey 🦊 Here's my very best:",
        confirm=(
            "Pleasure doing business 🦊 Order **{po}** confirmed, arriving **{when}**. "
            "(The honey offer stands forever 😉)"
        ),
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

    async def handle(self, msg, tools, room_id):
        text = msg.content
        lowered = text.lower()
        buyer = msg.sender_name or MOCHI.name
        days = self.profile.delivery_days
        await self.nap(THINKING_SECONDS[self.member.name])

        if "needed within" in lowered:
            quote = deal.build_quote(self.profile, deal.parse_rfq_table(text))
            reply = (
                f"{self.voice.hello}\n\n{deal.format_quote_table(quote)}\n\n"
                f"**Total: {money(quote.total)}** · 🚚 delivery in **{plural(days, 'day')}** ({self.voice.quip})"
            )
            if upsell := self.profile.upsell:
                reply += (
                    f"\n\n🍯 Psst… add our **{upsell.name}** ({upsell.blurb}) for just "
                    f"**{money(upsell.price)}**? Your customers would *love* it."
                )
            await tools.send_message(reply, mentions=[buyer])
        elif "could you do" in lowered:
            final = deal.respond_to_counters(self.profile, deal.parse_counter_table(text))
            declined = self.profile.upsell and "no honey" in lowered
            intro = self.voice.upsell_declined if declined else self.voice.final
            await tools.send_message(
                f"{intro}\n\n{deal.format_quote_table(final)}\n\n"
                f"**Total: {money(final.total)}** · 🚚 delivery in **{plural(days, 'day')}**",
                mentions=[buyer],
            )
        elif "purchase order" in lowered:
            po = re.search(r"CAPY-[0-9A-Z-]+", text)
            await tools.send_message(
                self.voice.confirm.format(po=po.group(0) if po else "", when=when(days)),
                mentions=[buyer],
            )
        elif "not this time" in lowered:
            await tools.send_message(self.voice.no_deal, mentions=[self.human(tools) or buyer])
        elif msg.sender_type == "User":
            stock = ", ".join(self.profile.prices)
            await tools.send_message(
                f"{self.voice.hello.split('!')[0]}! I sell {stock}. Send me a table to quote 🧾",
                mentions=[self.human(tools)],
            )


# --- Mochi: head buyer -------------------------------------------------------------------------------


@dataclass
class Deal:
    hq_room: str
    hq: AgentTools
    owner: dict[str, Any] | None
    items: list[deal.LineItem]
    expected: int = 0  # suppliers we asked for a quote
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


ApprovalHook = Callable[[str], Awaitable[None]]


class Mochi(CapyAgent):
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

    # -- routing --

    async def handle(self, msg, tools, room_id):
        d = self.deal
        if msg.sender_name == TOFU.name and "running low" in msg.content:
            await self.start_deal(msg, tools, room_id)
        elif d and room_id in d.room_ids:
            await self.on_supplier_message(d, msg, tools)
        elif d and msg.sender_name == YUZU.name and d.stage == "budget":
            await self.on_budget(d, msg)
        elif d and msg.sender_type == "User" and d.stage == "approval":
            await self.on_owner_reply(d, msg, tools)
        elif msg.sender_type == "User":
            await tools.send_message(
                "Hi boss! 🍊 Ask Tofu for a pantry check (`@Tofu pantry check`) and I'll take it from there.",
                mentions=[self.human(tools)],
            )

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
        await tools.send_message(
            f"On it, Tofu! 🍊 I looked around Band and found **{len(suppliers)} suppliers**: {self.oxford(suppliers)}. "
            "Opening a quote room with each, back soon with the best deal!",
            mentions=[self.human(tools)],
        )
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
        await self.nap(1.0)
        await room.send_message(
            f"Hi friend! 🍊 Capy Café would love a quote:\n\n{deal.format_rfq_table(d.items)}\n\n"
            "What's your best price and delivery time?",
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
                if len(d.finals) < len(d.counters):
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
        await self.nap(1.5)
        d.awards = deal.choose_winners(d.items, d.quotes)
        d.counters = deal.counter_offers(d.awards, d.quotes)

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

        for supplier, room in d.rooms.items():
            counters = d.counters.get(supplier)
            if not counters:
                await room.send_message(
                    "Thank you so much for the quote! 🍊 Not this time, but we'll be back.", mentions=[supplier]
                )
                continue
            leverage = [c for c in counters if c.seen_elsewhere is not None]
            lines = []
            if d.quotes[supplier].upsell:
                lines.append("No honey today, thank you, just the list please 🍯🙅")
            if leverage:
                c = leverage[0]
                lines.append(
                    f"I've seen {c.line.item} at **{money(c.seen_elsewhere)}/{c.line.unit}** elsewhere. "
                    "Could you meet me here?"
                )
            else:
                lines.append("You're already the cheapest ✨ Could you round it down a little for a regular customer?")
            await room.send_message(
                "Thank you! 🍊 " + " ".join(lines) + f"\n\n{deal.format_counter_table(counters)}",
                mentions=[supplier],
            )

    async def ask_budget(self, d: Deal) -> None:
        await self.nap(1.0)
        parts = " · ".join(
            f"{line.item} {money(line.subtotal)} ({q.supplier})" for q in d.finals.values() for line in q.lines
        )
        await self.set_tasks(d, active_form="Final offers are in, checking the budget with Yuzu")
        await d.hq.send_message(
            f"Budget check please 🪙 Planned order: **{money(d.total)}**\n{parts}",
            mentions=[YUZU.name],
        )

    # -- step 4: budget verdict, maybe ask the owner --

    async def on_budget(self, d: Deal, msg) -> None:
        if "within budget" in msg.content.lower():
            await d.hq.send_message("Within budget, placing the orders now 🍊", mentions=[self.human(d.hq)])
            await self.place_orders(d)
            return
        d.stage = "approval"
        await self.nap(1.0)
        last_paid = {name: item.last_paid for name, item in PANTRY_BY_NAME.items()}
        before = deal.last_month_cost(d.finals.values(), last_paid)
        saved = before - d.total
        pct = round(saved / before * 100)
        over = deal.first_amount(msg.content.split("That's", 1)[-1])
        summary = deal.md_table(
            ["item", "from", "price", "arrives"],
            [
                [line.item, f"{q.supplier}", money(line.subtotal), when(q.delivery_days)]
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
        d.attention_id = getattr(getattr(event, "data", None), "id", None)
        log.info("🙋 Mochi asks the owner to approve %s (%s over budget)", money(d.total), money(over))
        await self.set_tasks(d, status="in_review", active_form="Waiting for the boss's OK")
        owner = d.owner or {}
        handle = owner.get("handle") or owner.get("name") or "boss"
        await d.hq.send_message(
            f"Boss! 🍊 I found a deal:\n\n{summary}\n\n"
            f"**Total {money(d.total)}**, that's **{money(saved)} less** than last month (−{pct}%). "
            f"It's {money(over)} over this week's budget, so I need your OK. "
            f"Reply **@{MOCHI.name} approve** or **@{MOCHI.name} no**.",
            mentions=[handle] if d.owner else None,
        )
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
            await tools.send_message("Yay, thank you boss! 🎉 Placing the orders now 🍊", mentions=[self.human(tools)])
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
            await tools.send_message(
                f"Just say **@{MOCHI.name} approve** or **@{MOCHI.name} no** 🍊", mentions=[self.human(tools)]
            )

    # -- step 5: purchase orders and the receipt --

    async def place_orders(self, d: Deal) -> None:
        d.stage = "ordering"
        stamp = date.today().strftime("%m%d")
        for n, (supplier, final) in enumerate(d.finals.items(), start=1):
            po = d.orders[supplier] = f"CAPY-{stamp}-{n}"
            await self.set_task_for(d, supplier, status="in_progress", active_form=f"{po} sent to {supplier}")
            await d.rooms[supplier].send_message(
                f"Deal! ✅ **Purchase order {po}**\n\n{deal.format_quote_table(final)}\n\n"
                f"**Total {money(final.total)}**, please deliver {when(final.delivery_days)}. Thank you, friend! 🍊",
                mentions=[supplier],
            )

    async def post_receipt(self, d: Deal) -> None:
        await self.nap(1.0)
        last_paid = {name: item.last_paid for name, item in PANTRY_BY_NAME.items()}
        before = deal.last_month_cost(d.finals.values(), last_paid)
        saved = before - d.total
        rows = [
            [d.orders[s], s, ", ".join(line.item for line in q.lines), money(q.total), when(q.delivery_days)]
            for s, q in d.finals.items()
        ]
        table = deal.md_table(["order", "supplier", "items", "total", "arrives"], rows)
        await d.hq.send_message(
            f"All done! 🍊🎉 {len(rows)} orders placed and confirmed:\n\n{table}\n\n"
            f"**Total {money(d.total)}** · saved **{money(saved)}** vs last month "
            f"(−{round(saved / before * 100)}%). Coffee lands tomorrow, before we run out ☕\n\n"
            f"Yuzu, please log {money(d.total)} (approved by the boss) 🪙",
            mentions=[YUZU.name, self.human(d.hq)],
        )
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
