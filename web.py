from flask import Flask, render_template, render_template_string, redirect, url_for
import db
import threading
import time

app = Flask(__name__)

DB_FILE = "crm.db"
db.set_db_path(DB_FILE)
db.init_db()

_SYNC_LOCK = threading.Lock()
_LAST_SYNC_AT = None
_LAST_SYNC_ERROR = None

# Единый справочник статусов (код -> отображение + css)
STATUS_BADGES = {
    "new": {"label": "Новий", "class": "badge--new"},
    "not_paid": {"label": "Не оплачено", "class": "badge--not-paid"},
    "hold": {"label": "На утриманні", "class": "badge--hold"},
    "ttn": {"label": "Створено ТТН", "class": "badge--ttn"},
    "confirmed_np": {"label": "Підтверджен НП", "class": "badge--confirmed-np"},
    "confirmed_up": {"label": "Підтверджен УП", "class": "badge--confirmed-up"},
    "shipped": {"label": "Відправлено", "class": "badge--shipped"},
    "canceled": {"label": "Скасовано", "class": "badge--canceled"},
    "bad": {"label": "Неадекват", "class": "badge--bad"},

    # запасной (если появится)
    "paid": {"label": "Оплачено", "class": "badge--paid"},
}


def normalize_status(raw_status: str):
    s = (raw_status or "").strip()
    sl = s.lower()

    # --- codes from Woo / internal ---
    if sl in ("new", "processing"):
        return "new"
    if sl in ("not_paid", "pending"):
        return "not_paid"
    if sl in ("hold", "on-hold"):
        return "hold"
    if sl in ("ttn", "ttn_created"):
        return "ttn"
    if sl in ("confirmed_np", "np_confirmed", "confirmed-np"):
        return "confirmed_np"
    if sl in ("confirmed_up", "up_confirmed", "confirmed-up"):
        return "confirmed_up"
    if sl in ("shipped", "completed"):
        return "shipped"
    if sl in ("canceled", "cancelled"):
        return "canceled"
    if sl in ("bad", "crazy"):
        return "bad"
    if sl in ("paid", "pay"):
        return "paid"

    # --- legacy text values in DB (ua/ru) ---
    if s in ("Новий", "Новый"):
        return "new"
    if s in ("Не оплачено", "Не оплачен"):
        return "not_paid"
    if s in ("На утриманні", "На удержании"):
        return "hold"
    if s in ("Створено ТТН", "Создана ТТН"):
        return "ttn"
    if s in ("Підтверджено НП", "Підтверджен НП", "Подтверждён НП"):
        return "confirmed_np"
    if s in ("Підтверджено УП", "Підтверджен УП", "Подтверждён УП"):
        return "confirmed_up"
    if s in ("Відправлено", "Отправлено"):
        return "shipped"
    if s in ("Скасовано", "Отменён"):
        return "canceled"
    if s in ("Невменяшка", "Неадекват"):
        return "bad"

    return "new"


@app.route("/")
def index():
    raw_orders = db.list_orders()
    orders = []

    for o in raw_orders:
        order = dict(o)
        raw_status = order.get("status", "")
        code = normalize_status(raw_status)
        badge = STATUS_BADGES.get(code, STATUS_BADGES["new"])
        order["status_code"] = code
        order["status_label"] = badge["label"]
        order["status_class"] = badge["class"]
        orders.append(order)

    return render_template(
        "index.html",
        orders=orders,
        last_sync_at=_LAST_SYNC_AT,
        last_sync_error=_LAST_SYNC_ERROR
    )


@app.post("/sync")
def sync_now():
    global _LAST_SYNC_AT, _LAST_SYNC_ERROR

    if not _SYNC_LOCK.acquire(blocking=False):
        return "Синхронизация уже выполняется", 409

    try:
        _LAST_SYNC_ERROR = None
        from sync import sync_orders
        sync_orders()
        _LAST_SYNC_AT = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        _LAST_SYNC_ERROR = str(e)
    finally:
        _SYNC_LOCK.release()

    return redirect(url_for("index"))


@app.route("/order/<int:woo_id>")
def order_card(woo_id: int):
    row = db.get_order_by_woo_id(woo_id)
    if not row:
        return "Заказ не найден", 404

    o = dict(row)
    raw_status = o.get("status", "")
    code = normalize_status(raw_status)
    badge = STATUS_BADGES.get(code, STATUS_BADGES["new"])
    o["status_code"] = code
    o["status_label"] = badge["label"]
    o["status_class"] = badge["class"]

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
            .comment{margin-top:12px; padding:10px; background:#fafafa; border:1px solid #e6e6e6; white-space:pre-wrap;}

            .badge{display:inline-block; padding:4px 10px; border-radius:999px; font-size:12px; font-weight:700;}
            .badge--new{background:#1976d2; color:#fff;}
            .badge--not-paid{background:#d32f2f; color:#fff;}
            .badge--hold{background:#cddc39; color:#1b1b1b;}
            .badge--ttn{background:#fb8c00; color:#fff;}
            .badge--confirmed-np{background:#1976d2; color:#fff;}
            .badge--confirmed-up{background:#03a9f4; color:#00324a;}
            .badge--shipped{background:#7b1fa2; color:#fff;}
            .badge--canceled{background:#616161; color:#fff;}
            .badge--bad{background:#212121; color:#fff;}
            .badge--paid{background:#2e7d32; color:#fff;}
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
            <div class=\"row\"><b>Статус:</b> <span class=\"badge {{ o['status_class'] }}\">{{ o['status_label'] }}</span></div>
            <div class=\"row\"><b>Коментарии:</b></div>
            <div class=\"comment\">{{ (o.get('comment') or '—') }}</div>
        </div>
    </body>
    </html>
    """

    return render_template_string(html, o=o)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
