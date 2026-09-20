from flask import Flask, render_template, request, redirect, url_for, g, session
import sqlite3
from datetime import datetime
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
DATABASE = "/data/raycrest.db"


MANAGER_PASSWORD = "1213"
app.secret_key = "raycrest-secret-key"


@app.template_filter("money")
def money_format(value):
    try:
        if value is None:
            return "0"

        return "{:,.0f}".format(float(value)).replace(",", ".")
    except:
        return "0"
    
WAREHOUSE_UPLOAD_FOLDER = os.path.join(
    app.static_folder,
    "uploads",
    "warehouse"
)

os.makedirs(
    WAREHOUSE_UPLOAD_FOLDER,
    exist_ok=True
)

ALLOWED_IMAGE_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}


def allowed_image(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_IMAGE_EXTENSIONS
    )


COMBO_RESTAURANT_PRICE = 700
COMBO_STAFF_PRICE = 1000

SUB_COMBO_RESTAURANT_PRICE = 700
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

def is_manager():
    return (
        "staff_name" in session
        and session.get("role") == "manager"
    )


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
            bill_done INTEGER DEFAULT 0,  -- legacy, no longer used
            bill_note TEXT DEFAULT '',  -- legacy, no longer used
            paid INTEGER DEFAULT 0,
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
    add_column_if_missing(db, "orders", "paid", "INTEGER DEFAULT 0")
    
    
    # Staff
    db.execute("""
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        position TEXT DEFAULT 'Nhân Viên',
        role TEXT DEFAULT 'staff'
    )
    """)
    
    # ==========================================
    # CREATE FIRST MANAGER IF NONE EXISTS
    # ==========================================

    manager_exists = db.execute("""
        SELECT id
        FROM staff
        WHERE role = 'manager'
        LIMIT 1
    """).fetchone()

    if manager_exists is None:
        db.execute("""
            INSERT OR IGNORE INTO staff (
                name,
                position,
                role
            )
            VALUES (?, ?, ?)
        """, (
            "Tommy",
            "Phó Giám Đốc",
            "manager"
        ))

    db.commit()
    
    
    add_column_if_missing(
        db,
        "staff",
        "position",
        "TEXT DEFAULT 'Nhân Viên'"
    )
    
    db.execute("""
    CREATE TABLE IF NOT EXISTS warehouse (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT NOT NULL,

        category TEXT DEFAULT 'Khác',

        quantity INTEGER DEFAULT 0,

        unit TEXT DEFAULT 'phần',

        image TEXT,

        note TEXT,

        created_at TEXT
    )
    """)
    
    db.execute("""
        UPDATE staff
        SET role = CASE
            WHEN position IN ('Giám Đốc', 'Phó Giám Đốc')
                THEN 'manager'
            ELSE 'staff'
        END
    """)

    db.commit()

    db.execute("""
        UPDATE staff
        SET position = ?, role = ?
        WHERE LOWER(name) = LOWER(?)
    """, ("Phó Giám Đốc", "manager", "Tommy"))

    db.execute("""
        UPDATE staff
        SET position = ?, role = ?
        WHERE LOWER(name) = LOWER(?)
    """, ("Nhân Viên", "staff", "Mia"))

    db.commit()
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS cost_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT UNIQUE,
            cost INTEGER DEFAULT 0
        )
    """)

    db.execute("""
     CREATE TABLE IF NOT EXISTS staff_advances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT,
            week_name TEXT,
            amount INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            created_at TEXT
        )
    """)
    
    add_column_if_missing(
        db,
            "staff_advances",
            "week_name",
            "TEXT DEFAULT 'Tuần 1'"
    )
    

    db.commit()

    default_costs = [
        ("combo_3_2", 0),
        ("combo_4_4", 0),
        ("water", 0),
        ("bread_300", 0),
        ("bread_400", 0),
        ("bread_600", 0)
    ]

    for item, cost in default_costs:
        db.execute("""
            INSERT OR IGNORE INTO cost_settings (item_name, cost)
            VALUES (?, ?)
        """, (item, cost))


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
    
def calculate_weekly_points_for_staff(staff_data):
    water = staff_data["total_water_single"]
    bread_300 = staff_data["total_small_bread"]
    bread_400 = staff_data["total_bread_400"]
    bread_600 = staff_data["total_bread_600"]

    combo_600_points = min(bread_600 // 2, water // 2)
    bread_600 -= combo_600_points * 2
    water -= combo_600_points * 2

    combo_400_points = min(bread_400 // 3, water // 2)
    bread_400 -= combo_400_points * 3
    water -= combo_400_points * 2

    combo_300_points = min(bread_300 // 4, water // 4)
    bread_300 -= combo_300_points * 4
    water -= combo_300_points * 4

    combo_main_points = staff_data["total_combos"]
    combo_sub_points = staff_data["total_sub_combo"]
    
    total_points = (
        combo_main_points
        + combo_sub_points
        + combo_600_points
        + combo_400_points
        + combo_300_points
    )

    return {
        "total_points": total_points,
        "combo_main_points": combo_main_points,
        "combo_sub_points": combo_sub_points,
        "combo_300_points": combo_300_points,
        "combo_400_points": combo_400_points,
        "combo_600_points": combo_600_points,
        "leftover_water": water,
        "leftover_bread_300": bread_300,
        "leftover_bread_400": bread_400,
        "leftover_bread_600": bread_600
    }


@app.route("/warehouse")
def warehouse():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    init_db()
    db = get_db()

    items = db.execute("""
        SELECT *
        FROM warehouse
        ORDER BY
            CASE
                WHEN quantity <= 0 THEN 1
                WHEN quantity <= 5 THEN 2
                ELSE 3
            END,
            name COLLATE NOCASE
    """).fetchall()


    total_items = len(items)

    in_stock = 0
    low_stock = 0
    out_stock = 0


    for item in items:

        quantity = item["quantity"] or 0

        if quantity <= 0:
            out_stock += 1

        elif quantity <= 5:
            low_stock += 1

        else:
            in_stock += 1


    return render_template(
        "warehouse.html",

        items=items,

        total_items=total_items,
        in_stock=in_stock,
        low_stock=low_stock,
        out_stock=out_stock,

        is_manager=(
            session.get("role") == "manager"
        )
    )

@app.route(
    "/warehouse/add",
    methods=["POST"]
)
def warehouse_add():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("warehouse"))


    name = request.form.get(
        "name",
        ""
    ).strip()

    category = request.form.get(
        "category",
        "Khác"
    ).strip()

    unit = request.form.get(
        "unit",
        "phần"
    ).strip()

    note = request.form.get(
        "note",
        ""
    ).strip()


    try:
        quantity = int(
            request.form.get(
                "quantity",
                0
            )
        )

    except ValueError:
        quantity = 0


    quantity = max(
        quantity,
        0
    )


    if not name:
        return redirect(
            url_for("warehouse")
        )


    # IMAGE

    image_filename = None

    image = request.files.get(
        "image"
    )


    if (
        image
        and image.filename
        and allowed_image(
            image.filename
        )
    ):

        filename = secure_filename(
            image.filename
        )

        # tránh trùng tên
        filename = (
            datetime.now().strftime(
                "%Y%m%d%H%M%S%f"
            )
            + "_"
            + filename
        )

        image.save(
            os.path.join(
                WAREHOUSE_UPLOAD_FOLDER,
                filename
            )
        )

        image_filename = filename


    db = get_db()

    db.execute("""
        INSERT INTO warehouse (
            name,
            category,
            quantity,
            unit,
            image,
            note,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        category,
        quantity,
        unit,
        image_filename,
        note,
        datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
    ))

    db.commit()


    return redirect(
        url_for("warehouse")
    )

@app.route(
    "/warehouse/<int:item_id>/quantity",
    methods=["POST"]
)
def warehouse_quantity(item_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("warehouse"))


    action = request.form.get(
        "action"
    )


    db = get_db()

    item = db.execute("""
        SELECT *
        FROM warehouse
        WHERE id = ?
    """, (item_id,)).fetchone()


    if not item:
        return redirect(
            url_for("warehouse")
        )


    quantity = item["quantity"] or 0


    if action == "plus":
        quantity += 1

    elif action == "minus":
        quantity = max(
            quantity - 1,
            0
        )


    db.execute("""
        UPDATE warehouse
        SET quantity = ?
        WHERE id = ?
    """, (
        quantity,
        item_id
    ))

    db.commit()


    return redirect(
        url_for("warehouse")
    )
    
@app.route(
    "/warehouse/<int:item_id>/delete",
    methods=["POST"]
)
def warehouse_delete(item_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("warehouse"))


    db = get_db()

    item = db.execute("""
        SELECT *
        FROM warehouse
        WHERE id = ?
    """, (item_id,)).fetchone()


    if item:

        # Xóa ảnh
        if item["image"]:

            image_path = os.path.join(
                WAREHOUSE_UPLOAD_FOLDER,
                item["image"]
            )

            if os.path.exists(image_path):
                os.remove(image_path)


        db.execute("""
            DELETE FROM warehouse
            WHERE id = ?
        """, (item_id,))

        db.commit()


    return redirect(
        url_for("warehouse")
    )
  
@app.route(
    "/warehouse/<int:item_id>/edit",
    methods=["POST"]
)
def warehouse_edit(item_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("warehouse"))

    db = get_db()

    item = db.execute("""
        SELECT *
        FROM warehouse
        WHERE id = ?
    """, (item_id,)).fetchone()

    if not item:
        return redirect(url_for("warehouse"))

    name = request.form.get("name", "").strip()
    category = request.form.get("category", "Khác").strip()
    unit = request.form.get("unit", "phần").strip()
    note = request.form.get("note", "").strip()

    try:
        quantity = int(
            request.form.get("quantity", 0)
        )
    except ValueError:
        quantity = 0

    quantity = max(quantity, 0)

    if not name:
        return redirect(url_for("warehouse"))

    # Giữ ảnh cũ mặc định
    image_filename = item["image"]

    new_image = request.files.get("image")

    if (
        new_image
        and new_image.filename
        and allowed_image(new_image.filename)
    ):

        # Xóa ảnh cũ
        if image_filename:

            old_path = os.path.join(
                WAREHOUSE_UPLOAD_FOLDER,
                image_filename
            )

            if os.path.exists(old_path):
                os.remove(old_path)

        # Lưu ảnh mới
        filename = secure_filename(
            new_image.filename
        )

        filename = (
            datetime.now().strftime(
                "%Y%m%d%H%M%S%f"
            )
            + "_"
            + filename
        )

        new_image.save(
            os.path.join(
                WAREHOUSE_UPLOAD_FOLDER,
                filename
            )
        )

        image_filename = filename

    db.execute("""
        UPDATE warehouse
        SET
            name = ?,
            category = ?,
            quantity = ?,
            unit = ?,
            image = ?,
            note = ?
        WHERE id = ?
    """, (
        name,
        category,
        quantity,
        unit,
        image_filename,
        note,
        item_id
    ))

    db.commit()

    return redirect(url_for("warehouse"))
  
@app.route("/dashboard")
def index():

    if "staff_name" not in session:
        return redirect(url_for("login"))

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
                "total_paid": 0,
                "total_unpaid": 0
            }

        weeks[week]["orders"].append(order)

        if order["paid"] == 1:
            weeks[week]["total_paid"] += 1
        else:
            weeks[week]["total_unpaid"] += 1
            continue

        staff_name = order["staff_name"]

        if staff_name not in weeks[week]["staff_rank"]:
            weeks[week]["staff_rank"][staff_name] = {
                "staff_name": staff_name,
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

        combos = order["combos"] or 0
        sub_combo = order["sub_combo"] or 0
        water = order["water_single"] or 0
        bread_300 = order["small_bread"] or 0
        bread_400 = order["bread_400"] or 0
        bread_600 = order["bread_600"] or 0
        restaurant_total = order["restaurant_total"] or 0
        staff_total = order["staff_total"] or 0
        profit = order["profit"] or 0

        weeks[week]["total_combos"] += combos
        weeks[week]["total_sub_combo"] += sub_combo
        weeks[week]["total_water_single"] += water
        weeks[week]["total_small_bread"] += bread_300
        weeks[week]["total_bread_400"] += bread_400
        weeks[week]["total_bread_600"] += bread_600
        weeks[week]["total_restaurant"] += restaurant_total
        weeks[week]["total_staff"] += staff_total
        weeks[week]["total_profit"] += profit

        staff = weeks[week]["staff_rank"][staff_name]

        staff["total_records"] += 1
        staff["total_combos"] += combos
        staff["total_sub_combo"] += sub_combo
        staff["total_water_single"] += water
        staff["total_small_bread"] += bread_300
        staff["total_bread_400"] += bread_400
        staff["total_bread_600"] += bread_600
        staff["total_restaurant"] += restaurant_total
        staff["total_staff"] += staff_total
        staff["total_profit"] += profit

    sorted_weeks = dict(
        sorted(
            weeks.items(),
            key=lambda item: get_week_number(item[0])
        )
    )

    for week_name, week_data in sorted_weeks.items():
        for staff in week_data["staff_rank"].values():
            point_result = calculate_weekly_points_for_staff(staff)

            staff["total_points"] = point_result["total_points"]
            staff["combo_300_points"] = point_result["combo_300_points"]
            staff["combo_400_points"] = point_result["combo_400_points"]
            staff["combo_600_points"] = point_result["combo_600_points"]
            staff["leftover_water"] = point_result["leftover_water"]
            staff["leftover_bread_300"] = point_result["leftover_bread_300"]
            staff["leftover_bread_400"] = point_result["leftover_bread_400"]
            staff["leftover_bread_600"] = point_result["leftover_bread_600"]

        week_data["staff_rank"] = sorted(
            week_data["staff_rank"].values(),
            key=lambda x: (
                x["total_points"],
                x["total_restaurant"],
                x["total_staff"]
            ),
            reverse=True
        )

    return render_template("index.html", weeks=sorted_weeks)

@app.route("/data-entry")
def data_entry():
    if "staff_name" not in session:
        return redirect(url_for("login"))

    return render_template("data_entry.html")

@app.route("/employees")
def employees():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    init_db()
    db = get_db()

    staff_list = db.execute("""
        SELECT id, name, position, role
        FROM staff
        ORDER BY
            CASE position
                WHEN 'Giám Đốc' THEN 1
                WHEN 'Phó Giám Đốc' THEN 2
                WHEN 'Quản Lý' THEN 3
                WHEN 'Nhân Viên' THEN 4
                WHEN 'Thực Tập' THEN 5
                ELSE 6
            END,
            name COLLATE NOCASE
    """).fetchall()

    return render_template(
        "employees.html",
        staff_list=staff_list
    )


@app.route("/employees/add", methods=["POST"])
def add_employee():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("employees"))

    name = request.form.get("name", "").strip()
    position = request.form.get("position", "Nhân Viên").strip()
    

    manager_positions = [
        "Giám Đốc",
        "Phó Giám Đốc",
    ]

    role = (
        "manager"
        if position in manager_positions
        else "staff"
    )

    if not name:
        return redirect(url_for("employees"))

    db = get_db()
    
    staff_name = session.get("staff_name")

    try:
        db.execute("""
            INSERT INTO staff (name, position, role)
            VALUES (?, ?, ?)
        """, (name, position, role))

        db.commit()

    except sqlite3.IntegrityError:
        pass

    return redirect(url_for("employees"))


@app.route("/employees/edit/<int:staff_id>", methods=["POST"])
def edit_employee(staff_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("employees"))

    name = request.form.get("name", "").strip()
    position = request.form.get("position", "Nhân Viên").strip()

    manager_positions = [
        "Giám Đốc",
        "Phó Giám Đốc",
    ]

    role = (
        "manager"
        if position in manager_positions
        else "staff"
    )

    if not name:
        return redirect(url_for("employees"))

    db = get_db()

    try:
        db.execute("""
            UPDATE staff
            SET name = ?,
                position = ?,
                role = ?
            WHERE id = ?
        """, (
            name,
            position,
            role,
            staff_id
        ))

        db.commit()

        # Nếu đang sửa chính tài khoản đang login
        if staff_id == session.get("staff_id"):
            session["staff_name"] = name
            session["position"] = position
            session["role"] = role

    except sqlite3.IntegrityError:
        pass

    return redirect(url_for("employees"))


@app.route("/employees/delete/<int:staff_id>", methods=["POST"])
def delete_employee(staff_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("data_entry"))

    # Không cho xóa chính tài khoản đang sử dụng
    if staff_id == session.get("staff_id"):
        return redirect(url_for("employees"))

    db = get_db()

    db.execute("""
        DELETE FROM staff
        WHERE id = ?
    """, (staff_id,))

    db.commit()

    return redirect(url_for("employees"))

@app.route("/ranking")
def ranking():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    init_db()
    db = get_db()

    # Lấy danh sách tuần
    weeks = db.execute("""
        SELECT DISTINCT week_name
        FROM orders
        WHERE week_name IS NOT NULL
          AND TRIM(week_name) != ''
        ORDER BY week_name DESC
    """).fetchall()

    selected_week = request.args.get("week", "").strip()

    # Nếu chưa chọn tuần → lấy tuần đầu tiên
    if not selected_week and weeks:
        selected_week = weeks[0]["week_name"]

    ranking_data = []

    if selected_week:

        rows = db.execute("""
            SELECT *
            FROM orders
            WHERE week_name = ?
              AND paid = 1
        """, (selected_week,)).fetchall()

        staff_points = {}

        for row in rows:

            name = row["staff_name"]

            if name not in staff_points:
                staff_points[name] = {
                    "name": name,
                    "points": 0,
                    "combos": 0,
                    "sub_combo": 0,
                    "water": 0,
                    "bread": 0
                }

            combos = row["combos"] or 0
            sub_combo = row["sub_combo"] or 0
            water = row["water_single"] or 0
            bread_300 = row["small_bread"] or 0
            bread_400 = row["bread_400"] or 0
            bread_600 = row["bread_600"] or 0

            # Combo chính
            main_points = combos

            # Combo phụ
            sub_points = sub_combo

            # Điểm từ bánh + nước
            remaining_water = water

            combo_600 = min(
                bread_600 // 2,
                remaining_water // 2
            )

            remaining_water -= combo_600 * 2

            combo_400 = min(
                bread_400 // 3,
                remaining_water // 2
            )

            remaining_water -= combo_400 * 2

            combo_300 = min(
                bread_300 // 4,
                remaining_water // 4
            )

            points = (
                main_points
                + sub_points
                + combo_600
                + combo_400
                + combo_300
            )

            staff_points[name]["points"] += points
            staff_points[name]["combos"] += combos
            staff_points[name]["sub_combo"] += sub_combo
            staff_points[name]["water"] += water

            staff_points[name]["bread"] += (
                bread_300
                + bread_400
                + bread_600
            )

        ranking_data = sorted(
            staff_points.values(),
            key=lambda x: x["points"],
            reverse=True
        )

    return render_template(
        "ranking.html",
        ranking_data=ranking_data,
        weeks=weeks,
        selected_week=selected_week
    )
    
@app.route("/statistics")
def statistics():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    init_db()
    db = get_db()

    current_name = session.get("staff_name")
    is_manager = session.get("role") == "manager"

    # =========================================
    # DANH SÁCH TUẦN
    # =========================================

    if is_manager:
        week_rows = db.execute("""
            SELECT DISTINCT week_name
            FROM orders
            WHERE week_name IS NOT NULL
              AND TRIM(week_name) != ''
            ORDER BY week_name
        """).fetchall()
    else:
        week_rows = db.execute("""
            SELECT DISTINCT week_name
            FROM orders
            WHERE week_name IS NOT NULL
              AND TRIM(week_name) != ''
              AND LOWER(staff_name) = LOWER(?)
            ORDER BY week_name
        """, (current_name,)).fetchall()

    weeks = [row["week_name"] for row in week_rows]

    # Sắp xếp Tuần 1, Tuần 2, Tuần 3...
    weeks = sorted(
        weeks,
        key=get_week_number
    )

    # =========================================
    # TUẦN ĐANG CHỌN
    # =========================================

    selected_week = request.args.get("week", "").strip()

    if selected_week not in weeks:
        selected_week = weeks[-1] if weeks else ""

    # =========================================
    # LẤY ORDER
    # Chỉ bill đã thanh toán
    # =========================================

    orders = []

    if selected_week:

        if is_manager:

            orders = db.execute("""
                SELECT *
                FROM orders
                WHERE week_name = ?
                  AND paid = 1
                ORDER BY id ASC
            """, (selected_week,)).fetchall()

        else:

            orders = db.execute("""
                SELECT *
                FROM orders
                WHERE week_name = ?
                  AND paid = 1
                  AND LOWER(staff_name) = LOWER(?)
                ORDER BY id ASC
            """, (
                selected_week,
                current_name
            )).fetchall()

    # =========================================
    # TỔNG CỦA TUẦN
    # =========================================

    total_records = 0

    total_combos = 0
    total_sub_combo = 0

    total_water = 0

    total_bread_300 = 0
    total_bread_400 = 0
    total_bread_600 = 0

    # Chỉ manager sử dụng
    total_restaurant = 0
    total_profit = 0

    # =========================================
    # 7 NGÀY
    # Python weekday:
    # Monday = 0
    # Sunday = 6
    # =========================================

    day_names = [
        "T2",
        "T3",
        "T4",
        "T5",
        "T6",
        "T7",
        "CN"
    ]

    daily_data = []

    for day_name in day_names:

        daily_data.append({
            "day": day_name,

            "total_records": 0,

            "total_combos": 0,
            "total_sub_combo": 0,

            "total_water_single": 0,

            "total_small_bread": 0,
            "total_bread_400": 0,
            "total_bread_600": 0,

            "total_restaurant": 0,
            "total_staff": 0,
            "total_profit": 0,

            "total_points": 0
        })

    # =========================================
    # ĐỌC ORDER
    # =========================================

    for order in orders:

        combos = order["combos"] or 0
        sub_combo = order["sub_combo"] or 0

        water = order["water_single"] or 0

        bread_300 = order["small_bread"] or 0
        bread_400 = order["bread_400"] or 0
        bread_600 = order["bread_600"] or 0

        # Tổng tuần
        total_records += 1

        total_combos += combos
        total_sub_combo += sub_combo

        total_water += water

        total_bread_300 += bread_300
        total_bread_400 += bread_400
        total_bread_600 += bread_600

        if is_manager:
            total_restaurant += (
                order["restaurant_total"] or 0
            )

            total_profit += (
                order["profit"] or 0
            )

        # =====================================
        # XÁC ĐỊNH NGÀY TỪ created_at
        # =====================================

        created_at = order["created_at"]

        if not created_at:
            continue

        try:

            order_date = datetime.strptime(
                created_at,
                "%Y-%m-%d %H:%M"
            )

        except (ValueError, TypeError):
            continue

        day_index = order_date.weekday()

        day = daily_data[day_index]

        # =====================================
        # CỘNG DỮ LIỆU NGÀY
        # =====================================

        day["total_records"] += 1

        day["total_combos"] += combos
        day["total_sub_combo"] += sub_combo

        day["total_water_single"] += water

        day["total_small_bread"] += bread_300
        day["total_bread_400"] += bread_400
        day["total_bread_600"] += bread_600

        day["total_restaurant"] += (
            order["restaurant_total"] or 0
        )

        day["total_staff"] += (
            order["staff_total"] or 0
        )

        day["total_profit"] += (
            order["profit"] or 0
        )

    # =========================================
    # TÍNH ĐIỂM CHO TỪNG NGÀY
    # =========================================

    for day in daily_data:

        point_result = (
            calculate_weekly_points_for_staff(day)
        )

        day["total_points"] = (
            point_result["total_points"]
        )

    # =========================================
    # TỔNG ĐIỂM TUẦN
    #
    # QUAN TRỌNG:
    # tính lại trên tổng tuần, không cộng điểm
    # từng ngày để tránh sai quy tắc ghép bánh/nước
    # =========================================

    week_point_data = {
        "total_combos": total_combos,
        "total_sub_combo": total_sub_combo,
        "total_water_single": total_water,
        "total_small_bread": total_bread_300,
        "total_bread_400": total_bread_400,
        "total_bread_600": total_bread_600
    }

    week_point_result = (
        calculate_weekly_points_for_staff(
            week_point_data
        )
    )

    total_points = (
        week_point_result["total_points"]
    )

    total_bread = (
        total_bread_300
        + total_bread_400
        + total_bread_600
    )

    # =========================================
    # CHART
    # =========================================

    chart_labels = [
        day["day"]
        for day in daily_data
    ]

    chart_points = [
        day["total_points"]
        for day in daily_data
    ]

    chart_combos = [
        (
            day["total_combos"]
            + day["total_sub_combo"]
        )
        for day in daily_data
    ]

    # =========================================
    # RENDER
    # =========================================

    return render_template(
        "statistics.html",

        is_manager=is_manager,

        weeks=weeks,
        selected_week=selected_week,

        total_points=total_points,

        total_records=total_records,

        total_combos=total_combos,
        total_sub_combo=total_sub_combo,

        total_water=total_water,
        total_bread=total_bread,

        total_restaurant=(
            total_restaurant
            if is_manager
            else None
        ),

        total_profit=(
            total_profit
            if is_manager
            else None
        ),

        daily_data=daily_data,

        chart_labels=chart_labels,
        chart_points=chart_points,
        chart_combos=chart_combos
    )
    
@app.route("/settings")
def settings():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    is_manager = session.get("role") == "manager"

    return render_template(
        "settings.html",
        is_manager=is_manager
    )
    

@app.route("/weeks")
def weeks():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    init_db()
    db = get_db()

    is_manager = session.get("role") == "manager"
    current_name = session.get("staff_name")

    # Manager xem toàn nhà hàng
    if is_manager:

        rows = db.execute("""
            SELECT
                week_name,
                COUNT(*) AS total_records,
                SUM(combos) AS total_combos,
                SUM(sub_combo) AS total_sub_combo,
                SUM(water_single) AS total_water,
                SUM(small_bread) AS total_small_bread,
                SUM(bread_400) AS total_bread_400,
                SUM(bread_600) AS total_bread_600
            FROM orders
            WHERE paid = 1
              AND week_name IS NOT NULL
              AND TRIM(week_name) != ''
            GROUP BY week_name
        """).fetchall()

    # Staff chỉ xem thành tích của chính mình
    else:

        rows = db.execute("""
            SELECT
                week_name,
                COUNT(*) AS total_records,
                SUM(combos) AS total_combos,
                SUM(sub_combo) AS total_sub_combo,
                SUM(water_single) AS total_water,
                SUM(small_bread) AS total_small_bread,
                SUM(bread_400) AS total_bread_400,
                SUM(bread_600) AS total_bread_600
            FROM orders
            WHERE paid = 1
              AND LOWER(staff_name) = LOWER(?)
              AND week_name IS NOT NULL
              AND TRIM(week_name) != ''
            GROUP BY week_name
        """, (current_name,)).fetchall()


    week_list = []

    for row in rows:

        data = {
            "week_name": row["week_name"],

            "total_records":
                row["total_records"] or 0,

            "total_combos":
                row["total_combos"] or 0,

            "total_sub_combo":
                row["total_sub_combo"] or 0,

            "total_water_single":
                row["total_water"] or 0,

            "total_small_bread":
                row["total_small_bread"] or 0,

            "total_bread_400":
                row["total_bread_400"] or 0,

            "total_bread_600":
                row["total_bread_600"] or 0
        }

        point_result = (
            calculate_weekly_points_for_staff(data)
        )

        data["total_points"] = (
            point_result["total_points"]
        )

        data["total_all_combos"] = (
            data["total_combos"]
            + data["total_sub_combo"]
        )

        week_list.append(data)


    week_list.sort(
        key=lambda x: get_week_number(
            x["week_name"]
        ),
        reverse=True
    )


    return render_template(
        "weeks.html",
        week_list=week_list,
        is_manager=is_manager
    )

@app.route("/", methods=["GET", "POST"])
def login():
    init_db()
    db = get_db()

    error = None
    manager_login = False
    entered_name = ""
    position = ""

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        pin = request.form.get("pin", "").strip()

        staff = db.execute("""
            SELECT *
            FROM staff
            WHERE LOWER(name) = LOWER(?)
        """, (name,)).fetchone()

        # Không tìm thấy nhân viên
        if staff is None:
            error = "Không tìm thấy tên của bạn trong danh sách RayCrest."

        else:

            # ==========================
            # TÀI KHOẢN MANAGER
            # ==========================
            if staff["role"] == "manager":

                manager_login = True
                entered_name = staff["name"]
                position = staff["position"]

                # Chưa nhập PIN
                if not pin:
                    return render_template(
                        "login.html",
                        error=None,
                        manager_login=True,
                        entered_name=entered_name,
                        position=position
                    )

                # PIN sai
                if pin != str(MANAGER_PASSWORD):
                    return render_template(
                        "login.html",
                        error="Mã PIN quản lý không chính xác.",
                        manager_login=True,
                        entered_name=entered_name,
                        position=position
                    )

            # ==========================
            # LOGIN THÀNH CÔNG
            # ==========================
            session["staff_id"] = staff["id"]
            session["staff_name"] = staff["name"]
            session["position"] = staff["position"]
            session["role"] = staff["role"]

            return redirect(url_for("index"))

    return render_template(
        "login.html",
        error=error,
        manager_login=manager_login,
        entered_name=entered_name,
        position=position
    )
    
    
@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))

@app.route("/add", methods=["POST"])
def add_order():
    staff_name = request.form["staff_name"]
    week_name = request.form["week_name"]

    combo_type = request.form["combo_type"]
    combo_qty = int(request.form["combo_qty"])

    water_single = int(request.form["water_single"])

    bread_type = request.form["bread_type"]
    bread_qty = int(request.form["bread_qty"])

    paid = 1 if request.form.get("paid") == "1" else 0

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
            paid,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        paid,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    db.commit()

    return redirect(url_for("index"))



@app.route("/delete/<int:order_id>", methods=["POST"])
def delete_order(order_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if not is_manager():
        return redirect(url_for("index"))

    db = get_db()

    db.execute(
        "DELETE FROM orders WHERE id = ?",
        (order_id,)
    )

    db.commit()

    return redirect(url_for("index"))


@app.route("/manager-cost", methods=["GET", "POST"])
def manager_cost():

    # ==============================
    # LOGIN / PERMISSION
    # ==============================

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("index"))

    init_db()
    db = get_db()


    # ==============================
    # MANAGER PASSWORD
    # ==============================

    if request.method == "POST":

        password = request.form.get(
            "password",
            ""
        )

        if password != str(MANAGER_PASSWORD):
            return "Sai password quản lý"

        g.manager_allowed = True


    # ==============================
    # GET AVAILABLE WEEKS
    # ==============================

    week_rows = db.execute("""
        SELECT DISTINCT week_name
        FROM orders
        WHERE week_name IS NOT NULL
          AND TRIM(week_name) != ''
    """).fetchall()

    weeks = [
        row["week_name"]
        for row in week_rows
    ]


    # Thêm những tuần có trong staff_advances
    advance_week_rows = db.execute("""
        SELECT DISTINCT week_name
        FROM staff_advances
        WHERE week_name IS NOT NULL
          AND TRIM(week_name) != ''
    """).fetchall()

    for row in advance_week_rows:

        if row["week_name"] not in weeks:
            weeks.append(
                row["week_name"]
            )


    # Nếu chưa có tuần
    if not weeks:
        weeks = ["Tuần 1"]


    # Sort Tuần 1, Tuần 2, Tuần 3...
    def week_sort_key(week):

        try:
            return int(
                "".join(
                    filter(str.isdigit, week)
                )
            )

        except (ValueError, TypeError):
            return 999999


    weeks.sort(
        key=week_sort_key
    )


    # ==============================
    # SELECTED WEEK
    # ==============================

    selected_week = request.args.get(
        "week"
    )

    if (
        not selected_week
        or selected_week not in weeks
    ):
        selected_week = weeks[-1]


    # ==============================
    # COST SETTINGS
    # ==============================

    costs = db.execute("""
        SELECT *
        FROM cost_settings
    """).fetchall()

    cost_dict = {
        row["item_name"]: row["cost"]
        for row in costs
    }


    # ==============================
    # ADVANCES - SELECTED WEEK ONLY
    # ==============================

    advances = db.execute("""
        SELECT *
        FROM staff_advances
        WHERE week_name = ?
        ORDER BY id DESC
    """, (
        selected_week,
    )).fetchall()


    # ==============================
    # PAID ORDERS - WEEK ONLY
    # ==============================

    orders = db.execute("""
        SELECT *
        FROM orders
        WHERE paid = 1
          AND week_name = ?
    """, (
        selected_week,
    )).fetchall()


    # ==============================
    # REVENUE / COST
    # ==============================

    total_revenue = 0
    total_cost = 0

    for order in orders:

        total_revenue += (
            order["restaurant_total"] or 0
        )

        total_cost += (
            (order["combos"] or 0)
            * cost_dict.get(
                "combo_3_2",
                0
            )
        )

        total_cost += (
            (order["sub_combo"] or 0)
            * cost_dict.get(
                "combo_4_4",
                0
            )
        )

        total_cost += (
            (order["water_single"] or 0)
            * cost_dict.get(
                "water",
                0
            )
        )

        total_cost += (
            (order["small_bread"] or 0)
            * cost_dict.get(
                "bread_300",
                0
            )
        )

        total_cost += (
            (order["bread_400"] or 0)
            * cost_dict.get(
                "bread_400",
                0
            )
        )

        total_cost += (
            (order["bread_600"] or 0)
            * cost_dict.get(
                "bread_600",
                0
            )
        )


    # ==============================
    # ADVANCE TOTAL
    # ==============================

    total_advance = sum(
        row["amount"] or 0
        for row in advances
    )


    # ==============================
    # REAL PROFIT
    # ==============================

    real_profit = (
        total_revenue
        - total_cost
        - total_advance
    )


    # ==============================
    # TEMPLATE
    # ==============================

    return render_template(
        "manager_cost.html",

        costs=costs,
        advances=advances,

        total_revenue=total_revenue,
        total_cost=total_cost,
        total_advance=total_advance,
        real_profit=real_profit,

        weeks=weeks,
        selected_week=selected_week
    )

@app.route("/toggle_paid/<int:order_id>", methods=["POST"])
def toggle_paid(order_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if not is_manager():
        return redirect(url_for("index"))

    paid = 1 if request.form.get("paid") == "1" else 0

    db = get_db()

    db.execute("""
        UPDATE orders
        SET paid = ?
        WHERE id = ?
    """, (paid, order_id))

    db.commit()

    return redirect(url_for("index"))

    return redirect(url_for("index"))

@app.route("/update-cost", methods=["POST"])
def update_cost():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if not is_manager():
        return redirect(url_for("index"))

    db = get_db()

    for key, value in request.form.items():

        try:
            cost = int(value)
        except (ValueError, TypeError):
            continue

        db.execute("""
            UPDATE cost_settings
            SET cost = ?
            WHERE item_name = ?
        """, (cost, key))

    db.commit()

    return redirect(url_for("manager_cost"))


@app.route(
    "/add-advance",
    methods=["POST"]
)
def add_advance():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "manager":
        return redirect(url_for("index"))

    db = get_db()

    staff_name = request.form.get(
        "staff_name",
        ""
    ).strip()

    ingredient = request.form.get(
        "ingredient",
        ""
    ).strip()

    week_name = request.form.get(
        "week_name",
        ""
    ).strip()

    try:
        amount = int(
            request.form.get(
                "amount",
                0
            )
        )

    except (ValueError, TypeError):
        amount = 0


    if (
        not staff_name
        or not ingredient
        or not week_name
        or amount <= 0
    ):
        return redirect(
            url_for(
                "manager_cost",
                week=week_name
            )
        )


    db.execute("""
        INSERT INTO staff_advances (
            staff_name,
            note,
            amount,
            week_name
        )
        VALUES (?, ?, ?, ?)
    """, (
        staff_name,
        ingredient,
        amount,
        week_name
    ))

    db.commit()


    return redirect(
        url_for(
            "manager_cost",
            week=week_name
        )
    )


@app.route("/delete-advance/<int:advance_id>", methods=["POST"])
def delete_advance(advance_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    if not is_manager():
        return redirect(url_for("index"))

    db = get_db()

    db.execute("""
        DELETE FROM staff_advances
        WHERE id = ?
    """, (advance_id,))

    db.commit()

    return redirect(url_for("manager_cost"))


if __name__ == "__main__":
    with app.app_context():
        init_db()

    app.run(debug=True)