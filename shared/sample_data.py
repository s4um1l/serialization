"""Deterministic test data factories for reproducible benchmarks.

Every function returns the same data every time — no randomness.
This ensures benchmark results are comparable across runs.
"""

from shared.models import (
    Customer,
    Driver,
    GeoPoint,
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    Restaurant,
)


# -- Canonical restaurant with a realistic menu --

BURGER_PALACE = Restaurant(
    id="rest0001",
    name="Börgér Palace 🍔",  # Unicode + emoji: encoding stress test
    location=GeoPoint(latitude=40.748817, longitude=-73.985428),
    menu=[
        MenuItem(
            id="menu0001",
            name="Classic Smash Burger",
            price_cents=1299,
            description="Two 4oz patties, American cheese, pickles, onion, secret sauce",
            category="main",
            allergens=["gluten", "dairy"],
            thumbnail_png=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,  # fake PNG header + padding
        ),
        MenuItem(
            id="menu0002",
            name="Spicy Tüñá Roll",  # diacritics: encoding stress test
            price_cents=1599,
            description="Fresh tuna, sriracha mayo, avocado, crispy shallots",
            category="main",
            is_vegetarian=False,
            allergens=["fish", "gluten", "soy"],
            thumbnail_png=b"\x89PNG\r\n\x1a\n" + b"\xff" * 48,
        ),
        MenuItem(
            id="menu0003",
            name="Truffle Fries",
            price_cents=899,
            description="Hand-cut fries, truffle oil, parmesan, fresh herbs",
            category="appetizer",
            is_vegetarian=True,
            allergens=["dairy"],
        ),
        MenuItem(
            id="menu0004",
            name="Matcha Milkshake",
            price_cents=799,
            description="Organic matcha, vanilla ice cream, oat milk",
            category="drink",
            is_vegetarian=True,
            allergens=["dairy"],
        ),
    ],
    tags={"cuisine": "american", "price_range": "$$", "delivery_radius_km": "5"},
)

CUSTOMER_ALICE = Customer(
    id="cust0001",
    name="Alice Nakamura",
    email="alice@example.com",
    phone="+1-555-0101",
    address="350 5th Ave, New York, NY 10118",
    location=GeoPoint(latitude=40.748817, longitude=-73.985428),
)

DRIVER_BOB = Driver(
    id="driv0001",
    name="Bob García",
    location=GeoPoint(latitude=40.752, longitude=-73.978),
    available=True,
    rating=4.8,
)


def make_small_order() -> Order:
    """1 item, minimal fields. Tests baseline payload size."""
    return Order(
        id="ord00001",
        platform_transaction_id=1001,
        customer=Customer(id="cust0001", name="Alice"),
        restaurant_id="rest0001",
        items=[
            OrderItem(menu_item=MenuItem(id="menu0001", name="Burger", price_cents=1299)),
        ],
        created_at=1700000000.0,
        updated_at=1700000000.0,
    )


def make_typical_order() -> Order:
    """3 items, driver assigned, notes, promo code. Realistic everyday order."""
    return Order(
        id="ord00002",
        platform_transaction_id=123456789,
        customer=CUSTOMER_ALICE,
        restaurant_id="rest0001",
        items=[
            OrderItem(
                menu_item=BURGER_PALACE.menu[0],  # Classic Smash Burger
                quantity=2,
                special_instructions="No pickles on one",
            ),
            OrderItem(
                menu_item=BURGER_PALACE.menu[2],  # Truffle Fries
                quantity=1,
            ),
            OrderItem(
                menu_item=BURGER_PALACE.menu[3],  # Matcha Milkshake
                quantity=2,
            ),
        ],
        status=OrderStatus.EN_ROUTE,
        payment_method=PaymentMethod.CREDIT_CARD,
        driver_id="driv0001",
        delivery_notes="Ring doorbell twice, leave at door",
        promo_code="SAVE20",
        tip_cents=500,
        created_at=1700000000.0,
        updated_at=1700000300.0,
        estimated_delivery_minutes=25,
        metadata={
            "source": "mobile_app",
            "app_version": "4.2.1",
            "session_id": "sess_abc123",
        },
    )


def make_large_order() -> Order:
    """20 items, all optional fields, binary thumbnails, large transaction ID.

    The platform_transaction_id is set to 2^53 + 1 (9007199254740993) —
    this value cannot be represented exactly as a JavaScript number (IEEE 754
    double), which silently rounds it to 9007199254740992. This is a real
    production bug that has caused financial reconciliation failures.
    """
    items = []
    for i in range(20):
        items.append(
            OrderItem(
                menu_item=MenuItem(
                    id=f"menu{i:04d}",
                    name=f"Item #{i} — «Spëcîal» 日本語テスト",
                    price_cents=999 + i * 100,
                    description=f"Description for item {i} with unicode: αβγδ",
                    category=["appetizer", "main", "drink", "dessert"][i % 4],
                    is_vegetarian=i % 3 == 0,
                    allergens=["gluten", "dairy", "nuts", "soy"][: (i % 4) + 1],
                    thumbnail_png=b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2,
                ),
                quantity=(i % 3) + 1,
                special_instructions=f"Note for item {i}" if i % 2 == 0 else "",
            )
        )

    return Order(
        id="ord00003",
        platform_transaction_id=9007199254740993,  # 2^53 + 1: breaks JSON in JS
        customer=Customer(
            id="cust0002",
            name="田中太郎",  # Japanese name: CJK encoding test
            email="tanaka@example.jp",
            phone="+81-90-1234-5678",
            address="東京都渋谷区神宮前1-1-1",
            location=GeoPoint(latitude=35.681236, longitude=139.767125),
        ),
        restaurant_id="rest0001",
        items=items,
        status=OrderStatus.PREPARING,
        payment_method=PaymentMethod.WALLET,
        driver_id="driv0001",
        delivery_notes="Please use the back entrance. ドアベルを鳴らしてください。",
        promo_code="BIGSALE50",
        tip_cents=2000,
        created_at=1700000000.0,
        updated_at=1700000600.0,
        estimated_delivery_minutes=45,
        metadata={
            "source": "web_app",
            "app_version": "4.2.1",
            "session_id": "sess_xyz789",
            "loyalty_tier": "gold",
            "special_event": "birthday",
        },
    )


def make_batch_orders(n: int) -> list[Order]:
    """Generate n deterministic orders for throughput benchmarks."""
    base = make_typical_order()
    orders = []
    for i in range(n):
        order = base.model_copy(
            update={
                "id": f"ord{i:05d}",
                "platform_transaction_id": 100000 + i,
                "created_at": 1700000000.0 + i,
                "updated_at": 1700000000.0 + i,
            }
        )
        orders.append(order)
    return orders
