"""HTTP routes for orders."""

from fastapi import APIRouter, HTTPException

from shared.models import Order

from ..services.order_service import OrderService

router = APIRouter()
service = OrderService()


@router.get("/orders/{order_id}")
def get_order(order_id: str):
    """Fetch a single order."""
    order = service.repository.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@router.post("/orders")
def create_order(payload: dict):
    """Create an order and take payment."""
    if not payload.get("customer_id"):
        raise HTTPException(status_code=400, detail="customer_id is required")
    order = Order(id=payload["id"], customer_id=payload["customer_id"])
    return service.create(order)


@router.delete("/orders/{order_id}")
def cancel_order(order_id: str):
    """Cancel an order."""
    return {"cancelled": order_id}
