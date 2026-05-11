from flask import Flask, render_template, request, redirect, url_for, g
import sqlite3
from datetime import datetime

app = Flask(__name__)
DATABASE = "raycrest.db"

COMBO_RESTAURANT_PRICE = 800
COMBO_STAFF_PRICE = 1000

WATER_RESTAURANT_PRICE = 50
WATER_STAFF_PRICE = 100

BREAD_RESTAURANT_PRICE = 100
BREAD_STAFF_PRICE = 200

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


def init_db():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT,
            week_name TEXT,
            combos INTEGER,
            water_single INTEGER,
            bread_single INTEGER,
            restaurant_total INTEGER,
            staff_total INTEGER,
            profit INTEGER,
            free_water INTEGER,
            combo_water INTEGER,
            created_at TEXT
        )
    """)

    db.commit()


def calculate_order(combos, water_single, bread_single):
    restaurant_total = (
        combos * COMBO_RESTAURANT_PRICE
        + water_single * WATER_RESTAURANT_PRICE
        + bread_single * BREAD_RESTAURANT_PRICE
    )

    staff_total = (
        combos * COMBO_STAFF_PRICE
        + water_single * WATER_STAFF_PRICE
        + bread_single * BREAD_STAFF_PRICE
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
                "total_water_single": 0,
                "total_bread_single": 0,
                "total_restaurant": 0,
                "total_staff": 0,
                "total_profit": 0
            }

        weeks[week]["orders"].append(order)
        weeks[week]["total_combos"] += order["combos"]
        weeks[week]["total_water_single"] += order["water_single"]
        weeks[week]["total_bread_single"] += order["bread_single"]
        weeks[week]["total_restaurant"] += order["restaurant_total"]
        weeks[week]["total_staff"] += order["staff_total"]
        weeks[week]["total_profit"] += order["profit"]

        staff = order["staff_name"]

        if staff not in weeks[week]["staff_rank"]:
            weeks[week]["staff_rank"][staff] = {
                "staff_name": staff,
                "total_records": 0,
                "total_combos": 0,
                "total_water_single": 0,
                "total_bread_single": 0,
                "total_points": 0,
                "total_restaurant": 0,
                "total_staff": 0,
                "total_profit": 0
            }

        weeks[week]["staff_rank"][staff]["total_records"] += 1
        weeks[week]["staff_rank"][staff]["total_combos"] += order["combos"]
        weeks[week]["staff_rank"][staff]["total_water_single"] += order["water_single"]
        weeks[week]["staff_rank"][staff]["total_bread_single"] += order["bread_single"]
        weeks[week]["staff_rank"][staff]["total_points"] += order["combos"]
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
            key=lambda x: (
                x["total_points"],
                x["total_combos"],
                x["total_staff"]
            ),
            reverse=True
        )

    return render_template(
        "index.html",
        weeks=sorted_weeks
    )


@app.route("/add", methods=["POST"])
def add_order():
    staff_name = request.form["staff_name"]
    week_name = request.form["week_name"]

    combos = int(request.form["combos"])
    water_single = int(request.form["water_single"])
    bread_single = int(request.form["bread_single"])

    result = calculate_order(combos, water_single, bread_single)

    db = get_db()

    db.execute("""
        INSERT INTO orders (
            staff_name,
            week_name,
            combos,
            water_single,
            bread_single,
            restaurant_total,
            staff_total,
            profit,
            free_water,
            combo_water,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        staff_name,
        week_name,
        combos,
        water_single,
        bread_single,
        result["restaurant_total"],
        result["staff_total"],
        result["profit"],
        result["free_water"],
        result["combo_water"],
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    db.commit()

    return redirect(url_for("index"))


@app.route("/delete/<int:order_id>", methods=["POST"])
def delete_order(order_id):
    db = get_db()
    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    db.commit()

    return redirect(url_for("index"))


if __name__ == "__main__":
    with app.app_context():
        init_db()

    app.run(debug=True)