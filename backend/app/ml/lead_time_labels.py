"""
Component category baseline lead times from industry reports.

Source: Sourceability Quarterly Lead Time Report — Q4 2025
        https://sourceability.com/lead-time-report
        (public, no registration required, updated quarterly)

Units: calendar days (weeks × 7).
These are category-level averages across all distributors globally.
The ML model learns to adjust these baselines based on per-offer features
(distance, tier, macro stress, risk score, stock coverage).
"""
from __future__ import annotations

# Category name → baseline lead time in calendar days
# Q4 2025 report values
CATEGORY_BASE_LEAD_DAYS: dict[str, int] = {
    # Semiconductors — long lead
    "Microcontrollers": 98,        # 14 weeks
    "Microprocessors": 98,
    "DSPs": 112,                   # 16 weeks
    "FPGAs": 112,
    "ASICs": 140,                  # 20 weeks
    "SoCs": 112,
    "Memory": 56,                  # 8 weeks
    # Analog / Mixed-Signal
    "ADCs": 84,                    # 12 weeks
    "DACs": 84,
    "Op-Amps": 70,                 # 10 weeks
    "Amplifiers": 70,
    "Comparators": 70,
    "Voltage Regulators": 70,
    "Power Management": 70,
    "Motor Drivers": 84,
    # RF & Wireless
    "RF Transceivers": 112,        # 16 weeks
    "RF Amplifiers": 112,
    "WiFi Modules": 84,            # 12 weeks
    "Bluetooth Modules": 84,
    "Zigbee Modules": 84,
    # Sensors
    "Sensors": 98,                 # 14 weeks
    "Temperature Sensors": 84,
    "Pressure Sensors": 98,
    "IMUs": 98,
    # Logic / Interface
    "Logic ICs": 42,               # 6 weeks
    "Interface ICs": 56,           # 8 weeks
    "Bus Transceivers": 56,
    # Passives & discretes — short lead
    "Resistors": 21,               # 3 weeks
    "Capacitors": 28,              # 4 weeks
    "Inductors": 28,
    "Diodes": 42,                  # 6 weeks
    "Transistors": 42,
    "MOSFETs": 56,                 # 8 weeks
    # Timing
    "Crystals/Oscillators": 56,
    "Oscillators": 56,
    "Clock ICs": 56,
    # Connectors & passives
    "Connectors": 28,
    "Switches": 28,
    "LEDs": 21,
    # Modules & SBCs
    "Development Boards": 14,      # 2 weeks (high stock)
    "Evaluation Boards": 14,
}

DEFAULT_LEAD_DAYS: int = 70  # 10-week fallback for unknown categories


def get_base_days(category: str) -> int:
    """Return baseline lead time days for a component category."""
    return CATEGORY_BASE_LEAD_DAYS.get(category, DEFAULT_LEAD_DAYS)
