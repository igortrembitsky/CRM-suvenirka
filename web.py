from flask import Flask, render_template, render_template_string, redirect, url_for, request, jsonify
import db
import threading
import time
import os
import requests
import woo_api

app = Flask(__name__)

DB_FILE = "crm.db"
db.set_db_path(DB_FILE)
db.init_db()

_SYNC_LOCK = threading.Lock()
_LAST_SYNC_AT = None
_LAST_SYNC_ERROR = None

NP_API_URL = "https://api.novaposhta.ua/v2.0/json/"
NP_API_KEY = os.environ.get("NP_API_KEY")

_NP_CACHE = {}
_WOO_CACHE = {}


def _np_post(payload: dict):
    r = requests.post(NP_API_URL, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data


def _cache_get(key):
    v = _NP_CACHE.get(key)
    if not v:
        return None
    ts, value = v
    if time.time() - ts > 60:
        return None
    return value


def _cache_set(key, value):
    _NP_CACHE[key] = (time.time(), value)


def _woo_cache_get(key):
    v = _WOO_CACHE.get(key)
    if not v:
        return None
    ts, value = v
    if time.time() - ts > 60:
        return None
    return value


def _woo_cache_set(key, value):
    _WOO_CACHE[key] = (time.time(), value)

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


@app.get("/np/cities")
def np_cities():
    if not NP_API_KEY:
        return jsonify({"error": "NP_API_KEY is not set"}), 500

    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])

    cache_key = ("cities", q.lower())
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "AddressGeneral",
        "calledMethod": "getCities",
        "methodProperties": {"FindByString": q, "Limit": 20},
    }

    data = _np_post(payload)
    if not data.get("success"):
        return jsonify({"error": data.get("errors") or "NP error"}), 502

    res = []
    for c in data.get("data", []):
        res.append({
            "ref": c.get("Ref"),
            "name": c.get("Description") or c.get("DescriptionRu") or "",
            "area": c.get("AreaDescription") or "",
            "region": c.get("RegionsDescription") or "",
        })

    _cache_set(cache_key, res)
    return jsonify(res)


@app.get("/woo/products")
def woo_products():
    q = (request.args.get("q") or "").strip()
    cache_key = ("products", q.lower())
    cached = _woo_cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        products = woo_api.get_products(per_page=50, search=q or None)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    res = []
    for p in products or []:
        res.append({
            "id": p.get("id"),
            "name": p.get("name") or "",
            "price": p.get("price") or p.get("regular_price") or "",
        })

    _woo_cache_set(cache_key, res)
    return jsonify(res)


@app.get("/np/warehouses")
def np_warehouses():
    if not NP_API_KEY:
        return jsonify({"error": "NP_API_KEY is not set"}), 500

    city_ref = (request.args.get("city_ref") or "").strip()
    q = (request.args.get("q") or "").strip()
    if not city_ref:
        return jsonify([])

    cache_key = ("wh", city_ref, q.lower())
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "AddressGeneral",
        "calledMethod": "getWarehouses",
        "methodProperties": {
            "CityRef": city_ref,
            "FindByString": q,
            "Limit": 50,
        },
    }

    data = _np_post(payload)
    if not data.get("success"):
        return jsonify({"error": data.get("errors") or "NP error"}), 502

    res = []
    for w in data.get("data", []):
        res.append({
            "ref": w.get("Ref"),
            "name": w.get("Description") or w.get("DescriptionRu") or "",
            "type": w.get("CategoryOfWarehouse") or w.get("TypeOfWarehouse") or "",
            "number": w.get("Number") or "",
        })

    _cache_set(cache_key, res)
    return jsonify(res)


@app.route("/order/<int:woo_id>", methods=["GET", "POST"])
def order_card(woo_id: int):
    row = db.get_order_by_woo_id(woo_id)
    if not row:
        return "Заказ не найден", 404

    if request.method == "POST":
        first_name = (request.form.get("first_name") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        city = (request.form.get("city") or "").strip()
        city_ref = (request.form.get("city_ref") or "").strip()
        address = (request.form.get("address") or "").strip()
        warehouse_ref = (request.form.get("warehouse_ref") or "").strip()
        comment = (request.form.get("comment") or "").strip()
        status_code = (request.form.get("status") or "new").strip()

        delivery_service = (request.form.get("delivery_service") or "").strip()
        payment_state = (request.form.get("payment_state") or "").strip()

        amount_raw = (request.form.get("amount") or "").strip().replace(",", ".")
        amount = None
        if amount_raw:
            try:
                amount = float(amount_raw)
            except Exception:
                amount = None

        items_names = request.form.getlist("item_name")
        items_qtys = request.form.getlist("item_qty")
        items = []
        for n, q in zip(items_names, items_qtys):
            name = (n or "").strip()
            if not name:
                continue
            try:
                qty = int(q)
            except Exception:
                qty = 1
            items.append({"name": name, "qty": qty})

        product_summary_parts = []
        for it in items:
            if it["qty"] and int(it["qty"]) > 1:
                product_summary_parts.append(f"{it['name']} x{int(it['qty'])}")
            else:
                product_summary_parts.append(it["name"])
        product_summary = "; ".join(product_summary_parts)

        customer_name = f"{first_name} {last_name}".strip()
        db.update_order_fields(
            woo_id,
            {
                "first_name": first_name,
                "last_name": last_name,
                "customer_name": customer_name,
                "phone": phone,
                "city": city,
                "city_ref": city_ref,
                "address": address,
                "warehouse_ref": warehouse_ref,
                "comment": comment,
                "status": status_code,
                "delivery_service": delivery_service,
                "payment_state": payment_state,
                "product": product_summary,
                "amount": amount,
            },
        )
        db.replace_order_items(woo_id, items)
        return redirect(url_for("order_card", woo_id=woo_id, saved=1))

    o = dict(row)

    if not (o.get("delivery_service") or "").strip():
        sm = (o.get("shipping_method") or "").lower()
        if "nova" in sm or "np" in sm:
            o["delivery_service"] = "np"
        elif "ukr" in sm or "up" in sm:
            o["delivery_service"] = "ukr"
        else:
            o["delivery_service"] = "np"

    if not (o.get("payment_state") or "").strip():
        o["payment_state"] = "cod"
    items_rows = db.get_order_items(woo_id)
    items = [dict(r) for r in items_rows]
    if not items:
        product = (o.get("product") or "").strip()
        if product:
            items = [{"name": product, "qty": 1}]

    raw_status = o.get("status", "")
    code = normalize_status(raw_status)
    badge = STATUS_BADGES.get(code, STATUS_BADGES["new"])
    o["status_code"] = code
    o["status_label"] = badge["label"]
    o["status_class"] = badge["class"]

    saved = request.args.get("saved") == "1"

    return render_template(
        "order.html",
        o=o,
        items=items,
        status_badges=STATUS_BADGES,
        saved=saved,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
