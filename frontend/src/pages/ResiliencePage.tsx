import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { type ScenarioResponse, type DeliveryTargetResponse, resilienceAPI, distributorsAPI } from '../services/api';
import { ScenarioCard } from '../components/ScenarioCard';
import { DeltaCard } from '../components/DeltaCard';
import { DistributorSelector, GeopoliticalRiskSelector, DeliveryTargetSelector } from '../components/DistributorSelector';
import { MonteCarloChart } from '../components/MonteCarloChart';
import { BOMImpactTable } from '../components/BOMImpactTable';

export default function ResiliencePage() {
  const [activeTab, setActiveTab] = useState<'distributor' | 'geopolitical' | 'delivery'>('distributor');

  // Global state: BOM from cart (fetch on mount)
  const [bomComponentIds, setBomComponentIds] = useState<number[]>([]);
  const [distributors, setDistributors] = useState<Array<{ id: number; name: string }>>([]);

  // Scenario 1: Distributor Failure
  const [selectedDistributorId, setSelectedDistributorId] = useState<number | null>(null);
  const [dfLoading, setDfLoading] = useState(false);
  const [dfError, setDfError] = useState<string | null>(null);
  const [dfResult, setDfResult] = useState<ScenarioResponse | null>(null);

  // Scenario 2: Geopolitical Risk
  const [riskMultiplier, setRiskMultiplier] = useState(1.0);
  const [grLoading, setGrLoading] = useState(false);
  const [grError, setGrError] = useState<string | null>(null);
  const [grResult, setGrResult] = useState<ScenarioResponse | null>(null);

  // Scenario 3: Delivery Target
  const [targetDeliveryDays, setTargetDeliveryDays] = useState(14);
  const [dtLoading, setDtLoading] = useState(false);
  const [dtError, setDtError] = useState<string | null>(null);
  const [dtResult, setDtResult] = useState<DeliveryTargetResponse | null>(null);

  // Load initial data (BOM from cart, distributors list)
  useEffect(() => {
    async function load() {
      try {
        // For now, use empty BOM (TODO: fetch from cart)
        // In production, this would fetch from useCartStore or api.cart.get()
        setBomComponentIds([]);

        // Fetch distributors list
        const response = await distributorsAPI.list();
        const dists = response.data || [];
        setDistributors(
          dists.map((d: any) => ({
            id: d.id,
            name: d.name,
          }))
        );
      } catch (e) {
        console.error("Failed to load initial data:", e);
      }
    }
    load();
  }, []);

  const onSimulateDistributorFailure = async () => {
    if (!selectedDistributorId) return;
    setDfLoading(true);
    setDfError(null);
    try {
      const result = await resilienceAPI.distributorFailure({
        distributor_id: selectedDistributorId,
        bom_component_ids: bomComponentIds,
      });
      setDfResult(result);
    } catch (e) {
      setDfError((e as Error).message);
    } finally {
      setDfLoading(false);
    }
  };

  const onSimulateGeopoliticalRisk = async () => {
    setGrLoading(true);
    setGrError(null);
    try {
      const result = await resilienceAPI.geopoliticalRisk({
        risk_multiplier: riskMultiplier,
        bom_component_ids: bomComponentIds,
      });
      setGrResult(result);
    } catch (e) {
      setGrError((e as Error).message);
    } finally {
      setGrLoading(false);
    }
  };

  const onSimulateDeliveryTarget = async () => {
    setDtLoading(true);
    setDtError(null);
    try {
      const result = await resilienceAPI.deliveryTarget({
        target_delivery_days: targetDeliveryDays,
        bom_component_ids: bomComponentIds,
      });
      setDtResult(result);
    } catch (e) {
      setDtError((e as Error).message);
    } finally {
      setDtLoading(false);
    }
  };

  return (
    <div className="container mx-auto px-6 py-8 overflow-y-auto h-full">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="mb-8"
      >
        <h1 className="text-4xl font-bold text-white mb-2">Resilience Scenarios</h1>
        <p className="text-slate-400">
          Explore supply chain trade-offs: what happens if a key distributor fails, risk spikes, or delivery accelerates?
        </p>
      </motion.div>

      {/* Tab Navigation */}
      <div className="flex gap-2 mb-6 border-b border-slate-700">
        <button
          onClick={() => setActiveTab('distributor')}
          className={`px-4 py-2 font-semibold border-b-2 transition ${
            activeTab === 'distributor'
              ? 'text-white border-blue-500'
              : 'text-slate-400 border-transparent hover:text-white hover:border-blue-500'
          }`}
        >
          Distributor Failure
        </button>
        <button
          onClick={() => setActiveTab('geopolitical')}
          className={`px-4 py-2 font-semibold border-b-2 transition ${
            activeTab === 'geopolitical'
              ? 'text-white border-blue-500'
              : 'text-slate-400 border-transparent hover:text-white hover:border-blue-500'
          }`}
        >
          Geopolitical Risk
        </button>
        <button
          onClick={() => setActiveTab('delivery')}
          className={`px-4 py-2 font-semibold border-b-2 transition ${
            activeTab === 'delivery'
              ? 'text-white border-blue-500'
              : 'text-slate-400 border-transparent hover:text-white hover:border-blue-500'
          }`}
        >
          Delivery Acceleration
        </button>
      </div>

      {/* Tab Content */}
      <div>
        {/* Scenario 1: Distributor Failure */}
        {activeTab === 'distributor' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <ScenarioCard title="Simulate Failure" loading={dfLoading} error={dfError}>
                <DistributorSelector
                  distributors={distributors}
                  selectedDistributorId={selectedDistributorId}
                  onSelect={setSelectedDistributorId}
                  onSimulate={onSimulateDistributorFailure}
                  loading={dfLoading}
                />
              </ScenarioCard>
            </div>

            <AnimatePresence>
              {dfResult && (
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4 }}
                  className="space-y-6"
                >
                  {/* Delta cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <DeltaCard
                      label="Total Cost"
                      baseline={dfResult.baseline_cost_usd}
                      scenario={dfResult.scenario_cost_usd}
                      delta_pct={dfResult.cost_delta_pct}
                      unit=" USD"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Delivery ETA"
                      baseline={dfResult.baseline_eta_days}
                      scenario={dfResult.scenario_eta_days}
                      delta_pct={dfResult.eta_delta_days}
                      unit=" days"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Risk Score"
                      baseline={dfResult.baseline_risk_score}
                      scenario={dfResult.scenario_risk_score}
                      delta_pct={dfResult.risk_delta}
                      unit=""
                      isBad={true}
                    />
                  </div>

                  {/* Monte Carlo Chart */}
                  <MonteCarloChart
                    baselineP10={dfResult.baseline_fulfillment_p10}
                    baselineP50={dfResult.baseline_fulfillment_p50}
                    baselineP90={dfResult.baseline_fulfillment_p90}
                    scenarioP10={dfResult.scenario_fulfillment_p10}
                    scenarioP50={dfResult.scenario_fulfillment_p50}
                    scenarioP90={dfResult.scenario_fulfillment_p90}
                    title="Fulfillment Rate (P10/P50/P90)"
                  />

                  {/* BOM Impact Table */}
                  <BOMImpactTable
                    affectedComponents={dfResult.affected_bom_ids.map((id) => ({
                      component_id: id,
                      mpn: `Component ${id}`,
                      current_supplier: "Primary",
                      alternative_suppliers: dfResult.affected_suppliers.map((s) => ({
                        name: s,
                        lead_time_days: 21,
                        cost_delta_pct: 5,
                      })),
                    }))}
                    title="Affected Components & Rerouting Options"
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* Scenario 2: Geopolitical Risk */}
        {activeTab === 'geopolitical' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <ScenarioCard title="Risk Settings" loading={grLoading} error={grError}>
                <GeopoliticalRiskSelector
                  riskMultiplier={riskMultiplier}
                  onRiskChange={setRiskMultiplier}
                  onSimulate={onSimulateGeopoliticalRisk}
                  loading={grLoading}
                />
              </ScenarioCard>
            </div>

            <AnimatePresence>
              {grResult && (
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4 }}
                  className="space-y-6"
                >
                  {/* Delta cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <DeltaCard
                      label="Total Cost"
                      baseline={grResult.baseline_cost_usd}
                      scenario={grResult.scenario_cost_usd}
                      delta_pct={grResult.cost_delta_pct}
                      unit=" USD"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Delivery ETA"
                      baseline={grResult.baseline_eta_days}
                      scenario={grResult.scenario_eta_days}
                      delta_pct={grResult.eta_delta_days}
                      unit=" days"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Risk Score"
                      baseline={grResult.baseline_risk_score}
                      scenario={grResult.scenario_risk_score}
                      delta_pct={grResult.risk_delta}
                      unit=""
                      isBad={true}
                    />
                  </div>

                  {/* Monte Carlo Chart */}
                  <MonteCarloChart
                    baselineP10={grResult.baseline_fulfillment_p10}
                    baselineP50={grResult.baseline_fulfillment_p50}
                    baselineP90={grResult.baseline_fulfillment_p90}
                    scenarioP10={grResult.scenario_fulfillment_p10}
                    scenarioP50={grResult.scenario_fulfillment_p50}
                    scenarioP90={grResult.scenario_fulfillment_p90}
                    title="Fulfillment Rate (P10/P50/P90)"
                  />

                  {/* BOM Impact Table */}
                  <BOMImpactTable
                    affectedComponents={grResult.affected_bom_ids.map((id) => ({
                      component_id: id,
                      mpn: `Component ${id}`,
                      current_supplier: "Primary",
                      alternative_suppliers: grResult.affected_suppliers.map((s) => ({
                        name: s,
                        lead_time_days: 21,
                        cost_delta_pct: 5,
                      })),
                    }))}
                    title="Affected Components & Rerouting Options"
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* Scenario 3: Delivery Target */}
        {activeTab === 'delivery' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <ScenarioCard title="Delivery Target" loading={dtLoading} error={dtError}>
                <DeliveryTargetSelector
                  targetDeliveryDays={targetDeliveryDays}
                  onTargetChange={setTargetDeliveryDays}
                  onSimulate={onSimulateDeliveryTarget}
                  loading={dtLoading}
                />
              </ScenarioCard>
            </div>

            <AnimatePresence>
              {dtResult && (
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4 }}
                  className="space-y-6"
                >
                  {/* Delta cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <DeltaCard
                      label="Total Cost"
                      baseline={dtResult.baseline_cost_usd}
                      scenario={dtResult.scenario_cost_usd}
                      delta_pct={dtResult.cost_delta_pct}
                      unit=" USD"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Delivery ETA"
                      baseline={dtResult.baseline_eta_days}
                      scenario={dtResult.scenario_eta_days}
                      delta_pct={dtResult.eta_delta_days}
                      unit=" days"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Risk Score"
                      baseline={dtResult.baseline_risk_score}
                      scenario={dtResult.scenario_risk_score}
                      delta_pct={dtResult.risk_delta}
                      unit=""
                      isBad={true}
                    />
                  </div>

                  {/* Monte Carlo Chart */}
                  <MonteCarloChart
                    baselineP10={dtResult.baseline_fulfillment_p10}
                    baselineP50={dtResult.baseline_fulfillment_p50}
                    baselineP90={dtResult.baseline_fulfillment_p90}
                    scenarioP10={dtResult.scenario_fulfillment_p10}
                    scenarioP50={dtResult.scenario_fulfillment_p50}
                    scenarioP90={dtResult.scenario_fulfillment_p90}
                    title="Fulfillment Rate (P10/P50/P90)"
                  />

                  {/* BOM Impact Table + Suppliers capable/cannot meet */}
                  <BOMImpactTable
                    affectedComponents={dtResult.affected_bom_ids.map((id) => ({
                      component_id: id,
                      mpn: `Component ${id}`,
                      current_supplier: "Primary",
                      alternative_suppliers: dtResult.affected_suppliers.map((s) => ({
                        name: s,
                        lead_time_days: 21,
                        cost_delta_pct: 5,
                      })),
                    }))}
                    title="Affected Components & Rerouting Options"
                  />

                  {/* Suppliers capable and cannot meet */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Suppliers capable */}
                    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 backdrop-blur-sm">
                      <h3 className="text-lg font-semibold text-white mb-4">Suppliers Capable</h3>
                      <div className="space-y-3">
                        {dtResult.suppliers_capable.map((sup, idx) => (
                          <div
                            key={idx}
                            className="bg-slate-800/50 border border-green-700 rounded p-3 flex justify-between items-center"
                          >
                            <div>
                              <div className="text-white font-medium">{sup.name}</div>
                              <div className="text-sm text-slate-400">
                                Lead time: {sup.lead_time_days} days | Avg cost: ${sup.cost_per_component_avg.toFixed(2)}
                              </div>
                            </div>
                            <div className="bg-green-500/20 text-green-300 px-3 py-1 rounded text-sm font-semibold">
                              Viable
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Suppliers cannot meet */}
                    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 backdrop-blur-sm">
                      <h3 className="text-lg font-semibold text-white mb-4">Cannot Meet Target</h3>
                      <div className="space-y-3">
                        {dtResult.suppliers_cannot_meet.map((sup, idx) => (
                          <div
                            key={idx}
                            className="bg-slate-800/50 border border-red-700 rounded p-3 flex justify-between items-center"
                          >
                            <div>
                              <div className="text-white font-medium">{sup.name}</div>
                              <div className="text-sm text-slate-400">
                                Min lead time: {sup.min_lead_time_days} days | {sup.reason}
                              </div>
                            </div>
                            <div className="bg-red-500/20 text-red-300 px-3 py-1 rounded text-sm font-semibold">
                              Not Viable
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  );
}
