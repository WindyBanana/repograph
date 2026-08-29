"""Persistence for orders."""

from shared.models import Order

from ..db import connect


class OrderRepository:
    """Reads and writes orders in PostgreSQL."""

    def get(self, order_id: str):
        cursor = connect().cursor()
        cursor.execute("SELECT id, customer_id, status FROM orders WHERE id = %s", (order_id,))
        return cursor.fetchone()

    def save(self, order: Order) -> None:
        cursor = connect().cursor()
        cursor.execute(
            "INSERT INTO orders (id, customer_id, status) VALUES (%s, %s, %s)",
            (order.id, order.customer_id, order.status),
        )
