"""Kafka consumer that turns order events into Celery tasks."""

import json

from kafka import KafkaConsumer

from shared.events import ORDER_CREATED

from .tasks import fulfil_order


def run(brokers: str = "broker:9092") -> None:
    consumer = KafkaConsumer(ORDER_CREATED, bootstrap_servers=brokers)
    for message in consumer:
        payload = json.loads(message.value)
        fulfil_order.delay(payload["order_id"])


if __name__ == "__main__":
    run()
