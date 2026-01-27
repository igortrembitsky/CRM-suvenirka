import db
from woo_api import get_orders

# -----------------------
# STATUS MAP
# -----------------------

def map_status(s):
    if s in ("pending", "failed"):
        return "Не оплачен"

    if s == "processing":
        return "Новий"

    if s == "completed":
        return "Відправлено"

    if s in ("cancelled", "canceled"):
        return "Скасовано"

    if s == "confirmed":
        return "Підтверджен"

    if s == "ttn_created":
        return "Створено ТТН"

    if s == "hold":
        return "На утриманні"

    if s == "bad":
        return "Невменяшка"

    if s == "no_answer":
        return "Недозвонилися"

    return s

# ------------------------------
# СИНХРОНИЗАЦИЯ С WOOCOMMERCE
# ------------------------------

def sync_orders():
    print("SYNC FUNCTION ENTERED")

    orders = get_orders(50)
    print("ORDERS COUNT:", len(orders))

    for o in orders:

        woo_id = int(o.get("id"))

        # ---------------- PRODUCT ----------------
        product = ""
        qty = 1

        if o.get("line_items"):
            name = o["line_items"][0].get("name", "")
            qty = o["line_items"][0].get("quantity", 1)
            product = name.split()[0]

        if qty > 1:
            product = f"{product} x{qty}"

        # ---------------- CUSTOMER ----------------
        billing = o.get("billing", {})
        shipping = o.get("shipping", {})

        first = billing.get("first_name", "")
        last = billing.get("last_name", "")
        middle = billing.get("company", "")

        customer_name = f"{first} {last} {middle}".strip()

        phone = billing.get("phone", "")
        city = shipping.get("city", "")
        address = shipping.get("address_1", "")

        # ---------------- SHIPPING METHOD ----------------
        shipping_method = ""
        if o.get("shipping_lines"):
            shipping_method = o["shipping_lines"][0].get("method_title", "")

       # print("=== SHIPPING_LINES ===")
       # print(o.get("shipping_lines"))
       # print("======================")

        # ---------------- STATUS ----------------
        woo_status = o.get("status")

        if woo_status == "processing":
            status = "Новий"

        elif woo_status == "completed":
            status = "Відправлено"

        elif woo_status == "cancelled":
            status = "Скасовано"

        elif woo_status == "pending":
            status = "Не оплачено"

        elif woo_status == "failed":
            status = "Не оплачено"

        elif woo_status == "on-hold":
            status = "На утриманні"

        elif woo_status == "confirmed":
            if "Нова" in shipping_method:
                status = "Підтверджен НП"
            elif "Укр" in shipping_method:
                status = "Підтверджен УП"
            else:
                status = "Підтверджен"

        else:
            status = woo_status

        # ---------------- SAVE ----------------
        order = {
            "woo_id": woo_id,
            "customer_name": customer_name,
            "phone": phone,
            "city": city,
            "address": address,
            "product": product,
            "amount": float(o.get("total", 0)),
            "status": status,
            "shipping_method": shipping_method
        }

        db.create_or_update_order(order)
        print("DEBUG: сохраняем заказ", woo_id)

    print("✅ Синхронизация завершена")
# -----------------------
# SHOW LIST
# -----------------------

def show_orders():
    rows = db.list_orders()

    print("\nWoo ID | Клиент | Телефон | Статус | Сумма | Товар")
    print("-"*100)

    for r in rows:
        print(
            f"{r['woo_id']} | "
            f"{r['customer_name']} | "
            f"{r['phone']} | "
            f"{r['status']} | "
            f"{r['amount']} | "
            f"{r['product']}"
        )


# -----------------------
# CARD
# -----------------------

def show_card():
    woo = input("Woo ID заказа: ")
    o = db.get_order_by_woo_id(int(woo))

    if not o:
        print("Заказ не найден")
        return

    print("\n-------------------------")
    print("Woo ID:", o["woo_id"])
    print("Клиент:", o["customer_name"])
    print("Телефон:", o["phone"])
    print("Город:", o["city"])
    print("Адрес:", o["address"])
    print("Товар:", o["product"])
    print("Оплата:", o["payment_method"])
    print("Сумма:", o["amount"])
    print("Статус:", o["status"])
    print("-------------------------")


# -----------------------
# CHANGE STATUS
# -----------------------

def change_status():
    woo = input("Woo ID заказа: ")
    status = input("Введите новый статус: ")
    db.update_status(int(woo), status)
    print("Статус обновлён")


# -----------------------
# MAIN
# -----------------------

def main():
    db.set_db_path("crm.db")
    db.init_db()

    while True:
        print("\n=== CRM Suvenirka ===")
        print("1 - Синхронизировать с WooCommerce")
        print("2 - Показать заказы")
        print("3 - Карточка заказа")
        print("4 - Изменить статус")
        print("0 - Выход")

        c = input("> ")

        if c=="1":
            sync_orders()
        elif c=="2":
            show_orders()
        elif c=="3":
            show_card()
        elif c=="4":
            change_status()
        elif c=="0":
            break


if __name__ == "__main__":
    main()
