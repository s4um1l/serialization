"""FoodDash Wire domain models — shared across all chapters.

These models represent inter-service messages in a food delivery platform
processing 1M messages/second across 20 microservices. They are intentionally
designed to stress-test serialization formats:

- Primitives: int, float, str, bool
- Large integers: platform_transaction_id > 2^53 (exposes JSON precision loss)
- Floats: latitude/longitude (exposes precision issues across formats)
- Strings: Unicode restaurant/menu names (exposes encoding issues)
- Enums: OrderStatus, PaymentMethod (exposes enum serialization differences)
- Collections: list of OrderItems, list of allergens, dict of metadata
- Nesting: Order → OrderItem → MenuItem (3 levels deep)
- Optional fields: driver_id, delivery_notes, promo_code
- Timestamps: float (Unix epoch)
- Binary data: thumbnail_png (bytes — exposes base64 overhead in JSON)
"""

from __future__ import annotations

import enum
import time
import uuid

from pydantic import BaseModel, Field


class OrderStatus(str, enum.Enum):
    PLACED = "placed"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    PICKED_UP = "picked_up"
    EN_ROUTE = "en_route"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


ORDER_FLOW = [
    OrderStatus.PLACED,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.PICKED_UP,
    OrderStatus.EN_ROUTE,
    OrderStatus.DELIVERED,
]


class PaymentMethod(str, enum.Enum):
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CASH = "cash"
    WALLET = "wallet"


class GeoPoint(BaseModel):
    """Latitude/longitude pair — tests float precision across formats."""

    latitude: float
    longitude: float


class MenuItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    price_cents: int
    description: str = ""
    category: str = ""
    is_vegetarian: bool = False
    allergens: list[str] = Field(default_factory=list)
    thumbnail_png: bytes = b""


class OrderItem(BaseModel):
    menu_item: MenuItem
    quantity: int = 1
    special_instructions: str = ""

    @property
    def subtotal_cents(self) -> int:
        return self.menu_item.price_cents * self.quantity


class Customer(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    email: str = ""
    phone: str = ""
    address: str = ""
    location: GeoPoint | None = None


class Driver(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    location: GeoPoint = Field(
        default_factory=lambda: GeoPoint(latitude=0.0, longitude=0.0)
    )
    available: bool = True
    rating: float = 5.0


class Restaurant(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    location: GeoPoint | None = None
    menu: list[MenuItem] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)
    logo_thumbnail: bytes = b""


class Order(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    platform_transaction_id: int = 0
    customer: Customer
    restaurant_id: str
    items: list[OrderItem]
    status: OrderStatus = OrderStatus.PLACED
    payment_method: PaymentMethod = PaymentMethod.CREDIT_CARD
    driver_id: str | None = None
    delivery_notes: str | None = None
    promo_code: str | None = None
    tip_cents: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    estimated_delivery_minutes: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def total_cents(self) -> int:
        return sum(item.subtotal_cents for item in self.items)
