from flask import Flask, render_template
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
