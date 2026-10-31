"""Analytics queries. All SQL is written here in advance and only the month values are
passed in as parameters, so a question can never change what SQL is executed.

Revenue = quantity * unit_price - discount (stored in the sales.revenue column),
and only orders with status 'Completed' are counted."""
import re


class AnalyticsError(ValueError):
    """A problem the user can understand, e.g. a month with no data."""


TOTAL_SQL = """
SELECT COUNT(*) AS orders, SUM(quantity) AS units,
       SUM(quantity * unit_price) AS gross_amount, SUM(discount) AS discounts,
       SUM(revenue) AS revenue
FROM sales WHERE status = 'Completed'"""

TOP_PRODUCT_SQL = """
SELECT product, SUM(revenue) AS revenue, SUM(quantity) AS units, COUNT(*) AS orders
FROM sales WHERE status = 'Completed'
GROUP BY product ORDER BY revenue DESC"""

TOP_REGION_SQL = """
SELECT region, SUM(revenue) AS revenue, SUM(quantity) AS units, COUNT(*) AS orders
FROM sales WHERE status = 'Completed'
GROUP BY region ORDER BY revenue DESC"""

TOP_CATEGORY_SQL = """
SELECT category, SUM(revenue) AS revenue, SUM(quantity) AS units, COUNT(*) AS orders
FROM sales WHERE status = 'Completed'
GROUP BY category ORDER BY revenue DESC"""

MONTHLY_SQL = """
SELECT month, SUM(revenue) AS revenue, COUNT(*) AS orders
FROM sales WHERE status = 'Completed'
GROUP BY month ORDER BY month"""

TWO_MONTHS_SQL = """
SELECT month, SUM(revenue) AS revenue, COUNT(*) AS orders
FROM sales WHERE status = 'Completed' AND month IN (?, ?)
GROUP BY month"""

DATA_RANGE_SQL = "SELECT MIN(month) AS first_month, MAX(month) AS last_month FROM sales"


def fetch_all(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def check_month(value):
    """Months must look like 2026-03."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise AnalyticsError(f"'{value}' is not a valid month. Use the format YYYY-MM, e.g. 2026-03.")
    return value


def total_revenue(conn):
    row = fetch_all(conn, TOTAL_SQL)[0]
    if row["orders"] == 0:
        raise AnalyticsError("There are no completed sales in the database.")
    return {"answer": f"Total revenue is {row['revenue']:,.0f} from {row['orders']} completed orders.",
            "figures": [row], "sql": TOTAL_SQL.strip()}


def top_group(conn, sql, label, measure):
    """Shared by top product / region / category: the first row has the highest revenue."""
    rows = fetch_all(conn, sql)
    if not rows:
        raise AnalyticsError("There are no completed sales in the database.")
    best = rows[0]
    tied = [r[label] for r in rows[1:] if r["revenue"] == best["revenue"]]
    note = f" (tied with {', '.join(tied)})" if tied else ""
    return {"answer": f"{best[label]} had the highest {measure}: {best['revenue']:,.0f}{note}.",
            "figures": rows, "sql": sql.strip()}


def top_product(conn):
    return top_group(conn, TOP_PRODUCT_SQL, "product", "revenue")


def top_region(conn):
    return top_group(conn, TOP_REGION_SQL, "region", "sales")


def top_category(conn):
    return top_group(conn, TOP_CATEGORY_SQL, "category", "revenue")


def monthly_trend(conn):
    rows = fetch_all(conn, MONTHLY_SQL)
    if not rows:
        raise AnalyticsError("There are no completed sales in the database.")

    previous = None
    for row in rows:
        if previous:
            row["change_pct"] = round((row["revenue"] - previous) / previous * 100, 1)
        else:
            row["change_pct"] = None      # first month has nothing to compare with
        previous = row["revenue"]

    peak = max(rows, key=lambda r: r["revenue"])
    return {"answer": f"Revenue by month for {len(rows)} months. The highest month was "
                      f"{peak['month']} with {peak['revenue']:,.0f}.",
            "figures": rows, "sql": MONTHLY_SQL.strip()}


def month_comparison(conn, month_a=None, month_b=None):
    if not month_a or not month_b:
        raise AnalyticsError("Please name two months to compare, e.g. 'compare February and March'.")
    month_a, month_b = check_month(month_a), check_month(month_b)
    if month_a == month_b:
        raise AnalyticsError("Please choose two different months.")

    found = {r["month"]: r for r in fetch_all(conn, TWO_MONTHS_SQL, (month_a, month_b))}
    for month in (month_a, month_b):
        if month not in found:
            data_range = fetch_all(conn, DATA_RANGE_SQL)[0]
            if data_range["first_month"] is None:
                raise AnalyticsError("There are no sales in the database.")
            raise AnalyticsError(f"There are no completed sales for {month}. The data covers "
                                 f"{data_range['first_month']} to {data_range['last_month']}.")

    a, b = found[month_a], found[month_b]
    difference = b["revenue"] - a["revenue"]
    percent = round(difference / a["revenue"] * 100, 1)
    if difference > 0:
        direction = "increased"
    elif difference < 0:
        direction = "decreased"
    else:
        direction = "stayed the same"

    return {"answer": f"Revenue {direction} from {a['revenue']:,.0f} in {month_a} to "
                      f"{b['revenue']:,.0f} in {month_b} ({difference:+,.0f}, {percent:+.1f}%).",
            "figures": [a, b,
                        {"month": "change", "revenue": difference,
                         "orders": b["orders"] - a["orders"], "change_pct": percent}],
            "sql": TWO_MONTHS_SQL.strip()}


# The only operations a question can be turned into.
# Each function takes the connection (and month_a / month_b for the comparison).
INTENTS = {
    "total_revenue": total_revenue,
    "top_product": top_product,
    "top_region": top_region,
    "top_category": top_category,
    "monthly_trend": monthly_trend,
    "month_comparison": month_comparison,
}
