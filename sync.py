from woo_api import get_orders
import db

# подключаем базу
db.set_db_path("crm.db")
db.init_db()

# -------------------------------------------------
# перевод статусов Woo → CRM
# -------------------------------------------------

def map_status(woo_status, shipping_method):
    woo_status = (woo_status or "").lower()
    shipping_method = (shipping_method or "").lower()

    # Не оплачен
    if woo_status in ["pending", "failed", "checkout-draft"]:
        return "not_paid"

    # Подтверждён (processing)
    if woo_status == "processing":
        if "nova" in shipping_method:
            return "confirmed_np"
        if "ukr" in shipping_method:
            return "confirmed_up"
        return "confirmed"

    # Отправлено
    if woo_status == "completed":
        return "shipped"

    # Отменён
    if woo_status == "cancelled":
        return "canceled"

    # На удержании
    if woo_status in ["on-hold", "hold"]:
        return "hold"

    # Невменяшка
    if woo_status == "bad":
        return "bad"

    return "new"

# -------------------------------------------------
# синхронизация
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
            first_word = name.split()[0] if name else ""
            product = first_word

        if qty > 1:
            product = f"{product} x{qty}"

        # ---------- CUSTOMER ----------
        billing = o.get("billing", {})
        shipping = o.get("shipping", {})

        first = billing.get("first_name", "")
        last = billing.get("last_name", "")
        middle = billing.get("company", "")

        customer_name = f"{first} {last} {middle}".strip()

        # ---------- ADDRESS ----------
        city = shipping.get("city", "")
        address = shipping.get("address_1", "")
        postcode = shipping.get("postcode", "")

        if postcode:
            address = f"{address}, отделение {postcode}"

        # ---------- SHIPPING METHOD ----------
        shipping_method = ""
        if o.get("shipping_lines"):
            shipping_method = o["shipping_lines"][0].get("method_id", "")

        # ---------- STATUS ----------
        status = map_status(o.get("status"), shipping_method)

        # ---------- SAVE ----------
        order = {
            "woo_id": int(o["id"]),
            "customer_name": customer_name,
            "phone": billing.get("phone", ""),
            "city": city,
            "address": address,
            "product": product,
            "amount": float(o.get("total", 0)),
            "status": status,
            "payment_method": o.get("payment_method", "")
        }

        db.create_or_update_order(order)
        print("DEBUG: сохраняем заказ", o["id"])

    print("✅ Синхронизация завершена")

# -------------------------------------------------

if __name__ == "__main__":
    sync_orders()
