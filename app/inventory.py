"""Inventory Data: the Wayfair "All Inventory Export", one row per product per warehouse.

Like the INVENTORY DATA tab's column M, the rows of one Part Number (one per warehouse) are checked together:
- the Retail Price must be the same in every warehouse, and
- the stock must agree: 0 (or blank) must be 0 everywhere; above 0 may differ between warehouses as long as all have stock.
Anything else is a MISMATCH to correct on the marketplace. The sheet hard-codes groups of 3 rows; here a group is every
row of the same Part Number, so 2 or 4 warehouses work too.
"""

from __future__ import annotations

import csv
import io
import json

from . import imports, versions
from .rules import to_float
from .db import conn, get_settings, log_activity, now_str, set_setting, tx

# (field, label, header names it is read from, after normalising: lower case, letters and digits only)
COLS = [
    ("part", "Part Number", ("partnumber", "supplierpartnumber")),
    ("mplid", "Wayfair MPLID", ("wayfairmplidpreviouslyknownaswayfairsku", "wayfairmplid", "mplid", "wayfairsku")),
    ("warehouse", "Warehouse Name", ("warehousename", "warehouse")),
    ("wh_type", "Warehouse Type", ("warehousetype",)),
    ("in_stock", "In Stock", ("instock",)),
    ("available", "Available", ("available",)),
    ("bis_qty", "Back In Stock Quantity", ("backinstockquantity",)),
    ("bis_date", "Back In Stock Date", ("backinstockdate",)),
    ("orders90", "Order Past 90 Days", ("orderpast90days", "orderspast90days")),
    ("stock_update", "In Stock Update", ("instockupdate",)),
    ("price", "Retail Price", ("retailprice", "price")),
    ("priority", "Priority Products", ("priorityproducts",)),
]
FIELDS = [c[0] for c in COLS]
PAGE = 100   # products (groups of warehouse rows) per page


def _num(v) -> float:
    """Google Sheets' N(): a number stays a number, anything else (blank, text) is 0."""
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return 0.0


def _price_key(v) -> str:
    s = str(v or "").replace(",", "").replace("$", "").strip()
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return s


def check_group(rows: list[dict]) -> tuple[str, str]:
    """('OK' | 'MISMATCH' | '', why). A product in only one warehouse has nothing to compare, like the sheet's blank."""
    if len(rows) < 2:
        return "", "Only one warehouse"
    why = []
    prices = {}
    for r in rows:
        prices.setdefault(_price_key(r["price"]), []).append(r)
    if len(prices) > 1:
        why.append("Price differs: " + ", ".join(
            f"{k or 'blank'} ({', '.join(_short(x['warehouse']) for x in v)})" for k, v in prices.items()))
    zero = [r for r in rows if _num(r["in_stock"]) == 0]
    if zero and len(zero) < len(rows):
        why.append("Stock 0 in " + ", ".join(_short(r["warehouse"]) for r in zero) + " but in stock in " +
                   ", ".join(f"{_short(r['warehouse'])} ({r['in_stock']})" for r in rows if r not in zero))
    return ("MISMATCH", "; ".join(why)) if why else ("OK", "")


def _short(warehouse: str) -> str:
    """'CITRUS COMMERCE LLC FL 32811' -> 'FL 32811' (the state and ZIP tell the warehouses apart)."""
    parts = str(warehouse or "").split()
    return " ".join(parts[-2:]) if len(parts) >= 2 else str(warehouse or "?")


def import_file(filename: str, data: bytes, user: str) -> dict:
    if not data:
        raise ValueError("The file is empty.")
    header, rows = imports.mz_read(filename, data)
    norm = [imports._norm(h) for h in header]
    idx = {}
    for f, _label, names in COLS:
        i = next((norm.index(n) for n in names if n in norm), None)
        if i is not None and i not in idx.values():
            idx[f] = i
    if "part" not in idx or "warehouse" not in idx:
        raise ValueError("Couldn't find the Part Number and Warehouse Name columns. Use the Wayfair All Inventory Export.")
    groups: dict[str, list[dict]] = {}
    for r in rows:
        rec = {f: (str(r[i]).strip() if i < len(r) else "") for f, i in idx.items()}
        for f in FIELDS:
            rec.setdefault(f, "")
        if not rec["part"]:
            continue
        groups.setdefault(rec["part"].lower(), []).append(rec)
    if not groups:
        raise ValueError("No inventory rows found in this file.")
    now = now_str()
    ok = mismatch = filled = 0
    versions.take_if_edited("Before the Inventory Data import", user)
    with tx() as c:
        skus = {r[0].lower(): r[0] for r in c.execute("SELECT sku FROM products WHERE active=1")}   # MPLID = catalog SKU
        c.execute("DELETE FROM inventory_rows")
        c.execute("DELETE FROM inventory_groups")
        for g, recs in enumerate(groups.values(), start=1):
            chk, why = check_group(recs)
            ok += chk == "OK"
            mismatch += chk == "MISMATCH"
            c.execute("INSERT INTO inventory_groups(grp, part, mplid, sku, warehouses, chk, why) VALUES(?,?,?,?,?,?,?)",
                      (g, recs[0]["part"], recs[0]["mplid"], skus.get(recs[0]["mplid"].lower()), len(recs), chk, why))
            # The catalog's IMPORTED INVENTORY and IMPORTED PRICE come from the product's first warehouse row
            sku = skus.get(recs[0]["mplid"].lower())
            if sku:
                qty = to_float(recs[0]["in_stock"])
                c.execute("UPDATE products SET wayfair_qty=?, wayfair_price=?, wayfair_updated_at=? WHERE sku=?",
                          (int(qty) if qty is not None else None, to_float(recs[0]["price"]), now, sku))
                filled += 1
            c.executemany(f"INSERT INTO inventory_rows(grp, {', '.join(FIELDS)}) VALUES(?{', ?' * len(FIELDS)})",
                          [(g, *[r[f] for f in FIELDS]) for r in recs])
        info = {"filename": filename, "at": now, "user": user, "rows": sum(len(v) for v in groups.values()),
                "products": len(groups), "ok_products": ok, "mismatch": mismatch,
                "catalog_filled": filled}
        set_setting(c, "inventory_import", json.dumps(info))
        log_activity(c, user, "imported the Inventory Data", "",
                     f"{info['products']:,} products ({info['rows']:,} warehouse rows) from {filename}: {mismatch:,} mismatched, "
                     f"{filled:,} catalog products got their imported inventory and price")
    return {"ok": True, **info}


def _filter(show: str, q: str) -> tuple[str, list]:
    where, args = ["1=1"], []
    if show == "mismatch":
        where.append("g.chk='MISMATCH'")
    elif show == "ok":
        where.append("g.chk='OK'")
    q = (q or "").strip().lower()
    if q:
        like = f"%{q}%"
        where.append("""(LOWER(g.part) LIKE ? OR LOWER(g.mplid) LIKE ? OR LOWER(COALESCE(p.name,'')) LIKE ?
            OR EXISTS(SELECT 1 FROM inventory_rows r WHERE r.grp=g.grp AND LOWER(r.warehouse) LIKE ?))""")
        args += [like] * 4
    return " AND ".join(where), args


_FROM = "FROM inventory_groups g LEFT JOIN products p ON p.sku=g.sku AND p.active=1"


def listing(show: str = "all", q: str = "", page: int = 0) -> dict:
    c = conn()
    info = json.loads(get_settings(c).get("inventory_import") or "null")
    row = c.execute("SELECT COUNT(*), SUM(chk='OK'), SUM(chk='MISMATCH'), SUM(chk='') FROM inventory_groups").fetchone()
    counts = {k: int(v or 0) for k, v in zip(("products", "ok", "mismatch", "single"), row)}
    counts["not_in_catalog"] = c.execute(f"SELECT COUNT(*) {_FROM} WHERE p.sku IS NULL").fetchone()[0]
    where, args = _filter(show, q)
    total = c.execute(f"SELECT COUNT(*) {_FROM} WHERE {where}", args).fetchone()[0]
    if int(page or 0) <= 0:                                  # page 0 = everything, for the one scrolling list
        pages, page, limit = 1, 0, ""
    else:
        pages = max(1, -(-total // PAGE))
        page = min(max(1, int(page)), pages)
        limit = f"LIMIT {PAGE} OFFSET {(page - 1) * PAGE}"
    groups = [dict(r) for r in c.execute(
        f"SELECT g.*, p.sku AS cat_sku, p.name {_FROM} WHERE {where} ORDER BY g.grp {limit}", args)]
    if groups:
        ids = {g["grp"] for g in groups}
        lo, hi = min(ids), max(ids)
        rows: dict[int, list] = {}
        for r in c.execute("SELECT * FROM inventory_rows WHERE grp BETWEEN ? AND ? ORDER BY id", (lo, hi)):
            if r["grp"] in ids:
                rows.setdefault(r["grp"], []).append({f: r[f] for f in FIELDS})
        for g in groups:
            g["rows"] = rows.get(g["grp"], [])
    return {"info": info, "counts": counts, "total": total, "page": page, "pages": pages,
            "columns": [{"k": k, "l": l} for k, l, _ in COLS], "groups": groups}


def export_csv(show: str = "mismatch", q: str = "") -> bytes:
    """The rows in the Inventory Export's own layout plus the check, for fixing on the marketplace."""
    c = conn()
    where, args = _filter(show, q)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([l for _, l, _ in COLS] + ["Check", "Why", "Catalog product"])
    for g in c.execute(f"SELECT g.grp, g.chk, g.why, p.name {_FROM} WHERE {where} ORDER BY g.grp", args).fetchall():
        for i, r in enumerate(c.execute("SELECT * FROM inventory_rows WHERE grp=? ORDER BY id", (g["grp"],))):
            w.writerow([r[f] for f in FIELDS] + ([{"OK": "OK", "MISMATCH": "MISMATCH"}.get(g["chk"], ""), g["why"], g["name"] or ""]
                                                  if i == 0 else ["", "", ""]))
    return out.getvalue().encode("utf-8-sig")
