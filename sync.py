from woo_api import get_orders
import db
import os
from woo_fields import (
    ORDER_FIELDS,
    BILLING_FIELDS,
    SHIPPING_FIELDS,
    SHIPPING_LINE_FIELDS,
    META_KEYS,
    LINE_ITEM_FIELDS
)

if db.DB_PATH is None:
    db.set_db_path(os.path.join(os.path.dirname(__file__), "crm.db"))
    db.init_db()

# ---------------------------------
# FINAL STATUS MAP
# ---------------------------------

def map_status(woo_status, shipping_method):
    woo_status = (woo_status or "").lower()
    shipping_method = (shipping_method or "").lower()

    if woo_status == "processing":
        return "Новий"

    if woo_status == "pending":
        return "Не оплачено"

    if woo_status == "pay":
        return "Оплачено"

    if woo_status == "confirmed":
        if "nova" in shipping_method:
            return "Підтверджен НП"
        if "ukr" in shipping_method:
            return "Підтверджен УП"
        return "Підтверджено"

    if woo_status == "ttn":
        return "Створено ТТН"

    if woo_status == "completed":
        return "Відправлено"

    if woo_status == "on-hold":
        return "На утриманні"

    if woo_status == "cancelled":
        return "Скасовано"

    if woo_status == "crazy":
        return "Неадекват"

    if woo_status == "na":
        return "Недозвонилися"

    return "Новий"

# ---------------------------------

def get_value(obj, path):
    parts = path.replace("]", "").split(".")
    cur = obj

    for p in parts:
        if "[" in p:
            name, index = p.split("[")
            cur = cur.get(name, [])
            cur = cur[int(index)] if len(cur) > int(index) else {}
        else:
            cur = cur.get(p, {})
    return cur or ""

# ---------------------------------

def sync_orders():
    per_page = 100
    max_existing_id = db.get_max_woo_id()
    page = 1
    pages_limit = 10

    orders = []
    while page <= pages_limit:
        chunk = get_orders(per_page, page=page)
        if not chunk:
            break

        orders.extend(chunk)

        if max_existing_id is not None:
            try:
                min_id_in_chunk = min(int(x.get("id")) for x in chunk if x.get("id") is not None)
            except Exception:
                min_id_in_chunk = None
            if min_id_in_chunk is not None and min_id_in_chunk <= max_existing_id:
                break

        page += 1

    for o in orders:

        # ---------- ITEMS (from Woo line_items) ----------
        items = []
        for li in (o.get("line_items") or []):
            name_li = (li.get("name") or "").strip()
            if not name_li:
                continue
            qty_li = li.get("quantity") or 1
            try:
                qty_li = int(qty_li)
            except Exception:
                qty_li = 1
            items.append({"name": name_li, "qty": qty_li})

        # ---------- PRODUCT ----------
        name = get_value(o, LINE_ITEM_FIELDS["name"])
        qty = get_value(o, LINE_ITEM_FIELDS["quantity"]) or 1

        product = name.split()[0] if name else ""
        if qty > 1:
            product = f"{product} x{qty}"

        # ---------- CUSTOMER ----------
        first = get_value(o, BILLING_FIELDS["first_name"])
        last = get_value(o, BILLING_FIELDS["last_name"])
        middle = get_value(o, BILLING_FIELDS["company"])
        customer_name = f"{first} {last} {middle}".strip()

        phone = get_value(o, BILLING_FIELDS["phone"])

        # ---------- SHIPPING BASE ----------
        city = get_value(o, SHIPPING_FIELDS["city"])
        address = get_value(o, SHIPPING_FIELDS["address"])
        postcode = get_value(o, SHIPPING_FIELDS["postcode"])

        # ---------- SHIPPING METHOD ----------
        shipping_method_id = get_value(o, SHIPPING_LINE_FIELDS["method_id"])
        shipping_method_title = get_value(o, SHIPPING_LINE_FIELDS["method_title"])
        shipping_method = (shipping_method_title or shipping_method_id or "")
        shipping_method_full = " ".join([str(shipping_method_id or "").strip(), str(shipping_method_title or "").strip()]).strip()

        sm_l = (shipping_method_full or shipping_method or "").lower()
        delivery_service = "np"
        if "ukr" in sm_l or "укр" in sm_l:
            delivery_service = "ukr"
        elif "nova" in sm_l or "np" in sm_l:
            delivery_service = "np"

        # ---------- META ----------
        warehouse_name = ""
        meta = get_value(o, "shipping_lines[0].meta_data")

        for m in meta or []:
            if m.get("key") == META_KEYS["warehouse_name"]:
                warehouse_name = m.get("value")
            if m.get("key") == META_KEYS["city_name"]:
                city = m.get("value")

        # ---------- ADDRESS LOGIC ----------
        if "nova" in (shipping_method_id or "").lower() or "nova" in (shipping_method_title or "").lower() or "np" in (shipping_method_id or "").lower() or "np" in (shipping_method_title or "").lower():
            if warehouse_name:
                address = warehouse_name

        elif "ukr" in (shipping_method_id or "").lower() or "ukr" in (shipping_method_title or "").lower() or "укр" in (shipping_method_title or "").lower():
            if postcode:
                address = f"{address}, {postcode}"

        # ---------- STATUS ----------
        status = map_status(o.get("status"), shipping_method)

        comment = get_value(o, ORDER_FIELDS["customer_note"])

        # ---------- SAVE ----------
        order = {
            "woo_id": int(get_value(o, ORDER_FIELDS["woo_id"])),
            "created_at": get_value(o, ORDER_FIELDS["created_at"]),
            "first_name": first,
            "last_name": last,
            "customer_name": customer_name,
            "phone": phone,
            "city": city,
            "address": address,
            "product": product,
            "items": items,
            "amount": float(get_value(o, ORDER_FIELDS["total"])),
            "status": status,
            "delivery_service": delivery_service,
            "shipping_method": shipping_method_full or shipping_method,
            "payment_method": get_value(o, ORDER_FIELDS["payment_method_title"]),
            "comment": comment
        }

        db.create_or_update_order(order)
        print("DEBUG:", order["woo_id"], status)

    print("✅ Синхронизация завершена")

# ---------------------------------

if __name__ == "__main__":
    sync_orders()
