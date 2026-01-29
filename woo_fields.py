"""
Единый источник полей WooCommerce → CRM
Используется как карта структуры заказа Woo
"""

# =====================================================
# ОСНОВНЫЕ ПОЛЯ ЗАКАЗА
# =====================================================

ORDER_FIELDS = {
    "woo_id": "id",
    "status": "status",
    "total": "total",
    "currency": "currency",
    "created_at": "date_created",
    "payment_method_id": "payment_method",
    "payment_method_title": "payment_method_title",
    "customer_note": "customer_note"
}

# =====================================================
# BILLING (ПЛАТЕЛЬЩИК)
# =====================================================

BILLING_FIELDS = {
    "first_name": "billing.first_name",
    "last_name": "billing.last_name",
    "company": "billing.company",
    "phone": "billing.phone",
    "email": "billing.email"
}

# =====================================================
# SHIPPING (АДРЕС)
# =====================================================

SHIPPING_FIELDS = {
    "first_name": "shipping.first_name",
    "last_name": "shipping.last_name",
    "company": "shipping.company",
    "city": "shipping.city",
    "address": "shipping.address_1",
    "postcode": "shipping.postcode",
    "country": "shipping.country"
}

# =====================================================
# SHIPPING LINE (СПОСОБ ДОСТАВКИ)
# =====================================================

SHIPPING_LINE_FIELDS = {
    "method_title": "shipping_lines[0].method_title",
    "method_id": "shipping_lines[0].method_id",
    "total": "shipping_lines[0].total"
}

# =====================================================
# META DATA (Новая Почта / Укрпошта)
# =====================================================

META_KEYS = {
    "city_name": "wcus_city_name",
    "city_ref": "wcus_city_ref",
    "warehouse_ref": "wcus_warehouse_ref",
    "warehouse_name": "wcus_warehouse_name",
    "positions": "Позиції"
}

# =====================================================
# LINE ITEMS (ТОВАРЫ)
# =====================================================

LINE_ITEM_FIELDS = {
    "name": "line_items[0].name",
    "quantity": "line_items[0].quantity",
    "product_id": "line_items[0].product_id",
    "sku": "line_items[0].sku",
    "price": "line_items[0].price",
    "total": "line_items[0].total"
}

# =====================================================
# ВОЗМОЖНЫЕ СТАТУСЫ WOO
# =====================================================

WOO_STATUSES = [
    "pending",
    "processing",
    "completed",
    "cancelled",
    "failed",
    "on-hold",
    "checkout-draft",
    "refunded",
    "trash"
]

# =====================================================
# ВОЗМОЖНЫЕ СПОСОБЫ ОПЛАТЫ
# =====================================================

PAYMENT_METHODS = [
    "cod",
    "liqpay",
    "wayforpay",
    "bacs",
    "stripe",
    "paypal"
]
