# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from flask import (
    Flask,
    render_template,
    render_template_string,
    redirect,
    url_for,
    request,
    jsonify,
    send_from_directory,
    abort,
    session
)

from functools import wraps
import db
import threading
import time
import os
import requests
import woo_api
import re
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import config as _config
except Exception:
    _config = None

# ============================
# APP INIT
# ============================

app = Flask(__name__)
app.secret_key = os.environ.get("CRM_SECRET_KEY") or "super_secret_key_change_me_123"
app.config["DEBUG"] = True
app.config["PROPAGATE_EXCEPTIONS"] = True

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
app.config.setdefault("SESSION_COOKIE_NAME", "crm_session_v2")
if os.environ.get("CRM_FORCE_HTTPS") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True

import traceback

@app.errorhandler(Exception)
def show_error(e):
    return "<pre>" + traceback.format_exc() + "</pre>", 500

app.debug = True

import logging

_log_file = os.environ.get("CRM_LOG_FILE")
if not _log_file:
    if os.name == "nt":
        _log_file = os.path.join(os.path.dirname(__file__), "error.log")
    else:
        _log_file = "/home/h60918c/crm_app/error.log"

try:
    _log_dir = os.path.dirname(_log_file)
    if _log_dir and not os.path.exists(_log_dir) and os.name == "nt":
        os.makedirs(_log_dir, exist_ok=True)
    logging.basicConfig(filename=_log_file, level=logging.ERROR)
except Exception:
    logging.basicConfig(level=logging.ERROR)

# ============================
# LOGIN SETTINGS
# ============================

CRM_LOGIN = "admin"
CRM_PASSWORD = "2587"

# ============================
# AUTH
# ============================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if username == CRM_LOGIN and password == CRM_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        return render_template("login.html", error="Неверный логин или пароль")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/login")

# ============================
# DB INIT
# ============================

DB_FILE = os.path.join(os.path.dirname(__file__), "crm.db")
db.set_db_path(DB_FILE)
db.init_db()

# ============================
# LOCKS
# ============================

_SYNC_LOCK = threading.Lock()
_LAST_SYNC_AT = None
_LAST_SYNC_ERROR = None

_STATUS_SYNC_LOCK = threading.Lock()
_LAST_STATUS_SYNC_AT = None
_LAST_STATUS_SYNC_ERROR = None

# ============================
# NOVA POSHTA
# ============================

NP_API_URL = "https://api.novaposhta.ua/v2.0/json/"
NP_API_KEY = os.environ.get("NP_API_KEY") or (getattr(_config, "NP_API_KEY", None) if _config else None)

NP_SENDER_REF = os.environ.get("NP_SENDER_REF") or (getattr(_config, "NP_SENDER_REF", None) if _config else None)
NP_SENDER_CONTACT_REF = os.environ.get("NP_SENDER_CONTACT_REF") or (getattr(_config, "NP_SENDER_CONTACT_REF", None) if _config else None)
NP_SENDER_ADDRESS_REF = os.environ.get("NP_SENDER_ADDRESS_REF") or (getattr(_config, "NP_SENDER_ADDRESS_REF", None) if _config else None)
NP_SENDER_CITY_REF = os.environ.get("NP_SENDER_CITY_REF") or (getattr(_config, "NP_SENDER_CITY_REF", None) if _config else None)
NP_SENDER_PHONE = os.environ.get("NP_SENDER_PHONE") or (getattr(_config, "NP_SENDER_PHONE", None) if _config else None)
NP_CARGO_DESCRIPTION = os.environ.get("NP_CARGO_DESCRIPTION") or (getattr(_config, "NP_CARGO_DESCRIPTION", None) if _config else None) or "Сувенірна продукція"

_NP_CACHE = {}

# ============================
# CRM → WOO STATUS MAP
# ============================

CRM_TO_WOO_STATUS = {
    "new": "processing",
    "not_paid": "pending",
    "paid": "pay",
    "hold": "on-hold",
    "ttn": "ttn",
    "confirmed": "confirmed",
    "shipped": "completed",
    "no_answer": os.environ.get("WOO_STATUS_NO_ANSWER") or "na",
    "canceled": "cancelled",
    "bad": "crazy",
}

def map_crm_status_to_woo(raw_status: str):
    code = normalize_status(raw_status)
    return CRM_TO_WOO_STATUS.get(code)


def _woo_sync_status_single(woo_id: int, crm_status_code: str):
    woo_status = map_crm_status_to_woo(crm_status_code)
    if not woo_status:
        return None
    woo_api.update_order_status(int(woo_id), woo_status)
    return woo_status


def _woo_sync_status_bulk(woo_ids: list[int], crm_status_code: str):
    woo_status = map_crm_status_to_woo(crm_status_code)
    if not woo_status:
        return 0
    updates = []
    for wid in (woo_ids or []):
        try:
            updates.append({"id": int(wid), "status": woo_status})
        except Exception:
            continue
    if not updates:
        return 0
    woo_api.update_orders_status_batch(updates)
    return len(updates)


PAYMENT_STATE_LABELS = {
    "paid": "LiqPay",
    "cod": "Наложка",
    "card": "На карту",
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


def format_amount_display(amount):
    if amount is None:
        return ""
    try:
        s = str(amount).strip().replace(",", ".")
        if not s:
            return ""
        n = float(s)
        return str(int(round(n)))
    except Exception:
        try:
            return str(amount)
        except Exception:
            return ""


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
    allowed = {"np.png", "up.png", "liq.png", "card.png", "notpay.png", "go.png", "logo.png"}
    if filename not in allowed:
        return abort(404)
    root = os.path.abspath(os.path.dirname(__file__))
    images_dir = os.path.join(root, "images")
    return send_from_directory(images_dir, filename)
_WOO_CACHE = {}


def _np_post(payload: dict):
    r = requests.post(NP_API_URL, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data


def _np_ensure_sender_config():
    missing = []
    if not NP_API_KEY:
        missing.append("NP_API_KEY")
    if not NP_SENDER_REF:
        missing.append("NP_SENDER_REF")
    if not NP_SENDER_CONTACT_REF:
        missing.append("NP_SENDER_CONTACT_REF")
    if not NP_SENDER_ADDRESS_REF:
        missing.append("NP_SENDER_ADDRESS_REF")
    if not NP_SENDER_CITY_REF:
        missing.append("NP_SENDER_CITY_REF")
    if not NP_SENDER_PHONE:
        missing.append("NP_SENDER_PHONE")
    if missing:
        raise RuntimeError("NP sender config missing: " + ", ".join(missing))


def _np_detect_service_type(order: dict):
    # Best-effort: if user selected a postomat, address text usually contains it.
    addr = (order.get("address") or "").lower()
    if "поштомат" in addr or "postomat" in addr:
        return "WarehousePostomat"
    return "WarehouseWarehouse"


def _np_build_internal_number(items: list[dict]):
    # "Внутрішній номер відправлення" – first words of item names.
    parts = []
    for it in (items or [])[:3]:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        words = [w for w in name.replace(";", " ").replace(",", " ").split() if w]
        if words:
            parts.append(words[0])
    return ", ".join(parts)[:50]


def _np_city_query_from_text(city_name: str):
    q = (city_name or "").strip()
    if not q:
        return ""
    q = q.split(",")[0].strip()
    low = q.lower()
    for pref in ("м.", "м ", "смт", "с.", "с ", "г.", "г "):
        if low.startswith(pref):
            q = q[len(pref):].strip()
            break
    return q


def _np_resolve_city_ref_by_name(city_name: str):
    q = _np_city_query_from_text(city_name)
    if not q:
        return ""
    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "AddressGeneral",
        "calledMethod": "getCities",
        "methodProperties": {"FindByString": q, "Limit": 20},
    }
    data = _np_post(payload)
    if not data.get("success"):
        return ""
    cities = data.get("data") or []
    ql = q.lower()
    for c in cities:
        name = (c.get("Description") or c.get("DescriptionRu") or "").strip()
        if name.lower() == ql:
            return (c.get("Ref") or "").strip()
    if cities and isinstance(cities[0], dict):
        return (cities[0].get("Ref") or "").strip()
    return ""


def _np_guess_warehouse_query(address_text: str):
    s = (address_text or "").strip()
    if not s:
        return ""
    low = s.lower()

    # Prefer explicit department/postomat number to avoid confusing it with house numbers.
    m = re.search(r"(відділення|отделение|поштомат|postomat)\s*№?\s*(\d{1,5})", low)
    if m:
        return m.group(2)
    m = re.search(r"№\s*(\d{1,5})", low)
    if m and ("відді" in low or "отдел" in low or "поштомат" in low or "postomat" in low):
        return m.group(1)

    # Fallback: use first part of description (do not guess by arbitrary digits to avoid house number).
    return s[:30]


def _np_resolve_warehouse_ref(city_ref: str, address_text: str):
    cr = (city_ref or "").strip()
    if not cr:
        return ""
    q = _np_guess_warehouse_query(address_text)
    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "AddressGeneral",
        "calledMethod": "getWarehouses",
        "methodProperties": {"CityRef": cr, "FindByString": q or "", "Limit": 50},
    }
    data = _np_post(payload)
    if not data.get("success"):
        return ""
    whs = data.get("data") or []
    ql = (q or "").strip().lower()
    if ql:
        for w in whs:
            num = (w.get("Number") or "").strip().lower()
            if num == ql:
                return (w.get("Ref") or "").strip()
    if whs and isinstance(whs[0], dict):
        return (whs[0].get("Ref") or "").strip()
    return ""


def _np_normalize_phone(raw: str):
    # raw may be non-string (e.g. dict from malformed data). Normalize defensively.
    if raw is None:
        s = ""
    elif isinstance(raw, (dict, list, tuple, set)):
        s = ""
    else:
        s = str(raw)
    s = s.strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    # Common UA formats
    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits
    if len(digits) == 12 and digits.startswith("380"):
        return digits
    # If user entered already with 38 + 10 digits
    if len(digits) == 12 and digits.startswith("38"):
        return digits
    # Best-effort: take last 12
    if len(digits) > 12:
        tail = digits[-12:]
        if tail.startswith("380"):
            return tail
    return digits


def _np_safe_strip(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list, tuple, set)):
        return ""
    try:
        return str(v).strip()
    except Exception:
        return ""


def _np_get_or_create_recipient(order: dict):
    """Return (recipient_ref, contact_ref, phone_norm, name_string)."""
    first_name = _np_safe_strip(order.get("first_name"))
    last_name = _np_safe_strip(order.get("last_name"))
    phone_norm = _np_normalize_phone(order.get("phone"))
    if not first_name and _np_safe_strip(order.get("customer_name")):
        # Try to parse from customer_name
        parts = [p for p in _np_safe_strip(order.get("customer_name")).split() if p]
        if parts:
            first_name = parts[0]
        if len(parts) >= 2 and not last_name:
            last_name = parts[1]

    if not first_name:
        first_name = "-"
    if not last_name:
        last_name = "-"
    if not phone_norm:
        raise RuntimeError("NP: recipient phone is empty")

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "Counterparty",
        "calledMethod": "save",
        "methodProperties": {
            "CounterpartyType": "PrivatePerson",
            "CounterpartyProperty": "Recipient",
            "FirstName": first_name,
            "LastName": last_name,
            "Phone": phone_norm,
        },
    }
    data = _np_post(payload)
    if not data.get("success"):
        raise RuntimeError("NP recipient error: " + str(data.get("errors") or data))

    dd = (data.get("data") or [])
    if not dd or not isinstance(dd, list) or not isinstance(dd[0], dict):
        raise RuntimeError("NP recipient unexpected response: " + str(data))

    recipient_ref = _np_safe_strip(dd[0].get("Ref"))
    cp = dd[0].get("ContactPerson")
    contact_ref = ""
    if isinstance(cp, dict):
        # NP may return either:
        # 1) {"Ref": "..."}
        # 2) {"success": True, "data": [{"Ref": "..."}], ...}
        contact_ref = _np_safe_strip(cp.get("Ref"))
        if not contact_ref:
            cp_data = cp.get("data")
            if isinstance(cp_data, list) and cp_data and isinstance(cp_data[0], dict):
                contact_ref = _np_safe_strip(cp_data[0].get("Ref"))
    else:
        contact_ref = _np_safe_strip(cp)

    name_string = _np_safe_strip(dd[0].get("Description")) or (last_name + " " + first_name).strip()
    if not recipient_ref or not contact_ref:
        raise RuntimeError("NP recipient refs missing: " + str(dd[0]))

    return recipient_ref, contact_ref, phone_norm, name_string


def np_create_ttn_for_order(woo_id: int):
    """Create Nova Poshta waybill (TTN) for given CRM order.

    Persists fields: ttn_number, ttn_error, ttn_created_at.
    """
    row = db.get_order_by_woo_id(int(woo_id))
    if not row:
        raise RuntimeError("Order not found")
    order = dict(row)

    if _np_safe_strip(order.get("ttn_number")):
        return {"ttn_number": order.get("ttn_number"), "already": True}

    if normalize_status(order.get("status")) != "ttn":
        return {"skipped": True, "reason": "status_not_ttn"}

    if _np_safe_strip(order.get("delivery_service")).lower() != "np":
        return {"skipped": True, "reason": "not_np_delivery"}

    _np_ensure_sender_config()

    city_ref = _np_safe_strip(order.get("city_ref"))
    wh_ref = _np_safe_strip(order.get("warehouse_ref"))
    if not city_ref or not wh_ref:
        raise RuntimeError("NP: missing city_ref/warehouse_ref")

    items_rows = db.get_order_items(int(woo_id))
    items = [dict(r) for r in items_rows]
    internal_num = _np_build_internal_number(items)

    try:
        amount = float(order.get("amount") or 0)
    except Exception:
        amount = 0.0

    service_type = _np_detect_service_type(order)
    ps = _np_safe_strip(order.get("payment_state")).lower()
    is_cod = ps == "cod"

    # COD is often unavailable for Postomat deliveries.
    # Behavior: auto-disable COD for postomat to allow TTN creation.
    if is_cod and service_type == "WarehousePostomat":
        is_cod = False

    recipient_ref, recipient_contact_ref, recipient_phone_norm, recipient_name = _np_get_or_create_recipient(order)
    sender_phone_norm = _np_normalize_phone(NP_SENDER_PHONE)
    if not sender_phone_norm:
        raise RuntimeError("NP: sender phone invalid")

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "InternetDocument",
        "calledMethod": "save",
        "methodProperties": {
            "PayerType": "Recipient",
            "PaymentMethod": "Cash",
            "DateTime": time.strftime("%d.%m.%Y"),
            "CargoType": "Cargo",
            "Weight": "1",
            "ServiceType": service_type,
            "SeatsAmount": "1",
            "Description": NP_CARGO_DESCRIPTION,
            "Cost": str(int(round(amount))) if amount else "1",
            "CitySender": NP_SENDER_CITY_REF,
            "Sender": NP_SENDER_REF,
            "SenderAddress": NP_SENDER_ADDRESS_REF,
            "ContactSender": NP_SENDER_CONTACT_REF,
            "SendersPhone": sender_phone_norm,
            "CityRecipient": city_ref,
            "RecipientAddress": wh_ref,
            "RecipientType": "PrivatePerson",
            "Recipient": recipient_ref,
            "ContactRecipient": recipient_contact_ref,
            "RecipientsPhone": recipient_phone_norm,
            "RecipientName": recipient_name,
            "InfoRegClientBarcodes": internal_num,
            "OptionsSeat": [{"volumetricWidth": 12, "volumetricLength": 20, "volumetricHeight": 5, "weight": 1}],
        },
    }

    # Remove optional None keys (NP is picky)
    mp = payload["methodProperties"]
    for k in list(mp.keys()):
        if mp[k] is None:
            mp.pop(k, None)

    # "Контроль оплати" in NP is enabled via AfterpaymentOnGoodsCost (per NP API docs).
    # NP may also require MoneyTransfer flag to be enabled for financial services.
    # For CRM payment_state=cod we pass the amount as an integer string.
    if is_cod and amount:
        try:
            mp["AfterpaymentOnGoodsCost"] = str(int(round(float(amount))))
        except Exception:
            mp["AfterpaymentOnGoodsCost"] = str(int(round(amount)))
        mp["MoneyTransfer"] = 1

    if is_cod and amount:
        mp["BackwardDeliveryData"] = [
            {
                "PayerType": "Recipient",
                "CargoType": "Money",
                "RedeliveryString": str(int(round(amount))),
            }
        ]

    data = _np_post(payload)
    if not data.get("success"):
        errs = data.get("errors")
        # Fallback: if COD is unavailable for this delivery, retry once without BackwardDeliveryData.
        if is_cod and errs:
            handled = False
            try:
                err_text = " ".join([str(x) for x in (errs if isinstance(errs, list) else [errs])])
            except Exception:
                err_text = str(errs)
            # If NP says we didn't enable financial service, retry once ensuring flags are set.
            if "only moneytransfer or afterpayment enable" in (err_text or "").lower():
                # Retry #1: enforce canonical formats.
                try:
                    mp["AfterpaymentOnGoodsCost"] = str(int(round(float(amount))))
                except Exception:
                    mp["AfterpaymentOnGoodsCost"] = str(int(round(amount)))
                mp["MoneyTransfer"] = "1"
                data = _np_post(payload)
                if not data.get("success"):
                    # Retry #2: enable payment control only (per NP example) without BackwardDeliveryData.
                    mp.pop("BackwardDeliveryData", None)
                    mp.pop("MoneyTransfer", None)
                    data = _np_post(payload)
                    if not data.get("success"):
                        raise RuntimeError(
                            "NP error: "
                            + str(data.get("errors") or data)
                            + " | debug: AfterpaymentOnGoodsCost="
                            + str(mp.get("AfterpaymentOnGoodsCost"))
                            + ", has_BackwardDeliveryData="
                            + str("BackwardDeliveryData" in mp)
                        )
                handled = True

            if (not handled) and ("післяплата недоступна" in (err_text or "").lower()):
                mp.pop("BackwardDeliveryData", None)
                mp.pop("AfterpaymentOnGoodsCost", None)
                mp.pop("MoneyTransfer", None)
                data = _np_post(payload)
                if not data.get("success"):
                    raise RuntimeError("NP error: " + str(data.get("errors") or data))
                handled = True

            if not handled:
                raise RuntimeError("NP error: " + str(errs or data))
        else:
            raise RuntimeError("NP error: " + str(errs or data))

    dd = (data.get("data") or [])
    if not dd or not isinstance(dd, list) or not isinstance(dd[0], dict):
        raise RuntimeError("NP unexpected response: " + str(data))
    ttn = _np_safe_strip(dd[0].get("IntDocNumber"))
    if not ttn:
        raise RuntimeError("NP did not return IntDocNumber: " + str(dd[0]))

    db.update_order_fields(
        int(woo_id),
        {
            "ttn_number": ttn,
            "ttn_error": "",
            "ttn_created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return {"ttn_number": ttn, "already": False}


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
    "no_answer": {"label": "Не додзвонилися", "class": "badge--no-answer"},
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
    if sl in ("no_answer", "no-answer", "na", "nedozvonilisya", "nedozvonylasia"):
        return "no_answer"
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
    if s in ("Не додзвонилися", "Недозвонилися", "Не дозвонились", "Недозвонились"):
        return "no_answer"
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
@login_required
def index():
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()

    auto_sync_latest = (os.environ.get("CRM_AUTO_SYNC_LATEST") or "0").strip() == "1"
    if auto_sync_latest and (not date_from and not date_to):
        if _SYNC_LOCK.acquire(blocking=False):
            try:
                global _LAST_SYNC_AT, _LAST_SYNC_ERROR
                _LAST_SYNC_ERROR = None
                from sync import sync_orders
                sync_orders()
                _LAST_SYNC_AT = time.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                _LAST_SYNC_ERROR = str(e)
            finally:
                _SYNC_LOCK.release()

    try:
        page = int((request.args.get("page") or "1").strip() or "1")
    except Exception:
        page = 1
    if page < 1:
        page = 1

    per_page = 100
    offset = (page - 1) * per_page

    total_count = db.count_orders_filtered(date_from or None, date_to or None)
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * per_page

    raw_orders = db.list_orders_filtered(
        date_from or None,
        date_to or None,
        limit=per_page,
        offset=offset,
    )
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

        order["amount_display"] = format_amount_display(order.get("amount"))

        if not (order.get("delivery_service") or "").strip():
            if (order.get("city_ref") or "").strip() or (order.get("warehouse_ref") or "").strip():
                order["delivery_service"] = "np"
            else:
                sm = (order.get("shipping_method") or "").lower()
                if "ukr" in sm or "укр" in sm or "up" in sm:
                    order["delivery_service"] = "ukr"
                elif "nova" in sm or "np" in sm:
                    order["delivery_service"] = "np"
                else:
                    order["delivery_service"] = "np"

        wid = order.get("woo_id")
        order["products_display"] = format_products_for_table(
            items_by_woo.get(wid, []),
            order.get("product")
        )
        orders.append(order)

    return render_template(
        "index.html",
        orders=orders,
        status_badges=STATUS_BADGES,
        date_from=date_from,
        date_to=date_to,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        last_sync_at=_LAST_SYNC_AT,
        last_sync_error=_LAST_SYNC_ERROR,
        last_status_sync_at=_LAST_STATUS_SYNC_AT,
        last_status_sync_error=_LAST_STATUS_SYNC_ERROR,
    )


@app.post("/order/<int:woo_id>/status")
def update_order_status_inline(woo_id: int):
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    status_code = (payload.get("status") or request.form.get("status") or "").strip()
    status_code = normalize_status(status_code)

    if status_code not in STATUS_BADGES:
        return jsonify({"error": "Invalid status"}), 400

    try:
        db.update_status(woo_id, status_code)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    ttn_number = None
    ttn_error = ""
    if status_code == "ttn":
        try:
            # clear previous error before attempt
            db.update_order_fields(int(woo_id), {"ttn_error": ""})
            res = np_create_ttn_for_order(int(woo_id))
            ttn_number = res.get("ttn_number")
        except Exception as e:
            ttn_error = str(e)
            try:
                db.update_order_fields(int(woo_id), {"ttn_error": ttn_error})
            except Exception:
                pass

    woo_status_sent = None
    woo_error = ""
    try:
        woo_status_sent = _woo_sync_status_single(int(woo_id), status_code)
    except Exception as e:
        woo_error = (str(e) or "")[:500]

    badge = STATUS_BADGES.get(status_code, STATUS_BADGES["new"])
    return jsonify(
        {
            "woo_id": woo_id,
            "status_code": status_code,
            "status_label": badge.get("label"),
            "status_class": badge.get("class"),
            "ttn_number": ttn_number,
            "ttn_error": ttn_error,
            "woo_status": woo_status_sent,
            "woo_error": woo_error,
        }
    )


@app.post("/orders/status_bulk")
def update_orders_status_bulk():
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    woo_ids = payload.get("woo_ids") or []
    status_code = (payload.get("status") or "").strip()
    status_code = normalize_status(status_code)

    if status_code not in STATUS_BADGES:
        return jsonify({"error": "Invalid status"}), 400

    try:
        ids = [int(x) for x in woo_ids if str(x).strip() != ""]
    except Exception:
        return jsonify({"error": "Invalid woo_ids"}), 400

    if not ids:
        return jsonify({"updated": []})

    try:
        db.update_status_bulk(ids, status_code)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    ttn_errors = {}
    if status_code == "ttn":
        for wid in ids:
            try:
                db.update_order_fields(int(wid), {"ttn_error": ""})
                np_create_ttn_for_order(int(wid))
            except Exception as e:
                msg = str(e)
                ttn_errors[str(wid)] = msg
                try:
                    db.update_order_fields(int(wid), {"ttn_error": msg})
                except Exception:
                    pass

    badge = STATUS_BADGES.get(status_code, STATUS_BADGES["new"])
    updated = []
    for wid in ids:
        updated.append(
            {
                "woo_id": wid,
                "status_code": status_code,
                "status_label": badge.get("label"),
                "status_class": badge.get("class"),
            }
        )

    woo_ok = 0
    woo_error = ""
    try:
        woo_ok = _woo_sync_status_bulk(ids, status_code)
    except Exception as e:
        woo_error = (str(e) or "")[:500]

    return jsonify({"updated": updated, "ttn_errors": ttn_errors, "woo_ok": woo_ok, "woo_error": woo_error})


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


@app.get("/woo/statuses")
@login_required
def woo_statuses():
    try:
        woo_id = (request.args.get("id") or "").strip()
        if not woo_id:
            return jsonify({"error": "Missing id"}), 400
        try:
            wid = int(woo_id)
        except Exception:
            return jsonify({"error": "Invalid id"}), 400

        o = woo_api.get_order(wid)
        return jsonify({
            "id": o.get("id"),
            "status": o.get("status"),
            "status_label": o.get("status"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/sync_range")
def sync_range_now():
    global _LAST_SYNC_AT, _LAST_SYNC_ERROR

    date_from = (request.form.get("date_from") or "").strip()
    date_to = (request.form.get("date_to") or "").strip()

    if not _SYNC_LOCK.acquire(blocking=False):
        return "Синхронизация уже выполняется", 409

    try:
        _LAST_SYNC_ERROR = None

        del_ok = 0
        del_failed = 0
        pending_del = db.list_pending_woo_deletes(limit=500)
        for r in pending_del:
            try:
                wid = int(r["woo_id"])
            except Exception:
                continue
            try:
                woo_api.delete_order(wid, force=True)
                db.delete_pending_woo_delete(wid)
                del_ok += 1
            except Exception:
                del_failed += 1

        if (date_from or "").strip() or (date_to or "").strip():
            from sync import sync_orders_range
            sync_orders_range(date_from or None, date_to or None)
        else:
            from sync import sync_orders
            sync_orders()
        _LAST_SYNC_AT = time.strftime("%Y-%m-%d %H:%M:%S") + f" (del_ok={del_ok}, del_fail={del_failed})"
    except Exception as e:
        _LAST_SYNC_ERROR = str(e)
    finally:
        _SYNC_LOCK.release()

    return redirect(url_for("index", date_from=date_from, date_to=date_to))


@app.post("/sync_statuses")
def sync_statuses_now():
    global _LAST_STATUS_SYNC_AT, _LAST_STATUS_SYNC_ERROR

    if not _STATUS_SYNC_LOCK.acquire(blocking=False):
        return "Синхронизация статусов уже выполняется", 409

    ok = 0
    failed = 0
    del_ok = 0
    del_failed = 0
    try:
        _LAST_STATUS_SYNC_ERROR = None

        started_at = time.time()

        pending_del = db.list_pending_woo_deletes(limit=500)
        for r in pending_del:
            try:
                wid = int(r["woo_id"])
            except Exception:
                continue
            try:
                woo_api.delete_order(wid, force=True)
                db.delete_pending_woo_delete(wid)
                del_ok += 1
            except Exception:
                del_failed += 1

        # Sync only latest orders (UI shows last 100)
        orders = db.list_orders()[:100]

        updates = []
        for o in orders:
            try:
                woo_id = int(o["woo_id"])
            except Exception:
                continue
            woo_status = map_crm_status_to_woo(o["status"])
            if not woo_status:
                continue
            updates.append({"id": woo_id, "status": woo_status})

        # Use Woo batch endpoint to reduce number of HTTP requests
        batch_size = 50
        for i in range(0, len(updates), batch_size):
            chunk = updates[i : i + batch_size]
            try:
                woo_api.update_orders_status_batch(chunk)
                ok += len(chunk)
            except Exception:
                failed += len(chunk)

        elapsed = round(time.time() - started_at, 2)
        _LAST_STATUS_SYNC_AT = (
            time.strftime("%Y-%m-%d %H:%M:%S")
            + f" (del_ok={del_ok}, del_fail={del_failed}, ok={ok}, fail={failed}, sec={elapsed})"
        )
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


@app.get("/np/debug/city_warehouse_refs")
@login_required
def np_debug_city_warehouse_refs():
    """Helper endpoint to find CityRef + WarehouseRef by human input.

    Example:
      /np/debug/city_warehouse_refs?city=Київ&warehouse=710
    """
    if not NP_API_KEY:
        return jsonify({"error": "NP_API_KEY is not set"}), 500

    city = (request.args.get("city") or "").strip()
    wh = (request.args.get("warehouse") or "").strip()
    if not city:
        return jsonify({"error": "Missing city"}), 400

    payload_city = {
        "apiKey": NP_API_KEY,
        "modelName": "AddressGeneral",
        "calledMethod": "getCities",
        "methodProperties": {"FindByString": city, "Limit": 20},
    }
    data_city = _np_post(payload_city)
    if not data_city.get("success"):
        return jsonify({"error": data_city.get("errors") or "NP error", "raw": data_city}), 502

    cities = []
    for c in data_city.get("data", []) or []:
        cities.append({
            "ref": c.get("Ref"),
            "name": c.get("Description") or c.get("DescriptionRu") or "",
            "area": c.get("AreaDescription") or "",
            "region": c.get("RegionsDescription") or "",
        })

    # Pick best city match
    city_ref = ""
    city_low = city.lower()
    for c in cities:
        if (c.get("name") or "").strip().lower() == city_low:
            city_ref = c.get("ref") or ""
            break
    if not city_ref and cities:
        city_ref = cities[0].get("ref") or ""

    res = {
        "city_input": city,
        "city_ref": city_ref,
        "cities": cities,
        "warehouse_input": wh,
        "warehouse_ref": "",
        "warehouses": [],
    }

    if city_ref:
        payload_wh = {
            "apiKey": NP_API_KEY,
            "modelName": "AddressGeneral",
            "calledMethod": "getWarehouses",
            "methodProperties": {
                "CityRef": city_ref,
                "FindByString": wh or "",
                "Limit": 100,
            },
        }
        data_wh = _np_post(payload_wh)
        if data_wh.get("success"):
            warehouses = []
            for w in data_wh.get("data", []) or []:
                warehouses.append({
                    "ref": w.get("Ref"),
                    "name": w.get("Description") or w.get("DescriptionRu") or "",
                    "number": w.get("Number") or "",
                    "type": w.get("CategoryOfWarehouse") or w.get("TypeOfWarehouse") or "",
                })
            res["warehouses"] = warehouses
            if wh:
                wh_low = wh.strip().lower()
                for w in warehouses:
                    if (w.get("number") or "").strip().lower() == wh_low:
                        res["warehouse_ref"] = w.get("ref") or ""
                        break
            if not res["warehouse_ref"] and warehouses:
                res["warehouse_ref"] = warehouses[0].get("ref") or ""
        else:
            res["warehouses_error"] = data_wh.get("errors") or "NP error"
            res["warehouses_raw"] = data_wh

    return jsonify(res)


@app.get("/np/debug/sender_refs")
@login_required
def np_debug_sender_refs():
    """Helper endpoint to find Sender/ContactSender refs.

    Example:
      /np/debug/sender_refs?q=Трембицька
    """
    if not NP_API_KEY:
        return jsonify({"error": "NP_API_KEY is not set"}), 500

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "Missing q"}), 400

    payload_cp = {
        "apiKey": NP_API_KEY,
        "modelName": "Counterparty",
        "calledMethod": "getCounterparties",
        "methodProperties": {
            "CounterpartyProperty": "Sender",
            "Page": "1",
            "FindByString": q,
        },
    }
    data_cp = _np_post(payload_cp)
    if not data_cp.get("success"):
        return jsonify({"error": data_cp.get("errors") or "NP error", "raw": data_cp}), 502

    counterparties = []
    for c in data_cp.get("data", []) or []:
        counterparties.append({
            "ref": c.get("Ref"),
            "description": c.get("Description") or "",
            "first_name": c.get("FirstName") or "",
            "last_name": c.get("LastName") or "",
            "counterparty_type": c.get("CounterpartyType") or "",
        })

    # Also try to fetch contacts for the first match (for convenience)
    contacts = []
    cp_ref = (counterparties[0].get("ref") if counterparties else "")
    if cp_ref:
        payload_contacts = {
            "apiKey": NP_API_KEY,
            "modelName": "Counterparty",
            "calledMethod": "getCounterpartyContactPersons",
            "methodProperties": {"Ref": cp_ref, "Page": "1"},
        }
        data_contacts = _np_post(payload_contacts)
        if data_contacts.get("success"):
            for p in data_contacts.get("data", []) or []:
                contacts.append({
                    "ref": p.get("Ref"),
                    "description": p.get("Description") or "",
                    "phones": p.get("Phones") or "",
                })
        else:
            contacts = [{"error": data_contacts.get("errors") or "NP error", "raw": data_contacts}]

    return jsonify({
        "query": q,
        "counterparties": counterparties,
        "first_counterparty_contacts": contacts,
    })


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
        status_code = normalize_status(status_code)

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

        if status_code == "ttn":
            try:
                db.update_order_fields(int(woo_id), {"ttn_error": ""})
                np_create_ttn_for_order(int(woo_id))
            except Exception as e:
                try:
                    db.update_order_fields(int(woo_id), {"ttn_error": str(e)})
                except Exception:
                    pass

        woo_err = ""
        try:
            _woo_sync_status_single(int(woo_id), status_code)
        except Exception as e:
            woo_err = (str(e) or "")[:500]
        if close_after_save:
            return redirect(url_for("index"))
        if woo_err:
            return redirect(url_for("order_card", woo_id=woo_id, saved=1, woo_err=woo_err))
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
    woo_err = (request.args.get("woo_err") or "").strip()

    return render_template(
        "order.html",
        o=o,
        items=items,
        status_badges=STATUS_BADGES,
        saved=saved,
        woo_err=woo_err,
        prev_woo_id=prev_woo_id,
        next_woo_id=next_woo_id,
    )


@app.route("/order/<int:woo_id>/delete", methods=["POST"])
def delete_order(woo_id: int):
    db.delete_order(woo_id)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
