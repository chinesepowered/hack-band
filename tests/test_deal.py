from decimal import Decimal

from capybargain import deal
from capybargain.pantry import PANTRY, PANTRY_BY_NAME, SPENT_THIS_WEEK, SUPPLIER_PROFILES, WEEKLY_BUDGET

D = Decimal


def round_one():
    items = deal.restock_list(PANTRY)
    rfq = deal.parse_rfq_table(deal.format_rfq_table(items))
    quotes = {}
    for name, profile in SUPPLIER_PROFILES.items():
        quote = deal.build_quote(profile, rfq)
        text = f"{deal.format_quote_table(quote)}\nDelivery in **{quote.delivery_days} days**"
        quotes[name] = deal.parse_quote(name, text)
    return items, quotes


def test_tofu_restocks_only_low_items_most_urgent_first():
    items = deal.restock_list(PANTRY)
    assert [(i.name, i.qty, i.deadline_days) for i in items] == [
        ("coffee beans", 10, 1),
        ("oat milk", 36, 3),
        ("flour", 7, 6),
    ]


def test_restock_table_round_trips():
    items = deal.restock_list(PANTRY)
    assert deal.parse_restock_table(deal.format_restock_table(PANTRY)) == items


def test_each_item_goes_to_the_cheapest_supplier_that_arrives_in_time():
    items, quotes = round_one()
    awards = deal.choose_winners(items, quotes)
    assert {name: a.supplier for name, a in awards.items()} == {
        "coffee beans": "Zippy",  # only next-day delivery beats the empty shelf
        "oat milk": "Foxy",  # Shelly is cheaper but 4 days is too slow
        "flour": "Shelly",
    }
    assert all(a.on_time for a in awards.values())


def test_counter_offers_use_cheaper_quotes_as_leverage():
    items, quotes = round_one()
    counters = deal.counter_offers(deal.choose_winners(items, quotes), quotes)
    targets = {c.line.item: (c.target, c.seen_elsewhere) for cs in counters.values() for c in cs}
    assert targets == {
        "coffee beans": (D("22.10"), D("19.00")),
        "oat milk": (D("2.60"), D("2.60")),
        "flour": (D("10.90"), None),  # already cheapest: ask for a regular-customer discount
    }


def test_final_offers_savings_and_budget():
    items, quotes = round_one()
    counters = deal.counter_offers(deal.choose_winners(items, quotes), quotes)
    finals = []
    for supplier, cs in counters.items():
        parsed = deal.parse_counter_table(deal.format_counter_table(cs))
        finals.append(deal.respond_to_counters(SUPPLIER_PROFILES[supplier], parsed))
    prices = {line.item: line.unit_price for q in finals for line in q.lines}
    assert prices == {"coffee beans": D("23.65"), "oat milk": D("2.70"), "flour": D("11.30")}

    total = deal.order_total(finals)
    last_paid = {name: item.last_paid for name, item in PANTRY_BY_NAME.items()}
    assert total == D("412.80")
    assert deal.last_month_cost(finals, last_paid) == D("466.70")

    check = deal.BudgetCheck(WEEKLY_BUDGET, SPENT_THIS_WEEK, total)
    assert check.left == D("397.70")
    assert check.over_by == D("15.10")
    assert not check.within


def test_supplier_never_goes_below_its_floor():
    profile = SUPPLIER_PROFILES["Zippy"]
    line = deal.QuoteLine("coffee beans", 10, "kg", D("26.00"))
    final = deal.respond_to_counters(profile, [deal.Counter(line, D("1.00"), None)])
    assert final.lines[0].unit_price == D("22.90")  # 88% of list, rounded to a nickel


def test_parse_money_and_amounts():
    assert deal.parse_money("**$1,234.50**") == D("1234.50")
    assert deal.first_amount("Planned order: **$412.80** (coffee $236.50)") == D("412.80")
