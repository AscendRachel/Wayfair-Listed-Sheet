"""Business rules: source status, title matching and pricing.

Everything here is a pure function (no database, no network) so it can be unit tested.
The status rules follow column Z ("Listing Status") of the MAXAYA LLC sheet, in the same order.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from . import variations

# ------------------------------------------------------------------ text helpers
CODE_MARKERS = re.compile(r"\(function\s*\(|P\.when\(|\{\s*var\s|window\.|document\.|=>\s*\{")


def strip_code(text: str | None) -> str:
    """Cut off JavaScript that scrapers sometimes pick up along with Amazon's delivery text."""
    text = text or ""
    m = CODE_MARKERS.search(text)
    return re.sub(r"\s+", " ", text[: m.start()] if m else text).strip()


def to_float(v) -> float | None:
    try:
        f = float(str(v).replace("$", "").replace(",", "").strip())
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def to_bool(v) -> int:
    t = str(v).strip().upper()
    if t in ("TRUE", "YES", "Y", "CHECKED"):
        return 1
    try:
        return 1 if float(t) > 0 else 0
    except ValueError:
        return 0


# Amazon image addresses look like https://m.media-amazon.com/images/I/81IhpPoiBmL._AC_SL1500_.jpg: an id, then a size
# code, then the extension. Keep only id + extension so any size can be asked for later (the grid uses small ones).
AMZ_IMAGE_RE = re.compile(r"^https?://m\.media-amazon\.com/images/I/([A-Za-z0-9%+_-]+)\.(?:[^/?#]*\.)?(jpg|jpeg|png)(?:[?#].*)?$", re.I)


def amazon_image_base(url: str | None) -> str:
    """The size-free address of an Amazon product image (' when it isn't one we can use)."""
    url = (url or "").strip()
    m = AMZ_IMAGE_RE.match(url)
    if m:
        return f"https://m.media-amazon.com/images/I/{m.group(1)}.{m.group(2).lower()}"
    return url[:500] if url.startswith("https://") and "/images/" in url else ""


ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.I)


def asin_from_link(link: str | None) -> str:
    m = ASIN_RE.search(link or "")
    return m.group(1).upper() if m else ""


# ------------------------------------------------------------------ source status
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
MONTH_RE = re.compile(r"(" + "|".join(MONTHS) + r")\s+(\d{1,2})")
RUN_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M")

STATUSES = ["Out of Stock", "OOS Different Item", "OOS Variation", "High Price", "Low Inventory", "TimeFrame", "Low Price",
            "Manual Check", "Check Inventory", "Normal", "Not checked"]


PROBLEM_STATUSES = ("Out of Stock", "OOS Different Item", "OOS Variation", "High Price", "Low Inventory", "TimeFrame",
                    "Low Price", "Manual Check", "Check Inventory")


def scrap_price(text: str | None) -> float | None:
    m = re.search(r"\$([\d,]+\.?\d*)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def parse_run(run_at: str | None) -> datetime | None:
    for fmt in RUN_FORMATS:
        try:
            return datetime.strptime((run_at or "").strip()[:19], fmt)
        except ValueError:
            continue
    return None


def lead_days(delivery: str | None, run_at: str | None) -> int | None:
    """Whole calendar days from the day of the check to the earliest delivery day in the text: tomorrow is day 1, so a
    product that arrives tomorrow is inside an allowance of 1 day, whatever time of day it was checked."""
    run = parse_run(run_at)
    best = earliest_delivery(delivery, run_at)
    return None if best is None or run is None else (best.date() - run.date()).days


# Amazon sometimes gives no date at all: "Get it tomorrow", "overnight by 10 PM".
RELATIVE_RE = re.compile(r"\b(today|tonight|tomorrow|overnight)\b", re.I)
RELATIVE_DAYS = {"today": 0, "tonight": 0, "tomorrow": 1, "overnight": 1}


def earliest_delivery(delivery: str | None, run_at: str | None) -> datetime | None:
    """The earliest delivery day mentioned in Amazon's delivery text: a date (year taken from the check date) or a word
    like tomorrow or overnight."""
    run = parse_run(run_at)
    if not run:
        return None
    today = datetime(run.year, run.month, run.day)
    best = None
    for m in MONTH_RE.finditer(delivery or ""):
        try:
            d = datetime(run.year, MONTHS.index(m.group(1)) + 1, int(m.group(2)))
        except ValueError:
            continue
        if d < today - timedelta(days=60):
            d = d.replace(year=run.year + 1)
        if best is None or d < best:
            best = d
    for m in RELATIVE_RE.finditer(delivery or ""):
        d = today + timedelta(days=RELATIVE_DAYS[m.group(1).lower()])
        if best is None or d < best:
            best = d
    return best


def _get(p, key):
    try:
        return p[key]
    except (KeyError, IndexError):
        return None


def title_problem(p, title_threshold: float = 50) -> str:
    """'changed' when the Amazon title shows a different item, 'mismatch' when too few of the catalog words are in it,
    '' when it is fine or someone already accepted it. p needs title, title_ok, title_conflict, title_score."""
    title = _get(p, "title") or ""
    if not title or (_get(p, "title_ok") or "") == title:
        return ""
    if _get(p, "title_conflict"):
        return "changed"
    score = _get(p, "title_score")
    return "mismatch" if score is not None and score < title_threshold else ""


def variation_problem(p) -> bool:
    return variations.differs(_get(p, "variation"), _get(p, "amazon_variation"))


NOT_STOCK = ("availability not found", "currently unavailable", "only", "unable to access page", "temporarily out of stock")


def compute_status(p, timeframe_days: float, title_threshold: float = 50) -> str:
    """The "Listing Status" column (Z) of the MAXAYA LLC sheet, in the same order:

        TimeFrame       delivery lead time > 6 days (checked first, whatever Inventory is)
        Out of Stock    Inventory on, Amazon says "Currently unavailable."
        Low Inventory   Inventory on, availability mentions "only"
        High Price      Inventory on, source price below the scraped Amazon price
        Low Price       Inventory on, source price above a non-zero scraped Amazon price
        Manual Check    Inventory on, "Availability not found"
        Check Inventory Inventory off, Listed on, and Amazon shows some other (in stock) availability

    The sheet needed three helper columns for the time frame (Extracted Delivery TF, the same as a date, Delivery Lead
    Time); here the lead time is worked out from the delivery text and the check time directly (lead_days).
    The scraper's own texts ("Unable to access page", "Temporarily out of stock.") are read like the sheet's nearest one.
    Two checks from the Michaels catalog come before the sheet's (Inventory on only): what Amazon sells now is not our item
    or not our variation, so its price, stock and delivery say nothing about ours:

        OOS Different Item  the Amazon title states a pack count / size that disagrees with the catalog (unless accepted)
        OOS Variation       the variation Amazon shows as selected disagrees with VARIATION

    Check Inventory is then not given when ticking Inventory would only turn the row into one of those two.
    p needs: availability, inventory, listed, source_price, price, delivery, run_at, and for the two checks
    title, title_ok, title_conflict, title_score, variation, amazon_variation (missing ones count as "no problem")."""
    a = p["availability"] or ""
    al = a.lower()
    inv = bool(p["inventory"])
    src = p["source_price"]
    v = scrap_price(p["price"])
    lead = lead_days(p["delivery"], p["run_at"])
    different_item = title_problem(p, title_threshold) == "changed"
    other_variation = variation_problem(p)
    if inv and different_item:
        return "OOS Different Item"
    if inv and other_variation:
        return "OOS Variation"
    if lead is not None and lead > timeframe_days:
        return "TimeFrame"
    if inv and ("currently unavailable" in al or "temporarily out of stock" in al):
        return "Out of Stock"
    if inv and "only" in al:
        return "Low Inventory"
    if inv and src is not None and v is not None and src < v:
        return "High Price"
    if inv and v and src is not None and src > v:
        return "Low Price"
    if inv and ("availability not found" in al or "unable to access page" in al):
        return "Manual Check"
    if (not inv and p["listed"] and a.strip() and not any(w in al for w in NOT_STOCK)
            and not different_item and not other_variation):
        return "Check Inventory"
    return "Normal" if a else "Not checked"


def explain_status(p, timeframe_days: float) -> str:
    """One plain-English line saying why a product has its status."""
    v = scrap_price(p["price"])
    money = lambda x: "—" if x is None else f"${x:,.2f}"
    st = p["status"]
    if st in ("High Price", "Low Price"):
        return f"Amazon is {money(v)}, your source price is {money(p['source_price'])}."
    if st == "TimeFrame":
        lead, best, run = lead_days(p["delivery"], p["run_at"]), earliest_delivery(p["delivery"], p["run_at"]), parse_run(p["run_at"])
        if lead is None:
            return "Delivery is further out than allowed."
        return (f"Earliest delivery is {best:%b %d}, {lead} days after the check on {run:%b %d} "
                f"(the delivery lead time; more than {timeframe_days:g} days is a TimeFrame).")
    if st == "Out of Stock":
        return "Amazon says “Currently unavailable.”"
    if st == "Low Inventory":
        return f"Amazon says “{p['availability']}”."
    if st == "Check Inventory":
        return f"Amazon says “{p['availability']}” but inventory is off."
    if st == "OOS Different Item":
        return "The Amazon listing changed to a different item (pack count or size no longer matches)."
    if st == "OOS Variation":
        return f"Amazon shows “{p['amazon_variation']}” but the catalog variation is “{p['variation']}”."
    if st == "Manual Check":
        return "The scraper couldn't open the Amazon page." if "unable to access" in (p["availability"] or "").lower() else "Availability couldn't be read."
    if st == "Not checked":
        return "No Amazon check yet."
    return "No issues from the last check."


# ------------------------------------------------------------------ title check
def title_check(catalog: str | None, amazon: str | None) -> tuple[int | None, str]:
    """Score 0-100 for how well the Amazon title matches the catalog name, plus a short note.
    The matching itself lives in titles.py (it also reports whether the listing really changed)."""
    from . import titles
    score, note, _ = titles.check(catalog, amazon)
    return score, note

# ------------------------------------------------------------------ pricing
# The MAXAYA LLC sheet's price columns:
#   K  3PL Fee                 = 3 when the row has a source link                      (the flat fee is set on the Pricing tab)
#   L  Source Price + 3PL Fee  = J + K
#   N  Selling Price           = L x (1 + M)       M = Mark Up Percentage, typed per product (0.48 = 48%)
#   P  Promo Price             = N / (1 - O)       O = PROMO PERCENTAGE, typed per product; blank when O is blank or 100%
# The price the marketplace should show (kept as auto_price, compared with the IMPORTED PRICE) is the promo price when
# there is one, else the selling price, to the cent.
DEFAULT_PRICING = {"fee": 3.0}


def fee_for(link: str | None, pr: dict) -> float | None:
    """3PL fee: the flat fee for every product that has a source link."""
    return float(pr["fee"]) if str(link or "").strip() else None


def cost_of(source_price: float | None, fee: float | None) -> float | None:
    return None if source_price is None or fee is None else source_price + fee


def selling_of(cost: float | None, markup: float | None) -> float | None:
    return None if cost is None or markup is None else cost * (1 + markup)


def promo_of(selling: float | None, promo_pct: float | None) -> float | None:
    return None if selling is None or promo_pct is None or promo_pct == 1 else selling / (1 - promo_pct)


def marketplace_price(selling: float | None, promo: float | None) -> float | None:
    v = promo if promo is not None else selling
    return None if v is None else round(v, 2)


def price_breakdown(link, source_price, markup, promo_pct, pr: dict) -> dict:
    fee = fee_for(link, pr)
    cost = cost_of(source_price, fee)
    selling = selling_of(cost, markup)
    promo = promo_of(selling, promo_pct)
    r = lambda x: None if x is None else round(x, 2)
    return {"fee": fee, "cost": r(cost), "markup": markup, "selling": r(selling), "promo_pct": promo_pct,
            "promo": r(promo), "auto": marketplace_price(selling, promo)}



