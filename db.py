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
        customer_name TEXT,
        phone TEXT,
        city TEXT,
        address TEXT,
        product TEXT,
        amount REAL,
        status TEXT,
        shipping_method TEXT
    )
    """)

    conn.commit()
    conn.close()

# ----------------------------

def create_or_update_order(o):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO orders
    (woo_id, customer_name, phone, city, address, product, amount, status, shipping_method)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        o.get("woo_id"),
        o.get("customer_name"),
        o.get("phone"),
        o.get("city"),
        o.get("address"),
        o.get("product"),
        o.get("amount"),
        o.get("status"),
        o.get("shipping_method")
    ))

    conn.commit()
    conn.close()

# ----------------------------

def list_orders():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT woo_id, customer_name, phone, status, amount, product
        FROM orders
        ORDER BY woo_id DESC
    """)

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

# ----------------------------

def update_status(woo_id, status):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("UPDATE orders SET status=? WHERE woo_id=?", (status, woo_id))

    conn.commit()
    conn.close()
