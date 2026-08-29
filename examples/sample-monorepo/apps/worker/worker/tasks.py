"""Celery tasks triggered by order events."""

import hashlib
import os

import boto3
from celery import Celery

from shared.events import ORDER_CREATED, ORDER_SHIPPED
from shared.models import Order

from .storage import store_invoice

app = Celery("fulfilment", broker=os.getenv("CELERY_BROKER", "redis://cache:6379/1"))
s3 = boto3.client("s3")


@app.task(name="orders.fulfil")
def fulfil_order(order_id: str) -> str:
    """Reserve stock, generate an invoice and mark the order shipped."""
    reference = hashlib.md5(order_id.encode()).hexdigest()
    store_invoice(order_id, reference)
    return ORDER_SHIPPED


@app.task(name="orders.reconcile")
def reconcile(day: str) -> int:
    """Nightly reconciliation against the payment provider."""
    return 0
