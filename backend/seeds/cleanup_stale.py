"""
One-shot cleanup: drop pre-pivot tables + wipe demo cart/orders.

Run once from project root:
    cd backend && source venv/bin/activate && python -m seeds.cleanup_stale
"""
from sqlalchemy import text

from app.core.database import engine

STALE_TABLES = [
    "materials",
    "suppliers",
    "production_hubs",
    "price_history",
    "price_forecasts",
]


def main():
    with engine.begin() as conn:
        for t in STALE_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
            print(f"dropped: {t}")
        # Wipe stale demo data — keeps users intact
        for t in ["cart_items", "orders"]:
            conn.execute(text(f"DELETE FROM {t}"))
            print(f"wiped: {t}")
    print("cleanup done.")


if __name__ == "__main__":
    main()
