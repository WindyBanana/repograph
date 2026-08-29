"""Invoice storage in S3."""

import boto3

BUCKET = "acme-invoices"
client = boto3.client("s3")


def store_invoice(order_id: str, reference: str) -> str:
    key = f"invoices/{order_id}.pdf"
    client.put_object(Bucket=BUCKET, Key=key, Body=reference.encode())
    return key
