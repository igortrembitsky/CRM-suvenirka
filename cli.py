import db
from woo_api import get_orders

# -----------------------
# STATUS MAP
# -----------------------

def map_status(s):
    if s == "pending":
        return "Не оплачен"
    if s == "processing":
        return "Новый"
    if s == "completed":
        return "Завершён"
    if s == "cancelled":
        return "Отменён"
    return s


# -----------------------
# SYNC
# -----------------------

def sync_orders():
    orders = get_orders(100)

    for o in orders:
        woo_id = int(o["id"])

        billing = o.get("billing", {})
        shipping = o.get("shipping", {})

        first = billing.get("first_name","")
        last = billing.get("last_name","")
        middle = billing.get("company","")

        customer_name = f"{first} {last} {middle}".strip()

        # ----- PRODUCT -----
        product = ""
        items = o.get("line_items", [])
        if items:
            name = items[0].get("name","")
            qty = items[0].get("quantity",1)
            first_word = name.split()[0]
            product = first_word if qty==1 else f"{first_word} x{qty}"

        # ----- ADDRESS -----
        city = shipping.get("city","")
        postcode = shipping.get("postcode","")
        address = shipping.get("address_1","")

        if postcode:
            address = f"{address}, отделение {postcode}"

        order = {
            "woo_id": woo_id,
            "customer_name": customer_name,
            "phone": billing.get("phone",""),
            "city": city,
            "address": address,
            "product": product,
            "amount": float(o.get("total",0)),
            "status": map_status(o.get("status")),
            "payment_method": o.get("payment_method_title","")
        }

        db.create_order(order)
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
