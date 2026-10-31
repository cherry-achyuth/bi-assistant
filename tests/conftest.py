from pathlib import Path

import pytest

from app import db
from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent
REAL_CSV = ROOT / "data" / "sales.csv"
HEADER = "Transaction_Id,Order_date,Product,Category,Region,Sales_channel,Quantity,Unit_price,Discount_amount,Status"

# Small dataset with totals worked out by hand (completed orders only):
#   T1 10*100 = 1000 (Jan, Mouse, North)      T2 2*500-100 = 900 (Jan, Chair, South)
#   T3 5*100  = 500  (Feb, Mouse, North)      T4 1*2000    = 2000 (Feb, Desk, South)
#   T5 is Returned (3*5000 = 15000, Chair, West) and must be ignored.
# total = 4400 | Desk 2000, Mouse 1500, Chair 900 | South 2900, North 1500
# Jan = 1900, Feb = 2500 -> +600 (+31.6%)
SMALL_ROWS = [
    "T1,05-01-2026,Mouse,Accessories,North,Online,10,100,0,Completed",
    "T2,10-01-2026,Chair,Furniture,South,Retail,2,500,100,Completed",
    "T3,03-02-2026,Mouse,Accessories,North,Online,5,100,0,Completed",
    "T4,04-02-2026,Desk,Furniture,South,Retail,1,2000,0,Completed",
    "T5,05-02-2026,Chair,Furniture,West,Retail,3,5000,0,Returned",
]


def write_csv(tmp_path, rows, name="test.csv"):
    path = tmp_path / name
    path.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def no_llm_by_default(monkeypatch):
    """Tests must not call the real API."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("USE_LLM", raising=False)


@pytest.fixture
def small_conn(tmp_path):
    return db.get_connection(write_csv(tmp_path, SMALL_ROWS))


@pytest.fixture
def small_client(tmp_path):
    return create_app(write_csv(tmp_path, SMALL_ROWS)).test_client()


@pytest.fixture
def real_conn():
    return db.get_connection(REAL_CSV)


@pytest.fixture
def real_client():
    return create_app(REAL_CSV).test_client()
