"""Tests for CSV loading (db.py) and the analytics queries (analytics.py)."""
import csv
import sqlite3

import pytest

from app import analytics, db
from tests.conftest import REAL_CSV, SMALL_ROWS, write_csv


def load_rows(tmp_path, rows):
    """Load rows into a fresh database; return (conn, rejected as {transaction_id: reason})."""
    conn = db.get_connection(write_csv(tmp_path, rows))
    rejected = {r["transaction_id"]: r["reason"]
                for r in conn.execute("SELECT transaction_id, reason FROM rejected_rows")}
    return conn, rejected


def count_sales(conn):
    return conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]


# ---------- CSV loading ----------

def test_real_csv_loads_and_rejects_the_two_bad_rows():
    conn = db.get_connection(REAL_CSV)
    rejected = {r["transaction_id"]: r["reason"]
                for r in conn.execute("SELECT transaction_id, reason FROM rejected_rows")}
    assert count_sales(conn) == 49
    assert rejected == {"TXN0034": "quantity must be greater than 0",
                        "TXN0051": "missing unit price"}


def test_rejected_row_keeps_line_number_and_raw_data(tmp_path):
    conn, _ = load_rows(tmp_path, [SMALL_ROWS[0], "T9,05-01-2026,Mouse,Accessories,North,Online,0,100,0,Completed"])
    row = conn.execute("SELECT * FROM rejected_rows").fetchone()
    assert row["line_number"] == 3                  # header is line 1
    assert "T9" in row["raw_row"]


def test_missing_values_are_rejected(tmp_path):
    rows = [
        "M1,05-01-2026,Mouse,Accessories,North,Online,5,100,0,Completed",   # valid
        "M2,05-01-2026,,Accessories,North,Online,5,100,0,Completed",        # no product
        "M3,05-01-2026,Mouse,Accessories,North,Online,,100,0,Completed",    # no quantity
        "M4,05-01-2026,Mouse,Accessories,North,Online,5,,0,Completed",      # no price
        "M5,05-01-2026,Mouse,Accessories,North,Online,5,\u00a0,0,Completed",  # price is only a non-breaking space
        "M6,05-01-2026,Mouse,Accessories,,Online,5,100,0,Completed",        # no region
    ]
    conn, rejected = load_rows(tmp_path, rows)
    assert count_sales(conn) == 1
    assert set(rejected) == {"M2", "M3", "M4", "M5", "M6"}
    assert rejected["M4"] == "missing unit price"
    assert rejected["M5"] == "missing unit price"


def test_blank_discount_means_no_discount(tmp_path):
    conn, rejected = load_rows(tmp_path, ["D1,05-01-2026,Mouse,Accessories,North,Online,5,100,,Completed"])
    assert rejected == {}
    assert conn.execute("SELECT discount, revenue FROM sales").fetchone()[:] == (0, 500)


def test_fractional_quantity_is_rejected(tmp_path):
    rows = [
        "F1,05-01-2026,Mouse,Accessories,North,Online,2.5,100,0,Completed",
        "F2,05-01-2026,Mouse,Accessories,North,Online,3.0,100,0,Completed",   # whole number written as 3.0
    ]
    conn, rejected = load_rows(tmp_path, rows)
    assert rejected == {"F1": "quantity must be a whole number"}
    assert conn.execute("SELECT quantity FROM sales").fetchall()[0][0] == 3


def test_duplicate_transaction_id_keeps_first_and_rejects_second(tmp_path):
    rows = [
        "X1,05-01-2026,Mouse,Accessories,North,Online,5,100,0,Completed",
        "X1,06-01-2026,Desk,Furniture,South,Retail,1,9999,0,Completed",
    ]
    conn, rejected = load_rows(tmp_path, rows)
    assert rejected == {"X1": "duplicate transaction id"}
    assert count_sales(conn) == 1
    assert conn.execute("SELECT product FROM sales").fetchone()[0] == "Mouse"   # first row kept


@pytest.mark.parametrize("row", [
    "B1,2026-01-05,Mouse,Accessories,North,Online,5,100,0,Completed",    # wrong date format
    "B2,31-02-2026,Mouse,Accessories,North,Online,5,100,0,Completed",    # date does not exist
    "B3,05-01-2026,Mouse,Accessories,North,Online,abc,100,0,Completed",  # text quantity
    "B4,05-01-2026,Mouse,Accessories,North,Online,5,nan,0,Completed",    # nan
    "B5,05-01-2026,Mouse,Accessories,North,Online,5,100,-10,Completed",  # negative discount
    "B6,05-01-2026,Mouse,Accessories,North,Online,5,100,600,Completed",  # discount > amount
    "B7,05-01-2026,Mouse,Accessories,North,Online,-3,100,0,Completed",   # negative quantity
    "B8,05-01-2026,Mouse,Accessories,North,Online,5,0,0,Completed",      # zero price
])
def test_other_invalid_rows_are_rejected_not_loaded(tmp_path, row):
    conn, rejected = load_rows(tmp_path, [row])
    assert count_sales(conn) == 0
    assert len(rejected) == 1


def test_every_input_row_is_either_loaded_or_rejected(tmp_path):
    rows = SMALL_ROWS + ["Z1,05-01-2026,Mouse,Accessories,North,Online,0,100,0,Completed"]
    conn, rejected = load_rows(tmp_path, rows)
    assert count_sales(conn) + len(rejected) == len(rows)


def test_csv_with_missing_column_gives_clear_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Transaction_Id,Product\nT1,Mouse\n")
    with pytest.raises(ValueError, match="missing required columns"):
        db.get_connection(path)


def test_revenue_is_quantity_times_price_minus_discount(small_conn):
    row = small_conn.execute("SELECT revenue FROM sales WHERE transaction_id = 'T2'").fetchone()
    assert row[0] == 2 * 500 - 100


def test_database_refuses_changes_after_loading(small_conn):
    with pytest.raises(sqlite3.OperationalError):
        small_conn.execute("DROP TABLE sales")
    with pytest.raises(sqlite3.OperationalError):
        small_conn.execute("DELETE FROM sales")


def test_table_constraint_blocks_bad_insert():
    conn = sqlite3.connect(":memory:")
    db.create_tables(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sales VALUES ('A','2026-01-01','2026-01','p','c','r','o',0,10,0,'Completed',0)")


# ---------- Analytics (values calculated by hand in conftest.py) ----------

def test_total_revenue_ignores_returned_orders(small_conn):
    result = analytics.total_revenue(small_conn)
    assert result["figures"][0]["revenue"] == 4400
    assert result["figures"][0]["orders"] == 4
    assert "4,400" in result["answer"]


def test_top_product_ignores_returned_orders(small_conn):
    result = analytics.top_product(small_conn)
    assert result["figures"][0]["product"] == "Desk"        # Chair would win if the Returned order counted
    assert [r["revenue"] for r in result["figures"]] == [2000, 1500, 900]


def test_top_region(small_conn):
    result = analytics.top_region(small_conn)
    assert result["figures"][0]["region"] == "South"
    assert result["figures"][0]["revenue"] == 2900
    assert "West" not in [r["region"] for r in result["figures"]]


def test_top_group_reports_ties(tmp_path):
    rows = ["A,05-01-2026,Mouse,Acc,North,Online,1,100,0,Completed",
            "B,05-01-2026,Desk,Fur,South,Online,1,100,0,Completed"]
    result = analytics.top_product(db.get_connection(write_csv(tmp_path, rows)))
    assert "tied with" in result["answer"]


def test_monthly_trend(small_conn):
    result = analytics.monthly_trend(small_conn)
    months = {r["month"]: r for r in result["figures"]}
    assert months["2026-01"]["revenue"] == 1900 and months["2026-01"]["change_pct"] is None
    assert months["2026-02"]["revenue"] == 2500 and months["2026-02"]["change_pct"] == 31.6


def test_month_comparison(small_conn):
    result = analytics.month_comparison(small_conn, "2026-01", "2026-02")
    change = result["figures"][2]
    assert change["revenue"] == 600 and change["change_pct"] == 31.6
    assert "increased" in result["answer"]


def test_month_comparison_going_down(small_conn):
    result = analytics.month_comparison(small_conn, "2026-02", "2026-01")
    assert result["figures"][2]["revenue"] == -600
    assert "decreased" in result["answer"]


def test_top_category(small_conn):
    assert analytics.top_category(small_conn)["figures"][0]["category"] == "Furniture"   # 2900 vs 1500


def test_real_dataset_matches_independent_calculation(real_conn):
    """Recalculate the answers from the raw CSV with plain Python and compare with the SQL results."""
    total, by_product, by_region, by_month = 0, {}, {}, {}
    with open(REAL_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            price = row["Unit_price"].replace("\u00a0", "").strip()
            quantity = int(row["Quantity"])
            if row["Status"] != "Completed" or price == "" or quantity == 0:
                continue
            amount = quantity * float(price) - float(row["Discount_amount"])
            total += amount
            by_product[row["Product"]] = by_product.get(row["Product"], 0) + amount
            by_region[row["Region"]] = by_region.get(row["Region"], 0) + amount
            month = row["Order_date"][3:5]            # DD-MM-YYYY -> MM
            by_month[month] = by_month.get(month, 0) + amount

    assert analytics.total_revenue(real_conn)["figures"][0]["revenue"] == total
    top_product = analytics.top_product(real_conn)["figures"][0]
    assert (top_product["product"], top_product["revenue"]) == max(by_product.items(), key=lambda kv: kv[1])
    top_region = analytics.top_region(real_conn)["figures"][0]
    assert (top_region["region"], top_region["revenue"]) == max(by_region.items(), key=lambda kv: kv[1])
    monthly = analytics.monthly_trend(real_conn)["figures"]
    assert [r["revenue"] for r in monthly] == [by_month[m] for m in sorted(by_month)]


# ---------- Empty database and invalid months ----------

@pytest.fixture
def empty_conn(tmp_path):
    return db.get_connection(write_csv(tmp_path, []))


@pytest.mark.parametrize("function", [analytics.total_revenue, analytics.top_product, analytics.top_region,
                                      analytics.top_category, analytics.monthly_trend])
def test_empty_database_gives_clear_error(empty_conn, function):
    with pytest.raises(analytics.AnalyticsError, match="no completed sales"):
        function(empty_conn)


def test_empty_database_month_comparison(empty_conn):
    with pytest.raises(analytics.AnalyticsError, match="no sales"):
        analytics.month_comparison(empty_conn, "2026-01", "2026-02")


def test_database_with_only_returned_orders_counts_as_empty(tmp_path):
    conn = db.get_connection(write_csv(tmp_path, [SMALL_ROWS[4]]))
    with pytest.raises(analytics.AnalyticsError):
        analytics.total_revenue(conn)


@pytest.mark.parametrize("bad_month", ["2026-13", "2026-00", "March", "2026-3", "26-03", 202603,
                                       "2026-01'; DROP TABLE sales; --", "2026-01 OR 1=1"])
def test_invalid_month_is_rejected(small_conn, bad_month):
    with pytest.raises(analytics.AnalyticsError, match="not a valid month"):
        analytics.month_comparison(small_conn, "2026-01", bad_month)
    assert count_sales(small_conn) == len(SMALL_ROWS)      # nothing was changed


@pytest.mark.parametrize("missing_month", [None, ""])
def test_missing_month_is_rejected(small_conn, missing_month):
    with pytest.raises(analytics.AnalyticsError, match="two months"):
        analytics.month_comparison(small_conn, missing_month, "2026-01")


def test_month_with_no_data_names_the_available_range(small_conn):
    with pytest.raises(analytics.AnalyticsError, match="2026-01 to 2026-02"):
        analytics.month_comparison(small_conn, "2026-01", "2026-09")


def test_comparing_a_month_with_itself_is_rejected(small_conn):
    with pytest.raises(analytics.AnalyticsError, match="two different months"):
        analytics.month_comparison(small_conn, "2026-01", "2026-01")


def test_comparison_needs_two_months(small_conn):
    with pytest.raises(analytics.AnalyticsError, match="two months"):
        analytics.month_comparison(small_conn, "2026-01", None)
