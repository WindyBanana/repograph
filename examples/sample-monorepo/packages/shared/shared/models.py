"""Order domain models shared by the API and the worker."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class OrderLine:
    sku: str
    quantity: int
    unit_price: float


@dataclass
class Order:
    """An order as it moves through the system."""

    id: str
    customer_id: str
    lines: List[OrderLine] = field(default_factory=list)
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total(self) -> float:
        return sum(line.quantity * line.unit_price for line in self.lines)
