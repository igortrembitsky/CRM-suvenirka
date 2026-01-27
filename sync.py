from woo_api import get_orders
import db
db.set_db_path("crm.db")
db.init_db()
def sync_orders():
    orders = get_orders(20)
    for o in orders:
        db.create_order({
    "customer_name": f"{o['billing']['first_name']} {o['billing']['last_name']}",
    "phone": o["billing"]["phone"],
    "city": o["billing"]["city"],
    "address": o["billing"]["address_1"],
    "amount": o["total"],
    "status": o["status"],
    "comment": f"Woo order #{o['id']}"
})

if __name__ == "__main__":
    sync_orders()
    print("Orders synced")
