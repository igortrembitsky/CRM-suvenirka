from flask import Flask, render_template, render_template_string
import db

app = Flask(__name__)

DB_FILE = "crm.db"
db.set_db_path(DB_FILE)
db.init_db()

# Все возможные варианты статусов → в наши
STATUS_MAP = {
    # новые
    "new": "Новый",
    "Новый": "Новый",

    # отменён
    "canceled": "Отменён",
    "cancelled": "Отменён",
    "Отменён": "Отменён",

    # подтверждён НП
    "np_confirmed": "Подтверждён НП",
    "confirmed_np": "Подтверждён НП",
    "Подтверждён НП": "Подтверждён НП",

    # подтверждён УП
    "up_confirmed": "Подтверждён УП",
    "confirmed_up": "Подтверждён УП",
    "Подтверждён УП": "Подтверждён УП",

    # создана ТТН
    "ttn_created": "Создана ТТН",
    "Создана ТТН": "Создана ТТН",

    # отправлено (Woo completed считаем отправленным)
    "completed": "Отправлено",
    "shipped": "Отправлено",
    "Отправлено": "Отправлено",

    # на удержании
    "hold": "На удержании",
    "На удержании": "На удержании",

    # не оплачен
    "not_paid": "Не оплачен",
    "Не оплачен": "Не оплачен",

    # невменяшка
    "bad": "Невменяшка",
    "Невменяшка": "Невменяшка",
}


@app.route("/")
def index():
    raw_orders = db.list_orders()
    orders = []

    for o in raw_orders:
        order = dict(o)
        raw_status = order.get("status", "")
        order["status"] = STATUS_MAP.get(raw_status, raw_status)
        orders.append(order)

    return render_template("index.html", orders=orders)


@app.route("/order/<int:woo_id>")
def order_card(woo_id: int):
    row = db.get_order_by_woo_id(woo_id)
    if not row:
        return "Заказ не найден", 404

    o = dict(row)
    raw_status = o.get("status", "")
    o["status"] = STATUS_MAP.get(raw_status, raw_status)

    html = """
    <!DOCTYPE html>
    <html lang=\"ru\">
    <head>
        <meta charset=\"UTF-8\">
        <title>Заказ {{ o['woo_id'] }}</title>
        <style>
            body{font-family: Arial, sans-serif; background:#f5f5f5;}
            .card{max-width:720px; margin:24px auto; background:white; padding:16px; border:1px solid #ddd;}
            .row{margin:6px 0;}
            a{text-decoration:none; color:#0066cc; font-weight:bold;}
        </style>
    </head>
    <body>
        <div class=\"card\">
            <div class=\"row\"><a href=\"/\">← Назад</a></div>
            <h2>Заказ №{{ o['woo_id'] }}</h2>
            <div class=\"row\"><b>Клиент:</b> {{ o['customer_name'] }}</div>
            <div class=\"row\"><b>Телефон:</b> {{ o['phone'] }}</div>
            <div class=\"row\"><b>Город:</b> {{ o['city'] }}</div>
            <div class=\"row\"><b>Адрес:</b> {{ o['address'] }}</div>
            <div class=\"row\"><b>Товар:</b> {{ o['product'] }}</div>
            <div class=\"row\"><b>Оплата:</b> {{ o['payment_method'] }}</div>
            <div class=\"row\"><b>Доставка:</b> {{ o['shipping_method'] }}</div>
            <div class=\"row\"><b>Сумма:</b> {{ o['amount'] }}</div>
            <div class=\"row\"><b>Статус:</b> {{ o['status'] }}</div>
        </div>
    </body>
    </html>
    """

    return render_template_string(html, o=o)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
