# db.py
import sqlite3
from datetime import datetime
from pathlib import Path

_db_path = None

def set_db_path(path: str):
    global _db_path
    _db_path = Path(path)

def get_conn():
    if _db_path is None:
        raise RuntimeError("DB path not set. Call set_db_path(app.user_data_dir/...) first.")
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        city TEXT,
        address TEXT,
        amount REAL DEFAULT 0,
        status TEXT DEFAULT 'new',
        comment TEXT,
        ttn_number TEXT
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(phone)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    conn.commit()
    conn.close()

def create_order(data: dict) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO orders (created_at, customer_name, phone, city, address, amount, status, comment)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(),
        data["customer_name"].strip(),
        data["phone"].strip(),
        data.get("city", "").strip(),
        data.get("address", "").strip(),
        float(data.get("amount") or 0),
        data.get("status", "new"),
        data.get("comment", "").strip(),
    ))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def update_order_status(order_id: int, status: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()

def get_order(order_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row

def list_orders(search: str = "", status: str = "all", limit: int = 200):
    conn = get_conn()
    cur = conn.cursor()

    where = []
    args = []

    if search.strip():
        s = f"%{search.strip()}%"
        where.append("(customer_name LIKE ? OR phone LIKE ? OR CAST(id AS TEXT) LIKE ?)")
        args += [s, s, s]

    if status != "all":
        where.append("status = ?")
        args.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"SELECT * FROM orders {where_sql} ORDER BY id DESC LIMIT {int(limit)}"
    cur.execute(sql, args)

    rows = cur.fetchall()
    conn.close()
    return rows