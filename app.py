from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    g,
    session,
    jsonify,
    send_from_directory
)

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json
import discord
import asyncio
import threading
import re

from werkzeug.utils import secure_filename

from google import genai
from google.genai import types


app = Flask(__name__)
DATABASE = "/data/raycrest.db"

VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def vietnam_now():
    return datetime.now(VIETNAM_TZ)

#BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#if os.path.exists("/data"):
   # DATABASE = "/data/raycrest.db"
#else:
#    DATABASE = os.path.join(BASE_DIR, "raycrest.db")

MANAGER_PASSWORD = "1213"
app.secret_key = "raycrest-secret-key"


# =========================================================
# GEMINI AI - INVENTORY SCANNER
# =========================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

GEMINI_MODEL = "gemini-3.8-flash"


# =========================================================
# DISCORD BOT
# =========================================================

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

DISCORD_BILL_CHANNEL_ID = 1502195194299289640

DISCORD_STAFF_MAP = {
    858231065940066344: "Shiron",
    470443924335493120: "Jm",
    692991143599800380: "Norra",
    236790720307003393: "Zon",
    301589370538950657: "Jikey",
    470958921398485032: "Tram",
    1370461037924454481: "Min",
    719413650057592884: "Beo",
    488358302703419392: "YoungL",
    1248365164839833754: "Leo",
    1073823473681584292: "kdog",
    377855029899427840: "Himel",
    478848905891545098: "Lỉn",
    823073979794325524: "Chanh",
    423151260473098240: "Eokay",
    417904033295106049: "Dun",
    416445971619381260: "Tommy",
    718848102462783599: "Heona",
}


def get_gemini_client():

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY chưa được cấu hình."
        )

    return genai.Client(
        api_key=GEMINI_API_KEY
    )


@app.template_filter("money")
def money_format(value):
    try:
        if value is None:
            return "0"

        return "{:,.0f}".format(float(value)).replace(",", ".")
    except:
        return "0"
    

WAREHOUSE_UPLOAD_FOLDER = "/data/warehouse_images"

os.makedirs(
    WAREHOUSE_UPLOAD_FOLDER,
    exist_ok=True
)


WAREHOUSE_LEGACY_FOLDER = os.path.join(
    app.static_folder,
    "uploads",
    "warehouse"
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

WATER_RESTAURANT_PRICE = 80
WATER_STAFF_PRICE = 100

SMALL_BREAD_RESTAURANT_PRICE = 150
SMALL_BREAD_STAFF_PRICE = 200

BREAD_400_RESTAURANT_PRICE = 250
BREAD_400_STAFF_PRICE = 300

BREAD_600_RESTAURANT_PRICE = 350
BREAD_600_STAFF_PRICE = 400

WATER_PER_COMBO = 2
FREE_WATER_EVERY_COMBOS = 2


def get_week_number(week_name):
    numbers = "".join(ch for ch in week_name if ch.isdigit())
    return int(numbers) if numbers else 999


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            DATABASE,
            timeout=30
        )

        g.db.row_factory = sqlite3.Row

        g.db.execute(
            "PRAGMA busy_timeout = 30000"
        )

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
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS discord_imports (
            discord_message_id TEXT PRIMARY KEY,
            discord_user_id TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            order_id INTEGER,
            raw_content TEXT,
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
    
        # =========================================================
    # REWARD PERIODS
    # Lưu từng kỳ phát thưởng đã chốt
    # =========================================================

    db.execute("""
        CREATE TABLE IF NOT EXISTS reward_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            week_name TEXT NOT NULL,

            period_name TEXT NOT NULL,

            reward_percent INTEGER NOT NULL,

            restaurant_revenue INTEGER DEFAULT 0,

            reward_pool INTEGER DEFAULT 0,

            total_points INTEGER DEFAULT 0,

            total_staff INTEGER DEFAULT 0,

            note TEXT DEFAULT '',

            closed_by TEXT,

            closed_at TEXT
        )
    """)


    # =========================================================
    # REWARD DETAILS
    # Snapshot tiền thưởng từng nhân viên
    # =========================================================

    db.execute("""
        CREATE TABLE IF NOT EXISTS reward_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            reward_period_id INTEGER NOT NULL,

            staff_name TEXT NOT NULL,

            points INTEGER DEFAULT 0,

            combos INTEGER DEFAULT 0,

            sub_combo INTEGER DEFAULT 0,

            restaurant_revenue INTEGER DEFAULT 0,

            reward_amount INTEGER DEFAULT 0,

            reward_ratio REAL DEFAULT 0,

            FOREIGN KEY (reward_period_id)
                REFERENCES reward_periods(id)
        )
    """)


    db.commit()
    
    
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
    
    
    # =========================================================
    # WAREHOUSE SCAN HISTORY
    # =========================================================

    db.execute("""
        CREATE TABLE IF NOT EXISTS warehouse_scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            item_count INTEGER DEFAULT 0
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS warehouse_scan_history_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            old_quantity INTEGER DEFAULT 0,
            new_quantity INTEGER DEFAULT 0,
            difference INTEGER DEFAULT 0,

            FOREIGN KEY (history_id)
                REFERENCES warehouse_scan_history(id)
        )
    """)

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
    

# =========================================================
# DISCORD BILL BOT
# =========================================================

def get_current_bill_week(db):
    rows = db.execute("""
        SELECT DISTINCT week_name
        FROM orders
        WHERE week_name IS NOT NULL
          AND TRIM(week_name) != ''
    """).fetchall()

    weeks = [
        row["week_name"]
        for row in rows
    ]

    if not weeks:
        return "Tuần 1"

    weeks = sorted(
        weeks,
        key=get_week_number
    )

    return weeks[-1]


def ensure_discord_import_table():
    db = sqlite3.connect(
        DATABASE,
        timeout=30
    )

    db.execute(
        "PRAGMA busy_timeout = 30000"
    )

    db.execute("""
        CREATE TABLE IF NOT EXISTS discord_imports (
            discord_message_id TEXT PRIMARY KEY,
            discord_user_id TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            order_id INTEGER,
            raw_content TEXT,
            created_at TEXT
        )
    """)

    db.commit()
    db.close()


def import_discord_combo_bill(
    discord_message_id,
    discord_user_id,
    staff_name,
    combo_qty,
    raw_content
):
    db = sqlite3.connect(
        DATABASE,
        timeout=30
    )

    db.row_factory = sqlite3.Row

    db.execute(
        "PRAGMA busy_timeout = 30000"
    )

    try:
        # -----------------------------------------
        # CHỐNG NHẬP TRÙNG
        # -----------------------------------------

        existing = db.execute("""
            SELECT discord_message_id
            FROM discord_imports
            WHERE discord_message_id = ?
        """, (
            str(discord_message_id),
        )).fetchone()

        if existing:
            return False

        # -----------------------------------------
        # KIỂM TRA NHÂN VIÊN CÓ TRÊN WEBSITE
        # -----------------------------------------

        staff = db.execute("""
            SELECT id, name
            FROM staff
            WHERE LOWER(name) = LOWER(?)
            LIMIT 1
        """, (
            staff_name,
        )).fetchone()

        if not staff:
            print(
                f"[Discord] Không tìm thấy nhân viên: "
                f"{staff_name}"
            )
            return False

        real_staff_name = staff["name"]

        # -----------------------------------------
        # TUẦN HIỆN TẠI
        # -----------------------------------------

        week_name = get_current_bill_week(db)

        # -----------------------------------------
        # 50 CB = 50 COMBO CHÍNH
        # -----------------------------------------

        combos = combo_qty
        sub_combo = 0
        water_single = 0
        small_bread = 0
        bread_400 = 0
        bread_600 = 0

        result = calculate_order(
            combos,
            sub_combo,
            water_single,
            small_bread,
            bread_400,
            bread_600
        )

        created_at = vietnam_now().strftime(
            "%Y-%m-%d %H:%M"
        )

        # -----------------------------------------
        # TẠO BILL
        # -----------------------------------------

        cursor = db.execute("""
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
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            real_staff_name,
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
            "Discord Bot",
            1,
            created_at
        ))

        order_id = cursor.lastrowid

        # -----------------------------------------
        # LƯU MESSAGE ID
        # -----------------------------------------

        db.execute("""
            INSERT INTO discord_imports (
                discord_message_id,
                discord_user_id,
                staff_name,
                order_id,
                raw_content,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(discord_message_id),
            str(discord_user_id),
            real_staff_name,
            order_id,
            raw_content,
            created_at
        ))

        db.commit()

        print(
            f"[Discord] Đã nhập bill: "
            f"{real_staff_name} - "
            f"{combo_qty} CB - "
            f"{week_name}"
        )

        return True

    except Exception as e:
        db.rollback()

        print(
            "[Discord] Lỗi nhập bill:",
            e
        )

        return False

    finally:
        db.close()


# =========================================================
# DISCORD CLIENT
# =========================================================

discord_intents = discord.Intents.default()
discord_intents.message_content = True

discord_client = discord.Client(
    intents=discord_intents
)


@discord_client.event
async def on_ready():
    print(
        f"[Discord] Bot đã online: "
        f"{discord_client.user}",
        flush=True
    )


@discord_client.event
async def on_message(message):

    # Không đọc tin nhắn của bot
    if message.author.bot:
        return

    # Chỉ đọc đúng channel báo bill
    if message.channel.id != DISCORD_BILL_CHANNEL_ID:
        return

    discord_user_id = message.author.id

    # Chỉ nhân viên đã đăng ký
    staff_name = DISCORD_STAFF_MAP.get(
        discord_user_id
    )

    if not staff_name:
        print(
            "[Discord] User chưa được liên kết:",
            discord_user_id
        )
        return

    content = message.content.strip()

    # -----------------------------------------
    # -----------------------------------------

    match = re.fullmatch(
        r"\s*(\d+)\s*(?:cb|combo)\s*",
        content,
        flags=re.IGNORECASE
    )

    if not match:
        return

    combo_qty = int(
        match.group(1)
    )

    # Giới hạn an toàn
    if combo_qty <= 0 or combo_qty > 100000:
        return

    success = await asyncio.to_thread(
        import_discord_combo_bill,
        message.id,
        discord_user_id,
        staff_name,
        combo_qty,
        content
    )

    if success:
        try:
            await message.add_reaction("✅")
        except Exception as e:
            print(
                "[Discord] Không thể thả reaction:",
                e
            )


def delete_discord_bill(discord_message_id):

    db = sqlite3.connect(
        DATABASE,
        timeout=30
    )

    db.row_factory = sqlite3.Row

    db.execute(
        "PRAGMA busy_timeout = 30000"
    )

    try:
        # Tìm bill được tạo từ message Discord
        imported = db.execute("""
            SELECT order_id
            FROM discord_imports
            WHERE discord_message_id = ?
            LIMIT 1
        """, (
            str(discord_message_id),
        )).fetchone()

        # Tin nhắn này không tạo bill
        if not imported:
            return False

        order_id = imported["order_id"]

        # Xóa bill
        if order_id:
            db.execute("""
                DELETE FROM orders
                WHERE id = ?
            """, (
                order_id,
            ))

        # Xóa liên kết Discord
        db.execute("""
            DELETE FROM discord_imports
            WHERE discord_message_id = ?
        """, (
            str(discord_message_id),
        ))

        db.commit()

        print(
            f"[Discord] Đã xóa Bill #{order_id} "
            f"do message {discord_message_id} bị xóa.",
            flush=True
        )

        return True

    except Exception as e:
        db.rollback()

        print(
            "[Discord] Lỗi khi xóa bill:",
            e,
            flush=True
        )

        return False

    finally:
        db.close()


@discord_client.event
async def on_raw_message_delete(payload):

    # Chỉ xử lý channel báo bill
    if payload.channel_id != DISCORD_BILL_CHANNEL_ID:
        return

    deleted = await asyncio.to_thread(
        delete_discord_bill,
        payload.message_id
    )

    if deleted:
        print(
            f"[Discord] Tin nhắn {payload.message_id} đã bị xóa "
            f"→ Bill tương ứng đã được xóa.",
            flush=True
        )


def run_discord_bot():

    if not DISCORD_BOT_TOKEN:
        print(
            "[Discord] Không có DISCORD_BOT_TOKEN."
        )
        return

    try:
        discord_client.run(
            DISCORD_BOT_TOKEN,
            log_handler=None
        )

    except Exception as e:
        print(
            "[Discord] Bot error:",
            e
        )


def start_discord_bot():
    thread = threading.Thread(
        target=run_discord_bot,
        daemon=True
    )

    thread.start()


# =========================================================
# KHỞI ĐỘNG DISCORD BOT AN TOÀN VỚI GUNICORN
# =========================================================

_discord_started = False
_discord_start_lock = threading.Lock()


def ensure_discord_bot_started():

    global _discord_started

    if _discord_started:
        return

    if not DISCORD_BOT_TOKEN:
        print(
            "[Discord] KHÔNG tìm thấy DISCORD_BOT_TOKEN.",
            flush=True
        )
        return

    with _discord_start_lock:

        if _discord_started:
            return

        print(
            "[Discord] Đang khởi động bot...",
            flush=True
        )

        start_discord_bot()

        _discord_started = True

    
@app.before_request
def start_discord_on_first_request():

    ensure_discord_bot_started()



    
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

# =========================================================
# WAREHOUSE IMAGE ROUTE
# Manager và Staff đều sử dụng cùng một nguồn ảnh
# =========================================================

@app.route("/warehouse-images/<path:filename>")
def warehouse_image(filename):

    # Phải đăng nhập mới được xem ảnh kho
    if "staff_name" not in session:
        return "", 403


    # =====================================================
    # 1. TÌM ẢNH TRÊN PERSISTENT DISK
    # =====================================================

    persistent_path = os.path.join(
        WAREHOUSE_UPLOAD_FOLDER,
        filename
    )

    if os.path.isfile(persistent_path):

        return send_from_directory(
            WAREHOUSE_UPLOAD_FOLDER,
            filename
        )


    # =====================================================
    # 2. FALLBACK CHO ẢNH CŨ TRONG STATIC
    # =====================================================

    legacy_path = os.path.join(
        WAREHOUSE_LEGACY_FOLDER,
        filename
    )

    if os.path.isfile(legacy_path):

        return send_from_directory(
            WAREHOUSE_LEGACY_FOLDER,
            filename
        )


    # =====================================================
    # 3. KHÔNG TÌM THẤY
    # =====================================================

    return "", 404


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

# =========================================================
# GEMINI INVENTORY SCANNER
# =========================================================

@app.route(
    "/warehouse/scan-inventory",
    methods=["POST"]
)
def warehouse_scan_inventory():

    # =========================================
    # LOGIN / PERMISSION
    # =========================================

    if "staff_name" not in session:
        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    if session.get("role") != "manager":
        return jsonify({
            "success": False,
            "error": "Bạn không có quyền sử dụng Inventory Scanner."
        }), 403
        

    # =========================================
    # CHECK IMAGE
    # =========================================

    image = request.files.get("image")

    if not image or not image.filename:
        return jsonify({
            "success": False,
            "error": "Không tìm thấy ảnh Inventory."
        }), 400


    if not allowed_image(image.filename):
        return jsonify({
            "success": False,
            "error": "Ảnh không hợp lệ. Chỉ hỗ trợ PNG, JPG, JPEG hoặc WEBP."
        }), 400


    # =========================================
    # LIMIT IMAGE SIZE
    # =========================================

    image_bytes = image.read()

    if not image_bytes:
        return jsonify({
            "success": False,
            "error": "File ảnh trống."
        }), 400

    # 10 MB
    if len(image_bytes) > 10 * 1024 * 1024:
        return jsonify({
            "success": False,
            "error": "Ảnh quá lớn. Tối đa 10MB."
        }), 400


    mime_type = image.mimetype

    if mime_type not in (
        "image/png",
        "image/jpeg",
        "image/webp"
    ):
        return jsonify({
            "success": False,
            "error": "Định dạng ảnh không được hỗ trợ."
        }), 400


    db = get_db()

    warehouse_rows = db.execute("""
        SELECT name
        FROM warehouse
        ORDER BY name COLLATE NOCASE
    """).fetchall()

    allowed_items = [
    row["name"]
        for row in warehouse_rows
    ]

    # Luôn cho AI nhận diện Hộp mảnh ghép RayCrest
    special_items = [
        "Hộp mảnh ghép RayCrest",
    ]

    for special_item in special_items:
        if not any(
            name.casefold() == special_item.casefold()
            for name in allowed_items
        ):
            allowed_items.append(special_item)

    allowed_lookup = {
        name.casefold(): name
        for name in allowed_items
    }


    if not allowed_items:
        return jsonify({
            "success": False,
            "error": "Kho chưa có mặt hàng để đối chiếu."
        }), 400


    # =========================================
    # PROMPT
    # =========================================

    item_list = "\n".join(
        f"- {name}"
        for name in allowed_items
    )

    prompt = f"""
Bạn đang đọc screenshot Inventory của game FiveM
cho nhà hàng RayCrest Restaurant.

Inventory thường là grid 5 cột x 5 hàng.

Mỗi slot có:

- góc trên bên trái: số lượng, ví dụ:
  x3
  x100
  x999
  x1,000
  x1,440
  x2,450

- góc trên bên phải: trọng lượng, ví dụ:
  60g
  2kg
  19.98kg
  20kg

- giữa slot: hình item

- phía dưới: tên item


QUY TẮC CỰC KỲ QUAN TRỌNG:

1. Chỉ đọc SỐ LƯỢNG ở góc trên bên trái.

2. TUYỆT ĐỐI không sử dụng weight ở góc trên bên phải
   làm quantity.

3. Ví dụ:
   x999 + 19.98kg
   thì quantity = 999.

4. x1,440 nghĩa là quantity = 1440.

5. Đọc từng slot từ trái sang phải,
   từ trên xuống dưới.

6. Nếu cùng một item xuất hiện nhiều slot,
   hãy cộng tất cả quantity của item đó.

7. Chỉ được sử dụng chính xác tên item
   trong danh sách RayCrest bên dưới.

8. Không tự tạo tên item mới.

9. Nếu không chắc chắn một slot là item nào,
   hãy bỏ qua slot đó.

10. Nếu không đọc chắc chắn quantity,
    hãy bỏ qua slot đó.

11. Không đoán.

12. Không tính slot trống.


DANH SÁCH ITEM HỢP LỆ:

{item_list}


Hãy phân tích screenshot và trả về các item đã cộng
quantity của những stack trùng nhau.
"""


    # =========================================
    # JSON SCHEMA
    # =========================================

    response_schema = {
        "type": "OBJECT",
        "properties": {

            "items": {
                "type": "ARRAY",

                "items": {
                    "type": "OBJECT",

                    "properties": {

                        "name": {
                            "type": "STRING"
                        },

                        "quantity": {
                            "type": "INTEGER"
                        }
                    },

                    "required": [
                        "name",
                        "quantity"
                    ]
                }
            }
        },

        "required": [
            "items"
        ]
    }


    # =========================================
    # CALL GEMINI
    # =========================================

    try:

        client = get_gemini_client()

        response = client.models.generate_content(

            model=GEMINI_MODEL,

            contents=[

                prompt,

                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                )
            ],

            config=types.GenerateContentConfig(

                temperature=0,

                response_mime_type="application/json",

                response_schema=response_schema
            )
        )


        if not response.text:
            raise RuntimeError(
                "Gemini không trả về kết quả."
            )


        result = json.loads(
            response.text
        )
        
        print("\n================ GEMINI DEBUG ================")
        print("MODEL:", GEMINI_MODEL)

        print("\nALLOWED ITEMS:")
        for item_name in allowed_items:
            print("-", repr(item_name))

        print("\nRAW GEMINI RESPONSE:")
        print(response.text)

        print("\nPARSED RESULT:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        print("================================================\n")


    except Exception as error:

        print(
            "GEMINI INVENTORY ERROR:",
            repr(error)
        )

        return jsonify({
            "success": False,
            "error":
                "Gemini không thể đọc Inventory. "
                + str(error)
        }), 500


    # =========================================
    # SERVER VALIDATION
    # =========================================

    allowed_lookup = {
        name.casefold(): name
        for name in allowed_items
    }

    totals = {}


    for ai_item in result.get("items", []):

        raw_name = str(
            ai_item.get("name", "")
        ).strip()

        try:
            quantity = int(
                ai_item.get("quantity", 0)
            )
        except (ValueError, TypeError):
            continue


        # invalid quantity
        if quantity <= 0:
            continue

        if quantity > 100000:
            continue



        database_name = allowed_lookup.get(
            raw_name.casefold()
        )

        # Gemini invented an item
        if not database_name:
            continue


        totals[database_name] = (
            totals.get(
                database_name,
                0
            )
            + quantity
        )


    # =========================================
    # FINAL RESULT
    # =========================================

    items = [
        {
            "name": name,
            "quantity": quantity
        }

        for name, quantity
        in totals.items()
    ]


    return jsonify({
        "success": True,
        "items": items,
        "count": len(items)
    })

  # =========================================================
# CONFIRM AI INVENTORY SCAN -> UPDATE WAREHOUSE
# =========================================================

@app.route("/warehouse/confirm-inventory-scan", methods=["POST"])
def warehouse_confirm_inventory_scan():

    # =====================================================
    # LOGIN / PERMISSION
    # =====================================================

    if "staff_name" not in session:
        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    if session.get("role") != "manager":
        return jsonify({
            "success": False,
            "error": "Bạn không có quyền nhập kho."
        }), 403


    # =====================================================
    # READ JSON
    # =====================================================

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "error": "Không nhận được dữ liệu nhập kho."
        }), 400

    items = data.get("items", [])

    if not isinstance(items, list):
        return jsonify({
            "success": False,
            "error": "Dữ liệu Inventory không hợp lệ."
        }), 400


    # =====================================================
    # DATABASE
    # =====================================================

    init_db()
    db = get_db()


    # =====================================================
    # LẤY TOÀN BỘ ITEM HIỆN CÓ TRONG KHO
    #
    # Scanner được xem là snapshot toàn bộ Inventory:
    #
    # - Có trong ảnh      -> quantity = số AI đọc được
    # - Không có trong ảnh -> quantity = 0
    #
    # =====================================================

    warehouse_rows = db.execute("""
        SELECT
            id,
            name,
            quantity
        FROM warehouse
        ORDER BY id ASC
    """).fetchall()

    if not warehouse_rows:
        return jsonify({
            "success": False,
            "error": "Kho hiện chưa có mặt hàng."
        }), 400


    # =====================================================
    # LOOKUP TÊN ITEM
    # =====================================================

    warehouse_lookup = {
        row["name"].casefold(): row
        for row in warehouse_rows
    }


    # =====================================================
    # VALIDATE KẾT QUẢ AI
    # =====================================================

    scanned_totals = {}

    for item in items:

        if not isinstance(item, dict):
            continue

        raw_name = str(
            item.get("name", "")
        ).strip()

        try:
            quantity = int(
                item.get("quantity", 0)
            )

        except (ValueError, TypeError):
            continue


        # Không nhận số âm
        if quantity < 0:
            continue

        # Chặn quantity bất thường
        if quantity > 100000:
            continue


        existing = warehouse_lookup.get(
            raw_name.casefold()
        )

        # Chỉ cho phép item đã tồn tại trong warehouse
        if not existing:
            continue


        real_name = existing["name"]

        # Nếu AI trả trùng item nhiều lần thì cộng lại
        scanned_totals[real_name] = (
            scanned_totals.get(real_name, 0)
            + quantity
        )


    # =====================================================
    # PHẢI CÓ ÍT NHẤT 1 ITEM AI NHẬN DIỆN
    #
    # Tránh trường hợp Gemini lỗi / đọc ảnh thất bại rồi
    # vô tình reset toàn bộ warehouse về 0.
    # =====================================================

    if not scanned_totals:
        return jsonify({
            "success": False,
            "error":
                "Không nhận diện được mặt hàng nào. "
                "Kho chưa được thay đổi."
        }), 400


    # =====================================================
    # SCAN INFO
    # =====================================================

    scan_time = vietnam_now().strftime(
        "%Y-%m-%d %H:%M"
    )

    scanned_by = session.get(
        "staff_name",
        "Không rõ"
    )

    imported_items = []


    try:

        # =================================================
        # CREATE HISTORY SESSION
        # =================================================

        history_cursor = db.execute("""
            INSERT INTO warehouse_scan_history (
                scanned_by,
                created_at,
                item_count
            )
            VALUES (?, ?, ?)
        """, (
            scanned_by,
            scan_time,
            0
        ))

        history_id = history_cursor.lastrowid


        # =================================================
        # ĐỒNG BỘ TOÀN BỘ WAREHOUSE
        # =================================================

        for warehouse_item in warehouse_rows:

            item_id = warehouse_item["id"]
            name = warehouse_item["name"]

            old_quantity = (
                warehouse_item["quantity"] or 0
            )


            # ---------------------------------------------
            # QUAN TRỌNG:
            #
            # Có trong screenshot -> quantity AI đọc được
            # Không có screenshot -> 0
            # ---------------------------------------------

            new_quantity = scanned_totals.get(
                name,
                0
            )

            difference = (
                new_quantity - old_quantity
            )


            # =================================================
            # UPDATE WAREHOUSE
            # =================================================

            db.execute("""
                UPDATE warehouse
                SET quantity = ?
                WHERE id = ?
            """, (
                new_quantity,
                item_id
            ))


            # =================================================
            # RESPONSE DATA
            # =================================================

            imported_items.append({
                "name": name,
                "old_quantity": old_quantity,
                "new_quantity": new_quantity,
                "difference": difference
            })


            # =================================================
            # HISTORY ITEM
            # Lưu tất cả item, kể cả không thay đổi
            # =================================================

            db.execute("""
                INSERT INTO warehouse_scan_history_items (
                    history_id,
                    item_name,
                    old_quantity,
                    new_quantity,
                    difference
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                history_id,
                name,
                old_quantity,
                new_quantity,
                difference
            ))


        # =====================================================
        # COUNT ITEM THỰC SỰ THAY ĐỔI
        # =====================================================

        changed_count = sum(
            1
            for item in imported_items
            if item["difference"] != 0
        )


        db.execute("""
            UPDATE warehouse_scan_history
            SET item_count = ?
            WHERE id = ?
        """, (
            changed_count,
            history_id
        ))


        db.commit()


    except Exception as error:

        db.rollback()

        print(
            "WAREHOUSE IMPORT ERROR:",
            repr(error)
        )

        return jsonify({
            "success": False,
            "error": "Không thể cập nhật kho."
        }), 500


    # =====================================================
    # SUCCESS
    # =====================================================

    return jsonify({
        "success": True,

        "message":
            f"Đã đồng bộ Inventory. "
            f"{changed_count} mặt hàng thay đổi.",

        "count": changed_count,

        "items": imported_items
    })
    


# =========================================================
# WAREHOUSE SCAN HISTORY
# =========================================================

@app.route("/warehouse/scan-history")
def warehouse_scan_history():

    # =========================================
    # LOGIN / PERMISSION
    # =========================================

    if "staff_name" not in session:
        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    if session.get("role") != "manager":
        return jsonify({
            "success": False,
            "error": "Bạn không có quyền xem lịch sử quét kho."
        }), 403

    init_db()
    db = get_db()

    # =========================================
    # LẤY 30 LẦN QUÉT GẦN NHẤT
    # =========================================

    history_rows = db.execute("""
        SELECT
            id,
            scanned_by,
            created_at,
            item_count
        FROM warehouse_scan_history
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    history = []

    for row in history_rows:

        item_rows = db.execute("""
            SELECT
                item_name,
                old_quantity,
                new_quantity,
                difference
            FROM warehouse_scan_history_items
            WHERE history_id = ?
            ORDER BY id ASC
        """, (
            row["id"],
        )).fetchall()

        items = []

        for item in item_rows:

            items.append({
                "name": item["item_name"],
                "old_quantity": item["old_quantity"] or 0,
                "new_quantity": item["new_quantity"] or 0,
                "difference": item["difference"] or 0
            })

        history.append({
            "id": row["id"],
            "scanned_by": row["scanned_by"],
            "created_at": row["created_at"],
            "item_count": row["item_count"] or 0,
            "items": items
        })

    return jsonify({
        "success": True,
        "history": history
    })

  
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



# =========================================================
# REWARD CALCULATION
# =========================================================

def calculate_reward_data(
    db,
    week_name,
    reward_percent
):

    # =====================================================
    # CHỈ LẤY BILL ĐÃ THANH TOÁN
    # =====================================================

    rows = db.execute("""
        SELECT *
        FROM orders
        WHERE week_name = ?
          AND paid = 1
    """, (
        week_name,
    )).fetchall()


    staff_data = {}

    total_restaurant_revenue = 0


    # =====================================================
    # GOM DỮ LIỆU THEO NHÂN VIÊN
    # =====================================================

    for row in rows:

        staff_name = (
            row["staff_name"]
            or "Không rõ"
        ).strip()


        if staff_name not in staff_data:

            staff_data[staff_name] = {
                "name": staff_name,

                "total_combos": 0,
                "total_sub_combo": 0,

                "total_water_single": 0,

                "total_small_bread": 0,
                "total_bread_400": 0,
                "total_bread_600": 0,

                "restaurant_revenue": 0
            }


        staff = staff_data[
            staff_name
        ]


        combos = (
            row["combos"]
            or 0
        )

        sub_combo = (
            row["sub_combo"]
            or 0
        )

        water = (
            row["water_single"]
            or 0
        )

        bread_300 = (
            row["small_bread"]
            or 0
        )

        bread_400 = (
            row["bread_400"]
            or 0
        )

        bread_600 = (
            row["bread_600"]
            or 0
        )

        restaurant_total = (
            row["restaurant_total"]
            or 0
        )


        staff["total_combos"] += (
            combos
        )

        staff["total_sub_combo"] += (
            sub_combo
        )

        staff["total_water_single"] += (
            water
        )

        staff["total_small_bread"] += (
            bread_300
        )

        staff["total_bread_400"] += (
            bread_400
        )

        staff["total_bread_600"] += (
            bread_600
        )

        staff["restaurant_revenue"] += (
            restaurant_total
        )


        total_restaurant_revenue += (
            restaurant_total
        )


    # =====================================================
    # TÍNH ĐIỂM
    # =====================================================

    reward_staff = []

    total_points = 0


    for staff in staff_data.values():

        point_result = (
            calculate_weekly_points_for_staff(
                staff
            )
        )


        points = (
            point_result[
                "total_points"
            ]
        )


        # Không có điểm thì không nhận thưởng
        if points <= 0:
            continue


        total_points += points


        reward_staff.append({
            "name":
                staff["name"],

            "points":
                points,

            "combos":
                staff["total_combos"],

            "sub_combo":
                staff["total_sub_combo"],

            "restaurant_revenue":
                staff["restaurant_revenue"],

            "reward_ratio":
                0,

            "reward_amount":
                0
        })


    # =====================================================
    # QUỸ THƯỞNG
    # =====================================================

    reward_pool = round(
        total_restaurant_revenue
        * reward_percent
        / 100
    )


    # =====================================================
    # CHIA THƯỞNG THEO ĐIỂM
    # =====================================================

    distributed = 0


    reward_staff.sort(
        key=lambda item: (
            item["points"],
            item["combos"],
            item["restaurant_revenue"]
        ),
        reverse=True
    )


    for index, staff in enumerate(
        reward_staff
    ):

        if total_points <= 0:

            reward_ratio = 0
            reward_amount = 0

        else:

            reward_ratio = (
                staff["points"]
                / total_points
            )


            # Người cuối cùng nhận phần dư
            # để tổng tiền luôn đúng reward_pool
            if (
                index
                == len(reward_staff) - 1
            ):

                reward_amount = (
                    reward_pool
                    - distributed
                )

            else:

                reward_amount = round(
                    reward_pool
                    * reward_ratio
                )


        staff[
            "reward_ratio"
        ] = reward_ratio


        staff[
            "reward_amount"
        ] = reward_amount


        distributed += (
            reward_amount
        )


    return {
        "week_name":
            week_name,

        "reward_percent":
            reward_percent,

        "restaurant_revenue":
            total_restaurant_revenue,

        "reward_pool":
            reward_pool,

        "total_points":
            total_points,

        "total_staff":
            len(reward_staff),

        "staff":
            reward_staff
    }
    

# =========================================================
# REWARDS PAGE
# =========================================================

@app.route("/rewards")
def rewards():

    if "staff_name" not in session:
        return redirect(
            url_for("login")
        )


    # Chỉ Manager được vào
    if session.get("role") != "manager":

        return redirect(
            url_for("index")
        )


    init_db()

    db = get_db()


    # =====================================================
    # DANH SÁCH TUẦN
    # =====================================================

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


    weeks = sorted(
        weeks,
        key=get_week_number,
        reverse=True
    )


    # =====================================================
    # TUẦN ĐANG CHỌN
    # =====================================================

    selected_week = request.args.get(
        "week",
        ""
    ).strip()


    if (
        not selected_week
        and weeks
    ):

        selected_week = weeks[0]


    # =====================================================
    # % QUỸ THƯỞNG
    # =====================================================

    try:

        reward_percent = int(
            request.args.get(
                "percent",
                25
            )
        )

    except (
        ValueError,
        TypeError
    ):

        reward_percent = 25


    # Chỉ cho phép 20%, 25%, 30%
    if reward_percent not in (20, 25, 30):
        reward_percent = 25


    # =====================================================
    # CALCULATE
    # =====================================================

    reward_data = {
        "week_name":
            selected_week,

        "reward_percent":
            reward_percent,

        "restaurant_revenue":
            0,

        "reward_pool":
            0,

        "total_points":
            0,

        "total_staff":
            0,

        "staff":
            []
    }


    if selected_week:

        reward_data = (
            calculate_reward_data(
                db,
                selected_week,
                reward_percent
            )
        )


    # =====================================================
    # KIỂM TRA TUẦN ĐÃ CHỐT CHƯA
    # =====================================================

    closed_period = None


    if selected_week:

        closed_period = db.execute("""
            SELECT *
            FROM reward_periods
            WHERE week_name = ?
            ORDER BY id DESC
            LIMIT 1
        """, (
            selected_week,
        )).fetchone()


    # =====================================================
    # LỊCH SỬ
    # =====================================================

    history = db.execute("""
        SELECT *
        FROM reward_periods
        ORDER BY id DESC
        LIMIT 50
    """).fetchall()


    return render_template(
        "rewards.html",

        weeks=weeks,

        selected_week=
            selected_week,

        reward_percent=
            reward_percent,

        reward_data=
            reward_data,

        closed_period=
            closed_period,

        history=
            history
    )
    
 
 # =========================================================
# CLOSE REWARD PERIOD
# =========================================================

@app.route(
    "/rewards/close",
    methods=["POST"]
)
def close_reward_period():

    if "staff_name" not in session:

        return redirect(
            url_for("login")
        )


    if session.get("role") != "manager":

        return redirect(
            url_for("index")
        )


    init_db()

    db = get_db()


    # =====================================================
    # FORM DATA
    # =====================================================

    week_name = request.form.get(
        "week_name",
        ""
    ).strip()


    period_name = request.form.get(
        "period_name",
        ""
    ).strip()


    note = request.form.get(
        "note",
        ""
    ).strip()


    try:

        reward_percent = int(
            request.form.get(
                "reward_percent",
                25
            )
        )

    except (
        ValueError,
        TypeError
    ):

        reward_percent = 25


    # =====================================================
    # VALIDATE
    # =====================================================

    if not week_name:

        return redirect(
            url_for("rewards")
        )
        
    
    # Chỉ cho phép 20%, 25%, 30%
    if reward_percent not in (20, 25, 30):
        reward_percent = 25


    if not period_name:

        period_name = (
            f"Phát thưởng {week_name}"
        )


    # =====================================================
    # KHÔNG CHỐT TRÙNG TUẦN
    # =====================================================

    existing = db.execute("""
        SELECT id
        FROM reward_periods
        WHERE week_name = ?
        LIMIT 1
    """, (
        week_name,
    )).fetchone()


    if existing:

        return redirect(
            url_for(
                "rewards",
                week=week_name,
                percent=reward_percent
            )
        )


    # =====================================================
    # TÍNH LẠI TRÊN SERVER
    # Không tin số tiền gửi từ browser
    # =====================================================

    reward_data = (
        calculate_reward_data(
            db,
            week_name,
            reward_percent
        )
    )


    if (
        reward_data[
            "total_points"
        ] <= 0
    ):

        return redirect(
            url_for(
                "rewards",
                week=week_name,
                percent=reward_percent
            )
        )


    if (
        reward_data[
            "reward_pool"
        ] <= 0
    ):

        return redirect(
            url_for(
                "rewards",
                week=week_name,
                percent=reward_percent
            )
        )


    closed_at = (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )


    closed_by = session.get(
        "staff_name",
        ""
    )


    # =====================================================
    # TRANSACTION
    # =====================================================

    try:

        cursor = db.execute("""
            INSERT INTO reward_periods (
                week_name,
                period_name,
                reward_percent,
                restaurant_revenue,
                reward_pool,
                total_points,
                total_staff,
                note,
                closed_by,
                closed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            week_name,
            period_name,
            reward_percent,

            reward_data[
                "restaurant_revenue"
            ],

            reward_data[
                "reward_pool"
            ],

            reward_data[
                "total_points"
            ],

            reward_data[
                "total_staff"
            ],

            note,
            closed_by,
            closed_at
        ))


        reward_period_id = (
            cursor.lastrowid
        )


        # =================================================
        # SNAPSHOT TỪNG NHÂN VIÊN
        # =================================================

        for staff in reward_data[
            "staff"
        ]:

            db.execute("""
                INSERT INTO reward_details (
                    reward_period_id,
                    staff_name,
                    points,
                    combos,
                    sub_combo,
                    restaurant_revenue,
                    reward_amount,
                    reward_ratio
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reward_period_id,

                staff[
                    "name"
                ],

                staff[
                    "points"
                ],

                staff[
                    "combos"
                ],

                staff[
                    "sub_combo"
                ],

                staff[
                    "restaurant_revenue"
                ],

                staff[
                    "reward_amount"
                ],

                staff[
                    "reward_ratio"
                ]
            ))


        db.commit()


    except Exception:

        db.rollback()

        raise


    return redirect(
        url_for(
            "reward_history_detail",
            reward_id=
                reward_period_id
        )
    )
 
# =========================================================
# REWARD HISTORY DETAIL
# =========================================================

@app.route(
    "/rewards/history/<int:reward_id>"
)
def reward_history_detail(
    reward_id
):

    if "staff_name" not in session:

        return redirect(
            url_for("login")
        )


    if session.get("role") != "manager":

        return redirect(
            url_for("index")
        )


    init_db()

    db = get_db()


    period = db.execute("""
        SELECT *
        FROM reward_periods
        WHERE id = ?
    """, (
        reward_id,
    )).fetchone()


    if period is None:

        return redirect(
            url_for("rewards")
        )


    details = db.execute("""
        SELECT *
        FROM reward_details
        WHERE reward_period_id = ?
        ORDER BY
            points DESC,
            reward_amount DESC
    """, (
        reward_id,
    )).fetchall()


    return render_template(
        "reward_history_detail.html",

        period=period,
        details=details
    )

 
    

@app.route("/ranking")
def ranking():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    init_db()
    db = get_db()

    # Lấy danh sách tuần
    # =========================================
    # DANH SÁCH TUẦN
    # =========================================

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

    weeks = sorted(
        weeks,
        key=get_week_number
    )


    selected_week = request.args.get(
        "week",
        ""
    ).strip()

    if selected_week not in weeks:
        selected_week = weeks[-1] if weeks else ""

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

# =========================================================
# BILL MANAGEMENT
# Manager: xem tất cả bill
# Staff: chỉ xem bill của chính mình
# =========================================================

@app.route("/bills")
def bills():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    init_db()
    db = get_db()

    is_manager = (
        session.get("role") == "manager"
    )

    current_staff = (
        session.get("staff_name", "")
        .strip()
    )

    # =========================================
    # FILTER
    # =========================================

    selected_week = request.args.get(
        "week",
        ""
    ).strip()

    search_name = request.args.get(
        "search",
        ""
    ).strip()


    # =========================================
    # GET AVAILABLE WEEKS
    # Manager: tuần của toàn hệ thống
    # Staff: chỉ tuần mà staff đó có bill
    # =========================================

    if is_manager:

        week_rows = db.execute("""
            SELECT DISTINCT week_name
            FROM orders
            WHERE week_name IS NOT NULL
              AND TRIM(week_name) != ''
        """).fetchall()

    else:

        week_rows = db.execute("""
            SELECT DISTINCT week_name
            FROM orders
            WHERE week_name IS NOT NULL
              AND TRIM(week_name) != ''
              AND LOWER(staff_name) = LOWER(?)
        """, (
            current_staff,
        )).fetchall()


    available_weeks = [
        row["week_name"]
        for row in week_rows
    ]

    # Sắp xếp Tuần 20, Tuần 19, Tuần 18...
    available_weeks = sorted(
        available_weeks,
        key=get_week_number,
        reverse=True
    )



    # =========================================
    # DEFAULT TO NEWEST WEEK
    # =========================================

    if not selected_week and available_weeks:
        selected_week = available_weeks[0]


    # =========================================
    # LOAD ONLY SELECTED WEEK
    # Không load toàn bộ database
    # =========================================

    orders = []

    if selected_week:

        query = """
            SELECT *
            FROM orders
            WHERE week_name = ?
        """

        params = [
            selected_week
        ]


        # Staff chỉ được xem bill của chính mình
        if not is_manager:

            query += """
                AND LOWER(staff_name) = LOWER(?)
            """

            params.append(
                current_staff
            )


        # Manager có thể tìm nhân viên
        # nhưng chỉ trong tuần đang xem
        if is_manager and search_name:

            query += """
                AND LOWER(staff_name)
                    LIKE LOWER(?)
            """

            params.append(
                f"%{search_name}%"
            )


        query += """
            ORDER BY id DESC
        """


        orders = db.execute(
            query,
            params
        ).fetchall()
        
    # ==========================================
    # STAFF WEEK SUMMARY
    # ==========================================

    staff_week_summary = {
        "combos": 0,
        "restaurant_total": 0,
        "staff_total": 0,
        "profit": 0
    }

    if not is_manager and selected_week:

        summary = db.execute("""
            SELECT
                COALESCE(SUM(combos), 0) +
                COALESCE(SUM(sub_combo), 0) AS combos,

                COALESCE(SUM(restaurant_total), 0) AS restaurant_total,

                COALESCE(SUM(staff_total), 0) AS staff_total,

                COALESCE(SUM(profit), 0) AS profit

            FROM orders

            WHERE week_name = ?
            AND LOWER(staff_name) = LOWER(?)
            AND paid = 1
        """, (
            selected_week,
            current_staff
        )).fetchone()

        if summary:
            staff_week_summary = {
                "combos": summary["combos"] or 0,
                "restaurant_total": summary["restaurant_total"] or 0,
                "staff_total": summary["staff_total"] or 0,
                "profit": summary["profit"] or 0
            }

     


    # =========================================
    # PAGE
    # =========================================

    return render_template(
        "bills.html",

        orders=orders,

        available_weeks=available_weeks,

        selected_week=selected_week,

        search_name=search_name,

        is_manager=is_manager,
        
        staff_week_summary=staff_week_summary
    )

@app.route(
    "/orders/<int:order_id>/delete",
    methods=["POST"]
)
def delete_order(order_id):

    # Chưa đăng nhập
    if "staff_name" not in session:
        return redirect(url_for("login"))

    # Chỉ Manager được xóa Bill
    if session.get("role") != "manager":
        return redirect(url_for("bills"))

    db = get_db()

    return_week = request.form.get(
        "return_week",
        ""
    ).strip()

    return_search = request.form.get(
        "return_search",
        ""
    ).strip()

    # Kiểm tra Bill tồn tại
    order = db.execute("""
        SELECT id
        FROM orders
        WHERE id = ?
        LIMIT 1
    """, (
        order_id,
    )).fetchone()

    if order:

        # Nếu Bill được tạo từ Discord
        # xóa luôn liên kết với message Discord
        db.execute("""
            DELETE FROM discord_imports
            WHERE order_id = ?
        """, (
            order_id,
        ))

        # Xóa Bill
        db.execute("""
            DELETE FROM orders
            WHERE id = ?
        """, (
            order_id,
        ))

        db.commit()

        print(
            f"[Bill] Đã xóa Bill #{order_id}",
            flush=True
        )

    return redirect(
        url_for(
            "bills",
            week=return_week,
            search=return_search
        )
    )


# =========================================================
# EDIT BILL
# Manager: sửa tất cả
# Staff: chỉ sửa bill của mình
# =========================================================

@app.route(
    "/orders/<int:order_id>/edit",
    methods=["POST"]
)
def edit_order(order_id):

    if "staff_name" not in session:
        return redirect(url_for("login"))

    db = get_db()

    # =========================================
    # FIND ORDER
    # =========================================

    order = db.execute("""
        SELECT *
        FROM orders
        WHERE id = ?
    """, (
        order_id,
    )).fetchone()

    if order is None:
        return redirect(
            url_for("bills")
        )

    # =========================================
    # PERMISSION
    # =========================================

    current_staff = (
        session.get(
            "staff_name",
            ""
        )
        .strip()
        .casefold()
    )

    order_staff = (
        str(
            order["staff_name"]
            or ""
        )
        .strip()
        .casefold()
    )

    is_manager = (
        session.get("role")
        == "manager"
    )

    # Staff chỉ sửa bill của chính mình
    if (
        not is_manager
        and current_staff != order_staff
    ):

        return redirect(
            url_for("bills")
        )

    # =========================================
    # WEEK
    # =========================================

    week_name = request.form.get(
        "week_name",
        ""
    ).strip()

    if not week_name:

        return redirect(
            url_for("bills")
        )

    if len(week_name) > 50:

        return redirect(
            url_for("bills")
        )

    # =========================================
    # QUANTITIES
    # =========================================

    try:

        combos = max(
            int(
                request.form.get(
                    "combos",
                    0
                )
            ),
            0
        )

        sub_combo = max(
            int(
                request.form.get(
                    "sub_combo",
                    0
                )
            ),
            0
        )

        water_single = max(
            int(
                request.form.get(
                    "water_single",
                    0
                )
            ),
            0
        )

        small_bread = max(
            int(
                request.form.get(
                    "small_bread",
                    0
                )
            ),
            0
        )

        bread_400 = max(
            int(
                request.form.get(
                    "bread_400",
                    0
                )
            ),
            0
        )

        bread_600 = max(
            int(
                request.form.get(
                    "bread_600",
                    0
                )
            ),
            0
        )

    except (ValueError, TypeError):

        return redirect(
            url_for("bills")
        )

    # =========================================
    # SAFETY LIMIT
    # =========================================

    quantities = [
        combos,
        sub_combo,
        water_single,
        small_bread,
        bread_400,
        bread_600
    ]

    if any(
        quantity > 100000
        for quantity in quantities
    ):

        return redirect(
            url_for("bills")
        )

    # =========================================
    # PAID
    # =========================================

    paid = (
        1
        if request.form.get("paid") == "1"
        else 0
    )

    # =========================================
    # RECALCULATE
    # =========================================

    result = calculate_order(
        combos,
        sub_combo,
        water_single,
        small_bread,
        bread_400,
        bread_600
    )

    # =========================================
    # UPDATE DATABASE
    # =========================================

    db.execute("""
        UPDATE orders

        SET
            week_name = ?,

            combos = ?,
            sub_combo = ?,

            water_single = ?,

            small_bread = ?,
            bread_400 = ?,
            bread_600 = ?,

            restaurant_total = ?,
            staff_total = ?,
            profit = ?,

            free_water = ?,
            combo_water = ?,

            paid = ?

        WHERE id = ?
    """, (

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

        paid,

        order_id
    ))

    db.commit()

    # =========================================
    # RETURN TO SAME FILTER
    # =========================================

    return redirect(
        url_for(
            "bills",
            week=request.form.get(
                "return_week",
                ""
            ),
            search=request.form.get(
                "return_search",
                ""
            )
        )
    )

@app.route("/add", methods=["POST"])
def add_order():

    if "staff_name" not in session:
        return redirect(url_for("login"))

    # Luôn lấy nhân viên từ tài khoản đang đăng nhập
    staff_name = session.get("staff_name")

    week_name = request.form.get(
        "week_name",
        ""
    ).strip()

    if not week_name:
        return redirect(url_for("data_entry"))

    if len(week_name) > 50:
        return redirect(url_for("data_entry"))

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