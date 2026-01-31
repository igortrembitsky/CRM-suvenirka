import sqlite3

DB_PATH = None

# ----------------------------

def set_db_path(path):
    global DB_PATH
    DB_PATH = path

def get_conn():
    if not DB_PATH:
        raise RuntimeError("DB path not set")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------------------

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        woo_id INTEGER UNIQUE,
        created_at TEXT,
        first_name TEXT,
        last_name TEXT,
        customer_name TEXT,
        phone TEXT,
        city TEXT,
        city_ref TEXT,
        address TEXT,
        warehouse_ref TEXT,
        product TEXT,
        amount REAL,
        amount_auto INTEGER,
        status TEXT,
        delivery_service TEXT,
        shipping_method TEXT,
        payment_state TEXT,
        payment_method TEXT,
        comment TEXT
    )
    """)

    cur.execute("PRAGMA table_info(orders)")
    cols = {r[1] for r in cur.fetchall()}
    if "comment" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN comment TEXT")

    if "created_at" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN created_at TEXT")

    if "amount_auto" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN amount_auto INTEGER")

    if "first_name" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN first_name TEXT")
    if "last_name" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN last_name TEXT")
    if "city_ref" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN city_ref TEXT")
    if "warehouse_ref" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN warehouse_ref TEXT")
    if "delivery_service" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN delivery_service TEXT")
    if "payment_state" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN payment_state TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        woo_id INTEGER,
        name TEXT,
        qty INTEGER,
        amount REAL,
        amount_auto INTEGER,
        FOREIGN KEY (woo_id) REFERENCES orders (woo_id)
    )
    """)

    cur.execute("PRAGMA table_info(order_items)")
    cols_items = {r[1] for r in cur.fetchall()}
    if "amount" not in cols_items:
        cur.execute("ALTER TABLE order_items ADD COLUMN amount REAL")
    if "amount_auto" not in cols_items:
        cur.execute("ALTER TABLE order_items ADD COLUMN amount_auto INTEGER")

    conn.commit()
    conn.close()


def delete_order(woo_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM order_items WHERE woo_id=?", (woo_id,))
    cur.execute("DELETE FROM orders WHERE woo_id=?", (woo_id,))

    conn.commit()
    conn.close()

# ----------------------------

def create_or_update_order(o):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO orders
    (woo_id, created_at, first_name, last_name, customer_name, phone, city, city_ref, address, warehouse_ref, product, amount, amount_auto, status, delivery_service, shipping_method, payment_state, payment_method, comment)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        o.get("woo_id"),
        o.get("created_at"),
        o.get("first_name"),
        o.get("last_name"),
        o.get("customer_name"),
        o.get("phone"),
        o.get("city"),
        o.get("city_ref"),
        o.get("address"),
        o.get("warehouse_ref"),
        o.get("product"),
        o.get("amount"),
        o.get("amount_auto"),
        o.get("status"),
        o.get("delivery_service"),
        o.get("shipping_method"),
        o.get("payment_state"),
        o.get("payment_method"),
        o.get("comment")
    ))

    items = o.get("items")
    if items is not None:
        cur.execute("DELETE FROM order_items WHERE woo_id=?", (o.get("woo_id"),))
        for it in items:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            qty = it.get("qty")
            try:
                qty = int(qty)
            except Exception:
                qty = 1
            cur.execute(
                "INSERT INTO order_items (woo_id, name, qty) VALUES (?, ?, ?)",
                (o.get("woo_id"), name, qty)
            )

    conn.commit()
    conn.close()

# ----------------------------

def list_orders():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT woo_id, created_at, customer_name, phone, status, payment_state, payment_method, amount, product
        FROM orders
        ORDER BY woo_id DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_order_items_for_orders(woo_ids):
    woo_ids = [int(x) for x in (woo_ids or []) if str(x).strip()]
    if not woo_ids:
        return []

    conn = get_conn()
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(woo_ids))
    cur.execute(
        f"SELECT woo_id, name, qty FROM order_items WHERE woo_id IN ({placeholders}) ORDER BY woo_id DESC, id ASC",
        tuple(woo_ids)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

# ----------------------------

def get_order_by_woo_id(woo_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM orders WHERE woo_id=?", (woo_id,))
    row = cur.fetchone()

    conn.close()
    return row


def get_prev_next_woo_ids(woo_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT MAX(woo_id) AS prev_id FROM orders WHERE woo_id < ?", (woo_id,))
    prev_row = cur.fetchone()
    prev_id = prev_row[0] if prev_row else None

    cur.execute("SELECT MIN(woo_id) AS next_id FROM orders WHERE woo_id > ?", (woo_id,))
    next_row = cur.fetchone()
    next_id = next_row[0] if next_row else None

    conn.close()
    return prev_id, next_id

# ----------------------------

def update_status(woo_id, status):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("UPDATE orders SET status=? WHERE woo_id=?", (status, woo_id))

    conn.commit()
    conn.close()


def get_order_items(woo_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT name, qty, amount, amount_auto FROM order_items WHERE woo_id=? ORDER BY id ASC",
        (woo_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def replace_order_items(woo_id: int, items):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM order_items WHERE woo_id=?", (woo_id,))

    for it in items or []:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        qty = it.get("qty")
        try:
            qty = int(qty)
        except Exception:
            qty = 1

        amount = it.get("amount")
        try:
            amount = float(amount) if amount is not None and str(amount).strip() != "" else None
        except Exception:
            amount = None

        amount_auto = it.get("amount_auto")
        try:
            amount_auto = 1 if int(amount_auto) == 1 else 0
        except Exception:
            amount_auto = 1

        cur.execute(
            "INSERT INTO order_items (woo_id, name, qty, amount, amount_auto) VALUES (?, ?, ?, ?, ?)",
            (woo_id, name, qty, amount, amount_auto)
        )

    conn.commit()
    conn.close()


def update_order_fields(woo_id, fields: dict):
    allowed = {
        "first_name",
        "last_name",
        "customer_name",
        "phone",
        "city",
        "city_ref",
        "address",
        "warehouse_ref",
        "status",
        "delivery_service",
        "shipping_method",
        "payment_state",
        "payment_method",
        "comment",
        "amount",
        "amount_auto",
        "product",
    }

    updates = []
    values = []

    for k, v in (fields or {}).items():
        if k not in allowed:
            continue
        updates.append(f"{k}=?")
        values.append(v)

    if not updates:
        return

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        f"UPDATE orders SET {', '.join(updates)} WHERE woo_id=?",
        (*values, woo_id)
    )

    conn.commit()
    conn.close()
