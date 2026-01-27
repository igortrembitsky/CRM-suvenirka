import requests
from config import WOO_URL, CONSUMER_KEY, CONSUMER_SECRET

def get_orders(per_page=100):
    url = f"{WOO_URL}/wp-json/wc/v3/orders"
    r = requests.get(
        url,
        auth=(CONSUMER_KEY, CONSUMER_SECRET),
        params={"per_page": per_page}
    )
    r.raise_for_status()
    return r.json()
