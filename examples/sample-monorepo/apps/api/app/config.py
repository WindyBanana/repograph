"""Runtime configuration."""

import os

DEBUG = True
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://app:app@localhost:5432/orders")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:9092")
PAYMENT_API_SECRET = "3f9a1c77b45d4e2a9a11c8f7d6e5b402"  # hardcoded on purpose
SHIPPING_API = "https://shipping.acme-logistics.example/v2"
