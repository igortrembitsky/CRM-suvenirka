from woo_api import get_orders
import db
from woo_fields import (
    ORDER_FIELDS,
    BILLING_FIELDS,
    SHIPPING_FIELDS,
    SHIPPING_LINE_FIELDS,
    META_KEYS,
    LINE_ITEM_FIELDS
)

db.set_db_path("crm.db")
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
            return "Підтверджено НП"
        if "ukr" in shipping_method:
            return "Підтверджено УП"
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
        return "Невменяшка"

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
    orders = get_orders(100)

    for o in orders:

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
        shipping_method = get_value(o, SHIPPING_LINE_FIELDS["method_id"])

        # ---------- META ----------
        warehouse_name = ""
        meta = get_value(o, "shipping_lines[0].meta_data")

        for m in meta or []:
            if m.get("key") == META_KEYS["warehouse_name"]:
                warehouse_name = m.get("value")
            if m.get("key") == META_KEYS["city_name"]:
                city = m.get("value")

        # ---------- ADDRESS LOGIC ----------
        if "nova" in shipping_method:
            if warehouse_name:
                address = warehouse_name

        elif "ukr" in shipping_method:
            if postcode:
                address = f"{address}, {postcode}"

        # ---------- STATUS ----------
        status = map_status(o.get("status"), shipping_method)

        # ---------- SAVE ----------
        order = {
            "woo_id": int(get_value(o, ORDER_FIELDS["woo_id"])),
            "customer_name": customer_name,
            "phone": phone,
            "city": city,
            "address": address,
            "product": product,
            "amount": float(get_value(o, ORDER_FIELDS["total"])),
            "status": status,
            "shipping_method": shipping_method,
            "payment_method": get_value(o, ORDER_FIELDS["payment_method_title"])
        }

        db.create_or_update_order(order)
        print("DEBUG:", order["woo_id"], status)

    print("✅ Синхронизация завершена")

# ---------------------------------

if __name__ == "__main__":
    sync_orders()
