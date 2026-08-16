from sqlalchemy import Boolean, Column, Date, Integer, String, Float, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Component(Base):
    """Electronic component from Nexar/Octopart dataset."""
    __tablename__ = "components"

    id = Column(Integer, primary_key=True, index=True)
    mpn = Column(String(100), nullable=False, index=True)  # Manufacturer Part Number
    manufacturer = Column(String(200), nullable=False, index=True)
    manufacturer_country = Column(String(100))
    category = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    datasheets = Column(JSON)  # list of URLs
    risk_score = Column(Float, default=0.0)  # 0-1 from Nexar analysis
    risk_factors = Column(JSON)  # e.g. ["chinese_origin", "single_source"]
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── DigiKey catalog attributes (migration 0006) ───────────────────────────
    # Populated by ``app.ml.lead_time_collector`` straight from the DigiKey
    # Product Information v4 response. These exist so the lead-time model can
    # use at SERVE time the same part-level features it trains on in
    # seeds/data/lead_time_panel/observed_lead_times.csv — previously it could
    # train on lifecycle/stocking status and then never see them in production.
    # NULL means "DigiKey did not return a value for this part". Never defaulted,
    # never derived: a NULL is a real absence, not a zero.
    lifecycle_status = Column(String(50))        # ProductStatus.Status
    normally_stocked = Column(Boolean)           # NormallyStocking
    discontinued = Column(Boolean)               # Discontinued
    end_of_life = Column(Boolean)                # EndOfLife
    digikey_category = Column(String(200))       # Category.Name (DigiKey taxonomy)
    digikey_subcategory = Column(String(200))    # Category.ChildCategories[0].Name

    # ── DigiKey catalog attributes (migration 0007) ───────────────────────────
    # Same story as the migration-0006 block above: these are trained on in the
    # panel CSV today but had nowhere to be served from. All part-level, all
    # nullable, all straight off the DigiKey response — NULL means DigiKey
    # returned no value for this part, never imputed to 0 / "".
    parameter_count = Column(Integer)             # parameter_count (# of Parameters entries)
    package_case = Column(String(200))            # package_case (Parameters "Package / Case")
    htsus_code = Column(String(50))                # htsus_code (Classifications.HtsusCode)
    rohs_status = Column(String(100))              # rohs_status (Classifications.RohsStatus)
    # digikey_unit_price is deliberately part-level and separate from
    # DistributorOffer.price. The panel trains on DigiKey's own quoted unit
    # price (dk_unit_price); serving DistributorOffer.price instead would be a
    # train/serve skew whenever a non-DigiKey offer — a different vendor's
    # price for the same part — happened to be the one the API resolved.
    digikey_unit_price = Column(Float)             # dk_unit_price (StandardPricing[0].UnitPrice)
    # max_break_qty / price_break_count look offer-shaped (they come from a
    # pricing table) but are stored part-level like the rest of this block:
    # the observed panel has exactly one DigiKey row per part, so there is one
    # observation to record, and storing it here makes it resolvable for every
    # offer of the part instead of NULL on every non-DigiKey offer.
    max_break_qty = Column(Integer)                 # max_break_qty (highest StandardPricing[].BreakQuantity)
    price_break_count = Column(Integer)             # price_break_count (len(StandardPricing))

    # LAST OBSERVED FACTORY LEAD TIME — this is the ML TARGET, stored so the
    # optimizer can use a REAL quoted lead time instead of a prediction when one
    # exists. It must NEVER be used as a model feature: doing so is label
    # leakage and would make the lead-time model trivially "perfect".
    observed_lead_time_weeks = Column(Float)     # ManufacturerLeadWeeks
    lead_time_observed_at = Column(Date)         # snapshot date of the above


class DistributorOffer(Base):
    """Real competitive price offer from a distributor for a component."""
    __tablename__ = "distributor_offers"

    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, nullable=False, index=True)
    distributor_id = Column(Integer, nullable=False, index=True)
    price = Column(Float)  # USD per unit (real from Nexar/Octopart)
    stock = Column(Integer, default=0)  # Real inventory count
    sku = Column(String(100))  # Distributor's SKU
    currency = Column(String(10), default="USD")
    moq = Column(Integer, default=1)  # Minimum order quantity

    # ── DigiKey packaging attributes (migration 0006) ─────────────────────────
    # Offer-level, because packaging and pack size are properties of a specific
    # distributor's offer, not of the part. Backfilled only for offers belonging
    # to the DigiKey distributor — the only source that returned them. NULL on
    # every other distributor's offers is honest, not missing data to impute.
    standard_pack = Column(Integer)      # ProductVariations[].StandardPackage
    packaging = Column(String(100))      # ProductVariations[].PackageType.Name
