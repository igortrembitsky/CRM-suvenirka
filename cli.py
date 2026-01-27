import db

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

def change_status():
    woo = input("Woo ID заказа: ")
    status = input("Введите новый статус: ")
    db.update_status(int(woo), status)
    print("Статус обновлён")

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
            from sync import sync_orders
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
