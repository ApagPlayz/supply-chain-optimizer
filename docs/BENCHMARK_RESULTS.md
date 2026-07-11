# Benchmark Results — run_id=4

**Generated:** 2026-07-06 20:30 UTC
**Rows:** 72 (9 BOMs × 8 rows: 4 arms×nominal + 2 milp×2 disruptions)
**Seed:** 42 · **Strategy:** balanced · **Holdout:** benchmark IS the holdout

Every arm's selection is scored through the SAME `landed_cost_breakdown` cost function, so MILP-vs-greedy is a fair comparison. Greedy arms are pure sourcing baselines with no route model — their ETA/CO2 are omitted; cost, supplier count and tail-risk are their story.

## A) Value of optimization — MILP vs greedy baselines (nominal)

| BOM | greedy $ | greedy_add $ | milp $ | save% vs greedy | save% vs greedy_add | suppliers greedy→milp |
|-----|---------:|-------------:|-------:|----------------:|--------------------:|:---------------------:|
| automotive_ecu | 722.40 | 494.92 | 289.75 | -59.89% | -41.46% | 4→2 |
| drone_flight_controller | 951.99 | 951.99 | 800.21 | -15.94% | -15.94% | 3→3 |
| industrial_motor_driver | 731.36 | 731.36 | 416.09 | -43.11% | -43.11% | 3→1 |
| iot_sensor_node | 466.39 | 350.37 | 131.77 | -71.75% | -62.39% | 3→1 |
| medical_monitoring_device | 583.45 | 362.35 | 354.29 | -39.28% | -2.22% | 3→2 |
| pcb_power_supply | 356.55 | 239.62 | 132.35 | -62.88% | -44.77% | 3→1 |
| rf_transceiver_module | 586.32 | 586.32 | 268.41 | -54.22% | -54.22% | 3→2 |
| robotics_servo_driver | 1088.12 | 749.71 | 649.03 | -40.35% | -13.43% | 4→1 |
| smart_meter | 783.46 | 783.46 | 427.99 | -45.37% | -45.37% | 3→1 |
| **TOTAL** | 6270.04 | 5250.10 | 3469.89 | -44.66% | -33.91% | — |

*Negative save% = MILP is cheaper (the win). MILP jointly optimizes component price, per-distributor transport and consolidation, so it consolidates orders the myopic greedy baseline cannot.*

## B) Value of resilience — graph-aware MILP vs blind MILP

Graph-aware routes spend ~0 extra nominally but cuts tail-risk under disruption. `plan_cascade_risk` = 1 − P50 fulfillment of the selected plan; `cvar_95` = mean emergency-cost multiplier of the worst-5% scenarios.

| BOM | scenario | nominal cost premium | cascade_risk (blind→graph, ↓) | cvar_95 (blind→graph, ↓) |
|-----|----------|---------------------:|:-----------------------------:|:------------------------:|
| automotive_ecu | stress | +0.00% | 1.0000→1.0000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| automotive_ecu | targeted | +0.00% | 0.2500→0.2500 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| drone_flight_controller | stress | +0.00% | 0.7500→0.7500 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| drone_flight_controller | targeted | +0.00% | 0.5000→0.5000 (+0.0000) | 1.1440→1.1440 (+0.0000) |
| industrial_motor_driver | stress | +16.62% | 1.0000→0.7500 (+0.2500) | 1.1500→1.1500 (+0.0000) |
| industrial_motor_driver | targeted | +16.62% | 1.0000→0.7500 (+0.2500) | 1.1500→1.1500 (+0.0000) |
| iot_sensor_node | stress | +84.46% | 1.0000→1.0000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| iot_sensor_node | targeted | +84.46% | 1.0000→0.5000 (+0.5000) | 1.1500→1.1500 (+0.0000) |
| medical_monitoring_device | stress | +0.00% | 0.0000→0.0000 (+0.0000) | 1.1125→1.1125 (+0.0000) |
| medical_monitoring_device | targeted | +0.00% | 0.0000→0.0000 (+0.0000) | 1.1125→1.1125 (+0.0000) |
| pcb_power_supply | stress | +81.05% | 1.0000→1.0000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| pcb_power_supply | targeted | +81.05% | 1.0000→0.2500 (+0.7500) | 1.1500→1.1500 (+0.0000) |
| rf_transceiver_module | stress | +0.00% | 1.0000→1.0000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| rf_transceiver_module | targeted | +0.00% | 1.0000→1.0000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| robotics_servo_driver | stress | +5.61% | 1.0000→0.5000 (+0.5000) | 1.1500→1.1500 (+0.0000) |
| robotics_servo_driver | targeted | +5.61% | 1.0000→0.5000 (+0.5000) | 1.1500→1.1500 (+0.0000) |
| smart_meter | stress | +25.41% | 1.0000→0.0000 (+1.0000) | 1.1500→1.1500 (+0.0000) |
| smart_meter | targeted | +25.41% | 1.0000→0.0000 (+1.0000) | 1.1500→1.0855 (+0.0645) |

*Annualization assumption: each BOM re-ordered ANNUAL_REORDERS=12×/yr (a stated modelling assumption, not measured cadence).*

