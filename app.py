from flask import Flask, render_template, request, redirect, url_for, g
import sqlite3
from datetime import datetime

app = Flask(__name__)
DATABASE = "/data/raycrest.db"

BILL_PIN = "1213"


@app.template_filter("money")
def money_format(value):
    if value is None:
        return "0"
    return "{:,.0f}".format(value).replace(",", ".")


COMBO_RESTAURANT_PRICE = 800
COMBO_STAFF_PRICE = 1000

SUB_COMBO_RESTAURANT_PRICE = 800
SUB_COMBO_STAFF_PRICE = 1000

WATER_RESTAURANT_PRICE = 70
WATER_STAFF_PRICE = 100

SMALL_BREAD_RESTAURANT_PRICE = 150
SMALL_BREAD_STAFF_PRICE = 250

BREAD_400_RESTAURANT_PRICE = 250
BREAD_400_STAFF_PRICE = 350

BREAD_600_RESTAURANT_PRICE = 350
BREAD_600_STAFF_PRICE = 500

WATER_PER_COMBO = 2
FREE_WATER_EVERY_COMBOS = 2


def get_week_number(week_name):
    numbers = "".join(ch for ch in week_name if ch.isdigit())
    return int(numbers) if numbers else 999


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def add_column_if_missing(db, table, column, definition):
    columns = db.execute(f"PRAGMA table_info({table})").fetchall()
    column_names = [col["name"] for col in columns]

    if column not in column_names:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        db.commit()


def init_db():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT,
            week_name TEXT,
            combos INTEGER DEFAULT 0,
            sub_combo INTEGER DEFAULT 0,
            water_single INTEGER DEFAULT 0,
            small_bread INTEGER DEFAULT 0,
            bread_400 INTEGER DEFAULT 0,
            bread_600 INTEGER DEFAULT 0,
            restaurant_total INTEGER DEFAULT 0,
            staff_total INTEGER DEFAULT 0,
            profit INTEGER DEFAULT 0,
            free_water INTEGER DEFAULT 0,
            combo_water INTEGER DEFAULT 0,
            bill_done INTEGER DEFAULT 0,
            bill_note TEXT DEFAULT '',
            created_at TEXT
        )
    """)

    db.commit()

    add_column_if_missing(db, "orders", "sub_combo", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "orders", "small_bread", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "orders", "bread_400", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "orders", "bread_600", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "orders", "bill_done", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "orders", "bill_note", "TEXT DEFAULT ''")


def calculate_order(combos, sub_combo, water_single, small_bread, bread_400, bread_600):
    restaurant_total = (
        combos * COMBO_RESTAURANT_PRICE
        + sub_combo * SUB_COMBO_RESTAURANT_PRICE
        + water_single * WATER_RESTAURANT_PRICE
        + small_bread * SMALL_BREAD_RESTAURANT_PRICE
        + bread_400 * BREAD_400_RESTAURANT_PRICE
        + bread_600 * BREAD_600_RESTAURANT_PRICE
    )

    staff_total = (
        combos * COMBO_STAFF_PRICE
        + sub_combo * SUB_COMBO_STAFF_PRICE
        + water_single * WATER_STAFF_PRICE
        + small_bread * SMALL_BREAD_STAFF_PRICE
        + bread_400 * BREAD_400_STAFF_PRICE
        + bread_600 * BREAD_600_STAFF_PRICE
    )

    profit = staff_total - restaurant_total
    combo_water = combos * WATER_PER_COMBO
    free_water = combos // FREE_WATER_EVERY_COMBOS

    return {
        "restaurant_total": restaurant_total,
        "staff_total": staff_total,
        "profit": profit,
        "combo_water": combo_water,
        "free_water": free_water
    }


@app.route("/")
def index():
    init_db()
    db = get_db()

    orders = db.execute("""
        SELECT *
        FROM orders
        ORDER BY id DESC
    """).fetchall()

    weeks = {}

    for order in orders:
        week = order["week_name"]

        if week not in weeks:
            weeks[week] = {
                "orders": [],
                "staff_rank": {},
                "total_combos": 0,
                "total_sub_combo": 0,
                "total_water_single": 0,
                "total_small_bread": 0,
                "total_bread_400": 0,
                "total_bread_600": 0,
                "total_restaurant": 0,
                "total_staff": 0,
                "total_profit": 0,
                "total_bill_done": 0,
                "total_bill_not_done": 0
            }

        weeks[week]["orders"].append(order)
        weeks[week]["total_combos"] += order["combos"]
        weeks[week]["total_sub_combo"] += order["sub_combo"]
        weeks[week]["total_water_single"] += order["water_single"]
        weeks[week]["total_small_bread"] += order["small_bread"]
        weeks[week]["total_bread_400"] += order["bread_400"]
        weeks[week]["total_bread_600"] += order["bread_600"]
        weeks[week]["total_restaurant"] += order["restaurant_total"]
        weeks[week]["total_staff"] += order["staff_total"]
        weeks[week]["total_profit"] += order["profit"]

        if order["bill_done"] == 1:
            weeks[week]["total_bill_done"] += 1
        else:
            weeks[week]["total_bill_not_done"] += 1

        staff = order["staff_name"]

        if staff not in weeks[week]["staff_rank"]:
            weeks[week]["staff_rank"][staff] = {
                "staff_name": staff,
                "total_records": 0,
                "total_combos": 0,
                "total_sub_combo": 0,
                "total_water_single": 0,
                "total_small_bread": 0,
                "total_bread_400": 0,
                "total_bread_600": 0,
                "total_points": 0,
                "total_restaurant": 0,
                "total_staff": 0,
                "total_profit": 0
            }

        weeks[week]["staff_rank"][staff]["total_records"] += 1
        weeks[week]["staff_rank"][staff]["total_combos"] += order["combos"]
        weeks[week]["staff_rank"][staff]["total_sub_combo"] += order["sub_combo"]
        weeks[week]["staff_rank"][staff]["total_water_single"] += order["water_single"]
        weeks[week]["staff_rank"][staff]["total_small_bread"] += order["small_bread"]
        weeks[week]["staff_rank"][staff]["total_bread_400"] += order["bread_400"]
        weeks[week]["staff_rank"][staff]["total_bread_600"] += order["bread_600"]
        weeks[week]["staff_rank"][staff]["total_points"] += order["combos"] + order["sub_combo"]
        weeks[week]["staff_rank"][staff]["total_restaurant"] += order["restaurant_total"]
        weeks[week]["staff_rank"][staff]["total_staff"] += order["staff_total"]
        weeks[week]["staff_rank"][staff]["total_profit"] += order["profit"]

    sorted_weeks = dict(
        sorted(
            weeks.items(),
            key=lambda item: get_week_number(item[0])
        )
    )

    for week in sorted_weeks.values():
        week["staff_rank"] = sorted(
            week["staff_rank"].values(),
            key=lambda x: (x["total_points"], x["total_combos"], x["total_staff"]),
            reverse=True
        )

    return render_template("index.html", weeks=sorted_weeks)


@app.route("/add", methods=["POST"])
def add_order():
    staff_name = request.form["staff_name"]
    week_name = request.form["week_name"]

    combo_type = request.form["combo_type"]
    combo_qty = int(request.form["combo_qty"])

    water_single = int(request.form["water_single"])

    bread_type = request.form["bread_type"]
    bread_qty = int(request.form["bread_qty"])

    combos = 0
    sub_combo = 0

    if combo_type == "main":
        combos = combo_qty
    elif combo_type == "sub":
        sub_combo = combo_qty

    small_bread = 0
    bread_400 = 0
    bread_600 = 0

    if bread_type == "small":
        small_bread = bread_qty
    elif bread_type == "bread_400":
        bread_400 = bread_qty
    elif bread_type == "bread_600":
        bread_600 = bread_qty

    result = calculate_order(
        combos,
        sub_combo,
        water_single,
        small_bread,
        bread_400,
        bread_600
    )

    db = get_db()

    db.execute("""
        INSERT INTO orders (
            staff_name,
            week_name,
            combos,
            sub_combo,
            water_single,
            small_bread,
            bread_400,
            bread_600,
            restaurant_total,
            staff_total,
            profit,
            free_water,
            combo_water,
            bill_done,
            bill_note,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        staff_name,
        week_name,
        combos,
        sub_combo,
        water_single,
        small_bread,
        bread_400,
        bread_600,
        result["restaurant_total"],
        result["staff_total"],
        result["profit"],
        result["free_water"],
        result["combo_water"],
        0,
        "",
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    db.commit()

    return redirect(url_for("index"))


@app.route("/toggle_bill/<int:order_id>", methods=["POST"])
def toggle_bill(order_id):
    pin = request.form.get("pin", "")
    bill_note = request.form.get("bill_note", "")

    if pin != BILL_PIN:
        return redirect(url_for("index"))

    db = get_db()

    db.execute("""
        UPDATE orders
        SET bill_done = 1,
            bill_note = ?
        WHERE id = ?
    """, (bill_note, order_id))

    db.commit()

    return redirect(url_for("index"))


@app.route("/undo_bill/<int:order_id>", methods=["POST"])
def undo_bill(order_id):
    pin = request.form.get("pin", "")

    if pin != BILL_PIN:
        return redirect(url_for("index"))

    db = get_db()

    db.execute("""
        UPDATE orders
        SET bill_done = 0,
            bill_note = ''
        WHERE id = ?
    """, (order_id,))

    db.commit()

    return redirect(url_for("index"))


@app.route("/delete/<int:order_id>", methods=["POST"])
def delete_order(order_id):
    pin = request.form.get("pin", "")

    if pin != BILL_PIN:
        return redirect(url_for("index"))

    db = get_db()
    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    db.commit()

    return redirect(url_for("index"))


if __name__ == "__main__":
    with app.app_context():
        init_db()

    app.run(debug=True)