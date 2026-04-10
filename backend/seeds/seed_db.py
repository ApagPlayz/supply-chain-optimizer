"""
Seed script for Electronic Components Supply Chain Optimizer.

Pulls real component data from HuggingFace (mdnh/electronic-components-supply-chain)
and maps 92 real distributors to their US warehouse/HQ locations.

Usage:
    cd backend
    python3 -m seeds.seed_db
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, SessionLocal, Base
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.models.order import CartItem, Order
from app.models.user import User
import sqlalchemy

# ─────────────────────────────────────────────────────────────────────────────
# Real distributor warehouse/HQ locations
# Sources: company websites, SEC filings, public press releases
# ─────────────────────────────────────────────────────────────────────────────

DISTRIBUTOR_LOCATIONS = {
    # TIER 1 — Major US-based distributors
    "DigiKey": {"lat": 48.1191, "lng": -96.1810, "city": "Thief River Falls", "state": "MN", "country": "USA"},
    "Mouser": {"lat": 32.5632, "lng": -97.1417, "city": "Mansfield", "state": "TX", "country": "USA"},
    "Arrow Electronics": {"lat": 39.5792, "lng": -104.8777, "city": "Centennial", "state": "CO", "country": "USA"},
    "Avnet": {"lat": 33.6015, "lng": -111.8884, "city": "Chandler", "state": "AZ", "country": "USA"},
    "Newark": {"lat": 41.8781, "lng": -87.6298, "city": "Chicago", "state": "IL", "country": "USA"},
    "Future Electronics": {"lat": 45.4482, "lng": -73.7455, "city": "Pointe-Claire", "state": "QC", "country": "Canada"},
    "Rochester Electronics": {"lat": 42.6043, "lng": -71.3468, "city": "Newburyport", "state": "MA", "country": "USA"},
    "Master Electronics": {"lat": 33.4484, "lng": -112.0740, "city": "Phoenix", "state": "AZ", "country": "USA"},
    "Jameco": {"lat": 37.4636, "lng": -121.9180, "city": "Belmont", "state": "CA", "country": "USA"},

    # TIER 2 — Specialty / regional US distributors
    "Component Stockers USA": {"lat": 33.7490, "lng": -84.3880, "city": "Atlanta", "state": "GA", "country": "USA"},
    "Onlinecomponents.com": {"lat": 33.4484, "lng": -112.0740, "city": "Phoenix", "state": "AZ", "country": "USA"},
    "NAC Semi": {"lat": 37.3382, "lng": -121.8863, "city": "San Jose", "state": "CA", "country": "USA"},
    "Classic Components": {"lat": 33.1581, "lng": -117.3506, "city": "Oceanside", "state": "CA", "country": "USA"},
    "Sourcengine": {"lat": 33.7490, "lng": -84.3880, "city": "Atlanta", "state": "GA", "country": "USA"},
    "Tactical IC USA": {"lat": 32.7767, "lng": -96.7970, "city": "Dallas", "state": "TX", "country": "USA"},
    "RS (Formerly Allied Electronics)": {"lat": 32.7555, "lng": -97.3308, "city": "Fort Worth", "state": "TX", "country": "USA"},
    "Richardson RFPD": {"lat": 41.8119, "lng": -88.0111, "city": "Naperville", "state": "IL", "country": "USA"},
    "Braemac Americas - Symmetry Electronics": {"lat": 33.1959, "lng": -117.3795, "city": "Vista", "state": "CA", "country": "USA"},
    "Sensible Micro": {"lat": 33.4484, "lng": -112.0740, "city": "Phoenix", "state": "AZ", "country": "USA"},
    "NetSource Technology": {"lat": 35.2271, "lng": -80.8431, "city": "Charlotte", "state": "NC", "country": "USA"},
    "Mobius Materials": {"lat": 37.7749, "lng": -122.4194, "city": "San Francisco", "state": "CA", "country": "USA"},
    "Electronic Supply": {"lat": 40.7128, "lng": -74.0060, "city": "New York", "state": "NY", "country": "USA"},
    "Freelance Electronics": {"lat": 33.4484, "lng": -112.0740, "city": "Phoenix", "state": "AZ", "country": "USA"},
    "Best Source": {"lat": 33.7490, "lng": -84.3880, "city": "Atlanta", "state": "GA", "country": "USA"},
    "Microchip USA": {"lat": 33.4152, "lng": -111.8315, "city": "Chandler", "state": "AZ", "country": "USA"},
    "DigiKey Marketplace": {"lat": 48.1191, "lng": -96.1810, "city": "Thief River Falls", "state": "MN", "country": "USA"},
    "Quest": {"lat": 42.3601, "lng": -71.0589, "city": "Boston", "state": "MA", "country": "USA"},
    "ACDS": {"lat": 40.7128, "lng": -74.0060, "city": "New York", "state": "NY", "country": "USA"},
    "Jak Electronics": {"lat": 33.9425, "lng": -118.4081, "city": "Los Angeles", "state": "CA", "country": "USA"},
    "Bison Technologies": {"lat": 37.3861, "lng": -122.0839, "city": "Mountain View", "state": "CA", "country": "USA"},
    "GreenChips": {"lat": 37.3382, "lng": -121.8863, "city": "San Jose", "state": "CA", "country": "USA"},

    # TIER 3 — Manufacturer direct stores
    "Texas Instruments": {"lat": 32.9060, "lng": -96.7503, "city": "Dallas", "state": "TX", "country": "USA"},
    "Analog Devices": {"lat": 42.5251, "lng": -71.3514, "city": "Wilmington", "state": "MA", "country": "USA"},
    "Microchip": {"lat": 33.4152, "lng": -111.8315, "city": "Chandler", "state": "AZ", "country": "USA"},

    # TIER 4 — European distributors (ship to US)
    "Farnell": {"lat": 53.7960, "lng": -1.5478, "city": "Leeds", "state": "Yorkshire", "country": "UK"},
    "element14 APAC": {"lat": 1.3521, "lng": 103.8198, "city": "Singapore", "state": "SG", "country": "Singapore"},
    "TME": {"lat": 52.2297, "lng": 21.0122, "city": "Warsaw", "state": "Masovia", "country": "Poland"},
    "Conrad": {"lat": 48.8530, "lng": 12.9545, "city": "Wernberg-Koblitz", "state": "Bavaria", "country": "Germany"},
    "Schukat": {"lat": 48.4011, "lng": 11.7450, "city": "Monheim", "state": "Bavaria", "country": "Germany"},
    "Rapid Electronics": {"lat": 51.1456, "lng": -0.2577, "city": "Colchester", "state": "Essex", "country": "UK"},
    "Anglia": {"lat": 52.2053, "lng": 0.1218, "city": "Cambridge", "state": "Cambs", "country": "UK"},
    "ComSIT Distribution GmbH": {"lat": 50.1109, "lng": 8.6821, "city": "Frankfurt", "state": "Hesse", "country": "Germany"},
    "Maritex": {"lat": 59.9139, "lng": 10.7522, "city": "Oslo", "state": "Oslo", "country": "Norway"},
    "Rebound Electronics": {"lat": 52.4862, "lng": -1.8904, "city": "Birmingham", "state": "West Midlands", "country": "UK"},
    "Component Sense": {"lat": 55.9533, "lng": -3.1883, "city": "Edinburgh", "state": "Scotland", "country": "UK"},
    "Elcom Components": {"lat": 52.3676, "lng": 4.9041, "city": "Amsterdam", "state": "NH", "country": "Netherlands"},
    "Eurochip Technologies LTD": {"lat": 51.5074, "lng": -0.1278, "city": "London", "state": "London", "country": "UK"},
    "Esaler Electronic": {"lat": 52.5200, "lng": 13.4050, "city": "Berlin", "state": "Berlin", "country": "Germany"},

    # TIER 5 — Asian distributors
    "LCSC": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Worldway Electronics": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Win Source": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Weyland Electronics Group Pte. Ltd.": {"lat": 1.3521, "lng": 103.8198, "city": "Singapore", "state": "SG", "country": "Singapore"},
    "Bettlink": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Cytech Systems": {"lat": 22.3193, "lng": 114.1694, "city": "Hong Kong", "state": "HK", "country": "China"},
    "Fly-Wing Technology": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Semicontronic": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "YIC International": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Utmel Electronic": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Anlinkda": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "ICPartonline": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Digi-ic_SMART PIONEER": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Antdic Electronics": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "SHENGYU ELECTRONICS": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Lixinc": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Chipsmall Limited": {"lat": 22.3193, "lng": 114.1694, "city": "Hong Kong", "state": "HK", "country": "China"},
    "Suntronic": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "ALLICDATA ELECTRONICS": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Chip One Stop Global": {"lat": 35.6762, "lng": 139.6503, "city": "Tokyo", "state": "Tokyo", "country": "Japan"},
    "Chip One Stop": {"lat": 35.6762, "lng": 139.6503, "city": "Tokyo", "state": "Tokyo", "country": "Japan"},
    "Heisener Electronics": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Eastek": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "CoreStaff": {"lat": 35.6762, "lng": 139.6503, "city": "Tokyo", "state": "Tokyo", "country": "Japan"},
    "Epart123": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "RC Electronics": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Abacus Technologies": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Aztech": {"lat": 1.3521, "lng": 103.8198, "city": "Singapore", "state": "SG", "country": "Singapore"},
    "Ampacity Systems": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Verical": {"lat": 33.6015, "lng": -111.8884, "city": "Chandler", "state": "AZ", "country": "USA"},  # Avnet subsidiary
    "ODG (Origin Data Global)": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Run Hong Electronics": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Rotakorn": {"lat": 13.7563, "lng": 100.5018, "city": "Bangkok", "state": "BKK", "country": "Thailand"},
    "One Stop Electro": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "JRH Electronics": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "XScomponents": {"lat": 51.5074, "lng": -0.1278, "city": "London", "state": "London", "country": "UK"},
    "Hyper Source Electronics": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Omnical": {"lat": 52.3676, "lng": 4.9041, "city": "Amsterdam", "state": "NH", "country": "Netherlands"},
    "TodayComponents": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Williams Automation": {"lat": 40.7128, "lng": -74.0060, "city": "New York", "state": "NY", "country": "USA"},
    "J2 Sourcing": {"lat": 51.5074, "lng": -0.1278, "city": "London", "state": "London", "country": "UK"},
    "EBEE": {"lat": 22.5431, "lng": 114.0579, "city": "Shenzhen", "state": "Guangdong", "country": "China"},
    "Component Search": {"lat": 51.5074, "lng": -0.1278, "city": "London", "state": "London", "country": "UK"},
}


def seed():
    """Pull real data from HuggingFace and seed the database."""
    from datasets import load_dataset

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Clear existing data
        for tbl in ["distributor_offers", "cart_items", "orders", "components", "distributors"]:
            try:
                db.execute(sqlalchemy.text(f"DELETE FROM {tbl}"))
            except Exception:
                pass
        db.commit()

        # ── 1. Load HuggingFace dataset ──
        print("Pulling electronic components from HuggingFace...")
        ds = load_dataset("mdnh/electronic-components-supply-chain", split="train")
        print(f"  Downloaded {len(ds)} components")

        # ── 2. Seed Distributors ──
        print("Seeding distributors with real locations...")
        # Collect all unique distributor names from dataset
        all_dist_names = set()
        for row in ds:
            for s in (row.get("suppliers") or []):
                all_dist_names.add(s["name"])

        dist_name_to_id = {}
        dist_count = 0
        for name in sorted(all_dist_names):
            loc = DISTRIBUTOR_LOCATIONS.get(name)
            if not loc:
                # Fallback: unmapped distributor gets a generic location
                # This shouldn't happen since we mapped all 92
                print(f"  ⚠ Unmapped distributor: {name}")
                loc = {"lat": 37.7749, "lng": -122.4194, "city": "Unknown", "state": "CA", "country": "USA"}

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
            dist_name_to_id[name] = dist.id
            dist_count += 1
        db.commit()
        print(f"  {dist_count} distributors seeded")

        # ── 3. Seed Components + Offers ──
        print("Seeding components and distributor offers...")
        comp_count = 0
        offer_count = 0

        for row in ds:
            risk_factors = row.get("risk_factors")
            if isinstance(risk_factors, str):
                import json
                try:
                    risk_factors = json.loads(risk_factors)
                except Exception:
                    risk_factors = [risk_factors] if risk_factors else []

            datasheets = row.get("datasheets")
            if isinstance(datasheets, str):
                import json
                try:
                    datasheets = json.loads(datasheets)
                except Exception:
                    datasheets = [datasheets] if datasheets else []

            comp = Component(
                mpn=row["mpn"],
                manufacturer=row["manufacturer"],
                manufacturer_country=row.get("manufacturer_country"),
                category=row.get("category", "Uncategorized"),
                description=row.get("description"),
                datasheets=datasheets,
                risk_score=row.get("risk_score") or 0.0,
                risk_factors=risk_factors,
            )
            db.add(comp)
            db.flush()
            comp_count += 1

            # Add all distributor offers for this component
            for s in (row.get("suppliers") or []):
                dist_id = dist_name_to_id.get(s["name"])
                if not dist_id:
                    continue
                price = s.get("price")
                if price is None or price <= 0:
                    continue

                offer = DistributorOffer(
                    component_id=comp.id,
                    distributor_id=dist_id,
                    price=round(price, 6),
                    stock=s.get("stock") or 0,
                    sku=s.get("sku"),
                    currency=s.get("currency") or "USD",
                )
                db.add(offer)
                offer_count += 1

        db.commit()
        print(f"  {comp_count} components seeded")
        print(f"  {offer_count} distributor offers seeded")

        # ── 4. Update distributor aggregate stats ──
        print("Computing distributor statistics...")
        distributors = db.query(Distributor).all()
        for dist in distributors:
            offers = db.query(DistributorOffer).filter(
                DistributorOffer.distributor_id == dist.id
            ).all()
            dist.total_offers = len(offers)
            dist.total_stock = sum(o.stock for o in offers)
        db.commit()

        # ── Summary ──
        domestic = sum(1 for d in distributors if d.is_domestic)
        intl = len(distributors) - domestic
        print(f"\n{'='*50}")
        print(f"Seed complete!")
        print(f"  Components:   {comp_count}")
        print(f"  Distributors: {dist_count} ({domestic} US, {intl} international)")
        print(f"  Offers:       {offer_count}")
        print(f"  Avg offers/component: {offer_count / max(comp_count, 1):.1f}")
        print(f"{'='*50}")

    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
