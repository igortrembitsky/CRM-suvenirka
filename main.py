# main.py
from kivy.lang import Builder
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.app import App
from kivy.uix.popup import Popup
from kivy.uix.label import Label

from settings import APP_NAME
import db


class OrdersListScreen(Screen):
    search_text = StringProperty("")
    status_filter = StringProperty("all")

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        self.ids.orders_list.clear_widgets()
        rows = db.list_orders(search=self.search_text, status=self.status_filter)

        for r in rows:
            status = r["status"]
            summary = f"#{r['id']}  {r['customer_name']}  {r['phone']}  | {status.upper()} | {r['amount']} грн"

            btn = Builder.load_string(f"""
Button:
    text: "{summary.replace('"', "'")}"
    size_hint_y: None
    height: "46dp"
    halign: "left"
    valign: "middle"
    text_size: self.size
""")
            btn.bind(on_release=lambda x, oid=r["id"]: self.open_order(oid))
            self.ids.orders_list.add_widget(btn)

    def open_order(self, order_id: int):
        app = App.get_running_app()
        app.current_order_id = order_id
        app.root.current = "detail"

    def go_create(self):
        App.get_running_app().root.current = "create"

    def apply_filter(self):
        self.search_text = self.ids.search_input.text
        self.status_filter = self.ids.status_spinner.text
        self.refresh()


class OrderCreateScreen(Screen):
    def save(self):
        name = self.ids.in_name.text.strip()
        phone = self.ids.in_phone.text.strip()

        if not name or not phone:
            Popup(title="Ошибка",
                  content=Label(text="Заполни ФИО и телефон"),
                  size_hint=(0.8, 0.3)).open()
            return

        data = {
            "customer_name": name,
            "phone": phone,
            "city": self.ids.in_city.text,
            "address": self.ids.in_address.text,
            "amount": self.ids.in_amount.text,
            "status": "new",
            "comment": self.ids.in_comment.text,
        }
        new_id = db.create_order(data)

        for wid in ("in_name", "in_phone", "in_city", "in_address", "in_amount", "in_comment"):
            self.ids[wid].text = ""

        app = App.get_running_app()
        app.current_order_id = new_id
        app.root.current = "detail"


class OrderDetailScreen(Screen):
    order_id = NumericProperty(0)

    def on_pre_enter(self, *args):
        app = App.get_running_app()
        self.order_id = int(getattr(app, "current_order_id", 0) or 0)
        self.load_order()

    def load_order(self):
        row = db.get_order(self.order_id)
        if not row:
            return

        self.ids.lbl_id.text = f"Заказ #{row['id']} от {row['created_at'][:19].replace('T',' ')}"
        self.ids.lbl_name.text = row["customer_name"]
        self.ids.lbl_phone.text = row["phone"]
        self.ids.lbl_city.text = row["city"] or "-"
        self.ids.lbl_address.text = row["address"] or "-"
        self.ids.lbl_amount.text = f"{row['amount']} грн"
        self.ids.lbl_comment.text = row["comment"] or "-"
        self.ids.status_spinner.text = row["status"]
        self.ids.lbl_ttn.text = row["ttn_number"] or "ТТН нет"

    def save_status(self):
        status = self.ids.status_spinner.text
        db.update_order_status(self.order_id, status)
        Popup(title="OK", content=Label(text="Статус сохранён"), size_hint=(0.7, 0.25)).open()
        self.load_order()


class CRMApp(App):
    current_order_id = 0

    def build(self):
        self.title = APP_NAME

        # ✅ путь базы: работает и на ПК, и на Android
        db_path = f"{self.user_data_dir}/crm.sqlite3"
        db.set_db_path(db_path)
        db.init_db()

        Builder.load_file("crm.kv")

        sm = ScreenManager()
        sm.add_widget(OrdersListScreen(name="list"))
        sm.add_widget(OrderCreateScreen(name="create"))
        sm.add_widget(OrderDetailScreen(name="detail"))
        return sm


if __name__ == "__main__":
    CRMApp().run()