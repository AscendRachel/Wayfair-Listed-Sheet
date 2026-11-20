import pytest

from app import rules
from app.rules import compute_status, title_check

PR = rules.DEFAULT_PRICING


def P(**kw):
    base = dict(availability="In Stock", inventory=1, source_price=10.0, price="$10.00", delivery="", run_at="2026-01-05 10:00:00", listed=1)
    base.update(kw)
    return base


def test_prices_follow_the_maxaya_sheet():
    # K = 3 with a source link; L = J + K; N = L x (1 + M); P = N / (1 - O)
    assert rules.fee_for("https://amazon.com/dp/B0CJM9WZCZ", PR) == 3 and rules.fee_for("", PR) is None
    b = rules.price_breakdown("https://amazon.com/dp/B0CJM9WZCZ", 23.99, 0.72, 0.22, PR)
    assert b["fee"] == 3 and b["cost"] == 26.99
    assert b["selling"] == pytest.approx(46.42, abs=0.005)                 # the sheet's row 3: 46.4228
    assert b["promo"] == pytest.approx(59.52, abs=0.005)                   # 59.5164..., the IMPORTED PRICE 59.52
    assert b["auto"] == 59.52                                              # the marketplace price is the promo price
    no_promo = rules.price_breakdown("x", 10, 0.48, None, PR)
    assert no_promo["promo"] is None and no_promo["auto"] == no_promo["selling"] == 19.24
    assert rules.price_breakdown("x", 10, None, 0.2, PR)["selling"] is None              # no mark up %: no selling price
    assert rules.price_breakdown("x", 10, 0.48, 1, PR)["promo"] is None                   # 100% promo: blank, like the sheet
    assert rules.price_breakdown("x", 10, 0, None, PR)["selling"] == 13                    # 0% is a mark up, not a blank


def test_status_order():
    assert compute_status(P(availability="Currently unavailable."), 6) == "Out of Stock"
    assert compute_status(P(availability="Only 3 left in stock"), 6) == "Low Inventory"
    assert compute_status(P(price="$12.00"), 6) == "High Price"          # source 10 < amazon 12
    assert compute_status(P(price="$8.00"), 6) == "Low Price"
    assert compute_status(P(availability="Availability not found"), 6) == "Manual Check"
    assert compute_status(P(inventory=0), 6) == "Check Inventory"
    assert compute_status(P(inventory=0, availability="Currently unavailable."), 6) == "Normal"
    assert compute_status(P(price="$10.00"), 6) == "Normal"
    assert compute_status(P(availability=""), 6) == "Not checked"
    assert compute_status(P(availability="Only 2 left in stock", price="$12.00"), 6) == "Low Inventory"   # before High Price


def test_out_of_stock_with_amazons_longer_wording():
    long = "Currently unavailable. We don't know when or if this item will be back in stock."
    assert compute_status(P(availability=long, price="Price not found", delivery="Delivery not found"), 6) == "Out of Stock"
    assert compute_status(P(availability=long, inventory=0), 6) == "Normal"                 # Inventory off: not an issue
    assert compute_status(P(availability="Temporarily out of stock.", price="Price not found"), 6) == "Out of Stock"
    assert compute_status(P(availability="Temporarily out of stock.", inventory=0), 6) == "Normal"


def test_unable_to_access_page_is_a_manual_check():
    p = dict(availability="Unable to access page", price="Price not found", delivery="Delivery not found")
    assert compute_status(P(**p), 6) == "Manual Check"
    assert compute_status(P(inventory=0, **p), 6) == "Normal"                               # Inventory off: not an issue


def test_timeframe_beats_everything():
    p = P(availability="Currently unavailable.", delivery="Delivery January 20", run_at="2026-01-05 10:00:00")
    assert compute_status(p, 6) == "TimeFrame"
    assert compute_status(p, 30) == "Out of Stock"


def test_timeframe_whatever_inventory_is_like_the_sheet():
    """The sheet's formula tests the lead time before it looks at Inventory, so an unticked row still reads TimeFrame
    (and so never Check Inventory). It isn't coloured and isn't counted as an issue to work on."""
    slow = dict(delivery="Delivery January 20", run_at="2026-01-05 10:00:00")
    assert compute_status(P(**slow), 6) == "TimeFrame"
    assert compute_status(P(inventory=0, **slow), 6) == "TimeFrame"


def test_the_sheets_timeframe_helper_columns_are_not_needed():
    """EARLIESTAMAZONDATE(D) -> DATEVALUE -> minus the last run -> more than 6 days = TimeFrame. The sheet's run time has a
    clock time, so 7 calendar days later is 6.55 days (> 6) and 6 calendar days is 5.55 (not > 6): whole days give the same answer."""
    text = ("FREE delivery Saturday, November 24 on orders shipped by Amazon over 35 dollars    "
            "Or Prime members get FREE delivery Wednesday, November 25. Order within 2 hrs 15 mins.")
    assert rules.earliest_delivery(text, "2026-11-17 10:44:53").day == 24
    assert rules.lead_days(text, "2026-11-17 10:44:53") == 7
    assert compute_status(P(delivery=text, run_at="2026-11-17 10:44:53"), 6) == "TimeFrame"
    assert compute_status(P(delivery=text.replace("24", "23"), run_at="2026-11-17 10:44:53"), 6) == "Normal"


def test_check_inventory_like_the_sheet():
    assert compute_status(P(inventory=0), 6) == "Check Inventory"
    assert compute_status(P(inventory=0, availability="Usually ships within 2 to 3 days"), 6) == "Check Inventory"
    for bad in ("Unable to access page", "Temporarily out of stock.", "Availability not found", "Currently unavailable.", "Only 3 left in stock", ""):
        assert compute_status(P(inventory=0, availability=bad), 6) in ("Normal", "Not checked"), bad
    assert compute_status(P(inventory=0, listed=0), 6) == "Normal"                             # not Listed: nothing to turn on
    slow = dict(delivery="Delivery January 20", run_at="2026-01-05 10:00:00")
    assert compute_status(P(inventory=0, **slow), 30) == "Check Inventory"                       # a looser limit makes it fine


def test_delivery_days_count_from_tomorrow_and_understand_tomorrow_or_overnight():
    ld = rules.lead_days
    assert ld("FREE delivery Tuesday, January 6", "2026-01-05 10:00:00") == 1                  # tomorrow is day 1
    assert ld("FREE delivery Tuesday, January 6", "2026-01-05 23:59:00") == 1                  # the time of the check doesn't matter
    assert ld("FREE delivery Wednesday, January 7", "2026-01-05 00:01:00") == 2
    assert ld("Get it today", "2026-01-05 10:00:00") == 0
    assert ld("FREE overnight delivery by 10 PM", "2026-01-05 10:00:00") == 1
    assert ld("FREE delivery Tomorrow", "2026-01-05 10:00:00") == 1
    assert ld("FREE delivery Friday, January 9 or fastest delivery Tomorrow", "2026-01-05 10:00:00") == 1    # the earliest one counts
    assert ld("Delivery not found", "2026-01-05 10:00:00") is None
    # an allowance of 2 days: tomorrow, the day after and an overnight text are fine, the day after that is a TimeFrame
    for text, want in (("FREE delivery Tomorrow", "Normal"), ("FREE overnight delivery", "Normal"),
                       ("FREE delivery Wednesday, January 7", "Normal"), ("FREE delivery Thursday, January 8", "TimeFrame")):
        assert compute_status(P(delivery=text), 2) == want, text
    assert compute_status(P(delivery="FREE delivery Tuesday, January 6"), 1) == "Normal"
    assert compute_status(P(delivery="FREE delivery Wednesday, January 7"), 1) == "TimeFrame"


def test_lead_days_year_rollover():
    d = rules.lead_days("Delivery January 3", "2025-12-30 00:00:00")
    assert d == 4.0


def test_title_check():
    s, _ = title_check("Acrylic Paint Set 12 Pack", "Acrylic Paint Set, 12 Pack Art Supplies")
    assert s >= 80
    s, note = title_check("Acrylic Paint Set 12 Pack", "Acrylic Paint Set 24 Pack")
    assert s <= 40 and "Pack size differs" in note
    assert title_check("Something", "")[0] is None
    s, _ = title_check("Garden Hose Nozzle", "Wireless Bluetooth Headphones")
    assert s < 20


def test_scrap_price_and_code_stripping():
    assert rules.scrap_price("Now $1,234.50 only") == 1234.5
    assert rules.scrap_price("Price not found") is None
    assert rules.strip_code("Arrives Tue (function(){ var x=1 })") == "Arrives Tue"


def test_oos_variation_compares_meaning_not_words():
    from app.variations import differs
    assert differs("Large, 12pcs", "Color: 12pcs/Size: Medium")                       # the size differs
    assert not differs("Large, 12pcs", "Size: Large/Number of Items: 12")             # same facts, worded differently
    assert not differs("12 pack", "Number of Items: 12")
    assert differs("Red", "Color: Blue") and not differs("Gray", "Color: Grey")
    assert not differs("Multi", "Color: Multi-colored")
    assert differs("12pcs", "Color: White/Number of Items: 24")
    assert not differs("13x10x3.5", "Color: White/Size: 13*10*3.5inch/Number of Items: 1")
    assert not differs("", "Color: Red") and not differs("Bunny3", "")                 # one side blank: never flagged
    assert not differs("Red 12pcs", "Color: Red")                                        # one side says less: not a disagreement
    assert not differs("Red", "Color: Red/Number of It…")                                # cut-off value


def test_oos_different_item_and_oos_variation_come_first():
    ok = dict(title="Wooden Frame 8 inch", title_ok="", title_conflict=0, title_score=90, variation="Large", amazon_variation="Size: Large")
    assert compute_status(P(**ok), 6) == "Normal"
    assert compute_status(P(**{**ok, "amazon_variation": "Size: Small"}), 6) == "OOS Variation"
    assert compute_status(P(**{**ok, "amazon_variation": "Size: Small", "price": "$12.00"}), 6) == "OOS Variation"   # beats High Price
    slow = dict(delivery="Delivery January 20", run_at="2026-01-05 10:00:00")
    assert compute_status(P(**{**ok, "amazon_variation": "Size: Small", **slow}), 6) == "OOS Variation"          # and TimeFrame
    assert compute_status(P(**{**ok, "title_conflict": 1}), 6) == "OOS Different Item"
    assert compute_status(P(**{**ok, "title_conflict": 1, "amazon_variation": "Size: Small"}), 6) == "OOS Different Item"
    assert compute_status(P(**{**ok, "title_conflict": 1, "title_ok": ok["title"]}), 6) == "Normal"          # the team accepted it
    assert compute_status(P(**{**ok, "title_conflict": 1, "inventory": 0}), 6) == "Normal"                   # Inventory off: nothing to turn off...
    assert compute_status(P(**{**ok, "amazon_variation": "Size: Small", "inventory": 0}), 6) == "Normal"     # ...and not worth turning on
    assert compute_status(P(**{**ok, "inventory": 0}), 6) == "Check Inventory"
    assert compute_status(P(**{**ok, "title_score": 10}), 6) == "Normal"                                     # a low title match alone changes nothing
    assert compute_status(P(**{**ok, "amazon_variation": ""}), 6) == "Normal"                                # not scraped yet: never flagged
