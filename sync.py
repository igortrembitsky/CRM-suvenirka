from woo_api import get_orders
import db

db.set_db_path("crm.db")
db.init_db()

# -------------------------------------------------

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

# -------------------------------------------------

def sync_orders():
    orders = get_orders(200)

    for o in orders:

        # ---------- PRODUCT ----------
        product = ""
        qty = 1

        if o.get("line_items"):
            name = o["line_items"][0].get("name", "")
            qty = o["line_items"][0].get("quantity", 1)
            product = name.split()[0]

        if qty > 1:
            product = f"{product} x{qty}"

        # ---------- CUSTOMER ----------
        billing = o.get("billing", {})
        shipping = o.get("shipping", {})

        customer_name = f"{billing.get('first_name','')} {billing.get('last_name','')} {billing.get('company','')}".strip()

        # ---------- ADDRESS ----------
        city = shipping.get("city", "")
        address = shipping.get("address_1", "")

        # ---------- SHIPPING METHOD ----------
        shipping_method = ""
        if o.get("shipping_lines"):
            shipping_method = o["shipping_lines"][0].get("method_id", "")

        # ---------- SHIPPING META ----------
        branch = ""
        if o.get("shipping_lines"):
            for m in o["shipping_lines"][0].get("meta_data", []):
                key = str(m.get("key","")).lower()
                val = str(m.get("value",""))
                if "відділен" in key or "warehouse" in key or "отдел" in key:
                    branch = val
                    break

        if branch:
            address = f"{address}, відділення {branch}"

        # ---------- STATUS ----------
        status = map_status(o.get("status"), shipping_method)

        # ---------- SAVE ----------
        order = {
            "woo_id": int(o["id"]),
            "customer_name": customer_name,
            "phone": billing.get("phone",""),
            "city": city,
            "address": address,
            "product": product,
            "amount": float(o.get("total",0)),
            "status": status,
            "shipping_method": shipping_method,
            "payment_method": o.get("payment_method_title","")
        }

        db.create_or_update_order(order)
        print("DEBUG:", o["id"])

    print("✅ Синхронизация завершена")

# -------------------------------------------------

if __name__ == "__main__":
    sync_orders()
