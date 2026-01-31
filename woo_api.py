import requests
from config import WOO_URL, CONSUMER_KEY, CONSUMER_SECRET

def get_orders(per_page=100, page=1):
    url = f"{WOO_URL}/wp-json/wc/v3/orders"
    r = requests.get(
        url,
        auth=(CONSUMER_KEY, CONSUMER_SECRET),
        params={
            "per_page": per_page,
            "page": page,
            "status": "any",
            "orderby": "date",
            "order": "desc",
        }
    )
    r.raise_for_status()
    return r.json()


def update_order_status(order_id: int, status: str):
    url = f"{WOO_URL}/wp-json/wc/v3/orders/{int(order_id)}"
    r = requests.put(
        url,
        auth=(CONSUMER_KEY, CONSUMER_SECRET),
        json={"status": status},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def update_orders_status_batch(updates: list[dict]):
    """Batch update orders in WooCommerce.

    updates: list of dicts like {"id": 123, "status": "processing"}
    """
    url = f"{WOO_URL}/wp-json/wc/v3/orders/batch"
    r = requests.post(
        url,
        auth=(CONSUMER_KEY, CONSUMER_SECRET),
        json={"update": updates},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def get_products(per_page=50, search=None):
    url = f"{WOO_URL}/wp-json/wc/v3/products"
    params = {
        "per_page": per_page,
        "status": "publish",
    }
    if search:
        params["search"] = search

    r = requests.get(
        url,
        auth=(CONSUMER_KEY, CONSUMER_SECRET),
        params=params
    )
    r.raise_for_status()
    return r.json()
