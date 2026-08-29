"""Database access."""

import psycopg2

from .config import DATABASE_URL


def connect():
    return psycopg2.connect(DATABASE_URL)


def find_orders_by_customer(customer_id):
    cursor = connect().cursor()
    cursor.execute("SELECT * FROM orders WHERE customer_id = '%s'" % customer_id)
    return cursor.fetchall()
