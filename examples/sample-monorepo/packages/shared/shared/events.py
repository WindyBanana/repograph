"""Event contracts published to Kafka."""

from dataclasses import dataclass

ORDER_CREATED = "orders.created"
ORDER_PAID = "orders.paid"
ORDER_SHIPPED = "orders.shipped"


@dataclass
class OrderCreated:
    order_id: str
    customer_id: str
    total: float

    topic = ORDER_CREATED
