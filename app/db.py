"""Loads the sales CSV into SQLite. Rows that fail validation are not discarded:
they are stored in the rejected_rows table together with the reason."""
import csv
import math
import sqlite3
from datetime import datetime

REQUIRED_COLUMNS = ["Transaction_Id", "Order_date", "Product", "Category", "Region",
                    "Sales_channel", "Quantity", "Unit_price", "Discount_amount", "Status"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
    transaction_id TEXT PRIMARY KEY,
    order_date     TEXT NOT NULL,       -- yyyy-mm-dd
    month          TEXT NOT NULL,       -- yyyy-mm, used for monthly queries
    product        TEXT NOT NULL,
    category       TEXT NOT NULL,
    region         TEXT NOT NULL,
    sales_channel  TEXT NOT NULL,
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    unit_price     REAL NOT NULL CHECK (unit_price > 0),
    discount       REAL NOT NULL DEFAULT 0 CHECK (discount >= 0),
    status         TEXT NOT NULL,
    revenue        REAL NOT NULL        -- quantity * unit_price - discount
);

CREATE TABLE IF NOT EXISTS rejected_rows (
    line_number    INTEGER,             -- line in the CSV file (header is line 1)
    transaction_id TEXT,
    reason         TEXT NOT NULL,
    raw_row        TEXT
);
"""


def parse_number(text):
    """Convert a CSV cell to a float. Returns None for a blank cell.
    Raises ValueError for text that is not a finite number."""
    # the dataset contains a non-breaking space (\xa0) in one price cell
    text = (text or "").replace("\xa0", " ").strip()
    if text == "":
        return None
    value = float(text)
    if not math.isfinite(value):      # float() accepts "nan" and "inf"
        raise ValueError("not a finite number")
    return value


def clean_row(row):
    """Validate one CSV row. Returns (clean_row, None) or (None, reason)."""
    for column in ["Transaction_Id", "Product", "Category", "Region", "Sales_channel", "Status"]:
        if not (row.get(column) or "").strip():
            return None, f"missing {column}"

    try:
        order_date = datetime.strptime(row["Order_date"].strip(), "%d-%m-%Y")
    except (ValueError, AttributeError):
        return None, "invalid order date (expected DD-MM-YYYY)"

    try:
        quantity = parse_number(row["Quantity"])
        unit_price = parse_number(row["Unit_price"])
        discount = parse_number(row["Discount_amount"])
    except ValueError:
        return None, "quantity, unit price or discount is not a number"

    if quantity is None:
        return None, "missing quantity"
    if unit_price is None:
        return None, "missing unit price"
    if discount is None:
        discount = 0.0                # a blank discount means no discount

    if not quantity.is_integer():
        return None, "quantity must be a whole number"
    if quantity <= 0:
        return None, "quantity must be greater than 0"
    if unit_price <= 0:
        return None, "unit price must be greater than 0"
    if discount < 0:
        return None, "discount cannot be negative"
    if discount > quantity * unit_price:
        return None, "discount is larger than the order amount"

    return {
        "transaction_id": row["Transaction_Id"].strip(),
        "order_date": order_date.strftime("%Y-%m-%d"),
        "month": order_date.strftime("%Y-%m"),
        "product": row["Product"].strip(),
        "category": row["Category"].strip(),
        "region": row["Region"].strip().title(),
        "sales_channel": row["Sales_channel"].strip(),
        "quantity": int(quantity),
        "unit_price": unit_price,
        "discount": discount,
        "status": row["Status"].strip().title(),
        "revenue": quantity * unit_price - discount,
    }, None


def create_tables(conn):
    conn.executescript(SCHEMA)


def load_csv(conn, csv_path):
    """Load the CSV into the sales table. Returns (loaded_count, rejected_count)."""
    create_tables(conn)
    conn.execute("DELETE FROM sales")
    conn.execute("DELETE FROM rejected_rows")

    loaded = 0
    rejected = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

        for line_number, row in enumerate(reader, start=2):
            clean, reason = clean_row(row)

            if clean is not None:
                try:
                    conn.execute(
                        "INSERT INTO sales VALUES (:transaction_id, :order_date, :month, :product, "
                        ":category, :region, :sales_channel, :quantity, :unit_price, :discount, "
                        ":status, :revenue)", clean)
                    loaded += 1
                    continue
                except sqlite3.IntegrityError:
                    # the PRIMARY KEY on transaction_id rejects the second copy
                    reason = "duplicate transaction id"

            rejected += 1
            conn.execute("INSERT INTO rejected_rows VALUES (?, ?, ?, ?)",
                         (line_number, (row.get("Transaction_Id") or "").strip(), reason, str(row)))

    conn.commit()
    return loaded, rejected


def get_connection(csv_path=None):
    """Create the in-memory database. The tables always exist, even without a CSV."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    if csv_path:
        load_csv(conn, csv_path)
    # extra safety: after loading, this connection refuses INSERT/UPDATE/DELETE/DROP
    conn.execute("PRAGMA query_only = ON")
    return conn
