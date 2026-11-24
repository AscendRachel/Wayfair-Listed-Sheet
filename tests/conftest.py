import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.mkdtemp(prefix="gt-test-")
os.environ["GT_DATA"] = _tmp
os.environ["GT_DB"] = str(Path(_tmp) / "test.db")
os.environ["GT_NO_AUTO_BACKUP"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402

# The MAXAYA LLC tab's columns. "Listing Status" is calculated in the sheet: the import ignores it and works it out again.
SAMPLE_CSV = """ASIN,Price,Availability,Estimated Delivery,Listed,Inventory,SKU,Product Name, Source Link,Source Price,Mark Up Percentage,PROMO PERCENTAGE,Promo Status,Source,Status,VARIATION,SPN,DISPLAY SKU,UPC,MPN,Listing Status,Last Optimization Run (Tapicker Output),Status Counter
B000000001,$12.50,In Stock,Arrives Tuesday,TRUE,TRUE,SKU-1,Acrylic Paint Set 12 Pack,https://www.amazon.com/dp/B000000001,10,48%,,,Amazon,Live,,MAX-0001-WF,,111,MPN-1,Low Price,2026-01-05 10:00:00,In Stock
B000000002,$3.00,Currently unavailable.,,TRUE,TRUE,SKU-2,Wooden Frame 8 inch,https://www.amazon.com/dp/B000000002?th=1,5,0.5,20%,Active,Amazon,Live,,MAX-0002-WF,Model: Oak,222,MPN-2,,2026-01-05 10:00:00,
,$7.00,In Stock,,TRUE,FALSE,SKU-3,No Weight Item,https://www.amazon.com/dp/B000000003,7,,,,Amazon,Live,,,,333,,,2026-01-05 10:00:00,
B000000004,,,,FALSE,TRUE,SKU-4,Not Amazon,https://example.com/x,3,50,,,,,,MAX-0004-WF,,,,,,
"""


@pytest.fixture(scope="session", autouse=True)
def _init():
    db.init()
    yield


@pytest.fixture()
def clean():
    """Empty every table between tests."""
    c = db.conn()
    for t in ("products", "history", "runs", "tasks", "agents", "imports", "wayfair_imports", "activity",
              "saved_views", "sessions", "users", "settings", "column_locks", "worklists", "brand_logo", "custom_columns", "versions"):
        c.execute(f"DELETE FROM {t}")
    auth.FAILED.clear()
    from app import protect
    protect.seed()                          # every test starts with the default (Wayfair) protections
    yield


@pytest.fixture()
def admin(clean):
    auth.add_user("boss", "The Boss", "password123", "admin")
    cl = TestClient(app)
    assert cl.post("/api/login", json={"username": "boss", "password": "password123"}).status_code == 200
    return cl


@pytest.fixture()
def loaded(admin):
    r = admin.post("/api/import", content=SAMPLE_CSV.encode(), headers={"X-Filename": "sheet.csv"})
    assert r.status_code == 200, r.text
    return admin
