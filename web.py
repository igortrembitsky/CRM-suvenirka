from flask import Flask, render_template, render_template_string, redirect, url_for, request, jsonify, send_from_directory, abort
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

_STATUS_SYNC_LOCK = threading.Lock()
_LAST_STATUS_SYNC_AT = None
_LAST_STATUS_SYNC_ERROR = None

NP_API_URL = "https://api.novaposhta.ua/v2.0/json/"
NP_API_KEY = os.environ.get("NP_API_KEY")

_NP_CACHE = {}


CRM_TO_WOO_STATUS = {
    "new": "processing",
    "not_paid": "pending",
    "paid": "pay",
    "hold": "on-hold",
    "ttn": "ttn",
    "confirmed": "confirmed",
    "shipped": "completed",
    "canceled": "cancelled",
    "bad": "crazy",
}


def map_crm_status_to_woo(raw_status: str):
    code = normalize_status(raw_status)
    return CRM_TO_WOO_STATUS.get(code)


PAYMENT_STATE_LABELS = {
    "paid": "Оплачено LiqPay",
    "cod": "Готівка при отриманні",
    "card": "Оплата на карту",
    "not_paid": "Не оплачено",
}


PAYMENT_STATE_ICONS = {
    "cod": "go.png",
    "paid": "liq.png",
    "card": "card.png",
    "not_paid": "notpay.png",
}


def payment_display(order: dict):
    # 1) If payment_state explicitly set in CRM - always show it in table
    ps = (order.get("payment_state") or "").strip().lower()
    if ps in PAYMENT_STATE_LABELS:
        return PAYMENT_STATE_LABELS.get(ps, ""), PAYMENT_STATE_ICONS.get(ps)

    # 2) If order status is 'not paid' - show it only when payment_state is empty/unknown
    try:
        st_code = normalize_status(order.get("status"))
    except Exception:
        st_code = ""
    if st_code == "not_paid":
        return "Не оплачено", PAYMENT_STATE_ICONS.get("not_paid")

    # 4) Fallback: infer from payment method/title
    pm = (order.get("payment_method") or "").strip().lower()
    pmt = (order.get("payment_method_title") or "").strip().lower()
    s = " ".join([pm, pmt]).strip()
    if not s:
        return "", None

    # cash on delivery
    if "cod" in s or "cash" in s or "гот" in s or "нал" in s or "при получ" in s or "при отрим" in s:
        return PAYMENT_STATE_LABELS["cod"], PAYMENT_STATE_ICONS.get("cod")

    # paid online / paid
    if "liqpay" in s or "fondy" in s or "stripe" in s or "paypal" in s or "оплат" in s:
        return PAYMENT_STATE_LABELS["paid"], PAYMENT_STATE_ICONS.get("paid")

    # explicit card transfer (only if clearly mentioned)
    if "на карту" in s or "карт" in s:
        return PAYMENT_STATE_LABELS["card"], PAYMENT_STATE_ICONS.get("card")

    return "", None


def payment_state_label(order: dict):
    ps = (order.get("payment_state") or "").strip().lower()
    if ps in PAYMENT_STATE_LABELS:
        return PAYMENT_STATE_LABELS.get(ps, "")

    # fallback: infer from payment method/title
    pm = (order.get("payment_method") or "").strip().lower()
    pmt = (order.get("payment_method_title") or "").strip().lower()
    s = " ".join([pm, pmt]).strip()

    if not s:
        return ""

    # typical Woo strings for cash on delivery
    if "cod" in s or "cash" in s or "гот" in s or "нал" in s or "при получ" in s or "при отрим" in s:
        return PAYMENT_STATE_LABELS["cod"]

    # explicit card transfer
    if "card" in s or "карт" in s:
        return PAYMENT_STATE_LABELS["card"]

    # heuristic: any explicit online/paid method
    if "liqpay" in s or "fondy" in s or "stripe" in s or "paypal" in s or "оплат" in s:
        return PAYMENT_STATE_LABELS["paid"]

    return ""


def payment_state_icon_filename(order: dict):
    ps = (order.get("payment_state") or "").strip().lower()
    if ps in PAYMENT_STATE_ICONS:
        return PAYMENT_STATE_ICONS.get(ps)
    return None


def infer_payment_state(order: dict):
    try:
        st_code = normalize_status(order.get("status"))
    except Exception:
        st_code = ""
    if st_code == "not_paid":
        return "not_paid"

    pm = (order.get("payment_method") or "").strip().lower()
    pmt = (order.get("payment_method_title") or "").strip().lower()
    s = " ".join([pm, pmt]).strip()
    if not s:
        return ""

    if "cod" in s or "cash" in s or "гот" in s or "нал" in s or "при получ" in s or "при отрим" in s:
        return "cod"
    if "liqpay" in s or "fondy" in s or "stripe" in s or "paypal" in s or "оплат" in s:
        return "paid"
    if "на карту" in s or "карт" in s:
        return "card"
    return ""


@app.get("/assets/<path:filename>")
def asset_file(filename: str):
    # serve only explicitly allowed icon files from project root
    allowed = {"np.png", "up.png", "liq.png", "card.png", "notpay.png", "go.png"}
    if filename not in allowed:
        return abort(404)
    root = os.path.abspath(os.path.dirname(__file__))
    return send_from_directory(root, filename)
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


def _get_woo_price_map():
    cached = _woo_cache_get(("products", ""))
    if cached is not None:
        items = cached
    else:
        items = woo_api.get_products(per_page=100, search=None)
        res = []
        for p in items or []:
            res.append({
                "id": p.get("id"),
                "name": p.get("name") or "",
                "price": p.get("price") or p.get("regular_price") or "",
            })
        _woo_cache_set(("products", ""), res)
        items = res

    price_map = {}
    for p in items or []:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        try:
            price = float(str(p.get("price") or "").replace(",", "."))
        except Exception:
            continue
        price_map[name] = price
    return price_map


def compute_items_total(items):
    price_map = _get_woo_price_map()
    total = 0.0
    found_any = False

    for it in items or []:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        price = price_map.get(name)
        if price is None:
            continue

        try:
            qty = int(it.get("qty") or 1)
        except Exception:
            qty = 1

        total += price * qty
        found_any = True

    if not found_any:
        return None

    return round(total, 2)


def compute_items_total_with_overrides(items):
    price_map = _get_woo_price_map()
    total = 0.0
    found_any = False

    for it in items or []:
        name = (it.get("name") or "").strip()
        if not name:
            continue

        try:
            qty = int(it.get("qty") or 1)
        except Exception:
            qty = 1

        try:
            amount_auto = 1 if int(it.get("amount_auto") or 0) == 1 else 0
        except Exception:
            amount_auto = 0

        if amount_auto == 1:
            price = price_map.get(name)
            if price is None:
                continue
            total += price * qty
            found_any = True
            continue

        # manual amount
        amt = it.get("amount")
        try:
            amt = float(str(amt).replace(",", ".")) if amt is not None and str(amt).strip() != "" else None
        except Exception:
            amt = None
        if amt is None:
            continue
        total += amt
        found_any = True

    if not found_any:
        return None

    return round(total, 2)

# Единый справочник статусов (код -> отображение + css)
STATUS_BADGES = {
    "new": {"label": "Новий", "class": "badge--new"},
    "not_paid": {"label": "Не оплачено", "class": "badge--not-paid"},
    "hold": {"label": "На утриманні", "class": "badge--hold"},
    "ttn": {"label": "Створено ТТН", "class": "badge--ttn"},
    "confirmed": {"label": "Підтверджен", "class": "badge--confirmed"},
    "shipped": {"label": "Відправлено", "class": "badge--shipped"},
    "canceled": {"label": "Скасовано", "class": "badge--canceled"},
    "bad": {"label": "Неадекват", "class": "badge--bad"},
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
    if sl in ("confirmed", "confirmed_np", "confirmed_up", "np_confirmed", "up_confirmed", "confirmed-np", "confirmed-up"):
        return "confirmed"
    if sl in ("shipped", "completed"):
        return "shipped"
    if sl in ("canceled", "cancelled"):
        return "canceled"
    if sl in ("bad", "crazy"):
        return "bad"
    if sl in ("paid", "pay"):
        return "confirmed"

    # --- legacy text values in DB (ua/ru) ---
    if s in ("Новий", "Новый"):
        return "new"
    if s in ("Не оплачено", "Не оплачен"):
        return "not_paid"
    if s in ("На утриманні", "На удержании"):
        return "hold"
    if s in ("Створено ТТН", "Создана ТТН"):
        return "ttn"
    if s in ("Підтверджено", "Підтверджен", "Подтверждён"):
        return "confirmed"
    if s in ("Підтверджено НП", "Підтверджен НП", "Подтверждён НП"):
        return "confirmed"
    if s in ("Підтверджено УП", "Підтверджен УП", "Подтверждён УП"):
        return "confirmed"
    if s in ("Відправлено", "Отправлено"):
        return "shipped"
    if s in ("Скасовано", "Отменён"):
        return "canceled"
    if s in ("Невменяшка", "Неадекват"):
        return "bad"

    return "new"


def format_created_at(raw: str):
    s = (raw or "").strip()
    if not s:
        return ""
    # Woo usually returns ISO like 2026-01-29T18:22:11
    if "T" in s:
        s = s.replace("T", " ")
    # keep YYYY-MM-DD HH:MM
    return s[:16]


def format_products_for_table(items, product_fallback: str):
    order = []
    totals = {}
    for it in items or []:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        first = name.split()[0]
        try:
            qty = int(it.get("qty") or 1)
        except Exception:
            qty = 1
        if first not in totals:
            order.append(first)
            totals[first] = 0
        totals[first] += qty

    if totals:
        parts = []
        for first in order:
            qty = totals.get(first, 0) or 0
            if qty > 1:
                parts.append(f"{first} x{qty}")
            else:
                parts.append(first)
        return ", ".join(parts)

    # fallback: orders.product like "Foo x2; Bar x1"
    pf = (product_fallback or "").strip()
    if not pf:
        return ""
    order = []
    totals = {}
    for chunk in pf.split(";"):
        c = chunk.strip()
        if not c:
            continue
        tokens = c.split()
        if not tokens:
            continue
        first = tokens[0]
        qty = None
        for t in tokens[1:]:
            tl = t.lower()
            if tl.startswith("x") and tl[1:].isdigit():
                qty = int(tl[1:])
                break
        if first not in totals:
            order.append(first)
            totals[first] = 0
        totals[first] += qty if (qty and qty > 0) else 1

    parts = []
    for first in order:
        qty = totals.get(first, 0) or 0
        if qty > 1:
            parts.append(f"{first} x{qty}")
        else:
            parts.append(first)
    return ", ".join(parts)


@app.route("/")
def index():
    raw_orders = db.list_orders()
    orders = []

    woo_ids = []
    for o in raw_orders:
        try:
            woo_ids.append(int(o["woo_id"]))
        except Exception:
            pass

    items_rows = db.get_order_items_for_orders(woo_ids)
    items_by_woo = {}
    for r in items_rows:
        wid = r["woo_id"]
        items_by_woo.setdefault(wid, []).append({"name": r["name"], "qty": r["qty"]})

    for o in raw_orders:
        order = dict(o)
        raw_status = order.get("status", "")
        code = normalize_status(raw_status)
        badge = STATUS_BADGES.get(code, STATUS_BADGES["new"])
        order["status_code"] = code
        order["status_label"] = badge["label"]
        order["status_class"] = badge["class"]
        order["created_at_display"] = format_created_at(order.get("created_at"))

        pay_label, icon_name = payment_display(order)
        order["payment_state_label"] = pay_label
        order["payment_icon_url"] = url_for("asset_file", filename=icon_name) if icon_name else ""

        wid = order.get("woo_id")
        order["products_display"] = format_products_for_table(
            items_by_woo.get(wid, []),
            order.get("product")
        )
        orders.append(order)

    return render_template(
        "index.html",
        orders=orders,
        last_sync_at=_LAST_SYNC_AT,
        last_sync_error=_LAST_SYNC_ERROR,
        last_status_sync_at=_LAST_STATUS_SYNC_AT,
        last_status_sync_error=_LAST_STATUS_SYNC_ERROR,
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


@app.post("/sync_statuses")
def sync_statuses_now():
    global _LAST_STATUS_SYNC_AT, _LAST_STATUS_SYNC_ERROR

    if not _STATUS_SYNC_LOCK.acquire(blocking=False):
        return "Синхронизация статусов уже выполняется", 409

    ok = 0
    failed = 0
    try:
        _LAST_STATUS_SYNC_ERROR = None

        orders = db.list_orders()
        for o in orders:
            try:
                woo_id = int(o["woo_id"])
            except Exception:
                continue
            woo_status = map_crm_status_to_woo(o["status"])
            if not woo_status:
                continue
            try:
                woo_api.update_order_status(woo_id, woo_status)
                ok += 1
            except Exception:
                failed += 1

        _LAST_STATUS_SYNC_AT = time.strftime("%Y-%m-%d %H:%M:%S") + f" (ok={ok}, fail={failed})"
    except Exception as e:
        _LAST_STATUS_SYNC_ERROR = str(e)
    finally:
        _STATUS_SYNC_LOCK.release()

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
        per_page = 100 if not q else 50
        products = woo_api.get_products(per_page=per_page, search=q or None)
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
        close_after_save = (request.args.get("close") or "").strip() == "1"

        first_name = (request.form.get("first_name") or "").strip()
        patronymic = (request.form.get("patronymic") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        city = (request.form.get("city") or "").strip()
        city_ref = (request.form.get("city_ref") or "").strip()
        address = (request.form.get("address") or "").strip()
        warehouse_ref = (request.form.get("warehouse_ref") or "").strip()
        comment = (request.form.get("comment") or "").strip()
        status_code = (request.form.get("status") or "new").strip()
        quick_status = (request.form.get("quick_status") or "").strip()
        if quick_status:
            status_code = quick_status

        delivery_service = (request.form.get("delivery_service") or "").strip()
        payment_state = (request.form.get("payment_state") or "").strip()

        # Persist patronymic inside first_name (no separate DB column)
        if (delivery_service or "").strip().lower() == "ukr":
            first_name = (" ".join([first_name, patronymic])).strip()

        if (payment_state or "").strip().lower() == "card" and (status_code or "").strip().lower() in ("not_paid", "pending"):
            status_code = "new"

        items_names = request.form.getlist("item_name")
        items_qtys = request.form.getlist("item_qty")
        items_amounts = request.form.getlist("item_amount")
        items_amount_auto = request.form.getlist("item_amount_auto")
        items = []
        for n, q, a, aa in zip(items_names, items_qtys, items_amounts, items_amount_auto):
            name = (n or "").strip()
            if not name:
                continue
            try:
                qty = int(q)
            except Exception:
                qty = 1

            amount = (a or "").strip().replace(",", ".")
            try:
                amount = float(amount) if amount else None
            except Exception:
                amount = None

            try:
                amount_auto = 1 if int(aa or 0) == 1 else 0
            except Exception:
                amount_auto = 0

            items.append({"name": name, "qty": qty, "amount": amount, "amount_auto": amount_auto})

        product_summary_parts = []
        for it in items:
            if it["qty"] and int(it["qty"]) > 1:
                product_summary_parts.append(f"{it['name']} x{int(it['qty'])}")
            else:
                product_summary_parts.append(it["name"])
        product_summary = "; ".join(product_summary_parts)

        amount_calc = compute_items_total_with_overrides(items)
        amount = amount_calc

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
                "amount_auto": 1,
            },
        )
        db.replace_order_items(woo_id, items)
        if close_after_save:
            return redirect(url_for("index"))
        return redirect(url_for("order_card", woo_id=woo_id, saved=1))

    o = dict(row)

    # Split stored first_name into first name + patronymic for Ukrposhta UI
    fn_raw = (o.get("first_name") or "").strip()

    o["first_name_only"] = ""
    o["patronymic"] = ""

    # 1) Try to parse from stored first_name (may already contain patronymic)
    if fn_raw:
        parts = [p for p in fn_raw.split(" ") if p]
        if len(parts) >= 2:
            o["first_name_only"] = parts[0]
            o["patronymic"] = " ".join(parts[1:])
        else:
            o["first_name_only"] = fn_raw

    # 2) If patronymic is still empty, try to derive from customer_name
    # Many records store full name like: "Фамилия Имя Отчество" in customer_name.
    if not (o.get("patronymic") or "").strip():
        full = (o.get("customer_name") or "").strip()
        ln = (o.get("last_name") or "").strip()
        if ln and full.lower().startswith((ln + " ").lower()):
            full = full[len(ln):].strip()

        parts_full = [p for p in full.split(" ") if p]
        if len(parts_full) >= 2:
            # If first_name_only is empty, take it from customer_name.
            if not (o.get("first_name_only") or "").strip():
                o["first_name_only"] = parts_full[0]

            # Patronymic is everything after first token.
            o["patronymic"] = " ".join(parts_full[1:])

    if o.get("amount_auto") is None:
        o["amount_auto"] = 1

    if not (o.get("delivery_service") or "").strip():
        sm = (o.get("shipping_method") or "").lower()
        if "nova" in sm or "np" in sm:
            o["delivery_service"] = "np"
        elif "ukr" in sm or "up" in sm:
            o["delivery_service"] = "ukr"
        else:
            o["delivery_service"] = "np"

    if not (o.get("payment_state") or "").strip():
        inferred = infer_payment_state(o)
        o["payment_state"] = inferred if inferred else "cod"
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

    prev_woo_id, next_woo_id = db.get_prev_next_woo_ids(woo_id)

    saved = request.args.get("saved") == "1"

    return render_template(
        "order.html",
        o=o,
        items=items,
        status_badges=STATUS_BADGES,
        saved=saved,
        prev_woo_id=prev_woo_id,
        next_woo_id=next_woo_id,
    )


@app.route("/order/<int:woo_id>/delete", methods=["POST"])
def delete_order(woo_id: int):
    db.delete_order(woo_id)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
