# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import sqlite3
from typing import Optional

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

    if "call_attempts" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN call_attempts INTEGER")

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

    if "is_deleted" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN is_deleted INTEGER")
        try:
            cur.execute("UPDATE orders SET is_deleted=0 WHERE is_deleted IS NULL")
        except Exception:
            pass
    if "deleted_at" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN deleted_at TEXT")

    if "ttn_number" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN ttn_number TEXT")
    if "ttn_error" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN ttn_error TEXT")
    if "ttn_created_at" not in cols:
        cur.execute("ALTER TABLE orders ADD COLUMN ttn_created_at TEXT")

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending_woo_deletes (
        woo_id INTEGER PRIMARY KEY
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


def purge_orders_bulk(woo_ids: list[int]):
    ids = [int(x) for x in (woo_ids or []) if int(x) > 0]
    if not ids:
        return

    conn = get_conn()
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(ids))
    cur.execute(f"DELETE FROM order_items WHERE woo_id IN ({placeholders})", tuple(ids))
    cur.execute(f"DELETE FROM orders WHERE woo_id IN ({placeholders})", tuple(ids))

    conn.commit()
    conn.close()


def trash_order(woo_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE orders SET is_deleted=1, deleted_at=datetime('now') WHERE woo_id=?",
        (int(woo_id),),
    )
    conn.commit()
    conn.close()


def restore_order(woo_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE orders SET is_deleted=0, deleted_at='' WHERE woo_id=?",
        (int(woo_id),),
    )
    conn.commit()
    conn.close()


def trash_orders_bulk(woo_ids: list[int]):
    ids = [int(x) for x in (woo_ids or []) if int(x) > 0]
    if not ids:
        return
    conn = get_conn()
    cur = conn.cursor()
    placeholders = ",".join(["?"] * len(ids))
    cur.execute(
        f"UPDATE orders SET is_deleted=1, deleted_at=datetime('now') WHERE woo_id IN ({placeholders})",
        tuple(ids),
    )
    conn.commit()
    conn.close()


def restore_orders_bulk(woo_ids: list[int]):
    ids = [int(x) for x in (woo_ids or []) if int(x) > 0]
    if not ids:
        return
    conn = get_conn()
    cur = conn.cursor()
    placeholders = ",".join(["?"] * len(ids))
    cur.execute(
        f"UPDATE orders SET is_deleted=0, deleted_at='' WHERE woo_id IN ({placeholders})",
        tuple(ids),
    )
    conn.commit()
    conn.close()


def delete_orders_bulk(woo_ids: list[int]):
    ids = [int(x) for x in (woo_ids or []) if int(x) > 0]
    if not ids:
        return

    conn = get_conn()
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(ids))
    cur.execute(f"DELETE FROM pending_woo_deletes WHERE woo_id IN ({placeholders})", tuple(ids))
    cur.execute(f"DELETE FROM order_items WHERE woo_id IN ({placeholders})", tuple(ids))
    cur.execute(f"DELETE FROM orders WHERE woo_id IN ({placeholders})", tuple(ids))

    conn.commit()
    conn.close()


def update_status_only(woo_id, status):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=? WHERE woo_id=?", (status, woo_id))
    conn.commit()
    conn.close()


def increment_call_attempts(woo_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE orders SET call_attempts=COALESCE(call_attempts, 0) + 1 WHERE woo_id=?",
        (int(woo_id),),
    )
    conn.commit()
    cur.execute("SELECT COALESCE(call_attempts, 0) FROM orders WHERE woo_id=?", (int(woo_id),))
    row = cur.fetchone()
    conn.close()
    try:
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def list_pending_woo_deletes(limit: int = 500):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT woo_id FROM pending_woo_deletes ORDER BY woo_id DESC LIMIT ?",
        (int(limit),),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_np_orders_missing_ttn(limit: int = 200):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT woo_id
        FROM orders
        WHERE lower(coalesce(delivery_service,''))='np'
          AND (ttn_number IS NULL OR trim(ttn_number)='')
        ORDER BY created_at DESC, woo_id DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    rows = cur.fetchall()
    conn.close()
    return [int(r[0]) for r in rows if r and r[0] is not None]


def pending_woo_delete_ids(limit: int = 10000) -> set[int]:
    rows = list_pending_woo_deletes(limit=limit)
    res: set[int] = set()
    for r in rows:
        try:
            res.add(int(r["woo_id"]))
        except Exception:
            continue
    return res


def delete_pending_woo_delete(woo_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM pending_woo_deletes WHERE woo_id=?", (woo_id,))
    conn.commit()
    conn.close()


def delete_order(woo_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO pending_woo_deletes (woo_id) VALUES (?)",
        (woo_id,),
    )

    cur.execute("DELETE FROM order_items WHERE woo_id=?", (woo_id,))
    cur.execute("DELETE FROM orders WHERE woo_id=?", (woo_id,))

    conn.commit()
    conn.close()

# ----------------------------

def create_or_update_order(o):
    conn = get_conn()
    cur = conn.cursor()

    call_attempts = o.get("call_attempts")
    if call_attempts is None and o.get("woo_id") is not None:
        try:
            cur.execute("SELECT call_attempts FROM orders WHERE woo_id=?", (o.get("woo_id"),))
            prev = cur.fetchone()
            if prev is not None:
                call_attempts = prev[0]
        except Exception:
            call_attempts = None

    cur.execute("""
    INSERT OR REPLACE INTO orders
    (woo_id, created_at, first_name, last_name, customer_name, phone, city, city_ref, address, warehouse_ref, product, amount, amount_auto, status, delivery_service, shipping_method, payment_state, payment_method, comment, call_attempts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        o.get("comment"),
        call_attempts,
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
        SELECT woo_id, created_at, customer_name, phone, status, payment_state, payment_method, amount, product,
               delivery_service, shipping_method, city_ref, warehouse_ref, comment,
               ttn_number, ttn_error, ttn_created_at
        FROM orders
        ORDER BY created_at DESC, woo_id DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def _build_created_at_range_where(from_date: Optional[str], to_date: Optional[str]):
    clauses = []
    params = []

    fd = (from_date or "").strip()
    td = (to_date or "").strip()

    if fd:
        clauses.append("created_at >= ?")
        params.append(fd + " 00:00:00")

    if td:
        clauses.append("created_at <= ?")
        params.append(td + " 23:59:59")

    where_sql = ""
    if clauses:
        where_sql = " WHERE " + " AND ".join(clauses)

    return where_sql, params


def _build_search_where(q: Optional[str]):
    qs = (q or "").strip()
    if not qs:
        return "", []

    like = f"%{qs}%"
    sql = (
        "("
        " cast(woo_id as text) like ?"
        " OR lower(coalesce(customer_name,'')) like lower(?)"
        " OR lower(coalesce(first_name,'')) like lower(?)"
        " OR lower(coalesce(last_name,'')) like lower(?)"
        " OR coalesce(phone,'') like ?"
        " OR lower(coalesce(city,'')) like lower(?)"
        " OR lower(coalesce(address,'')) like lower(?)"
        " OR lower(coalesce(product,'')) like lower(?)"
        " OR lower(coalesce(comment,'')) like lower(?)"
        " OR coalesce(ttn_number,'') like ?"
        " OR exists(SELECT 1 FROM order_items oi WHERE oi.woo_id = orders.woo_id AND lower(coalesce(oi.name,'')) like lower(?))"
        ")"
    )
    params = [
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
        like,
    ]
    return sql, params


def count_orders_filtered(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    q: Optional[str] = None,
    trash: bool = False,
) -> int:
    conn = get_conn()
    cur = conn.cursor()

    where_sql, params = _build_created_at_range_where(from_date, to_date)
    q_sql, q_params = _build_search_where(q)

    if q_sql:
        if where_sql:
            where_sql = where_sql + " AND " + q_sql
        else:
            where_sql = " WHERE " + q_sql
        params = list(params) + list(q_params)

    del_sql = " is_deleted=1 " if trash else " coalesce(is_deleted,0)=0 "
    if where_sql:
        where_sql = where_sql + " AND " + del_sql
    else:
        where_sql = " WHERE " + del_sql

    cur.execute("SELECT COUNT(*) FROM orders" + where_sql, params)
    row = cur.fetchone()
    conn.close()
    return int(row[0] or 0) if row else 0


def list_orders_filtered(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    q: Optional[str] = None,
    trash: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    conn = get_conn()
    cur = conn.cursor()

    where_sql, params = _build_created_at_range_where(from_date, to_date)
    q_sql, q_params = _build_search_where(q)

    if q_sql:
        if where_sql:
            where_sql = where_sql + " AND " + q_sql
        else:
            where_sql = " WHERE " + q_sql
        params = list(params) + list(q_params)

    del_sql = " is_deleted=1 " if trash else " coalesce(is_deleted,0)=0 "
    if where_sql:
        where_sql = where_sql + " AND " + del_sql
    else:
        where_sql = " WHERE " + del_sql

    sql = (
        "SELECT woo_id, created_at, customer_name, phone, status, payment_state, payment_method, amount, product, "
        "       delivery_service, shipping_method, city_ref, warehouse_ref, comment, "
        "       ttn_number, ttn_error, ttn_created_at "
        "FROM orders" + where_sql + " ORDER BY created_at DESC, woo_id DESC LIMIT ? OFFSET ?"
    )
    cur.execute(sql, (*params, int(limit), int(offset)))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_max_woo_id():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT MAX(woo_id) FROM orders")
    row = cur.fetchone()
    conn.close()
    try:
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


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


def get_existing_woo_ids(woo_ids) -> set[int]:
    ids = [int(x) for x in (woo_ids or []) if str(x).strip()]
    if not ids:
        return set()

    conn = get_conn()
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(ids))
    cur.execute(
        f"SELECT woo_id FROM orders WHERE woo_id IN ({placeholders})",
        tuple(ids),
    )
    rows = cur.fetchall()
    conn.close()

    res: set[int] = set()
    for r in rows:
        try:
            res.add(int(r[0]))
        except Exception:
            continue
    return res

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


def update_status_bulk(woo_ids: list[int], status: str):
    ids = [int(x) for x in (woo_ids or []) if str(x).strip() != ""]
    if not ids:
        return

    conn = get_conn()
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(ids))

    sql = f"UPDATE orders SET status=? WHERE woo_id IN ({placeholders})"
    cur.execute(sql, (status, *ids))

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
        "ttn_number",
        "ttn_error",
        "ttn_created_at",
        "call_attempts",
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
