import sqlite3

DB_PATH = None

# -------------------------
# CONNECTION
# -------------------------

def set_db_path(path):
    global DB_PATH
    DB_PATH = path


def get_conn():
    if not DB_PATH:
        raise RuntimeError("DB path not set")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# -------------------------
# INIT
# -------------------------

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
            payment_method TEXT
        )
    """)

    conn.commit()
    conn.close()


# -------------------------
# CREATE / UPDATE
# -------------------------

def create_order(order):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM orders WHERE woo_id=?
    """, (order["woo_id"],))

    row = cur.fetchone()

    if row:
        conn.close()
        return

    cur.execute("""
        INSERT INTO orders
        (woo_id, customer_name, phone, city, address, product, amount, status, payment_method)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        order["woo_id"],
        order["customer_name"],
        order["phone"],
        order["city"],
        order["address"],
        order["product"],
        order["amount"],
        order["status"],
        order["payment_method"]
    ))

    conn.commit()
    conn.close()


# -------------------------
# READ
# -------------------------

def list_orders():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM orders
        ORDER BY woo_id DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_order_by_woo_id(woo_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM orders WHERE woo_id=?
    """, (woo_id,))

    row = cur.fetchone()
    conn.close()
    return row


# -------------------------
# UPDATE
# -------------------------

def update_status(woo_id, status):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE orders SET status=? WHERE woo_id=?
    """, (status, woo_id))

    conn.commit()
    conn.close()
