import json

from app import db


def pricing(c):
    return c.get("/api/meta").json()["pricing"]


def test_pricing_is_the_flat_3pl_fee(loaded):
    assert pricing(loaded) == {"fee": 3.0}
    assert "table_labels" not in loaded.get("/api/meta").json()


def test_settings_saved_by_an_older_version_fall_back_to_the_default_fee(loaded):
    old = {"markup": 1.6, "fee_buffer": 4, "active_table": "current", "tables": {"current": [{"max": 10, "fee": 5.0}]}}
    with db.tx() as c:
        db.set_setting(c, "pricing", json.dumps(old))
    assert pricing(loaded) == {"fee": 3.0}
    with db.tx() as c:                                    # leave the shared test database as it was
        c.execute("DELETE FROM settings WHERE key='pricing'")


def test_changing_the_fee_reprices_everything(loaded):
    before = loaded.get("/api/products/SKU-1").json()["product"]
    assert before["fee"] == 3 and before["auto_price"] == 19.24                   # (10 + 3) x 1.48
    prev = loaded.post("/api/pricing/preview", json={"pricing": {"fee": 4}}).json()
    assert prev["up"] == 3 and prev["none"] == 1                                    # SKU-3 has no mark up %: no price
    r = loaded.post("/api/pricing", json={"pricing": {"fee": 4}}).json()
    assert r["ok"] and r["pricing"] == {"fee": 4.0}
    after = loaded.get("/api/products/SKU-1").json()["product"]
    assert after["fee"] == 4 and after["auto_price"] == 20.72                       # (10 + 4) x 1.48
    assert loaded.get("/api/products/SKU-2").json()["product"]["auto_price"] == 16.88   # (5 + 4) x 1.5 / (1 - 0.2)
    log = loaded.get("/api/activity", params={"q": "3PL fee"}).json()["items"]
    assert log and "recalculated" in log[0]["detail"]
    assert loaded.post("/api/pricing", json={"pricing": {"fee": 3}}).json()["ok"]  # put the default back


def test_the_fee_is_validated(loaded):
    assert loaded.post("/api/pricing", json={"pricing": {"fee": -1}}).status_code == 400
    assert loaded.post("/api/pricing", json={"pricing": {"fee": "x"}}).status_code == 400


def test_current_pricing_impact_is_zero(loaded):
    i = loaded.get("/api/pricing/impact").json()
    assert i["up"] == 0 and i["down"] == 0 and i["products"] == 4 and "other" not in i
