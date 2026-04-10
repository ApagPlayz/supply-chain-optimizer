"""
Live seeder — pulls component data from Nexar API instead of HuggingFace.

Usage:
    cd backend
    python3 -m seeds.seed_live

Prerequisites:
    NEXAR_API_KEY must be set in .env (free evaluation key from nexar.com/api)

This seeder queries Nexar for a curated set of electronic component categories
and seeds the DB with live data: current stock levels, real prices, lead times.

Compared to seed_db.py (HuggingFace static snapshot):
  + Real-time stock and pricing
  + Live lead times
  + Current lifecycle status
  - Requires Nexar API key
  - Free tier limited to 1,000 part lookups

Fallback: if NEXAR_API_KEY is not set, this script falls back to seed_db.py
          (HuggingFace dataset) automatically.

Seeding strategy:
  1. Query Nexar for representative parts from each component category
  2. For each part, retrieve all distributor offers
  3. Map distributors to warehouse locations (reuses DISTRIBUTOR_LOCATIONS from seed_db.py)
  4. Store in Component + DistributorOffer tables
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, SessionLocal, Base
from app.core.config import settings
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.models.order import CartItem, Order
import sqlalchemy

# Import the distributor location map from the original seeder
from seeds.seed_db import DISTRIBUTOR_LOCATIONS

# ── Component categories + representative search queries ───────────────────────
# These queries are passed to Nexar's supSearch endpoint.
# Each will return up to RESULTS_PER_QUERY components from Nexar's database.
CATEGORY_QUERIES = [
    ("Microcontrollers", "microcontroller ARM Cortex"),
    ("Microcontrollers", "ESP32 WiFi Bluetooth"),
    ("Microcontrollers", "STM32 microcontroller"),
    ("ADC", "analog digital converter 16-bit precision"),
    ("DAC", "digital analog converter audio"),
    ("Op-Amps", "operational amplifier rail-to-rail"),
    ("Memory", "flash memory SPI NOR"),
    ("Memory", "EEPROM I2C"),
    ("RF", "RF transceiver 2.4GHz"),
    ("RF", "LoRa module wireless"),
    ("Motor Drivers", "stepper motor driver H-bridge"),
    ("Power Management", "LDO voltage regulator"),
    ("Power Management", "DC-DC converter buck switching"),
    ("Logic Gates", "74HC logic gates"),
    ("DSP", "digital signal processor TI"),
    ("SoC", "system on chip wireless IoT"),
    ("Sensors", "temperature sensor I2C digital"),
    ("Sensors", "accelerometer MEMS 3-axis"),
    ("Connectors", "USB Type-C connector"),
    ("Passives", "ceramic capacitor 100nF 0402"),
]

RESULTS_PER_QUERY = 10  # Stay well within free tier (1k parts lifetime)


async def seed_from_nexar():
    """Pull real data from Nexar API and seed the database."""
    from app.core.clients.nexar_client import NexarClient

    if not settings.NEXAR_CLIENT_ID or not settings.NEXAR_CLIENT_SECRET:
        print("❌ NEXAR_CLIENT_ID / NEXAR_CLIENT_SECRET not set in .env")
        print("   Get free credentials at: https://nexar.com/api")
        print("   Falling back to HuggingFace dataset seeder...")
        from seeds.seed_db import seed
        seed()
        return

    client = NexarClient(settings.NEXAR_CLIENT_ID, settings.NEXAR_CLIENT_SECRET)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Clear existing data
        print("Clearing existing data...")
        for tbl in ["distributor_offers", "cart_items", "orders", "components", "distributors"]:
            try:
                db.execute(sqlalchemy.text(f"DELETE FROM {tbl}"))
            except Exception:
                pass
        db.commit()

        # ── 1. Seed all known distributors first ──────────────────────────────
        print("Seeding distributor locations...")
        dist_name_to_id: dict = {}
        for name, loc in DISTRIBUTOR_LOCATIONS.items():
            dist = Distributor(
                name=name,
                latitude=loc["lat"],
                longitude=loc["lng"],
                city=loc["city"],
                state=loc["state"],
                country=loc["country"],
                is_domestic=loc["country"] == "USA",
            )
            db.add(dist)
            db.flush()
            dist_name_to_id[name.lower()] = dist.id
        db.commit()
        print(f"  {len(dist_name_to_id)} distributors seeded")

        # ── 2. Fetch components from Nexar ────────────────────────────────────
        print(f"\nFetching components from Nexar API ({len(CATEGORY_QUERIES)} queries)...")
        all_parts = []
        seen_mpns = set()
        total_api_calls = 0

        for category, query in CATEGORY_QUERIES:
            print(f"  [{category}] {query!r}...")
            parts = await client.search_category(query, limit=RESULTS_PER_QUERY)
            total_api_calls += 1

            for part in parts:
                mpn = part.get("mpn", "")
                if not mpn or mpn in seen_mpns:
                    continue
                seen_mpns.add(mpn)
                all_parts.append((category, part))

            print(f"    → {len(parts)} parts found (total unique: {len(seen_mpns)})")

            # Rate limiting: don't hammer the API
            await asyncio.sleep(0.1)

        print(f"\nTotal unique components fetched: {len(all_parts)}")
        print(f"Total Nexar API calls: {total_api_calls}")

        # ── 3. Seed components + offers ───────────────────────────────────────
        print("\nSeeding components and distributor offers...")
        comp_count = 0
        offer_count = 0
        skipped = 0

        for category, part in all_parts:
            mpn = part.get("mpn", "")
            if not mpn:
                continue

            manufacturer_name = part.get("manufacturer", {}).get("name", "Unknown")
            description = part.get("shortDescription")
            category_name = part.get("category", {}).get("name") or category

            # Detect Chinese-origin manufacturers for risk scoring
            chinese_manufacturers = {
                "lcsc", "jlcpcb", "allicdata", "bettlink", "utmel",
                "worldway", "win source", "heisener", "suntronic",
            }
            manufacturer_country = None
            risk_factors = []
            if any(cm in manufacturer_name.lower() for cm in chinese_manufacturers):
                manufacturer_country = "CN"
                risk_factors = ["chinese_origin"]

            comp = Component(
                mpn=mpn,
                manufacturer=manufacturer_name,
                manufacturer_country=manufacturer_country,
                category=category_name,
                description=description,
                datasheets=[],
                risk_score=0.3 if "chinese_origin" in risk_factors else 0.1,
                risk_factors=risk_factors,
            )
            db.add(comp)
            db.flush()
            comp_count += 1

            # Fetch individual component offers (separate API call for full pricing)
            try:
                part_detail = await client.search_mpn(mpn)
                total_api_calls += 1
                await asyncio.sleep(0.05)

                if part_detail:
                    offers = client.parse_offers(part_detail)
                else:
                    offers = client.parse_offers(part)
            except Exception as e:
                print(f"    ⚠ Failed to fetch offers for {mpn}: {e}")
                offers = client.parse_offers(part)

            for offer_data in offers:
                dist_name = offer_data.get("distributor", "")
                if not dist_name:
                    continue

                # Match to known distributor (fuzzy name match)
                dist_id = _find_distributor_id(dist_name, dist_name_to_id)
                if not dist_id:
                    # Add unknown distributor with fallback location
                    new_dist = Distributor(
                        name=dist_name,
                        latitude=37.7749,
                        longitude=-122.4194,
                        city="Unknown",
                        state="CA",
                        country="USA",
                        is_domestic=True,
                    )
                    db.add(new_dist)
                    db.flush()
                    dist_name_to_id[dist_name.lower()] = new_dist.id
                    dist_id = new_dist.id

                price = offer_data.get("price")
                if price is None or price <= 0:
                    continue

                offer = DistributorOffer(
                    component_id=comp.id,
                    distributor_id=dist_id,
                    price=round(float(price), 6),
                    stock=offer_data.get("stock") or 0,
                    sku=offer_data.get("sku"),
                    currency=offer_data.get("currency") or "USD",
                )
                db.add(offer)
                offer_count += 1

            if comp_count % 10 == 0:
                db.commit()  # Commit in batches to avoid memory buildup
                print(f"  Progress: {comp_count}/{len(all_parts)} components, {offer_count} offers")

        db.commit()

        # ── 4. Update distributor stats ───────────────────────────────────────
        print("\nComputing distributor statistics...")
        distributors = db.query(Distributor).all()
        for dist in distributors:
            offers = db.query(DistributorOffer).filter(
                DistributorOffer.distributor_id == dist.id
            ).all()
            dist.total_offers = len(offers)
            dist.total_stock = sum(o.stock for o in offers)
        db.commit()

        # ── Summary ───────────────────────────────────────────────────────────
        domestic = sum(1 for d in distributors if d.is_domestic)
        intl = len(distributors) - domestic
        print(f"\n{'='*55}")
        print(f"✅ Live seed complete! (Nexar API)")
        print(f"  Components:       {comp_count}")
        print(f"  Distributors:     {len(distributors)} ({domestic} US, {intl} international)")
        print(f"  Offers:           {offer_count}")
        print(f"  Avg offers/part:  {offer_count / max(comp_count, 1):.1f}")
        print(f"  Nexar API calls:  {total_api_calls}")
        print(f"  Skipped:          {skipped}")
        print(f"{'='*55}")
        print(f"\nNOTE: Free Nexar tier has a 1,000-part lookup lifetime limit.")
        print(f"      You used approximately {total_api_calls} of your quota this run.")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Error during live seeding: {e}")
        raise
    finally:
        db.close()


def _find_distributor_id(name: str, name_to_id: dict) -> int | None:
    """
    Fuzzy match distributor name to a known distributor ID.
    Handles variations like "DigiKey" vs "digikey" vs "Digi-Key Electronics".
    """
    name_lower = name.lower().strip()

    # Direct match
    if name_lower in name_to_id:
        return name_to_id[name_lower]

    # Partial match — check if known name appears in the query string or vice versa
    for known_name, dist_id in name_to_id.items():
        if known_name in name_lower or name_lower in known_name:
            return dist_id

    # Common aliases
    aliases = {
        "digi-key": "digikey",
        "digikey electronics": "digikey",
        "mouser electronics": "mouser",
        "arrow electronics": "arrow electronics",
        "avnet": "avnet",
        "newark": "newark",
        "farnell": "farnell",
        "element14": "farnell",
        "lcsc electronics": "lcsc",
        "rs components": "rs (formerly allied electronics)",
        "allied electronics": "rs (formerly allied electronics)",
    }
    for alias, canonical in aliases.items():
        if alias in name_lower and canonical in name_to_id:
            return name_to_id[canonical]

    return None


if __name__ == "__main__":
    print("Supply Chain Optimizer — Live Data Seeder")
    print("Using Nexar API for real-time component data")
    print("")
    asyncio.run(seed_from_nexar())
