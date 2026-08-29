"""Order use cases."""

import json

import redis
import requests
import stripe

from shared.events import ORDER_CREATED, OrderCreated
from shared.models import Order

from ..config import PAYMENT_API_SECRET, REDIS_URL, SHIPPING_API
from ..repositories.order_repository import OrderRepository

cache = redis.Redis.from_url(REDIS_URL)
stripe.api_key = PAYMENT_API_SECRET


class OrderService:
    """Creates orders, takes payment and publishes the resulting event."""

    def __init__(self) -> None:
        self.repository = OrderRepository()

    def create(self, order: Order) -> Order:
        if not order.lines:
            raise ValueError("an order needs at least one line")
        charge = stripe.Charge.create(amount=int(order.total * 100), currency="nok")
        order.status = "paid" if charge else "pending"
        self.repository.save(order)
        cache.set(f"order:{order.id}", json.dumps({"status": order.status}))
        self.publish(OrderCreated(order.id, order.customer_id, order.total))
        return order

    def publish(self, event: OrderCreated) -> None:
        from kafka import KafkaProducer

        producer = KafkaProducer(bootstrap_servers="broker:9092")
        producer.send(ORDER_CREATED, json.dumps(event.__dict__).encode())

    def request_shipment(self, order_id: str):
        return requests.post(f"{SHIPPING_API}/shipments", json={"order": order_id}, verify=False)
