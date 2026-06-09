"""
Shared freight and transport constants.

All values are cited from published industry sources. Previously duplicated
between costs.py and sourcing.py -- now defined once and imported by both.
"""

# -- Physical / unit constants ------------------------------------------------
KM_PER_MILE = 1.60934
LBS_PER_KG = 2.20462
CWT_PER_LB = 0.01  # 1 hundredweight = 100 lbs

# -- Freight cost constants (cited) -------------------------------------------
# ATRI 2023: An Analysis of the Operational Costs of Trucking
TL_RATE_USD_PER_MILE = 2.271

# FreightWaves SONAR Q4 2023 + Old Dominion 2023 published tariff
LTL_BASE_FEE_USD = 75.0
LTL_RATE_USD_PER_CWT_MILE = 0.43

# BTS Commodity Flow Survey 2022
GROUND_KM_PER_DAY = 800.0

# EPA SmartWay 2023 heavy-duty truck factor: 161.8 g CO2e / ton-mile
CO2_G_PER_TON_MILE = 161.8

# -- International air freight constants (electronics, avg ~0.05 kg/unit) ------
# IATA Cargo Market Report 2023: average all-in airfreight rate for electronics
# to US: $3-7/kg depending on origin; $5.0/kg is mid-market.
# Minimum consignment handling charge (DHL/FedEx commercial): ~$150 base.
AIR_FREIGHT_BASE_USD = 150.0
AIR_FREIGHT_RATE_USD_PER_KG = 5.0
