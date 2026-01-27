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

def map_status(woo_status, shipping_method):
    woo_status = (woo_status or "").lower()
    shipping_method = (shipping_method or "").lower()

    if woo_status in ["pending", "failed", "checkout-draft"]:
        return "not_paid"

    if woo_status == "processing":
        if "nova" in shipping_method:
            return "confirmed_np"
        if "ukr" in shipping_method:
            return "confirmed_up"
        return "confirmed"

    if woo_status == "completed":
        return "shipped"

    if woo_status == "cancelled":
        return "canceled"

    if woo_status in ["on-hold", "hold"]:
        return "hold"

    if woo_status == "bad":
        return "bad"

    return "new"

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

        # PRODUCT
        name = get_value(o, LINE_ITEM_FIELDS["name"])
        qty = get_value(o, LINE_ITEM_FIELDS["quantity"]) or 1
        product = name.split()[0] if name else ""
        if qty > 1:
            product = f"{product} x{qty}"

        # CUSTOMER
        first = get_value(o, BILLING_FIELDS["first_name"])
        last = get_value(o, BILLING_FIELDS["last_name"])
        middle = get_value(o, BILLING_FIELDS["company"])
        customer_name = f"{first} {last} {middle}".strip()

        phone = get_value(o, BILLING_FIELDS["phone"])

        # ADDRESS
        city = get_value(o, SHIPPING_FIELDS["city"])
        address = get_value(o, SHIPPING_FIELDS["address"])

        # SHIPPING
        shipping_method = get_value(o, SHIPPING_LINE_FIELDS["method_id"])

        # META
        branch = ""
        meta = get_value(o, "shipping_lines[0].meta_data")
        for m in meta or []:
            if m.get("key") == META_KEYS["warehouse_name"]:
                branch = m.get("value")
            if m.get("key") == META_KEYS["city_name"]:
                city = m.get("value")

        if branch:
            address = f"{address}, {branch}"

        # STATUS
        status = map_status(get_value(o, ORDER_FIELDS["status"]), shipping_method)

        # SAVE
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
        print("DEBUG:", order["woo_id"])

    print("✅ Синхронизация завершена")

# ---------------------------------

if __name__ == "__main__":
    sync_orders()
