"""The negotiation itself: shopping lists, quotes, counter-offers and orders.

Everything here is pure and deterministic so it can be unit tested. Agents
exchange these as markdown tables inside ordinary Band chat messages, which
keeps every step readable for the humans watching the room and parseable for
the agents taking part.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from capybargain.pantry import PantryItem, SupplierProfile

CENT = Decimal("0.01")
NICKEL = Decimal("0.05")


# --- money --------------------------------------------------------------------


def money(amount: Decimal) -> str:
    return f"${amount.quantize(CENT):,.2f}"


def parse_money(text: str) -> Decimal:
    return Decimal(re.sub(r"[^0-9.]", "", text)).quantize(CENT)


def to_nickel(amount: Decimal, rounding: str = ROUND_HALF_UP) -> Decimal:
    return ((amount / NICKEL).quantize(Decimal(1), rounding=rounding) * NICKEL).quantize(CENT)


# --- markdown tables -----------------------------------------------------------


def md_table(headers: list[str], rows: Iterable[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def parse_md_table(text: str) -> list[dict[str, str]]:
    """Rows of the first markdown table in ``text``, keyed by lowercased header."""
    rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    cells = [[c.strip().strip("*") for c in row.strip("|").split("|")] for row in rows]
    headers = [h.lower() for h in cells[0]]
    return [dict(zip(headers, row)) for row in cells[2:] if len(row) == len(headers)]


def _days(text: str) -> int:
    match = re.search(r"(\d+)", text)
    if not match:
        raise ValueError(f"no number of days in {text!r}")
    return int(match.group(1))


def _qty(text: str) -> tuple[int, str]:
    match = re.match(r"\s*(\d+)\s*(.*)", text)
    if not match:
        raise ValueError(f"no quantity in {text!r}")
    return int(match.group(1)), match.group(2).strip()


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 or word == "kg" else f"{n} {word}s"


# --- the shopping list ------------------------------------------------------------


@dataclass(frozen=True)
class LineItem:
    name: str
    qty: int
    unit: str
    deadline_days: int


def restock_list(pantry: Iterable[PantryItem]) -> list[LineItem]:
    """What Tofu asks Mochi to buy, most urgent first."""
    low = [item for item in pantry if item.is_low]
    low.sort(key=lambda item: item.days_left)
    return [LineItem(i.name, i.needed, i.unit, i.deadline_days) for i in low]


def format_restock_table(pantry: Iterable[PantryItem]) -> str:
    rows = []
    for item in sorted((i for i in pantry if i.is_low), key=lambda i: i.days_left):
        on_hand = int(item.on_hand) if float(item.on_hand).is_integer() else item.on_hand
        rows.append(
            [
                item.name,
                plural(on_hand, item.unit),
                plural(item.needed, item.unit),
                plural(item.deadline_days, "day"),
            ]
        )
    return md_table(["item", "on shelf", "order", "runs out in"], rows)


def parse_restock_table(text: str) -> list[LineItem]:
    items = []
    for row in parse_md_table(text):
        qty, unit = _qty(row["order"])
        items.append(LineItem(row["item"], qty, _singular(unit), _days(row["runs out in"])))
    return items


def _singular(unit: str) -> str:
    return unit[:-1] if unit.endswith("s") and unit != "kg" else unit


def format_rfq_table(items: Iterable[LineItem]) -> str:
    return md_table(
        ["item", "qty", "needed within"],
        [[i.name, plural(i.qty, i.unit), plural(i.deadline_days, "day")] for i in items],
    )


def parse_rfq_table(text: str) -> list[LineItem]:
    items = []
    for row in parse_md_table(text):
        qty, unit = _qty(row["qty"])
        items.append(LineItem(row["item"], qty, _singular(unit), _days(row["needed within"])))
    return items


# --- quotes --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuoteLine:
    item: str
    qty: int
    unit: str
    unit_price: Decimal

    @property
    def subtotal(self) -> Decimal:
        return (self.unit_price * self.qty).quantize(CENT)


@dataclass(frozen=True)
class Quote:
    supplier: str
    lines: tuple[QuoteLine, ...]
    delivery_days: int
    upsell: str | None = None

    @property
    def total(self) -> Decimal:
        return sum((line.subtotal for line in self.lines), Decimal("0.00"))

    def line(self, item: str) -> QuoteLine | None:
        return next((line for line in self.lines if line.item == item), None)


def build_quote(profile: SupplierProfile, items: Iterable[LineItem]) -> Quote:
    lines = tuple(
        QuoteLine(i.name, i.qty, i.unit, profile.prices[i.name])
        for i in items
        if i.name in profile.prices
    )
    upsell = None
    if profile.upsell:
        u = profile.upsell
        upsell = f"{u.name} ({u.blurb}) for just {money(u.price)}"
    return Quote(profile.name, lines, profile.delivery_days, upsell)


def format_quote_table(quote: Quote) -> str:
    return md_table(
        ["item", "qty", "unit price", "subtotal"],
        [
            [line.item, plural(line.qty, line.unit), money(line.unit_price), money(line.subtotal)]
            for line in quote.lines
        ],
    )


DELIVERY_RE = re.compile(r"delivery in \**(\d+) days?", re.IGNORECASE)


def parse_quote(supplier: str, text: str) -> Quote:
    lines = []
    for row in parse_md_table(text):
        qty, unit = _qty(row["qty"])
        lines.append(QuoteLine(row["item"], qty, _singular(unit), parse_money(row["unit price"])))
    match = DELIVERY_RE.search(text)
    if not match:
        raise ValueError(f"{supplier}'s quote has no delivery time")
    upsell = None
    if "psst" in text.lower():
        upsell = "upsell"
    return Quote(supplier, tuple(lines), int(match.group(1)), upsell)


# --- choosing and haggling ----------------------------------------------------------------


@dataclass(frozen=True)
class Award:
    item: LineItem
    supplier: str
    line: QuoteLine
    on_time: bool


def choose_winners(items: Iterable[LineItem], quotes: Mapping[str, Quote]) -> dict[str, Award]:
    """Cheapest supplier that delivers before the shelf runs out, per item.

    If nobody is fast enough, take the fastest one and flag it.
    """
    awards = {}
    for item in items:
        offers = [(q, q.line(item.name)) for q in quotes.values() if q.line(item.name)]
        if not offers:
            continue
        on_time = [(q, line) for q, line in offers if q.delivery_days <= item.deadline_days]
        if on_time:
            quote, line = min(on_time, key=lambda o: (o[1].unit_price, o[0].delivery_days))
        else:
            quote, line = min(offers, key=lambda o: (o[0].delivery_days, o[1].unit_price))
        awards[item.name] = Award(item, quote.supplier, line, bool(on_time))
    return awards


@dataclass(frozen=True)
class Counter:
    line: QuoteLine
    target: Decimal
    seen_elsewhere: Decimal | None  # lowest price another supplier offered


def counter_offers(awards: Mapping[str, Award], quotes: Mapping[str, Quote]) -> dict[str, list[Counter]]:
    """What Mochi asks each winning supplier for in round two.

    If someone else was cheaper (even if too slow), ask to move toward that
    price, but never more than 15% off. If the winner is already the cheapest,
    ask for a polite 5% regular-customer discount.
    """
    counters: dict[str, list[Counter]] = {}
    for award in awards.values():
        current = award.line.unit_price
        others = [
            q.line(award.item.name).unit_price
            for q in quotes.values()
            if q.supplier != award.supplier and q.line(award.item.name)
        ]
        lowest = min(others) if others else None
        if lowest is not None and lowest < current:
            target = max(lowest, to_nickel(current * Decimal("0.85"), ROUND_FLOOR))
            counters.setdefault(award.supplier, []).append(Counter(award.line, target, lowest))
        else:
            target = to_nickel(current * Decimal("0.95"), ROUND_FLOOR)
            counters.setdefault(award.supplier, []).append(Counter(award.line, target, None))
    return counters


def format_counter_table(counters: Iterable[Counter]) -> str:
    return md_table(
        ["item", "qty", "your price", "could you do"],
        [
            [c.line.item, plural(c.line.qty, c.line.unit), money(c.line.unit_price), money(c.target)]
            for c in counters
        ],
    )


def parse_counter_table(text: str) -> list[Counter]:
    counters = []
    for row in parse_md_table(text):
        qty, unit = _qty(row["qty"])
        line = QuoteLine(row["item"], qty, _singular(unit), parse_money(row["your price"]))
        counters.append(Counter(line, parse_money(row["could you do"]), None))
    return counters


def respond_to_counters(profile: SupplierProfile, counters: Iterable[Counter]) -> Quote:
    """A supplier's final offer: give up ``meet`` of the gap, never below its floor."""
    lines = []
    for c in counters:
        current = c.line.unit_price
        floor = profile.prices[c.line.item] * profile.floor
        conceded = current - profile.meet * (current - c.target)
        price = min(current, to_nickel(max(c.target, floor, conceded)))
        lines.append(QuoteLine(c.line.item, c.line.qty, c.line.unit, price))
    return Quote(profile.name, tuple(lines), profile.delivery_days)


# --- orders and budget ------------------------------------------------------------------------


def order_total(final_quotes: Iterable[Quote]) -> Decimal:
    return sum((q.total for q in final_quotes), Decimal("0.00"))


def last_month_cost(final_quotes: Iterable[Quote], last_paid: Mapping[str, Decimal]) -> Decimal:
    return sum(
        ((last_paid[line.item] * line.qty).quantize(CENT) for q in final_quotes for line in q.lines),
        Decimal("0.00"),
    )


@dataclass(frozen=True)
class BudgetCheck:
    budget: Decimal
    spent: Decimal
    order: Decimal

    @property
    def left(self) -> Decimal:
        return self.budget - self.spent

    @property
    def over_by(self) -> Decimal:
        return max(Decimal("0.00"), self.order - self.left)

    @property
    def within(self) -> bool:
        return self.over_by == 0


AMOUNT_RE = re.compile(r"\$([0-9][0-9,]*\.[0-9]{2})")


def first_amount(text: str) -> Decimal:
    match = AMOUNT_RE.search(text)
    if not match:
        raise ValueError(f"no dollar amount in {text!r}")
    return parse_money(match.group(1))
