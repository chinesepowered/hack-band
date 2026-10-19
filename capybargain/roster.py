"""Who works at Capy Café, and who sells to it.

Names are what other participants @mention. Descriptions are visible to every
agent through ``band_lookup_peers``, so Mochi finds suppliers by reading them:
any peer whose description starts with ``SUPPLIER_PREFIX`` is a supplier.
"""

from __future__ import annotations

from dataclasses import dataclass

SUPPLIER_PREFIX = "Supplier ·"


@dataclass(frozen=True)
class Member:
    key: str  # key in agent_config.yaml
    name: str
    emoji: str
    role: str
    description: str


MOCHI = Member(
    key="mochi",
    name="Mochi",
    emoji="🍊",
    role="Head Buyer",
    description=(
        "Head buyer at Capy Café 🍊 A calm capybara who collects quotes from "
        "suppliers, haggles politely and never overpays. Mention me with a "
        "shopping list."
    ),
)
TOFU = Member(
    key="tofu",
    name="Tofu",
    emoji="🥕",
    role="Pantry Keeper",
    description=(
        "Pantry keeper at Capy Café 🥕 Counts the shelves every morning and "
        "tells Mochi what needs restocking."
    ),
)
YUZU = Member(
    key="yuzu",
    name="Yuzu",
    emoji="🪙",
    role="Treasurer",
    description=(
        "Treasurer at Capy Café 🪙 Watches the weekly budget and flags any "
        "order that needs the owner's OK."
    ),
)
SHELLY = Member(
    key="shelly",
    name="Shelly",
    emoji="🐢",
    role="Slow & Steady Farm",
    description=(
        f"{SUPPLIER_PREFIX} Shelly's Slow & Steady Farm 🐢 Oat milk, flour, "
        "coffee beans. The lowest prices around; deliveries take 4 days."
    ),
)
ZIPPY = Member(
    key="zippy",
    name="Zippy",
    emoji="🐦",
    role="Zippy Express Pantry",
    description=(
        f"{SUPPLIER_PREFIX} Zippy Express Pantry 🐦 Oat milk, flour, coffee "
        "beans. Next-day delivery at premium prices."
    ),
)
FOXY = Member(
    key="foxy",
    name="Foxy",
    emoji="🦊",
    role="Foxy Wholesale",
    description=(
        f"{SUPPLIER_PREFIX} Foxy Wholesale 🦊 Oat milk, flour, coffee beans "
        "and honey bundles. 2-day delivery, always has a deal for you."
    ),
)

CAFE_STAFF = (MOCHI, TOFU, YUZU)
SUPPLIERS = (SHELLY, ZIPPY, FOXY)
EVERYONE = CAFE_STAFF + SUPPLIERS
BY_NAME = {m.name: m for m in EVERYONE}
