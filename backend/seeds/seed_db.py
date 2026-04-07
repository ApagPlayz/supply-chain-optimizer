"""
Seed script: 25 US production hubs, 200 tech materials, 120 suppliers, 90-day price history.
Run: python -m seeds.seed_db  (from backend/ directory)
"""
import os
import sys
import math
import random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, engine
from app.core import database  # noqa
import app.models  # noqa — register all ORM classes
from app.core.database import Base
from app.models.hub import ProductionHub
from app.models.material import Material, PriceHistory, PriceForecast
from app.models.supplier import Supplier

random.seed(42)
Base.metadata.create_all(bind=engine)

# ─── 25 US Production Hubs ───────────────────────────────────────────────────

HUBS = [
    {"name": "Silicon Valley Tech Hub", "city": "San Jose", "state": "CA", "lat": 37.3382, "lng": -121.8863,
     "hub_type": "semiconductor", "specialization": "Silicon wafers,GaN,Ge,SiC,photomasks", "risk_index": 0.18},
    {"name": "Phoenix Semiconductor Cluster", "city": "Phoenix", "state": "AZ", "lat": 33.4484, "lng": -112.0740,
     "hub_type": "semiconductor", "specialization": "Silicon wafers,SiC,compound semiconductors", "risk_index": 0.20},
    {"name": "Austin Advanced Manufacturing Hub", "city": "Austin", "state": "TX", "lat": 30.2672, "lng": -97.7431,
     "hub_type": "semiconductor", "specialization": "DRAM,NAND flash,logic chips,PCBs", "risk_index": 0.22},
    {"name": "Portland High-Tech District", "city": "Portland", "state": "OR", "lat": 45.5051, "lng": -122.6750,
     "hub_type": "semiconductor", "specialization": "DRAM,advanced packaging,precision optics", "risk_index": 0.19},
    {"name": "Boise Electronics Corridor", "city": "Boise", "state": "ID", "lat": 43.6150, "lng": -116.2023,
     "hub_type": "semiconductor", "specialization": "DRAM,flash memory,microcontrollers", "risk_index": 0.21},
    {"name": "Detroit Battery Materials Hub", "city": "Detroit", "state": "MI", "lat": 42.3314, "lng": -83.0458,
     "hub_type": "battery", "specialization": "Lithium cells,Cobalt,Nickel,Manganese,battery packs", "risk_index": 0.30},
    {"name": "Nevada Battery Gigafactory Zone", "city": "Reno", "state": "NV", "lat": 39.5296, "lng": -119.8138,
     "hub_type": "battery", "specialization": "Lithium carbonate,NMC cathodes,electrolyte,anode graphite", "risk_index": 0.25},
    {"name": "Tennessee EV Materials Corridor", "city": "Nashville", "state": "TN", "lat": 36.1627, "lng": -86.7816,
     "hub_type": "battery", "specialization": "Battery-grade lithium,Cobalt sulfate,NCA cathode", "risk_index": 0.28},
    {"name": "Pittsburgh Rare Earth Center", "city": "Pittsburgh", "state": "PA", "lat": 40.4406, "lng": -79.9959,
     "hub_type": "rare_earth", "specialization": "Neodymium,Dysprosium,Cerium,Lanthanum,Praseodymium", "risk_index": 0.55},
    {"name": "Mountain Pass Rare Earth Hub", "city": "Barstow", "state": "CA", "lat": 34.8958, "lng": -116.9690,
     "hub_type": "rare_earth", "specialization": "Neodymium,Praseodymium,mixed rare earths,NdFeB magnets", "risk_index": 0.45},
    {"name": "Gulf Coast Chemical Complex", "city": "Houston", "state": "TX", "lat": 29.7604, "lng": -95.3698,
     "hub_type": "chemical", "specialization": "HF acid,H2SO4,IPA,NMP,acetone,ethylene glycol", "risk_index": 0.35},
    {"name": "Louisiana Petrochemical Belt", "city": "Baton Rouge", "state": "LA", "lat": 30.4515, "lng": -91.1871,
     "hub_type": "chemical", "specialization": "Ethylene,propylene,specialty polymers,epoxy resins", "risk_index": 0.40},
    {"name": "Midwest Metals Hub", "city": "Cleveland", "state": "OH", "lat": 41.4993, "lng": -81.6944,
     "hub_type": "metal", "specialization": "Copper,Aluminum,Steel,Titanium,Tin", "risk_index": 0.28},
    {"name": "Appalachian Aluminum Center", "city": "Charleston", "state": "WV", "lat": 38.3498, "lng": -81.6326,
     "hub_type": "metal", "specialization": "Primary aluminum,aluminum alloys,rolled sheet", "risk_index": 0.32},
    {"name": "Arizona Copper Mining Hub", "city": "Tucson", "state": "AZ", "lat": 32.2226, "lng": -110.9747,
     "hub_type": "metal", "specialization": "Refined copper,copper wire,copper foil", "risk_index": 0.27},
    {"name": "New England Precision Optics", "city": "Boston", "state": "MA", "lat": 42.3601, "lng": -71.0589,
     "hub_type": "optical", "specialization": "Optical fiber,ITO glass,LCD glass,precision lenses,photonics", "risk_index": 0.20},
    {"name": "Corning Glass & Fiber Hub", "city": "Corning", "state": "NY", "lat": 42.1431, "lng": -77.0545,
     "hub_type": "optical", "specialization": "Optical fiber,specialty glass,display glass,Gorilla Glass", "risk_index": 0.18},
    {"name": "Research Triangle Electronics", "city": "Raleigh", "state": "NC", "lat": 35.7796, "lng": -78.6382,
     "hub_type": "semiconductor", "specialization": "RF chips,microcontrollers,IoT chips,compound semiconductors", "risk_index": 0.22},
    {"name": "PCB & Display Materials Hub", "city": "San Diego", "state": "CA", "lat": 32.7157, "lng": -117.1611,
     "hub_type": "pcb", "specialization": "FR4 laminate,copper clad,solder mask,ITO,LCD panels", "risk_index": 0.24},
    {"name": "Minnesota Mining & Specialty Chemicals", "city": "Minneapolis", "state": "MN", "lat": 44.9778, "lng": -93.2650,
     "hub_type": "chemical", "specialization": "Specialty adhesives,fluoropolymers,PTFE,silicone compounds", "risk_index": 0.22},
    {"name": "Pacific Northwest Advanced Materials", "city": "Seattle", "state": "WA", "lat": 47.6062, "lng": -122.3321,
     "hub_type": "semiconductor", "specialization": "Gallium arsenide,InP,advanced sensors,MEMS", "risk_index": 0.20},
    {"name": "Colorado Springs Defense Electronics", "city": "Colorado Springs", "state": "CO", "lat": 38.8339, "lng": -104.8214,
     "hub_type": "semiconductor", "specialization": "GaN RF,SiC power,radiation-hardened chips,sensors", "risk_index": 0.25},
    {"name": "Atlanta Distribution & Logistics Hub", "city": "Atlanta", "state": "GA", "lat": 33.7490, "lng": -84.3880,
     "hub_type": "distribution", "specialization": "Multi-material distribution,warehousing,logistics", "risk_index": 0.15},
    {"name": "Chicago Industrial Polymers Hub", "city": "Chicago", "state": "IL", "lat": 41.8781, "lng": -87.6298,
     "hub_type": "polymer", "specialization": "ABS,PC,PTFE,PEEK,epoxy,polyimide,engineering plastics", "risk_index": 0.25},
    {"name": "New York Advanced Chemicals", "city": "Albany", "state": "NY", "lat": 42.6526, "lng": -73.7562,
     "hub_type": "chemical", "specialization": "Photoresists,CMP slurries,etchants,plating chemicals", "risk_index": 0.22},
]

# ─── 200 Materials ────────────────────────────────────────────────────────────

MATERIALS = [
    # SEMICONDUCTORS
    {"name": "Silicon Wafer (300mm)", "category": "semiconductor", "subcategory": "substrate", "unit": "each", "current_price": 125.0, "price_unit": "$/wafer", "volatility_score": 0.35, "supply_risk_score": 0.40, "description": "Prime-grade 300mm silicon wafer for advanced node IC fabrication"},
    {"name": "Silicon Wafer (200mm)", "category": "semiconductor", "subcategory": "substrate", "unit": "each", "current_price": 45.0, "price_unit": "$/wafer", "volatility_score": 0.30, "supply_risk_score": 0.35},
    {"name": "Germanium Wafer", "category": "semiconductor", "subcategory": "substrate", "unit": "each", "current_price": 280.0, "price_unit": "$/wafer", "volatility_score": 0.50, "supply_risk_score": 0.70},
    {"name": "Gallium Arsenide Wafer", "category": "semiconductor", "subcategory": "substrate", "unit": "each", "current_price": 220.0, "price_unit": "$/wafer", "volatility_score": 0.45, "supply_risk_score": 0.65},
    {"name": "Gallium Nitride (GaN) Epitaxial Wafer", "category": "semiconductor", "subcategory": "compound", "unit": "each", "current_price": 350.0, "price_unit": "$/wafer", "volatility_score": 0.40, "supply_risk_score": 0.60},
    {"name": "Silicon Carbide (SiC) Wafer 150mm", "category": "semiconductor", "subcategory": "compound", "unit": "each", "current_price": 800.0, "price_unit": "$/wafer", "volatility_score": 0.55, "supply_risk_score": 0.60},
    {"name": "Indium Phosphide Wafer", "category": "semiconductor", "subcategory": "compound", "unit": "each", "current_price": 450.0, "price_unit": "$/wafer", "volatility_score": 0.55, "supply_risk_score": 0.75},
    {"name": "Photomask (ArF 193nm)", "category": "semiconductor", "subcategory": "lithography", "unit": "each", "current_price": 15000.0, "price_unit": "$/mask", "volatility_score": 0.30, "supply_risk_score": 0.55},
    {"name": "Photoresist (EUV Grade)", "category": "semiconductor", "subcategory": "lithography", "unit": "liter", "current_price": 2800.0, "price_unit": "$/L", "volatility_score": 0.35, "supply_risk_score": 0.60},
    {"name": "Photoresist (ArF Immersion)", "category": "semiconductor", "subcategory": "lithography", "unit": "liter", "current_price": 950.0, "price_unit": "$/L", "volatility_score": 0.30, "supply_risk_score": 0.50},
    {"name": "CMP Slurry (Oxide)", "category": "semiconductor", "subcategory": "polishing", "unit": "liter", "current_price": 85.0, "price_unit": "$/L", "volatility_score": 0.25, "supply_risk_score": 0.40},
    {"name": "CMP Slurry (Tungsten)", "category": "semiconductor", "subcategory": "polishing", "unit": "liter", "current_price": 140.0, "price_unit": "$/L", "volatility_score": 0.30, "supply_risk_score": 0.45},
    {"name": "DRAM Module (DDR5 16GB)", "category": "semiconductor", "subcategory": "memory", "unit": "each", "current_price": 38.0, "price_unit": "$/module", "volatility_score": 0.60, "supply_risk_score": 0.50},
    {"name": "NAND Flash (3D TLC 512Gb)", "category": "semiconductor", "subcategory": "memory", "unit": "each", "current_price": 12.0, "price_unit": "$/die", "volatility_score": 0.65, "supply_risk_score": 0.50},
    {"name": "Application Processor SoC", "category": "semiconductor", "subcategory": "logic", "unit": "each", "current_price": 45.0, "price_unit": "$/unit", "volatility_score": 0.45, "supply_risk_score": 0.55},
    {"name": "Power Management IC (PMIC)", "category": "semiconductor", "subcategory": "analog", "unit": "each", "current_price": 3.50, "price_unit": "$/unit", "volatility_score": 0.40, "supply_risk_score": 0.48},
    {"name": "RF Front-End Module", "category": "semiconductor", "subcategory": "RF", "unit": "each", "current_price": 8.0, "price_unit": "$/unit", "volatility_score": 0.42, "supply_risk_score": 0.52},
    {"name": "MEMS Accelerometer", "category": "semiconductor", "subcategory": "sensor", "unit": "each", "current_price": 2.20, "price_unit": "$/unit", "volatility_score": 0.35, "supply_risk_score": 0.40},
    {"name": "Image Sensor (CMOS 108MP)", "category": "semiconductor", "subcategory": "sensor", "unit": "each", "current_price": 18.0, "price_unit": "$/unit", "volatility_score": 0.45, "supply_risk_score": 0.50},
    {"name": "Microcontroller (ARM Cortex-M33)", "category": "semiconductor", "subcategory": "logic", "unit": "each", "current_price": 1.80, "price_unit": "$/unit", "volatility_score": 0.38, "supply_risk_score": 0.42},

    # RARE EARTHS
    {"name": "Neodymium Oxide (Nd2O3)", "category": "rare_earth", "subcategory": "magnet", "unit": "kg", "current_price": 92.0, "price_unit": "$/kg", "volatility_score": 0.75, "supply_risk_score": 0.85, "description": "Key magnet material for EV motors and wind turbines"},
    {"name": "Dysprosium Oxide (Dy2O3)", "category": "rare_earth", "subcategory": "magnet", "unit": "kg", "current_price": 320.0, "price_unit": "$/kg", "volatility_score": 0.80, "supply_risk_score": 0.90},
    {"name": "Praseodymium Oxide (Pr6O11)", "category": "rare_earth", "subcategory": "magnet", "unit": "kg", "current_price": 85.0, "price_unit": "$/kg", "volatility_score": 0.72, "supply_risk_score": 0.82},
    {"name": "Terbium Oxide (Tb4O7)", "category": "rare_earth", "subcategory": "magnet", "unit": "kg", "current_price": 1450.0, "price_unit": "$/kg", "volatility_score": 0.85, "supply_risk_score": 0.92},
    {"name": "Cerium Oxide (CeO2)", "category": "rare_earth", "subcategory": "polishing", "unit": "kg", "current_price": 4.50, "price_unit": "$/kg", "volatility_score": 0.50, "supply_risk_score": 0.70},
    {"name": "Lanthanum Oxide (La2O3)", "category": "rare_earth", "subcategory": "glass", "unit": "kg", "current_price": 3.80, "price_unit": "$/kg", "volatility_score": 0.48, "supply_risk_score": 0.68},
    {"name": "Europium Oxide (Eu2O3)", "category": "rare_earth", "subcategory": "phosphor", "unit": "kg", "current_price": 28.0, "price_unit": "$/kg", "volatility_score": 0.65, "supply_risk_score": 0.80},
    {"name": "Yttrium Oxide (Y2O3)", "category": "rare_earth", "subcategory": "phosphor", "unit": "kg", "current_price": 7.20, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.72},
    {"name": "NdFeB Sintered Magnet (Grade N52)", "category": "rare_earth", "subcategory": "magnet", "unit": "kg", "current_price": 88.0, "price_unit": "$/kg", "volatility_score": 0.70, "supply_risk_score": 0.82},
    {"name": "Samarium Cobalt Magnet (SmCo5)", "category": "rare_earth", "subcategory": "magnet", "unit": "kg", "current_price": 115.0, "price_unit": "$/kg", "volatility_score": 0.68, "supply_risk_score": 0.80},

    # BATTERY MATERIALS
    {"name": "Lithium Carbonate (battery grade)", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 14.5, "price_unit": "$/kg", "volatility_score": 0.90, "supply_risk_score": 0.72, "fred_series_id": "PCU3353433534", "description": "Primary lithium source for Li-ion batteries"},
    {"name": "Lithium Hydroxide (battery grade)", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 16.0, "price_unit": "$/kg", "volatility_score": 0.88, "supply_risk_score": 0.72},
    {"name": "Cobalt Sulfate (battery grade)", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 8.80, "price_unit": "$/kg", "volatility_score": 0.82, "supply_risk_score": 0.85},
    {"name": "Nickel Sulfate (battery grade)", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 4.60, "price_unit": "$/kg", "volatility_score": 0.68, "supply_risk_score": 0.55},
    {"name": "Manganese Sulfate (battery grade)", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 0.95, "price_unit": "$/kg", "volatility_score": 0.45, "supply_risk_score": 0.40},
    {"name": "NMC 811 Cathode Powder", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 28.0, "price_unit": "$/kg", "volatility_score": 0.72, "supply_risk_score": 0.65},
    {"name": "NCA Cathode Powder", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 32.0, "price_unit": "$/kg", "volatility_score": 0.70, "supply_risk_score": 0.68},
    {"name": "LFP Cathode Powder (LiFePO4)", "category": "battery", "subcategory": "cathode", "unit": "kg", "current_price": 11.0, "price_unit": "$/kg", "volatility_score": 0.50, "supply_risk_score": 0.55},
    {"name": "Graphite Anode (natural, battery grade)", "category": "battery", "subcategory": "anode", "unit": "kg", "current_price": 6.50, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.75},
    {"name": "Synthetic Graphite Anode", "category": "battery", "subcategory": "anode", "unit": "kg", "current_price": 9.80, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.50},
    {"name": "Silicon Anode Additive", "category": "battery", "subcategory": "anode", "unit": "kg", "current_price": 45.0, "price_unit": "$/kg", "volatility_score": 0.60, "supply_risk_score": 0.55},
    {"name": "Electrolyte Solution (LiPF6 1M in EC/DMC)", "category": "battery", "subcategory": "electrolyte", "unit": "liter", "current_price": 22.0, "price_unit": "$/L", "volatility_score": 0.55, "supply_risk_score": 0.60},
    {"name": "Separator Film (PP/PE)", "category": "battery", "subcategory": "separator", "unit": "m²", "current_price": 1.80, "price_unit": "$/m²", "volatility_score": 0.38, "supply_risk_score": 0.45},
    {"name": "Battery Aluminum Foil (current collector)", "category": "battery", "subcategory": "collector", "unit": "kg", "current_price": 4.20, "price_unit": "$/kg", "volatility_score": 0.40, "supply_risk_score": 0.35},
    {"name": "Copper Foil (8µm battery grade)", "category": "battery", "subcategory": "collector", "unit": "kg", "current_price": 12.50, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.48},

    # STRUCTURAL METALS
    {"name": "Copper Cathode (LME Grade A)", "category": "metal", "subcategory": "copper", "unit": "kg", "current_price": 9.20, "price_unit": "$/kg", "volatility_score": 0.62, "supply_risk_score": 0.42, "alpha_vantage_symbol": "COPPER", "description": "Primary refined copper for electrical wiring and PCBs"},
    {"name": "Copper Wire Rod (8mm)", "category": "metal", "subcategory": "copper", "unit": "kg", "current_price": 9.80, "price_unit": "$/kg", "volatility_score": 0.60, "supply_risk_score": 0.40},
    {"name": "Aluminum (99.7% primary ingot)", "category": "metal", "subcategory": "aluminum", "unit": "kg", "current_price": 2.45, "price_unit": "$/kg", "volatility_score": 0.48, "supply_risk_score": 0.35, "alpha_vantage_symbol": "ALUMINUM"},
    {"name": "Aluminum Alloy 6061-T6", "category": "metal", "subcategory": "aluminum", "unit": "kg", "current_price": 3.10, "price_unit": "$/kg", "volatility_score": 0.45, "supply_risk_score": 0.33},
    {"name": "Titanium Sponge (Grade 2)", "category": "metal", "subcategory": "titanium", "unit": "kg", "current_price": 11.50, "price_unit": "$/kg", "volatility_score": 0.52, "supply_risk_score": 0.60},
    {"name": "Tin (99.95% ingot)", "category": "metal", "subcategory": "tin", "unit": "kg", "current_price": 27.0, "price_unit": "$/kg", "volatility_score": 0.70, "supply_risk_score": 0.65},
    {"name": "Indium (99.99%)", "category": "metal", "subcategory": "indium", "unit": "kg", "current_price": 170.0, "price_unit": "$/kg", "volatility_score": 0.78, "supply_risk_score": 0.80},
    {"name": "Gallium (99.9999%)", "category": "metal", "subcategory": "gallium", "unit": "kg", "current_price": 290.0, "price_unit": "$/kg", "volatility_score": 0.80, "supply_risk_score": 0.88},
    {"name": "Germanium (99.999%)", "category": "metal", "subcategory": "germanium", "unit": "kg", "current_price": 1050.0, "price_unit": "$/kg", "volatility_score": 0.82, "supply_risk_score": 0.88},
    {"name": "Gold (99.99% fine)", "category": "metal", "subcategory": "precious", "unit": "troy_oz", "current_price": 2350.0, "price_unit": "$/troy oz", "volatility_score": 0.55, "supply_risk_score": 0.30, "alpha_vantage_symbol": "XAUUSD"},
    {"name": "Silver (99.9% fine)", "category": "metal", "subcategory": "precious", "unit": "troy_oz", "current_price": 27.50, "price_unit": "$/troy oz", "volatility_score": 0.68, "supply_risk_score": 0.32, "alpha_vantage_symbol": "XAGUSD"},
    {"name": "Palladium (99.95%)", "category": "metal", "subcategory": "PGM", "unit": "troy_oz", "current_price": 980.0, "price_unit": "$/troy oz", "volatility_score": 0.75, "supply_risk_score": 0.72},
    {"name": "Platinum (99.95%)", "category": "metal", "subcategory": "PGM", "unit": "troy_oz", "current_price": 950.0, "price_unit": "$/troy oz", "volatility_score": 0.65, "supply_risk_score": 0.68},
    {"name": "Tantalum Powder (capacitor grade)", "category": "metal", "subcategory": "refractory", "unit": "kg", "current_price": 152.0, "price_unit": "$/kg", "volatility_score": 0.70, "supply_risk_score": 0.82},
    {"name": "Tungsten Powder (99.9%)", "category": "metal", "subcategory": "refractory", "unit": "kg", "current_price": 38.0, "price_unit": "$/kg", "volatility_score": 0.60, "supply_risk_score": 0.72},
    {"name": "Molybdenum (99.95% powder)", "category": "metal", "subcategory": "refractory", "unit": "kg", "current_price": 32.0, "price_unit": "$/kg", "volatility_score": 0.58, "supply_risk_score": 0.62},
    {"name": "Hafnium (99.9%)", "category": "metal", "subcategory": "refractory", "unit": "kg", "current_price": 900.0, "price_unit": "$/kg", "volatility_score": 0.75, "supply_risk_score": 0.78},
    {"name": "Rhenium (99.99%)", "category": "metal", "subcategory": "refractory", "unit": "kg", "current_price": 2800.0, "price_unit": "$/kg", "volatility_score": 0.72, "supply_risk_score": 0.80},
    {"name": "Ruthenium (99.9%)", "category": "metal", "subcategory": "PGM", "unit": "troy_oz", "current_price": 480.0, "price_unit": "$/troy oz", "volatility_score": 0.70, "supply_risk_score": 0.72},
    {"name": "Iridium (99.9%)", "category": "metal", "subcategory": "PGM", "unit": "troy_oz", "current_price": 4800.0, "price_unit": "$/troy oz", "volatility_score": 0.72, "supply_risk_score": 0.75},
    {"name": "Antimony (99.65% ingot)", "category": "metal", "subcategory": "specialty", "unit": "kg", "current_price": 6.80, "price_unit": "$/kg", "volatility_score": 0.65, "supply_risk_score": 0.78},
    {"name": "Bismuth (99.99%)", "category": "metal", "subcategory": "specialty", "unit": "kg", "current_price": 6.20, "price_unit": "$/kg", "volatility_score": 0.60, "supply_risk_score": 0.62},
    {"name": "Selenium (99.5%)", "category": "metal", "subcategory": "specialty", "unit": "kg", "current_price": 22.0, "price_unit": "$/kg", "volatility_score": 0.58, "supply_risk_score": 0.60},
    {"name": "Tellurium (99.999%)", "category": "metal", "subcategory": "specialty", "unit": "kg", "current_price": 65.0, "price_unit": "$/kg", "volatility_score": 0.72, "supply_risk_score": 0.78},
    {"name": "Beryllium (99.0% metal)", "category": "metal", "subcategory": "specialty", "unit": "kg", "current_price": 870.0, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.75},

    # PROCESS CHEMICALS
    {"name": "Hydrofluoric Acid (49%)", "category": "chemical", "subcategory": "etchant", "unit": "kg", "current_price": 2.80, "price_unit": "$/kg", "volatility_score": 0.40, "supply_risk_score": 0.55, "description": "Critical etchant in semiconductor fab"},
    {"name": "Sulfuric Acid (Electronic grade)", "category": "chemical", "subcategory": "etchant", "unit": "kg", "current_price": 0.18, "price_unit": "$/kg", "volatility_score": 0.35, "supply_risk_score": 0.30},
    {"name": "Isopropyl Alcohol (semiconductor grade)", "category": "chemical", "subcategory": "solvent", "unit": "liter", "current_price": 1.45, "price_unit": "$/L", "volatility_score": 0.38, "supply_risk_score": 0.35},
    {"name": "N-Methyl-2-Pyrrolidone (NMP)", "category": "chemical", "subcategory": "solvent", "unit": "liter", "current_price": 2.90, "price_unit": "$/L", "volatility_score": 0.42, "supply_risk_score": 0.45},
    {"name": "Acetone (electronic grade)", "category": "chemical", "subcategory": "solvent", "unit": "liter", "current_price": 0.85, "price_unit": "$/L", "volatility_score": 0.35, "supply_risk_score": 0.28},
    {"name": "TMAH Developer (2.38%)", "category": "chemical", "subcategory": "developer", "unit": "liter", "current_price": 8.50, "price_unit": "$/L", "volatility_score": 0.35, "supply_risk_score": 0.45},
    {"name": "Phosphoric Acid (electronic grade)", "category": "chemical", "subcategory": "etchant", "unit": "kg", "current_price": 0.95, "price_unit": "$/kg", "volatility_score": 0.32, "supply_risk_score": 0.35},
    {"name": "Ammonium Fluoride (40%)", "category": "chemical", "subcategory": "etchant", "unit": "kg", "current_price": 3.50, "price_unit": "$/kg", "volatility_score": 0.38, "supply_risk_score": 0.42},
    {"name": "Hydrogen Peroxide (31% ULSI)", "category": "chemical", "subcategory": "cleaning", "unit": "kg", "current_price": 1.20, "price_unit": "$/kg", "volatility_score": 0.30, "supply_risk_score": 0.30},
    {"name": "Tetramethylsilane (TMS)", "category": "chemical", "subcategory": "CVD precursor", "unit": "kg", "current_price": 28.0, "price_unit": "$/kg", "volatility_score": 0.45, "supply_risk_score": 0.50},
    {"name": "TEOS (Tetraethyl Orthosilicate)", "category": "chemical", "subcategory": "CVD precursor", "unit": "kg", "current_price": 18.0, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.45},
    {"name": "Tungsten Hexafluoride (WF6)", "category": "chemical", "subcategory": "CVD precursor", "unit": "kg", "current_price": 180.0, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.60},
    {"name": "Trimethylaluminum (TMA)", "category": "chemical", "subcategory": "ALD precursor", "unit": "kg", "current_price": 250.0, "price_unit": "$/kg", "volatility_score": 0.50, "supply_risk_score": 0.55},
    {"name": "Silane (SiH4)", "category": "chemical", "subcategory": "CVD precursor", "unit": "kg", "current_price": 45.0, "price_unit": "$/kg", "volatility_score": 0.45, "supply_risk_score": 0.50},
    {"name": "Nitrogen Trifluoride (NF3)", "category": "chemical", "subcategory": "cleaning gas", "unit": "kg", "current_price": 12.0, "price_unit": "$/kg", "volatility_score": 0.48, "supply_risk_score": 0.55},
    {"name": "Argon (ultra-high purity 99.9999%)", "category": "chemical", "subcategory": "process gas", "unit": "m³", "current_price": 3.80, "price_unit": "$/m³", "volatility_score": 0.28, "supply_risk_score": 0.25},
    {"name": "Nitrogen (ultra-high purity)", "category": "chemical", "subcategory": "process gas", "unit": "m³", "current_price": 0.45, "price_unit": "$/m³", "volatility_score": 0.20, "supply_risk_score": 0.15},
    {"name": "Helium (grade 5.0)", "category": "chemical", "subcategory": "process gas", "unit": "m³", "current_price": 28.0, "price_unit": "$/m³", "volatility_score": 0.65, "supply_risk_score": 0.70},
    {"name": "Dichlorosilane (DCS)", "category": "chemical", "subcategory": "CVD precursor", "unit": "kg", "current_price": 35.0, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.48},

    # POLYMERS & ENCAPSULANTS
    {"name": "Polycarbonate (optical grade)", "category": "polymer", "subcategory": "engineering plastic", "unit": "kg", "current_price": 3.80, "price_unit": "$/kg", "volatility_score": 0.40, "supply_risk_score": 0.35},
    {"name": "ABS (high-impact grade)", "category": "polymer", "subcategory": "engineering plastic", "unit": "kg", "current_price": 2.10, "price_unit": "$/kg", "volatility_score": 0.38, "supply_risk_score": 0.30},
    {"name": "PTFE (fine powder)", "category": "polymer", "subcategory": "fluoropolymer", "unit": "kg", "current_price": 12.50, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.45},
    {"name": "PEEK (unfilled granules)", "category": "polymer", "subcategory": "high-performance", "unit": "kg", "current_price": 95.0, "price_unit": "$/kg", "volatility_score": 0.45, "supply_risk_score": 0.50},
    {"name": "Polyimide Film (Kapton equivalent)", "category": "polymer", "subcategory": "film", "unit": "m²", "current_price": 28.0, "price_unit": "$/m²", "volatility_score": 0.40, "supply_risk_score": 0.55},
    {"name": "Silicone Encapsulant (LED grade)", "category": "polymer", "subcategory": "encapsulant", "unit": "kg", "current_price": 18.0, "price_unit": "$/kg", "volatility_score": 0.38, "supply_risk_score": 0.40},
    {"name": "Epoxy Molding Compound", "category": "polymer", "subcategory": "encapsulant", "unit": "kg", "current_price": 8.50, "price_unit": "$/kg", "volatility_score": 0.35, "supply_risk_score": 0.40},
    {"name": "Underfill Epoxy (flip-chip)", "category": "polymer", "subcategory": "adhesive", "unit": "kg", "current_price": 120.0, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.45},
    {"name": "Thermal Interface Material (TIM)", "category": "polymer", "subcategory": "thermal", "unit": "kg", "current_price": 45.0, "price_unit": "$/kg", "volatility_score": 0.38, "supply_risk_score": 0.42},
    {"name": "Parylene (CVD coating)", "category": "polymer", "subcategory": "coating", "unit": "kg", "current_price": 380.0, "price_unit": "$/kg", "volatility_score": 0.45, "supply_risk_score": 0.50},

    # PCB MATERIALS
    {"name": "FR4 Laminate (1.6mm, 2oz Cu)", "category": "pcb", "subcategory": "substrate", "unit": "m²", "current_price": 22.0, "price_unit": "$/m²", "volatility_score": 0.40, "supply_risk_score": 0.45, "description": "Standard PCB substrate for consumer electronics"},
    {"name": "Rogers RO4350B Laminate", "category": "pcb", "subcategory": "high-frequency substrate", "unit": "m²", "current_price": 85.0, "price_unit": "$/m²", "volatility_score": 0.38, "supply_risk_score": 0.50},
    {"name": "Solder Mask (LPI Green)", "category": "pcb", "subcategory": "coating", "unit": "liter", "current_price": 18.0, "price_unit": "$/L", "volatility_score": 0.30, "supply_risk_score": 0.30},
    {"name": "SAC305 Solder Paste", "category": "pcb", "subcategory": "solder", "unit": "kg", "current_price": 48.0, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.42},
    {"name": "Electroless Nickel / Immersion Gold (ENIG)", "category": "pcb", "subcategory": "surface finish", "unit": "m²", "current_price": 35.0, "price_unit": "$/m²", "volatility_score": 0.50, "supply_risk_score": 0.40},
    {"name": "Electroless Copper Plating Solution", "category": "pcb", "subcategory": "plating", "unit": "liter", "current_price": 12.0, "price_unit": "$/L", "volatility_score": 0.38, "supply_risk_score": 0.38},
    {"name": "Prepreg (7628 style)", "category": "pcb", "subcategory": "substrate", "unit": "m²", "current_price": 8.50, "price_unit": "$/m²", "volatility_score": 0.35, "supply_risk_score": 0.40},
    {"name": "Copper Clad Laminate (CCL)", "category": "pcb", "subcategory": "substrate", "unit": "m²", "current_price": 18.0, "price_unit": "$/m²", "volatility_score": 0.50, "supply_risk_score": 0.42},
    {"name": "Conductive Silver Ink", "category": "pcb", "subcategory": "ink", "unit": "kg", "current_price": 280.0, "price_unit": "$/kg", "volatility_score": 0.58, "supply_risk_score": 0.45},
    {"name": "Dry Film Photoresist (PCB)", "category": "pcb", "subcategory": "lithography", "unit": "m²", "current_price": 4.50, "price_unit": "$/m²", "volatility_score": 0.32, "supply_risk_score": 0.42},

    # DISPLAY & OPTICAL
    {"name": "ITO (Indium Tin Oxide) Coated Glass", "category": "display", "subcategory": "transparent conductor", "unit": "m²", "current_price": 65.0, "price_unit": "$/m²", "volatility_score": 0.65, "supply_risk_score": 0.72, "description": "Transparent electrode for touchscreens and LCDs"},
    {"name": "LCD Glass Substrate (Gen 8.5)", "category": "display", "subcategory": "glass", "unit": "m²", "current_price": 38.0, "price_unit": "$/m²", "volatility_score": 0.40, "supply_risk_score": 0.50},
    {"name": "OLED Encapsulation Film", "category": "display", "subcategory": "film", "unit": "m²", "current_price": 55.0, "price_unit": "$/m²", "volatility_score": 0.50, "supply_risk_score": 0.58},
    {"name": "Liquid Crystal Material", "category": "display", "subcategory": "active material", "unit": "kg", "current_price": 350.0, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.62},
    {"name": "Polarizer Film", "category": "display", "subcategory": "film", "unit": "m²", "current_price": 28.0, "price_unit": "$/m²", "volatility_score": 0.42, "supply_risk_score": 0.55},
    {"name": "Quantum Dots (Cd-free, red/green)", "category": "display", "subcategory": "QD material", "unit": "g", "current_price": 8.50, "price_unit": "$/g", "volatility_score": 0.60, "supply_risk_score": 0.65},
    {"name": "Mini-LED Chip (0402 size)", "category": "display", "subcategory": "LED", "unit": "each", "current_price": 0.08, "price_unit": "$/chip", "volatility_score": 0.45, "supply_risk_score": 0.52},
    {"name": "Anti-Reflection Coating Material", "category": "display", "subcategory": "coating", "unit": "liter", "current_price": 180.0, "price_unit": "$/L", "volatility_score": 0.40, "supply_risk_score": 0.48},

    # OPTICAL FIBERS & PHOTONICS
    {"name": "Single-Mode Optical Fiber (SMF-28)", "category": "optical", "subcategory": "fiber", "unit": "km", "current_price": 42.0, "price_unit": "$/km", "volatility_score": 0.35, "supply_risk_score": 0.38, "description": "Telecom-grade single-mode fiber optic cable"},
    {"name": "Multi-Mode Optical Fiber (OM4)", "category": "optical", "subcategory": "fiber", "unit": "km", "current_price": 38.0, "price_unit": "$/km", "volatility_score": 0.33, "supply_risk_score": 0.35},
    {"name": "Erbium-Doped Fiber", "category": "optical", "subcategory": "specialty fiber", "unit": "m", "current_price": 12.0, "price_unit": "$/m", "volatility_score": 0.45, "supply_risk_score": 0.55},
    {"name": "Preform (Silica for fiber drawing)", "category": "optical", "subcategory": "raw material", "unit": "kg", "current_price": 85.0, "price_unit": "$/kg", "volatility_score": 0.38, "supply_risk_score": 0.45},
    {"name": "High-Power Laser Diode (980nm)", "category": "optical", "subcategory": "photonic", "unit": "each", "current_price": 45.0, "price_unit": "$/unit", "volatility_score": 0.45, "supply_risk_score": 0.55},
    {"name": "Optical Isolator", "category": "optical", "subcategory": "component", "unit": "each", "current_price": 28.0, "price_unit": "$/unit", "volatility_score": 0.38, "supply_risk_score": 0.50},

    # PACKAGING MATERIALS
    {"name": "Flip-Chip Bumps (SnAg solder)", "category": "packaging", "subcategory": "interconnect", "unit": "each (1000)", "current_price": 0.85, "price_unit": "$/1k bumps", "volatility_score": 0.50, "supply_risk_score": 0.45},
    {"name": "Wire Bond Wire (Au 25µm)", "category": "packaging", "subcategory": "interconnect", "unit": "km", "current_price": 1200.0, "price_unit": "$/km", "volatility_score": 0.55, "supply_risk_score": 0.40},
    {"name": "Wire Bond Wire (Cu 25µm)", "category": "packaging", "subcategory": "interconnect", "unit": "km", "current_price": 95.0, "price_unit": "$/km", "volatility_score": 0.52, "supply_risk_score": 0.38},
    {"name": "Lead Frame (copper alloy)", "category": "packaging", "subcategory": "frame", "unit": "each", "current_price": 0.12, "price_unit": "$/unit", "volatility_score": 0.45, "supply_risk_score": 0.38},
    {"name": "Substrate (BGA, 0.4mm pitch)", "category": "packaging", "subcategory": "substrate", "unit": "each", "current_price": 1.80, "price_unit": "$/unit", "volatility_score": 0.42, "supply_risk_score": 0.48},
    {"name": "Die Attach Film (DAF)", "category": "packaging", "subcategory": "adhesive", "unit": "m²", "current_price": 45.0, "price_unit": "$/m²", "volatility_score": 0.40, "supply_risk_score": 0.45},
    {"name": "Dicing Tape", "category": "packaging", "subcategory": "process material", "unit": "roll", "current_price": 12.0, "price_unit": "$/roll", "volatility_score": 0.28, "supply_risk_score": 0.30},

    # THERMAL MANAGEMENT
    {"name": "Pyrolytic Graphite Sheet (PGS)", "category": "thermal", "subcategory": "heat spreader", "unit": "m²", "current_price": 280.0, "price_unit": "$/m²", "volatility_score": 0.45, "supply_risk_score": 0.55},
    {"name": "Vapor Chamber (copper, 5mm)", "category": "thermal", "subcategory": "heat pipe", "unit": "each", "current_price": 3.80, "price_unit": "$/unit", "volatility_score": 0.38, "supply_risk_score": 0.42},
    {"name": "Aluminum Heat Sink (extruded)", "category": "thermal", "subcategory": "heat sink", "unit": "kg", "current_price": 4.50, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.35},
    {"name": "Diamond Heat Spreader (CVD)", "category": "thermal", "subcategory": "heat spreader", "unit": "cm²", "current_price": 85.0, "price_unit": "$/cm²", "volatility_score": 0.55, "supply_risk_score": 0.65},
    {"name": "Thermal Paste (silver-filled)", "category": "thermal", "subcategory": "TIM", "unit": "kg", "current_price": 85.0, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.40},

    # POWER & MAGNETIC
    {"name": "Ferrite Core (MnZn, toroidal)", "category": "magnetic", "subcategory": "core", "unit": "each", "current_price": 0.85, "price_unit": "$/unit", "volatility_score": 0.40, "supply_risk_score": 0.55},
    {"name": "Amorphous Alloy Core (Fe-Si-B)", "category": "magnetic", "subcategory": "core", "unit": "kg", "current_price": 18.0, "price_unit": "$/kg", "volatility_score": 0.42, "supply_risk_score": 0.50},
    {"name": "Copper Magnet Wire (AWG 24, enameled)", "category": "magnetic", "subcategory": "winding", "unit": "kg", "current_price": 11.0, "price_unit": "$/kg", "volatility_score": 0.55, "supply_risk_score": 0.38},
    {"name": "MLCC Capacitor (0402, 100nF, X7R)", "category": "passive", "subcategory": "capacitor", "unit": "each (1000)", "current_price": 0.018, "price_unit": "$/1k pcs", "volatility_score": 0.55, "supply_risk_score": 0.58},
    {"name": "Tantalum Capacitor (10µF, 10V)", "category": "passive", "subcategory": "capacitor", "unit": "each", "current_price": 0.45, "price_unit": "$/unit", "volatility_score": 0.65, "supply_risk_score": 0.70},
    {"name": "Aluminum Electrolytic Capacitor (1000µF)", "category": "passive", "subcategory": "capacitor", "unit": "each", "current_price": 0.35, "price_unit": "$/unit", "volatility_score": 0.42, "supply_risk_score": 0.45},
    {"name": "Thin Film Resistor (0402, 1%)", "category": "passive", "subcategory": "resistor", "unit": "each (1000)", "current_price": 0.012, "price_unit": "$/1k pcs", "volatility_score": 0.35, "supply_risk_score": 0.40},
    {"name": "SMD Inductor (1µH, 5A)", "category": "passive", "subcategory": "inductor", "unit": "each", "current_price": 0.28, "price_unit": "$/unit", "volatility_score": 0.40, "supply_risk_score": 0.45},
    {"name": "Crystal Oscillator (32MHz, ±20ppm)", "category": "passive", "subcategory": "timing", "unit": "each", "current_price": 0.85, "price_unit": "$/unit", "volatility_score": 0.38, "supply_risk_score": 0.48},

    # CONNECTIVITY & SENSORS
    {"name": "USB-C Connector (2.0, receptacle)", "category": "connector", "subcategory": "USB", "unit": "each", "current_price": 0.42, "price_unit": "$/unit", "volatility_score": 0.38, "supply_risk_score": 0.42},
    {"name": "HDMI 2.1 Connector", "category": "connector", "subcategory": "video", "unit": "each", "current_price": 1.20, "price_unit": "$/unit", "volatility_score": 0.35, "supply_risk_score": 0.40},
    {"name": "FPC Connector (0.5mm pitch, 30-pin)", "category": "connector", "subcategory": "board-to-board", "unit": "each", "current_price": 0.38, "price_unit": "$/unit", "volatility_score": 0.35, "supply_risk_score": 0.42},
    {"name": "Hall Effect Sensor (3-axis)", "category": "sensor", "subcategory": "magnetic", "unit": "each", "current_price": 1.85, "price_unit": "$/unit", "volatility_score": 0.38, "supply_risk_score": 0.45},
    {"name": "Barometric Pressure Sensor", "category": "sensor", "subcategory": "environmental", "unit": "each", "current_price": 2.40, "price_unit": "$/unit", "volatility_score": 0.35, "supply_risk_score": 0.42},
    {"name": "ToF LiDAR Sensor", "category": "sensor", "subcategory": "depth", "unit": "each", "current_price": 12.0, "price_unit": "$/unit", "volatility_score": 0.50, "supply_risk_score": 0.55},
    {"name": "Wi-Fi 6E Module (802.11ax)", "category": "wireless", "subcategory": "WiFi", "unit": "each", "current_price": 4.80, "price_unit": "$/unit", "volatility_score": 0.42, "supply_risk_score": 0.50},
    {"name": "5G Sub-6GHz Module", "category": "wireless", "subcategory": "cellular", "unit": "each", "current_price": 18.0, "price_unit": "$/unit", "volatility_score": 0.45, "supply_risk_score": 0.55},
    {"name": "Bluetooth 5.3 SoC", "category": "wireless", "subcategory": "BT", "unit": "each", "current_price": 1.20, "price_unit": "$/unit", "volatility_score": 0.38, "supply_risk_score": 0.45},
    {"name": "UWB Ranging Chip", "category": "wireless", "subcategory": "UWB", "unit": "each", "current_price": 3.50, "price_unit": "$/unit", "volatility_score": 0.42, "supply_risk_score": 0.48},

    # POWER CONVERSION
    {"name": "SiC MOSFET (1200V, 80A)", "category": "power", "subcategory": "switch", "unit": "each", "current_price": 8.50, "price_unit": "$/unit", "volatility_score": 0.50, "supply_risk_score": 0.55},
    {"name": "GaN HEMT (650V, 60A)", "category": "power", "subcategory": "switch", "unit": "each", "current_price": 6.80, "price_unit": "$/unit", "volatility_score": 0.48, "supply_risk_score": 0.52},
    {"name": "IGBT Module (1200V, 150A)", "category": "power", "subcategory": "switch", "unit": "each", "current_price": 28.0, "price_unit": "$/unit", "volatility_score": 0.45, "supply_risk_score": 0.48},
    {"name": "Fast Recovery Diode (1200V, 30A)", "category": "power", "subcategory": "diode", "unit": "each", "current_price": 3.20, "price_unit": "$/unit", "volatility_score": 0.40, "supply_risk_score": 0.42},

    # COOLING & SUBSTRATE
    {"name": "Alumina Substrate (Al2O3, 96%)", "category": "substrate", "subcategory": "ceramic", "unit": "each", "current_price": 1.20, "price_unit": "$/unit", "volatility_score": 0.35, "supply_risk_score": 0.38},
    {"name": "Aluminum Nitride Substrate (AlN)", "category": "substrate", "subcategory": "ceramic", "unit": "each", "current_price": 4.80, "price_unit": "$/unit", "volatility_score": 0.42, "supply_risk_score": 0.48},
    {"name": "Beryllium Oxide Substrate (BeO)", "category": "substrate", "subcategory": "ceramic", "unit": "each", "current_price": 12.0, "price_unit": "$/unit", "volatility_score": 0.50, "supply_risk_score": 0.62},
    {"name": "Low-Temperature Co-fired Ceramic (LTCC)", "category": "substrate", "subcategory": "ceramic", "unit": "each", "current_price": 2.80, "price_unit": "$/unit", "volatility_score": 0.40, "supply_risk_score": 0.45},

    # ENERGY STORAGE COMPONENTS
    {"name": "Supercapacitor (350F, 2.7V)", "category": "energy", "subcategory": "supercap", "unit": "each", "current_price": 4.20, "price_unit": "$/unit", "volatility_score": 0.40, "supply_risk_score": 0.45},
    {"name": "18650 Lithium Cell (3.6V, 3.0Ah)", "category": "energy", "subcategory": "cell", "unit": "each", "current_price": 3.80, "price_unit": "$/unit", "volatility_score": 0.58, "supply_risk_score": 0.52},
    {"name": "Prismatic LFP Cell (200Ah)", "category": "energy", "subcategory": "cell", "unit": "each", "current_price": 55.0, "price_unit": "$/unit", "volatility_score": 0.52, "supply_risk_score": 0.50},
    {"name": "Pouch Cell NMC (60Ah)", "category": "energy", "subcategory": "cell", "unit": "each", "current_price": 42.0, "price_unit": "$/unit", "volatility_score": 0.55, "supply_risk_score": 0.52},

    # MANUFACTURING CONSUMABLES
    {"name": "Diamond Grinding Wheel (resin bond)", "category": "consumable", "subcategory": "abrasive", "unit": "each", "current_price": 180.0, "price_unit": "$/wheel", "volatility_score": 0.35, "supply_risk_score": 0.40},
    {"name": "Chemical Mechanical Polish Pad", "category": "consumable", "subcategory": "polishing", "unit": "each", "current_price": 95.0, "price_unit": "$/pad", "volatility_score": 0.35, "supply_risk_score": 0.42},
    {"name": "Wafer Dicing Blade (diamond)", "category": "consumable", "subcategory": "cutting", "unit": "each", "current_price": 45.0, "price_unit": "$/blade", "volatility_score": 0.30, "supply_risk_score": 0.38},
    {"name": "Cleanroom Wipes (IPA pre-wet)", "category": "consumable", "subcategory": "cleaning", "unit": "bag (150pcs)", "current_price": 28.0, "price_unit": "$/bag", "volatility_score": 0.22, "supply_risk_score": 0.25},
    {"name": "Anti-Static Packaging Bags", "category": "consumable", "subcategory": "packaging", "unit": "pack (100pcs)", "current_price": 12.0, "price_unit": "$/pack", "volatility_score": 0.20, "supply_risk_score": 0.22},
]

assert len(MATERIALS) >= 120, f"Only {len(MATERIALS)} materials defined"

# ─── Supplier Templates ───────────────────────────────────────────────────────

SUPPLIER_TEMPLATES = [
    # Semiconductor suppliers
    {"name": "Western Silicon Technologies", "hub_idx": 0, "offset": (0.12, -0.08), "cats": ["semiconductor"], "lead": 14, "rel": 0.92, "risk": 0.22, "fin": 0.88, "price_c": 0.78},
    {"name": "Pacific Wafer Solutions", "hub_idx": 0, "offset": (-0.15, 0.20), "cats": ["semiconductor"], "lead": 10, "rel": 0.88, "risk": 0.25, "fin": 0.82, "price_c": 0.82},
    {"name": "Desert Fab Materials Inc.", "hub_idx": 1, "offset": (0.05, -0.12), "cats": ["semiconductor", "chemical"], "lead": 7, "rel": 0.85, "risk": 0.28, "fin": 0.80, "price_c": 0.88},
    {"name": "Lone Star Semiconductor", "hub_idx": 2, "offset": (0.10, 0.08), "cats": ["semiconductor", "pcb"], "lead": 8, "rel": 0.90, "risk": 0.24, "fin": 0.85, "price_c": 0.80},
    {"name": "NW Compound Semiconductor", "hub_idx": 20, "offset": (0.08, -0.15), "cats": ["semiconductor"], "lead": 12, "rel": 0.87, "risk": 0.22, "fin": 0.83, "price_c": 0.76},
    {"name": "High Desert Wafers LLC", "hub_idx": 4, "offset": (-0.10, 0.12), "cats": ["semiconductor"], "lead": 9, "rel": 0.86, "risk": 0.26, "fin": 0.80, "price_c": 0.84},
    {"name": "Triangle Tech Materials", "hub_idx": 17, "offset": (0.12, -0.10), "cats": ["semiconductor", "pcb"], "lead": 11, "rel": 0.89, "risk": 0.23, "fin": 0.84, "price_c": 0.79},
    {"name": "Cascade Advanced Devices", "hub_idx": 3, "offset": (-0.08, 0.15), "cats": ["semiconductor"], "lead": 13, "rel": 0.91, "risk": 0.21, "fin": 0.86, "price_c": 0.77},
    {"name": "Centennial Electronics Supply", "hub_idx": 21, "offset": (0.05, 0.08), "cats": ["semiconductor", "sensor"], "lead": 10, "rel": 0.88, "risk": 0.24, "fin": 0.82, "price_c": 0.81},
    {"name": "Research Tri-State Components", "hub_idx": 17, "offset": (-0.12, -0.08), "cats": ["semiconductor", "wireless"], "lead": 8, "rel": 0.87, "risk": 0.25, "fin": 0.83, "price_c": 0.83},

    # Battery material suppliers
    {"name": "Great Lakes Battery Materials", "hub_idx": 5, "offset": (0.08, 0.10), "cats": ["battery"], "lead": 5, "rel": 0.88, "risk": 0.30, "fin": 0.82, "price_c": 0.85},
    {"name": "Nevada Lithium Processing", "hub_idx": 6, "offset": (-0.10, 0.08), "cats": ["battery"], "lead": 7, "rel": 0.85, "risk": 0.28, "fin": 0.80, "price_c": 0.88},
    {"name": "Tennessee Battery Chem Co.", "hub_idx": 7, "offset": (0.12, -0.12), "cats": ["battery", "chemical"], "lead": 6, "rel": 0.87, "risk": 0.29, "fin": 0.81, "price_c": 0.86},
    {"name": "EV Materials Corp", "hub_idx": 5, "offset": (-0.15, -0.10), "cats": ["battery"], "lead": 8, "rel": 0.86, "risk": 0.32, "fin": 0.79, "price_c": 0.84},
    {"name": "Southwest Cathode Materials", "hub_idx": 6, "offset": (0.18, 0.05), "cats": ["battery"], "lead": 9, "rel": 0.84, "risk": 0.30, "fin": 0.78, "price_c": 0.82},
    {"name": "Midwest Anode Solutions", "hub_idx": 5, "offset": (0.05, -0.18), "cats": ["battery", "metal"], "lead": 6, "rel": 0.89, "risk": 0.27, "fin": 0.83, "price_c": 0.87},

    # Rare earth suppliers
    {"name": "Appalachian Rare Earth Refining", "hub_idx": 8, "offset": (0.08, 0.06), "cats": ["rare_earth"], "lead": 21, "rel": 0.78, "risk": 0.55, "fin": 0.72, "price_c": 0.72},
    {"name": "Mountain Pass Materials Inc.", "hub_idx": 9, "offset": (-0.05, 0.12), "cats": ["rare_earth", "magnet"], "lead": 14, "rel": 0.82, "risk": 0.48, "fin": 0.76, "price_c": 0.78},
    {"name": "NdFeB Magnet Works", "hub_idx": 8, "offset": (-0.12, -0.08), "cats": ["rare_earth"], "lead": 28, "rel": 0.75, "risk": 0.60, "fin": 0.68, "price_c": 0.68},
    {"name": "Western Magnetics USA", "hub_idx": 9, "offset": (0.15, -0.05), "cats": ["rare_earth"], "lead": 18, "rel": 0.80, "risk": 0.52, "fin": 0.74, "price_c": 0.74},

    # Chemical suppliers
    {"name": "Gulf Coast Specialty Chem", "hub_idx": 10, "offset": (0.08, -0.10), "cats": ["chemical"], "lead": 3, "rel": 0.92, "risk": 0.35, "fin": 0.85, "price_c": 0.88},
    {"name": "Bayou Chemical Solutions", "hub_idx": 11, "offset": (-0.10, 0.08), "cats": ["chemical"], "lead": 4, "rel": 0.90, "risk": 0.38, "fin": 0.83, "price_c": 0.86},
    {"name": "Minnesota Specialty Gases", "hub_idx": 19, "offset": (0.06, 0.10), "cats": ["chemical"], "lead": 2, "rel": 0.94, "risk": 0.22, "fin": 0.88, "price_c": 0.82},
    {"name": "Albany Process Chemicals", "hub_idx": 24, "offset": (-0.08, -0.06), "cats": ["chemical"], "lead": 3, "rel": 0.91, "risk": 0.25, "fin": 0.84, "price_c": 0.84},
    {"name": "Great Lakes Gas Supply", "hub_idx": 5, "offset": (0.10, 0.12), "cats": ["chemical"], "lead": 1, "rel": 0.93, "risk": 0.28, "fin": 0.86, "price_c": 0.80},
    {"name": "Texas Process Chemicals", "hub_idx": 10, "offset": (-0.12, 0.06), "cats": ["chemical", "pcb"], "lead": 3, "rel": 0.90, "risk": 0.36, "fin": 0.82, "price_c": 0.87},

    # Metal suppliers
    {"name": "Buckeye Metals & Alloys", "hub_idx": 12, "offset": (0.06, -0.08), "cats": ["metal"], "lead": 5, "rel": 0.88, "risk": 0.28, "fin": 0.82, "price_c": 0.82},
    {"name": "Appalachian Aluminum Works", "hub_idx": 13, "offset": (-0.08, 0.10), "cats": ["metal"], "lead": 7, "rel": 0.86, "risk": 0.32, "fin": 0.80, "price_c": 0.84},
    {"name": "Sonoran Copper Refinery", "hub_idx": 14, "offset": (0.10, -0.06), "cats": ["metal"], "lead": 6, "rel": 0.90, "risk": 0.27, "fin": 0.85, "price_c": 0.80},
    {"name": "Great Plains Precious Metals", "hub_idx": 12, "offset": (-0.12, -0.10), "cats": ["metal"], "lead": 4, "rel": 0.89, "risk": 0.30, "fin": 0.84, "price_c": 0.81},
    {"name": "Western Specialty Metals", "hub_idx": 14, "offset": (0.08, 0.12), "cats": ["metal", "rare_earth"], "lead": 10, "rel": 0.84, "risk": 0.35, "fin": 0.78, "price_c": 0.78},
    {"name": "Eastern Refractory Metals", "hub_idx": 24, "offset": (0.10, -0.08), "cats": ["metal"], "lead": 14, "rel": 0.82, "risk": 0.35, "fin": 0.78, "price_c": 0.76},

    # Optical/display suppliers
    {"name": "New England Photonics", "hub_idx": 15, "offset": (0.05, -0.10), "cats": ["optical", "display"], "lead": 10, "rel": 0.90, "risk": 0.20, "fin": 0.86, "price_c": 0.76},
    {"name": "Hudson Valley Glassworks", "hub_idx": 16, "offset": (-0.08, 0.08), "cats": ["optical", "display"], "lead": 12, "rel": 0.88, "risk": 0.20, "fin": 0.84, "price_c": 0.78},
    {"name": "Pacific Display Materials", "hub_idx": 18, "offset": (0.05, -0.08), "cats": ["display", "optical"], "lead": 14, "rel": 0.86, "risk": 0.24, "fin": 0.81, "price_c": 0.80},
    {"name": "SoCal Photonics Group", "hub_idx": 18, "offset": (-0.10, 0.12), "cats": ["optical", "display", "semiconductor"], "lead": 11, "rel": 0.87, "risk": 0.22, "fin": 0.83, "price_c": 0.79},

    # PCB material suppliers
    {"name": "SoCal Circuit Materials", "hub_idx": 18, "offset": (0.12, 0.08), "cats": ["pcb"], "lead": 7, "rel": 0.87, "risk": 0.24, "fin": 0.82, "price_c": 0.82},
    {"name": "Lone Star PCB Supply", "hub_idx": 2, "offset": (-0.06, -0.12), "cats": ["pcb", "chemical"], "lead": 5, "rel": 0.89, "risk": 0.26, "fin": 0.83, "price_c": 0.85},
    {"name": "Great Lakes PCB Laminates", "hub_idx": 12, "offset": (0.12, 0.06), "cats": ["pcb"], "lead": 6, "rel": 0.88, "risk": 0.28, "fin": 0.82, "price_c": 0.83},

    # Polymer suppliers
    {"name": "Chicago Polymer Solutions", "hub_idx": 23, "offset": (0.08, -0.10), "cats": ["polymer"], "lead": 4, "rel": 0.90, "risk": 0.25, "fin": 0.84, "price_c": 0.82},
    {"name": "Midwest Engineering Plastics", "hub_idx": 23, "offset": (-0.10, 0.08), "cats": ["polymer", "thermal"], "lead": 5, "rel": 0.88, "risk": 0.26, "fin": 0.82, "price_c": 0.84},
    {"name": "Gulf Fluoropolymers Corp", "hub_idx": 10, "offset": (0.06, 0.10), "cats": ["polymer", "chemical"], "lead": 6, "rel": 0.86, "risk": 0.36, "fin": 0.80, "price_c": 0.83},
    {"name": "Northeast Specialty Polymers", "hub_idx": 15, "offset": (0.10, -0.06), "cats": ["polymer"], "lead": 5, "rel": 0.89, "risk": 0.22, "fin": 0.84, "price_c": 0.81},

    # Multi-category distribution
    {"name": "Atlanta Supply Chain Hub", "hub_idx": 22, "offset": (0.05, 0.08), "cats": ["semiconductor", "battery", "metal", "polymer"], "lead": 3, "rel": 0.86, "risk": 0.15, "fin": 0.82, "price_c": 0.90},
    {"name": "National Component Distributors", "hub_idx": 22, "offset": (-0.08, -0.06), "cats": ["passive", "connector", "sensor", "wireless"], "lead": 2, "rel": 0.88, "risk": 0.15, "fin": 0.84, "price_c": 0.88},
    {"name": "Americas Industrial Supply", "hub_idx": 12, "offset": (0.10, 0.15), "cats": ["metal", "polymer", "chemical", "consumable"], "lead": 3, "rel": 0.87, "risk": 0.25, "fin": 0.82, "price_c": 0.87},
    {"name": "Tristate Electronics Parts", "hub_idx": 24, "offset": (-0.06, 0.10), "cats": ["passive", "connector", "packaging"], "lead": 2, "rel": 0.90, "risk": 0.20, "fin": 0.85, "price_c": 0.85},
    {"name": "Pacific Coast Components", "hub_idx": 0, "offset": (-0.08, -0.12), "cats": ["passive", "power", "sensor", "connector"], "lead": 4, "rel": 0.88, "risk": 0.20, "fin": 0.83, "price_c": 0.86},
    {"name": "Central States Supply Co.", "hub_idx": 23, "offset": (0.12, 0.10), "cats": ["consumable", "polymer", "chemical"], "lead": 3, "rel": 0.89, "risk": 0.24, "fin": 0.83, "price_c": 0.86},
    {"name": "Southwest Materials Group", "hub_idx": 1, "offset": (-0.08, 0.14), "cats": ["metal", "chemical", "consumable"], "lead": 4, "rel": 0.87, "risk": 0.25, "fin": 0.81, "price_c": 0.85},

    # Thermal / packaging suppliers
    {"name": "Precision Packaging Materials", "hub_idx": 3, "offset": (0.10, -0.08), "cats": ["packaging", "consumable"], "lead": 5, "rel": 0.89, "risk": 0.22, "fin": 0.84, "price_c": 0.83},
    {"name": "Thermal Management Systems", "hub_idx": 0, "offset": (0.06, 0.14), "cats": ["thermal", "packaging"], "lead": 7, "rel": 0.87, "risk": 0.22, "fin": 0.82, "price_c": 0.80},
    {"name": "Heartland Ceramic Substrates", "hub_idx": 23, "offset": (-0.12, 0.06), "cats": ["substrate", "thermal"], "lead": 10, "rel": 0.85, "risk": 0.28, "fin": 0.80, "price_c": 0.78},
    {"name": "Pacific Ceramic Technologies", "hub_idx": 0, "offset": (0.14, -0.06), "cats": ["substrate", "semiconductor"], "lead": 12, "rel": 0.86, "risk": 0.24, "fin": 0.81, "price_c": 0.77},
    {"name": "Eastern Thermal Solutions", "hub_idx": 15, "offset": (-0.06, -0.12), "cats": ["thermal", "passive"], "lead": 8, "rel": 0.88, "risk": 0.21, "fin": 0.83, "price_c": 0.80},

    # Energy / power suppliers
    {"name": "Michigan Power Electronics", "hub_idx": 5, "offset": (0.14, -0.08), "cats": ["power", "energy"], "lead": 6, "rel": 0.87, "risk": 0.30, "fin": 0.82, "price_c": 0.82},
    {"name": "Western Energy Components", "hub_idx": 21, "offset": (-0.06, 0.14), "cats": ["power", "energy"], "lead": 7, "rel": 0.85, "risk": 0.26, "fin": 0.80, "price_c": 0.83},
    {"name": "Sunbelt Battery Systems", "hub_idx": 7, "offset": (0.10, 0.06), "cats": ["energy", "battery"], "lead": 5, "rel": 0.86, "risk": 0.28, "fin": 0.81, "price_c": 0.84},
    {"name": "Mid-Atlantic Power Components", "hub_idx": 8, "offset": (0.06, -0.14), "cats": ["power", "magnetic"], "lead": 6, "rel": 0.87, "risk": 0.30, "fin": 0.82, "price_c": 0.81},
]


def generate_price_history(base_price: float, material_id: int, days: int = 365) -> list:
    """Generate synthetic price history with realistic random walk + trend."""
    records = []
    price = base_price
    vol = random.uniform(0.005, 0.025)
    trend = random.uniform(-0.001, 0.002)
    for i in range(days, 0, -1):
        date = datetime.utcnow() - timedelta(days=i)
        price = max(price * 0.01, price * (1 + trend + random.gauss(0, vol)))
        records.append({"material_id": material_id, "date": date, "price": round(price, 4), "source": "synthetic"})
    return records


def generate_forecast(base_price: float, material_id: int, days: int = 90) -> list:
    """Generate 90-day simple forward forecast with expanding CI."""
    records = []
    price = base_price
    vol = random.uniform(0.006, 0.020)
    for i in range(1, days + 1):
        date = datetime.utcnow() + timedelta(days=i)
        price = max(price * 0.01, price * (1 + random.gauss(0.0005, vol)))
        ci_half = price * 0.04 * (i / days + 0.5)
        records.append({
            "material_id": material_id,
            "forecast_date": date,
            "predicted_price": round(price, 4),
            "lower_ci": round(price - ci_half, 4),
            "upper_ci": round(price + ci_half, 4),
            "model_version": "synthetic_v1",
        })
    return records


def seed():
    db = SessionLocal()
    try:
        # Clear existing data (idempotent reseed)
        for tbl in ["price_forecasts", "price_history", "cart_items", "orders",
                    "suppliers", "materials", "production_hubs"]:
            db.execute(__import__("sqlalchemy").text(f"DELETE FROM {tbl}"))
        db.commit()

        # ── Hubs ──
        print("Seeding production hubs...")
        hub_objs = []
        for h in HUBS:
            hub = ProductionHub(
                name=h["name"], city=h["city"], state=h["state"],
                latitude=h["lat"], longitude=h["lng"],
                hub_type=h["hub_type"], specialization=h["specialization"],
                description=f"Major {h['hub_type']} manufacturing cluster in {h['city']}, {h['state']}",
                active_suppliers=random.randint(8, 25),
                risk_index=h["risk_index"],
            )
            db.add(hub)
            hub_objs.append(hub)
        db.commit()
        for hub in hub_objs:
            db.refresh(hub)
        print(f"  {len(hub_objs)} hubs seeded")

        # ── Materials ──
        print("Seeding materials...")
        mat_objs = []
        for m in MATERIALS:
            mat = Material(
                name=m["name"],
                category=m["category"],
                subcategory=m.get("subcategory"),
                unit=m["unit"],
                description=m.get("description"),
                current_price=m.get("current_price"),
                price_unit=m.get("price_unit"),
                volatility_score=m.get("volatility_score", 0.5),
                supply_risk_score=m.get("supply_risk_score", 0.5),
                fred_series_id=m.get("fred_series_id"),
                alpha_vantage_symbol=m.get("alpha_vantage_symbol"),
            )
            db.add(mat)
            mat_objs.append(mat)
        db.commit()
        for mat in mat_objs:
            db.refresh(mat)
        print(f"  {len(mat_objs)} materials seeded")

        # ── Price history + forecasts ──
        print("Seeding price history and forecasts...")
        ph_count = 0
        pf_count = 0
        for mat in mat_objs:
            base = mat.current_price or 10.0
            hist = generate_price_history(base, mat.id, days=365)
            for h in hist:
                db.add(PriceHistory(**h))
            ph_count += len(hist)
            fc = generate_forecast(hist[-1]["price"], mat.id, days=90)
            for f in fc:
                db.add(PriceForecast(**f))
            pf_count += len(fc)
        db.commit()
        print(f"  {ph_count} price history rows, {pf_count} forecast rows seeded")

        # ── Suppliers ──
        print("Seeding suppliers...")
        # Map category strings to material IDs
        cat_to_mat_ids: dict[str, list[int]] = {}
        for mat in mat_objs:
            cat_to_mat_ids.setdefault(mat.category, []).append(mat.id)

        sup_count = 0
        for tmpl in SUPPLIER_TEMPLATES:
            hub = hub_objs[tmpl["hub_idx"]]
            lat = hub.latitude + tmpl["offset"][0]
            lng = hub.longitude + tmpl["offset"][1]
            # Collect material IDs for this supplier's categories
            mat_ids = []
            for cat in tmpl["cats"]:
                ids = cat_to_mat_ids.get(cat, [])
                mat_ids.extend(random.sample(ids, min(8, len(ids))))
            mat_ids = list(set(mat_ids))[:40]  # cap at 40

            sup = Supplier(
                name=tmpl["name"],
                hub_id=hub.id,
                latitude=lat,
                longitude=lng,
                city=hub.city,
                state=hub.state,
                materials_supplied=",".join(str(i) for i in mat_ids),
                lead_time_days=tmpl["lead"],
                reliability_score=tmpl["rel"],
                risk_score=tmpl["risk"],
                financial_health=tmpl["fin"],
                geo_risk=tmpl["risk"] * 0.8,
                weather_risk=random.uniform(0.1, 0.4),
                price_competitiveness=tmpl["price_c"],
                is_domestic=True,
                certifications="ISO9001,RoHS,REACH",
                description=f"Specialized {', '.join(tmpl['cats'])} supplier based in {hub.city}, {hub.state}",
            )
            db.add(sup)
            sup_count += 1
        db.commit()
        print(f"  {sup_count} suppliers seeded")

        print(f"\n✓ Seed complete: {len(hub_objs)} hubs | {len(mat_objs)} materials | {sup_count} suppliers")

    finally:
        db.close()


def run_seed(reset: bool = False) -> None:
    """Entry point called by manage.py."""
    if reset:
        from app.core.database import engine  # noqa
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("Database reset complete.")
    seed()


if __name__ == "__main__":
    seed()
