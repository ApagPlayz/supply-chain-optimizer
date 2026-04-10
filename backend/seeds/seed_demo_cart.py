"""
Seed curated 5-part BOM into the demo user's cart.

Run once: python -m seeds.seed_demo_cart
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.component import Component, DistributorOffer
from app.models.order import CartItem
from app.models.user import User

# (mpn, quantity) — component_ids looked up dynamically by MPN
CURATED_BOM = [
    ("ESP32-WROOM-32UE-N4", 50),
    ("STM32F103C8T6", 50),
    ("GD25Q64CSIGR", 50),
    ("ESP8266EX", 50),
    ("ATMEGA328P-PU", 25),
]

DEMO_EMAIL = "demo@example.com"


def main():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if not user:
            raise SystemExit(f"Demo user {DEMO_EMAIL} not found — run seed_db first")

        # Clear any existing cart items
        db.query(CartItem).filter(CartItem.user_id == user.id).delete()

        for mpn, qty in CURATED_BOM:
            comp = db.query(Component).filter(Component.mpn == mpn).first()
            if not comp:
                raise SystemExit(f"Component {mpn} not found in DB — run seed_db first")

            # Pick the cheapest US offer as the default cart selection
            offer = db.execute(
                select(DistributorOffer)
                .where(DistributorOffer.component_id == comp.id)
                .order_by(DistributorOffer.price.asc())
                .limit(1)
            ).scalar_one_or_none()

            if not offer or not offer.price:
                raise SystemExit(f"No valid offer for {mpn}")

            db.add(CartItem(
                user_id=user.id,
                component_id=comp.id,
                distributor_id=offer.distributor_id,
                quantity=qty,
                unit_price=offer.price,
            ))
        db.commit()
        n = db.query(CartItem).filter(CartItem.user_id == user.id).count()
        print(f"seeded {n} cart items for {DEMO_EMAIL}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
