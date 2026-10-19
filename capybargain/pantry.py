"""Capy Café's world: the pantry, the budget, and what each supplier charges.

In a real deployment the pantry would come from the café's point-of-sale
system and each supplier's price list would live inside that supplier's own
agent, in that supplier's own Band account. Here it is a fixed snapshot so the
demo is reproducible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PantryItem:
    name: str
    unit: str
    on_hand: float
    par: float  # how much we like to have on the shelf after a restock
    daily_use: float
    last_paid: Decimal  # unit price paid last month, used to report savings

    @property
    def days_left(self) -> float:
        return self.on_hand / self.daily_use

    @property
    def is_low(self) -> bool:
        return self.on_hand < self.par / 2

    @property
    def needed(self) -> int:
        return max(0, math.ceil(self.par - self.on_hand))

    @property
    def deadline_days(self) -> int:
        """Latest delivery (in days) before the shelf runs empty."""
        return max(1, math.floor(self.days_left))


PANTRY = (
    PantryItem("coffee beans", "kg", on_hand=2, par=12, daily_use=2, last_paid=Decimal("25.00")),
    PantryItem("oat milk", "carton", on_hand=12, par=48, daily_use=4, last_paid=Decimal("3.20")),
    PantryItem("flour", "bag", on_hand=3, par=10, daily_use=0.5, last_paid=Decimal("14.50")),
    PantryItem("cocoa", "tin", on_hand=5, par=6, daily_use=0.25, last_paid=Decimal("9.00")),
    PantryItem("matcha", "tin", on_hand=4, par=5, daily_use=0.3, last_paid=Decimal("18.00")),
)
PANTRY_BY_NAME = {item.name: item for item in PANTRY}

WEEKLY_BUDGET = Decimal("500.00")
SPENT_THIS_WEEK = Decimal("102.30")


@dataclass(frozen=True)
class Upsell:
    name: str
    blurb: str
    price: Decimal


@dataclass(frozen=True)
class SupplierProfile:
    name: str
    delivery_days: int
    prices: dict[str, Decimal]
    # How much of the gap to the buyer's counter-offer the supplier gives up
    # (0 = never budges, 1 = accepts any counter), and the lowest fraction of
    # list price it will ever accept.
    meet: Decimal
    floor: Decimal
    upsell: Upsell | None = None


SUPPLIER_PROFILES = {
    "Shelly": SupplierProfile(
        name="Shelly",
        delivery_days=4,
        prices={"coffee beans": Decimal("19.00"), "oat milk": Decimal("2.60"), "flour": Decimal("11.50")},
        meet=Decimal("0.35"),
        floor=Decimal("0.95"),
    ),
    "Zippy": SupplierProfile(
        name="Zippy",
        delivery_days=1,
        prices={"coffee beans": Decimal("26.00"), "oat milk": Decimal("3.40"), "flour": Decimal("15.50")},
        meet=Decimal("0.60"),
        floor=Decimal("0.88"),
    ),
    "Foxy": SupplierProfile(
        name="Foxy",
        delivery_days=2,
        prices={"coffee beans": Decimal("23.00"), "oat milk": Decimal("2.95"), "flour": Decimal("13.50")},
        meet=Decimal("0.70"),
        floor=Decimal("0.90"),
        upsell=Upsell("Honey Bundle", "12 jars of wildflower honey", Decimal("36.00")),
    ),
}
