"""Seed the cross_dock_hubs table from the static FREIGHT_HUBS list."""
from app.core.database import Base, SessionLocal, engine
from app.models.cross_dock_hub import CrossDockHub
from app.optimization.freight_hubs import FREIGHT_HUBS


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(CrossDockHub).delete()
        for h in FREIGHT_HUBS:
            db.add(CrossDockHub(
                id=h.id, name=h.name, operator=h.operator, hub_type=h.hub_type,
                city=h.city, state=h.state,
                latitude=h.latitude, longitude=h.longitude,
                source_citation="Spec §5.5 (verified against public databases)",
            ))
        db.commit()
        n = db.query(CrossDockHub).count()
        print(f"seeded {n} cross-dock hubs")
    finally:
        db.close()


if __name__ == "__main__":
    main()
