from app.inventory import check_group

H = "Part Number,Wayfair MPLID (previously known as Wayfair SKU),Warehouse Name,Warehouse Type,In Stock,Available,Back In Stock Quantity,Back In Stock Date,Order Past 90 Days,In Stock Update,Retail Price,Priority Products\n"


def R(stock, price, wh="CITRUS COMMERCE LLC CO 80907"):
    return {"warehouse": wh, "in_stock": stock, "price": price}


def test_check_follows_the_sheet():
    assert check_group([R("19", "335.99"), R("19", "335.99"), R("19", "335.99")])[0] == "OK"
    assert check_group([R("20", "235.99"), R("19", "235.99"), R("1", "235.99")])[0] == "OK"      # stock may differ above 0
    assert check_group([R("0", "319.99"), R("", "319.99"), R("0", "319.99")])[0] == "OK"         # blank counts as 0
    assert check_group([R("", ""), R("", ""), R("", "")])[0] == "OK"
    chk, why = check_group([R("19", "10"), R("0", "10", "CITRUS COMMERCE LLC FL 32811"), R("4", "10")])
    assert chk == "MISMATCH" and "Stock 0 in FL 32811" in why
    chk, why = check_group([R("5", "10.00"), R("5", "10"), R("5", "12.5", "CITRUS COMMERCE LLC MI 49010")])
    assert chk == "MISMATCH" and "Price differs" in why and "MI 49010" in why
    assert check_group([R("5", "10")])[0] == ""                                                # one warehouse: nothing to compare


def test_inventory_import_and_listing(loaded):
    rows = "".join(f"P{i},SKU-{i},CITRUS COMMERCE LLC {w},Dropship,{s},{s},0,,,,{p},SRB\n"
                   for i, w, s, p in [(1, "CO 80907", 3, "9.99"), (1, "FL 32811", 0, "9.99"), (1, "MI 49010", 3, "9.99"),
                                      (2, "CO 80907", 5, "4.00"), (2, "FL 32811", 6, "4.00"), (2, "MI 49010", 7, "4.00"),
                                      (9, "CO 80907", 0, "1"), (9, "FL 32811", 0, "2"), (9, "MI 49010", 0, "1")])
    r = loaded.post("/api/inventory/import", content=(H + rows).encode(), headers={"X-Filename": "inv.csv"}).json()
    assert r["products"] == 3 and r["rows"] == 9 and r["mismatch"] == 2 and r["ok_products"] == 1
    assert r["catalog_filled"] == 2                                     # P9's SKU-9 isn't in the catalog
    p1 = loaded.get("/api/products/SKU-1").json()["product"]
    assert p1["wayfair_qty"] == 3 and p1["wayfair_price"] == 9.99      # the first warehouse row (CO), not FL's 0
    d = loaded.get("/api/inventory", params={"show": "mismatch"}).json()
    assert d["page"] == 0 and d["total"] == 2
    assert [g["part"] for g in d["groups"]] == ["P1", "P9"] and d["counts"]["not_in_catalog"] == 1
    assert d["groups"][0]["name"] == "Acrylic Paint Set 12 Pack" and len(d["groups"][0]["rows"]) == 3
    assert [g["part"] for g in loaded.get("/api/inventory", params={"q": "paint"}).json()["groups"]] == ["P1"]
    csv = loaded.get("/api/export/inventory.csv").content.decode("utf-8-sig")
    assert csv.count("MISMATCH") == 2 and len(csv.strip().splitlines()) == 7
    # a new upload replaces the old one
    loaded.post("/api/inventory/import", content=(H + rows.split("\n", 3)[3]).encode(), headers={"X-Filename": "inv2.csv"})
    assert loaded.get("/api/inventory").json()["counts"]["products"] == 2
