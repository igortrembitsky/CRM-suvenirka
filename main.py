from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import StringProperty

import db
from woo_api import get_orders


class OrdersListScreen(Screen):
    search_text = StringProperty("")
    status_filter = StringProperty("all")

    def on_pre_enter(self):
        self.refresh()

    def refresh(self):
        self.ids.orders_list.clear_widgets()

        rows = db.list_orders()

        if not rows:
            from kivy.uix.label import Label
            self.ids.orders_list.add_widget(
                Label(text="Нет заказов", size_hint_y=None, height=40)
            )
            return

        from kivy.uix.button import Button

        for r in rows:
            text = f"#{r['woo_id']} | {r['customer_name']} | {r['phone']}"

            btn = Button(
                text=text,
                size_hint_y=None,
                height=48,
                on_release=lambda x, woo_id=r["woo_id"]: self.open_order(woo_id)
            )

            self.ids.orders_list.add_widget(btn)

    def open_order(self, woo_id):
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button

        order = db.get_order_by_woo_id(int(woo_id))
        if not order:
            layout = BoxLayout(orientation="vertical", padding=10, spacing=10)
            layout.add_widget(Label(text="Заказ не найден"))
            close_btn = Button(text="Закрыть", size_hint_y=None, height=40)
            layout.add_widget(close_btn)

            popup = Popup(
                title="Карточка заказа",
                content=layout,
                size_hint=(0.9, 0.9)
            )

            close_btn.bind(on_release=popup.dismiss)
            popup.open()
            return

        layout = BoxLayout(orientation="vertical", padding=10, spacing=10)

        layout.add_widget(Label(text=f"Заказ №{order['woo_id']}"))
        layout.add_widget(Label(text=f"Клиент: {order['customer_name']}"))
        layout.add_widget(Label(text=f"Телефон: {order['phone']}"))
        layout.add_widget(Label(text=f"Город: {order['city']}"))
        layout.add_widget(Label(text=f"Адрес: {order['address']}"))
        layout.add_widget(Label(text=f"Товар: {order['product']}"))
        layout.add_widget(Label(text=f"Оплата: {order['payment_method']}"))
        layout.add_widget(Label(text=f"Сумма: {order['amount']} грн"))
        layout.add_widget(Label(text=f"Статус: {order['status']}"))

        close_btn = Button(text="Закрыть", size_hint_y=None, height=40)
        layout.add_widget(close_btn)

        popup = Popup(
            title="Карточка заказа",
            content=layout,
            size_hint=(0.9, 0.9)
        )

        close_btn.bind(on_release=popup.dismiss)
        popup.open()

    def apply_filter(self):
        self.refresh()

    def go_create(self):
        print("Создание заказа позже сделаем 🙂")


class CRMApp(App):
    def build(self):
        Builder.load_file("crm.kv")
        sm = ScreenManager()
        sm.add_widget(OrdersListScreen(name="orders"))
        return sm

    def refresh_all(self):
        try:
            from sync import sync_orders
            sync_orders()
        except Exception as e:
            print("Ошибка обновления заказов:", e)

        try:
            screen = self.root.get_screen("orders")
            screen.refresh()
        except Exception as e:
            print("Ошибка обновления интерфейса:", e)


if __name__ == "__main__":
    CRMApp().run()
