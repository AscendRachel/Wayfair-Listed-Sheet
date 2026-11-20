from app import db
from tests.test_sheet import cells


def _skus(c, color):
    r = c.post("/api/sheet/skus", json={"color": color})
    assert r.status_code == 200, r.text
    return sorted(r.json()["skus"])


def test_column_conditions_and_sort_by_colour(loaded):
    def ask(**q):
        r = loaded.post("/api/sheet/skus", json=q)
        assert r.status_code == 200, r.text
        return r.json()["skus"]

    # text conditions (names: Acrylic Paint Set 12 Pack, Wooden Frame 8 inch, No Weight Item, Not Amazon)
    assert ask(cf_name="eq:wooden frame 8 inch") == ["SKU-2"]
    assert ask(cf_name="sw:No ") == ["SKU-3", "SKU-4"] or sorted(ask(cf_name="sw:No ")) == ["SKU-3", "SKU-4"]
    assert ask(cf_name="ew:Pack") == ["SKU-1"]
    assert sorted(ask(cf_name="nc:frame")) == ["SKU-1", "SKU-3", "SKU-4"]
    assert ask(cf_name="Frame") == ["SKU-2"]                                      # a plain value still means "contains"
    # number conditions (source prices 10, 5, 7, 3)
    assert sorted(ask(cf_source_price="!=10")) == ["SKU-2", "SKU-3", "SKU-4"]
    assert sorted(ask(cf_source_price="4..7")) == ["SKU-2", "SKU-3"]
    assert sorted(ask(cf_markup_pct=">=0.5")) == ["SKU-2", "SKU-4"]
    # sort by colour puts the rows of that colour first, a leading - puts them last
    cells(loaded, ("SKU-3", "status", "High Price"))
    db.conn().execute("UPDATE products SET inventory=1, status='High Price' WHERE sku='SKU-3'")
    red = set(ask(color="hp"))
    assert "SKU-3" in red and len(red) < 4
    first, last = ask(sort="color:hp"), ask(sort="-color:hp")
    assert set(first[:len(red)]) == red and set(last[-len(red):]) == red
    assert ask(sort="color:nonsense") == ask()                                     # an unknown colour leaves the order alone


def test_price_differences_only_count_for_products_with_inventory_on(loaded):
    c = db.conn()
    c.execute("UPDATE products SET wayfair_price=99, auto_price=10, inventory=1 WHERE sku='SKU-1'")
    c.execute("UPDATE products SET wayfair_price=99, auto_price=10, inventory=0 WHERE sku='SKU-2'")
    assert loaded.get("/api/queues").json()["counts"]["mz-price"] == 1
    assert loaded.post("/api/sheet/skus", json={"queue": "mz-price"}).json()["skus"] == ["SKU-1"]
    csv = loaded.get("/api/export/wayfair-fixes.csv")
    assert csv.status_code == 200 and "SKU-1" in csv.text and "SKU-2" not in csv.text         # the price-fix export too


def test_issue_cards_only_count_products_with_inventory_on(loaded):
    c = db.conn()
    c.execute("UPDATE products SET status='High Price', inventory=1 WHERE sku='SKU-1'")
    c.execute("UPDATE products SET status='High Price', inventory=0 WHERE sku='SKU-2'")          # e.g. a status typed over, or left from before it was unticked
    c.execute("UPDATE products SET status='Low Inventory', inventory=0 WHERE sku='SKU-3'")
    c.execute("UPDATE products SET status='TimeFrame', inventory=0 WHERE sku='SKU-4'")
    counts = loaded.get("/api/queues").json()["counts"]
    assert counts["High Price"] == 1 and counts.get("Low Inventory", 0) == 0 and counts.get("TimeFrame", 0) == 0
    for q, want in (("High Price", ["SKU-1"]), ("Low Inventory", []), ("TimeFrame", [])):
        assert loaded.post("/api/sheet/skus", json={"queue": q}).json()["skus"] == want       # the list a card opens matches its number
    c.execute("UPDATE products SET inventory=1 WHERE sku IN ('SKU-3','SKU-4')")
    counts = loaded.get("/api/queues").json()["counts"]
    assert counts["Low Inventory"] == 1 and counts["TimeFrame"] == 1                             # ticking Inventory brings them back


def test_filter_by_colour_finds_the_rows_the_grid_paints(loaded):
    """The MAXAYA LLC sheet's conditional formatting: row colours from the Listing Status (Inventory on, or off for
    Check Inventory) and the single-cell rules (duplicates in black, AMAZON in a name, sold counts, the sold tick)."""
    cells(loaded, ("SKU-1", "status", "High Price"), ("SKU-2", "status", "Out of Stock"), ("SKU-4", "inventory", "TRUE"))
    c = db.conn()
    c.execute("UPDATE products SET inventory=1 WHERE sku IN ('SKU-1','SKU-2')")
    c.execute("UPDATE products SET sold_2026=2 WHERE sku='SKU-1'")
    c.execute("UPDATE products SET status='Not checked' WHERE sku='SKU-4'")
    # SKU-3 (Inventory off, Listed, In Stock) is Check Inventory: cyan
    assert _skus(loaded, "hp") == ["SKU-1"]
    assert _skus(loaded, "oos") == ["SKU-2"]
    assert _skus(loaded, "chk") == ["SKU-3"]
    assert _skus(loaded, "none") == ["SKU-4"]
    assert _skus(loaded, "hp,oos") == ["SKU-1", "SKU-2"]                      # several colours: any of them
    for st, k in (("Low Price", "lp"), ("Low Inventory", "li"), ("TimeFrame", "tf"), ("Manual Check", "mc")):
        c.execute("UPDATE products SET status=? WHERE sku='SKU-4'", (st,))
        assert _skus(loaded, k) == ["SKU-4"], st
    c.execute("UPDATE products SET inventory=0 WHERE sku='SKU-4'")
    assert _skus(loaded, "mc") == []                                           # a row colour needs Inventory on (Check Inventory: off)
    assert _skus(loaded, "box_sold") == ["SKU-1"] and _skus(loaded, "sold_total") == ["SKU-1"] and _skus(loaded, "sold_2026") == ["SKU-1"]
    assert _skus(loaded, "name_amazon") == ["SKU-4"]                           # "Not Amazon": AMAZON in the Product Name, any case
    cells(loaded, ("SKU-4", "name", "Plain gift card"))
    assert _skus(loaded, "name_amazon") == []
    assert _skus(loaded, "nonsense") == []                                     # an unknown colour shows nothing, not everything
    # duplicates: the same value (ignoring case and spaces) on two rows blacks out both
    assert _skus(loaded, "dup_upc") == [] and _skus(loaded, "dup_spn") == []
    cells(loaded, ("SKU-3", "upc", "111 "), ("SKU-3", "spn", "max-0001-wf"))
    assert _skus(loaded, "dup_upc") == ["SKU-1", "SKU-3"] and _skus(loaded, "dup_spn") == ["SKU-1", "SKU-3"]
    rows = {r["sku"]: r for r in loaded.post("/api/sheet/rows", json={"skus": ["SKU-1", "SKU-2", "SKU-3"]}).json()["rows"]}
    assert set(rows["SKU-1"]["_dup"]) == {"upc", "spn"} and rows["SKU-2"]["_dup"] == []
    cells(loaded, ("SKU-2", "name", "acrylic paint set 12 pack"))
    assert _skus(loaded, "dup_name") == ["SKU-1", "SKU-2"]

    # it combines with the other filters, and is kept in saved views and work lists
    assert loaded.post("/api/sheet/skus", json={"color": "hp,oos", "q": "Wooden"}).json()["skus"] == []
    assert loaded.post("/api/sheet/skus", json={"color": "hp,oos", "q": "paint"}).json()["skus"] == ["SKU-1", "SKU-2"]
    assert loaded.post("/api/views", json={"name": "Reds", "params": {"color": "hp"}}).status_code == 200
    assert loaded.get("/api/views").json()["items"][0]["params"]["color"] == "hp"
    w = loaded.post("/api/work", json={"name": "Reds", "params": {"color": "hp"}, "skus": ["SKU-1"]}).json()
    assert loaded.get(f"/api/work/{w['id']}").json()["params"] == {"color": "hp"}


def test_colour_filters_are_per_column_by_colour_name_and_combine(loaded):
    """Like Google Sheets: each column has its own colour filter, picked by colour (not by rule), and filters on different
    columns narrow the view together instead of replacing each other."""
    ask = lambda **q: sorted(loaded.post("/api/sheet/skus", json=q).json()["skus"])
    cells(loaded, ("SKU-3", "upc", "111"))                                           # SKU-1 and SKU-3 share a UPC: black in UPC
    c = db.conn()
    c.execute("UPDATE products SET inventory=1, status='High Price' WHERE sku IN ('SKU-1','SKU-3')")
    c.execute("UPDATE products SET inventory=1, status='Low Price' WHERE sku='SKU-2'")
    c.execute("UPDATE products SET status='Normal', name='Not Amazon' WHERE sku='SKU-4'")
    assert ask(cf_asin="fill:red") == ["SKU-1", "SKU-3"]
    assert ask(cf_asin="fill:gray") == ["SKU-2"]
    assert ask(cf_name="fill:red") == ["SKU-1", "SKU-3", "SKU-4"]                     # red rows, and the name saying AMAZON
    assert ask(cf_upc="fill:black") == ["SKU-1", "SKU-3"]                             # black wins over the red row colour
    assert ask(cf_upc="fill:red") == []
    assert ask(cf_asin="fill:none") == ["SKU-4"]
    # two columns, and a colour plus an ordinary filter: both apply
    assert ask(cf_asin="fill:red", cf_upc="fill:black") == ["SKU-1", "SKU-3"]
    assert ask(cf_asin="fill:red", cf_source_price=">8") == ["SKU-1"]
    assert ask(cf_asin="fill:red", cf_name="eq:no weight item") == ["SKU-3"]
    assert ask(cf_asin="fill:gray", cf_upc="fill:black") == []
    # a column that can't be that colour finds nothing; nonsense finds nothing
    assert ask(cf_spn="fill:cyan") == [] and ask(cf_asin="fill:purple") == []
    c.execute("UPDATE products SET sold_2026=3 WHERE sku='SKU-2'")
    assert ask(cf_inventory="text:red") == ["SKU-2"] and ask(cf_sold_2026="fill:cyan") == ["SKU-2"]
    # sort by colour, per column
    first = loaded.post("/api/sheet/skus", json={"sort": "color:asin:fill:gray"}).json()["skus"]
    assert first[0] == "SKU-2"
    last = loaded.post("/api/sheet/skus", json={"sort": "-color:upc:fill:black"}).json()["skus"]
    assert set(last[-2:]) == {"SKU-1", "SKU-3"}


def test_oos_different_item_and_oos_variation_have_their_colours(loaded):
    c = db.conn()
    c.execute("UPDATE products SET inventory=1, status='OOS Different Item' WHERE sku='SKU-1'")
    c.execute("UPDATE products SET inventory=1, status='OOS Variation' WHERE sku='SKU-2'")
    c.execute("UPDATE products SET inventory=0, status='OOS Variation' WHERE sku='SKU-3'")       # Inventory off: no colour
    assert _skus(loaded, "oosdi") == ["SKU-1"] and _skus(loaded, "oosv") == ["SKU-2"]
    ask = lambda **q: sorted(loaded.post("/api/sheet/skus", json=q).json()["skus"])
    assert ask(cf_variation="fill:palegreen") == ["SKU-1"] and ask(cf_amazon_variation="fill:yellow") == ["SKU-2"]
    # the scraper's variation turns a product into OOS Variation, and the Title Check column is back
    loaded.post("/api/sheet/cells", json={"edits": [{"sku": "SKU-4", "field": "variation", "value": "Large"}]})
    c.execute("UPDATE products SET amazon_variation='Size: Small' WHERE sku='SKU-4'")
    loaded.post("/api/sheet/cells", json={"edits": [{"sku": "SKU-4", "field": "variation", "value": "LARGE"}]})
    row = loaded.post("/api/sheet/rows", json={"skus": ["SKU-4"]}).json()["rows"][0]
    assert row["status"] == "OOS Variation" and "title_check" in row


def test_work_list_from_a_column_colour_filter_tracks_resolved_rows(loaded):
    params = next(p for p in ({"cf_sku": f"fill:{c}"} for c in ("red", "green", "gray", "orange", "magenta", "cyan"))
                  if loaded.post("/api/sheet/skus", json=p).json()["skus"])     # an issue row colour the sample data has
    skus = loaded.post("/api/sheet/skus", json=params).json()["skus"]
    w = loaded.post("/api/work", json={"name": "Colour", "params": params, "skus": skus}).json()
    assert loaded.get(f"/api/work/{w['id']}").json()["open"] == len(skus)
    loaded.post("/api/sheet/cells", json={"edits": [{"sku": skus[0], "field": "inventory", "value": "FALSE"}, {"sku": skus[0], "field": "listed", "value": "FALSE"}]})
    got = loaded.get(f"/api/work/{w['id']}").json()
    assert skus[0] in got["resolved"] and got["total"] == len(skus) and skus[0] in got["edited"]   # fixed rows stay, marked
