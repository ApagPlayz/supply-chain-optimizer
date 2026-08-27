import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ShieldAlert } from 'lucide-react';
import {
  type AffectedComponentDetail,
  type BomLine,
  type ScenarioResponse,
  type DeliveryTargetResponse,
  type CriticalitySweepResponse,
  type DualSourcingResponse,
  type SensitivityResponse,
  resilienceAPI,
  distributorsAPI,
  cartAPI,
  componentsAPI,
} from '../services/api';
import { ScenarioCard } from '../components/ScenarioCard';
import { DeltaCard } from '../components/DeltaCard';
import { DistributorSelector, GeopoliticalRiskSelector, DeliveryTargetSelector } from '../components/DistributorSelector';
import { MonteCarloChart } from '../components/MonteCarloChart';
import { BOMImpactTable } from '../components/BOMImpactTable';
import { CriticalitySweepTable } from '../components/CriticalitySweepTable';
import { DualSourcingTable } from '../components/DualSourcingTable';
import { TornadoChart } from '../components/TornadoChart';
import { BomCostBreakdownTable } from '../components/BomCostBreakdownTable';

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// Single source of truth for the simulation count quoted in the UI. This must track
// `N_SCENARIOS` in backend/app/graph/simulation.py — the API does not return the count,
// so this is the one place it is written down rather than being retyped in prose.
const MC_SCENARIOS = 1000;
const mcLabel = `${MC_SCENARIOS.toLocaleString()} Monte Carlo scenarios`;

// A cost delta says nothing useful on its own when the scenario also destroys
// fulfilment: the cheapest possible supply chain is one that ships nothing. This is
// the same trap that made the deleted Digital Twin page paint a −100% cost delta
// green. Where fulfilment falls, say so on the cost card itself.
function fulfilmentCaveat(r: ScenarioResponse): string | undefined {
  const drop = r.baseline_fulfillment_p50 - r.scenario_fulfillment_p50;
  if (drop <= 0.001) return undefined;
  return (
    `Read with care: fulfilment falls ${(r.baseline_fulfillment_p50 * 100).toFixed(0)}% → ` +
    `${(r.scenario_fulfillment_p50 * 100).toFixed(0)}%. This cost covers only what can still ` +
    `be sourced, so it understates the true impact.`
  );
}

// Shared $-framing for the "Total Cost" delta card across all three scenarios.
const COST_TOOLTIP =
  'Real dollars: each BOM line valued at the average of its real distributor offer ' +
  `prices, then inflated by the Monte Carlo emergency-procurement model (${mcLabel}). ` +
  'The delta is the extra spend the disruption forces.';

// Translates the CVaR-95 cost multiplier into a concrete dollar figure: the extra
// procurement spend exposed in the worst-5% of disruption scenarios. Fully derived
// from real data — baseline BOM spend × (CVaR-95 − 1).
//
// A BOM that is fully hedged against the scenario (every line still has a surviving
// supplier) genuinely prices out to $0 here — CVaR-95 only measures the emergency
// premium for a line that becomes completely unavailable, and no line does. That is
// a correct finding, not a broken computation, but leading the tile with $0.00 reads
// as one. When the API's own `hedging` block confirms zero lines were orphaned AND
// carries a `cost_substitution` figure (the real cost: re-sourcing to the
// next-cheapest surviving offer), the tile leads with THAT number instead and states
// plainly that zero tail exposure is the correct answer for a hedged BOM. The CVaR
// figure and formula stay visible underneath — this reframes which number is the
// headline, it does not suppress either one. Any real tail exposure (a line actually
// orphaned) keeps the original CVaR-led framing untouched.
function SpendAtRiskBanner({ result }: { result: ScenarioResponse }) {
  const hedging = result.hedging;
  const substitution = result.cost_substitution;
  const isFullyHedged =
    hedging != null &&
    hedging.fully_hedged === true &&
    hedging.n_lines_orphaned === 0 &&
    substitution != null;

  if (isFullyHedged && substitution) {
    const pct = substitution.baseline_component_cost_usd
      ? (substitution.substitution_delta_usd / substitution.baseline_component_cost_usd) * 100
      : 0;
    return (
      <div className="bg-amber-500/5 border border-amber-500/30 rounded-xl p-4 flex items-center gap-4">
        <div className="p-2 rounded-lg bg-amber-500/10 shrink-0">
          <ShieldAlert className="w-5 h-5 text-amber-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold uppercase tracking-wider text-amber-400">
            Substitution Cost · Fully Hedged
          </div>
          <div className="text-2xl font-bold text-white tabular-nums">
            {usd(substitution.substitution_delta_usd)}
            <span className="text-sm font-semibold text-slate-400 ml-2">
              ({pct >= 0 ? '+' : ''}{pct.toFixed(1)}%)
            </span>
          </div>
          {/*
            This sentence used to hardcode "is correctly $0.00" whenever the BOM was
            fully hedged, ignoring procurement_spend_at_risk_usd entirely — so on a
            cart where the API returned $15.28 at CVaR-95 1.150 the banner printed
            "correctly $0.00 — baseline spend x (CVaR-95 1.150 - 1)", disproving its
            own figure on its own face. It now renders the value it is describing.
          */}
          <p className="text-[11px] text-slate-400 mt-0.5">
            {hedging.statement} Procurement spend at risk (CVaR-95) is{' '}
            {usd(result.procurement_spend_at_risk_usd)} — baseline BOM spend × (CVaR-95{' '}
            {result.baseline_cvar_95.toFixed(3)} − 1)
            {result.procurement_spend_at_risk_usd === 0
              ? ', which is zero here because no line becomes unavailable'
              : ', the extra emergency-procurement spend in the worst 5% of scenarios'}
            ; the cost of this outage is re-sourcing{' '}
            {substitution.n_lines_repriced} line{substitution.n_lines_repriced === 1 ? '' : 's'}{' '}
            to the next-cheapest surviving offer, shown above and broken out below.
            {result.quantity_source === 'explicit' && result.total_units != null && (
              <> Priced on the real build: {result.total_units.toLocaleString()} units.</>
            )}
            {result.quantity_source === 'assumed_one_unit_per_line' && (
              <> Priced at one unit per line — quantities were not supplied, so this is a
              prototype figure, not a build.</>
            )}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-amber-500/5 border border-amber-500/30 rounded-xl p-4 flex items-center gap-4">
      <div className="p-2 rounded-lg bg-amber-500/10 shrink-0">
        <ShieldAlert className="w-5 h-5 text-amber-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-semibold uppercase tracking-wider text-amber-400">
          Procurement Spend at Risk · CVaR-95
        </div>
        <div className="text-2xl font-bold text-white tabular-nums">
          {usd(result.procurement_spend_at_risk_usd)}
        </div>
        <p className="text-[11px] text-slate-400 mt-0.5">
          Extra emergency-procurement spend in the worst-5% of {mcLabel} = baseline BOM
          spend × (CVaR-95 {result.baseline_cvar_95.toFixed(3)} − 1).
          {result.quantity_source === 'explicit' && result.total_units != null && (
            <> Priced on the real build: {result.total_units.toLocaleString()} units.</>
          )}
          {result.quantity_source === 'assumed_one_unit_per_line' && (
            <> Priced at one unit per line — quantities were not supplied, so this is a
            prototype figure, not a build.</>
          )}
        </p>
      </div>
    </div>
  );
}

// Rows for the BOM impact table. The API answers per component — real MPN, the
// distributor the line is actually sourced from, and the alternatives that can still
// serve THAT line under the scenario. The page used to build these itself from
// `affected_bom_ids`, stamping the literal string "Primary" on every row and hanging
// the BOM-WIDE alternative list off each one, so a line the outage orphans was shown
// offering ten reroute options it does not have.
function impactRows(
  result: ScenarioResponse,
  mpnById: Record<number, string>,
): AffectedComponentDetail[] {
  if (result.affected_components) return result.affected_components;
  // Only reachable for a response cached before the API carried per-line detail.
  // Say nothing rather than something invented.
  return result.affected_bom_ids.map((id) => ({
    component_id: id,
    mpn: mpnById[id] || `Component ${id}`,
    current_supplier: null,
    alternative_suppliers: [],
  }));
}

export default function ResiliencePage() {
  const [activeTab, setActiveTab] = useState<'distributor' | 'geopolitical' | 'delivery' | 'recommendations'>('distributor');

  // Abort controllers for cancelling in-flight requests
  const abortControllerRef = useRef<AbortController>(new AbortController());

  // Global state: BOM from cart (fetch on mount)
  const [bomComponentIds, setBomComponentIds] = useState<number[]>([]);
  const [mpnById, setMpnById] = useState<Record<number, string>>({});
  const [quantityById, setQuantityById] = useState<Record<number, number>>({});
  const [usingDefaultBom, setUsingDefaultBom] = useState(false);
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

  // Scenario 4: Recommendations (criticality sweep + dual-sourcing + tornado)
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);
  const [recHasRun, setRecHasRun] = useState(false);
  const [sweepResult, setSweepResult] = useState<CriticalitySweepResponse | null>(null);
  const [dualSourcingResult, setDualSourcingResult] = useState<DualSourcingResponse | null>(null);
  const [tornadoResult, setTornadoResult] = useState<SensitivityResponse | null>(null);

  // Load initial data (BOM from cart, distributors list)
  useEffect(() => {
    async function load() {
      try {
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
        console.error("Failed to load distributors:", e);
      }

      // Build the BOM the scenarios run against. Prefer the user's cart; if it is
      // empty or unauthenticated, fall back to a DEMONSTRATIVE default BOM.
      //
      // The old fallback took the first 6 components by id — ~$25 of total spend,
      // all multi-sourced — so the flagship scenario returned 0.0% cost delta,
      // 0.0-day ETA delta, 0.000 risk delta and 100% fulfilment in every case. The
      // page's headline feature demoed as a wall of zeros.
      //
      // Instead: seed from the network's real single-source exposure — the components
      // where losing one distributor actually breaks something — plus the highest-value
      // multi-sourced parts for contrast. Nothing is hardcoded; the ids are derived at
      // runtime from the catalogue's own offer counts (see below for why not from
      // /benchmark/single-source-components).
      try {
        const ids: number[] = [];
        const mpnMap: Record<number, string> = {};
        const qtyMap: Record<number, number> = {};
        const cartDistributorCounts = new Map<number, number>();
        try {
          const cart = await cartAPI.get();
          for (const item of cart.data || []) {
            ids.push(item.component_id);
            if (item.mpn) mpnMap[item.component_id] = item.mpn;
            qtyMap[item.component_id] = item.quantity ?? 1;
            if (item.distributor_id != null) {
              cartDistributorCounts.set(
                item.distributor_id,
                (cartDistributorCounts.get(item.distributor_id) ?? 0) + 1
              );
            }
          }
        } catch {
          // not logged in / empty cart — fall through to default BOM
        }

        // Pre-select the distributor this cart leans on hardest, so "Simulate
        // Failure" is enabled on arrival instead of sitting greyed out until the
        // user guesses which of 92 distributors is worth failing.
        if (cartDistributorCounts.size > 0) {
          let topId: number | null = null;
          let topCount = 0;
          for (const [distId, count] of cartDistributorCounts) {
            if (count > topCount) {
              topCount = count;
              topId = distId;
            }
          }
          if (topId != null) setSelectedDistributorId(topId);
        }

        if (ids.length === 0) {
          try {
            const comps = await componentsAPI.list();
            const list: Array<{
              id: number;
              mpn?: string;
              num_offers?: number;
              min_price?: number | null;
            }> = comps.data?.items || comps.data || [];

            // NOTE: we deliberately do NOT use GET /benchmark/single-source-components
            // here. That endpoint currently over-reports — it lists components such as
            // 170/174/180/183/186 as single-source when each in fact has 3–4 distributor
            // offers, so seeding from it produced a BOM whose "sole supplier" failure
            // changed nothing (risk delta 0.000, fulfilment flat at 100%). The
            // catalogue's own `num_offers` agrees with GET /components/{id}/offers, so
            // we trust that instead. (Backend defect, out of scope for this pass.)
            const trulySingleSource = list
              .filter((c) => c.num_offers === 1)
              .sort((a, b) => (b.min_price ?? 0) - (a.min_price ?? 0))
              .slice(0, 16);

            // Resolve each one's sole distributor, then fail the distributor that owns
            // the most of them — the most instructive single failure in the network.
            const sole = await Promise.all(
              trulySingleSource.map(async (c) => {
                try {
                  const res = await componentsAPI.offers(c.id);
                  const offers = Array.isArray(res.data) ? res.data : [];
                  return offers.length === 1
                    ? { component: c, distributorId: offers[0].distributor_id as number }
                    : null;
                } catch {
                  return null;
                }
              })
            );

            const byDistributor = new Map<number, typeof trulySingleSource>();
            for (const s of sole) {
              if (!s) continue;
              const bucket = byDistributor.get(s.distributorId) || [];
              bucket.push(s.component);
              byDistributor.set(s.distributorId, bucket);
            }

            let seededDistributorId: number | null = null;
            let best: typeof trulySingleSource = [];
            for (const [distId, bucket] of byDistributor) {
              if (bucket.length > best.length) {
                best = bucket;
                seededDistributorId = distId;
              }
            }

            for (const c of best.slice(0, 5)) {
              ids.push(c.id);
              if (c.mpn) mpnMap[c.id] = c.mpn;
              qtyMap[c.id] = 1;
            }

            // Add the highest-value multi-sourced parts for contrast: the BOM should
            // not be uniformly fragile, and the re-sourcing story needs lines that
            // actually survive and move to another distributor.
            const multiSource = list
              .filter((c) => (c.num_offers ?? 0) > 1)
              .sort((a, b) => (b.min_price ?? 0) - (a.min_price ?? 0));
            for (const c of multiSource) {
              if (ids.length >= 8) break;
              if (ids.includes(c.id)) continue;
              ids.push(c.id);
              if (c.mpn) mpnMap[c.id] = c.mpn;
              qtyMap[c.id] = 1;
            }

            // Pre-select the distributor whose failure this BOM is built to expose, so
            // "Simulate Failure" returns a real result on the first click.
            if (seededDistributorId != null) setSelectedDistributorId(seededDistributorId);
          } catch {
            // catalogue unavailable — leave the BOM empty rather than inventing one
          }
          setUsingDefaultBom(true);
        }

        setBomComponentIds(ids);
        setMpnById(mpnMap);
        setQuantityById(qtyMap);
      } catch (e) {
        console.error("Failed to load BOM:", e);
      }
    }
    load();
  }, []);

  // Cleanup: cancel pending requests on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current.abort();
    };
  }, []);

  // The BOM these scenarios are priced on, WITH its quantities. Posting bare
  // `bom_component_ids` makes the API price one unit per line, which is why the
  // summary tiles read $4.04 above a $166.94 line-by-line table for the same cart.
  const bomItems: BomLine[] = useMemo(
    () => bomComponentIds.map((id) => ({ component_id: id, quantity: quantityById[id] ?? 1 })),
    [bomComponentIds, quantityById],
  );

  const onSimulateDistributorFailure = useCallback(async () => {
    if (!selectedDistributorId) {
      setDfError("Please select a distributor");
      return;
    }
    setDfLoading(true);
    setDfError(null);

    // Reset abort controller for new request
    abortControllerRef.current = new AbortController();

    try {
      const result = await resilienceAPI.distributorFailure(
        {
          distributor_id: selectedDistributorId,
          items: bomItems,
        },
        abortControllerRef.current.signal
      );
      setDfResult(result);
    } catch (e) {
      const message = (e as Error).message;
      if (message.includes("timeout")) {
        setDfError("Simulation took too long (>30s). Try a smaller BOM or try again.");
      } else if (message.includes("API error")) {
        setDfError("Backend error. Check that the server is running.");
      } else if (message.includes("aborted")) {
        setDfError(null); // Silently clear if aborted (unmount)
      } else {
        setDfError(message || "Unknown error");
      }
      // Still clear result to reset state
      setDfResult(null);
    } finally {
      setDfLoading(false);
    }
  }, [selectedDistributorId, bomItems]);

  const onSimulateGeopoliticalRisk = async () => {
    setGrLoading(true);
    setGrError(null);

    // Reset abort controller for new request
    abortControllerRef.current = new AbortController();

    try {
      const result = await resilienceAPI.geopoliticalRisk(
        {
          risk_multiplier: riskMultiplier,
          items: bomItems,
        },
        abortControllerRef.current.signal
      );
      setGrResult(result);
    } catch (e) {
      const message = (e as Error).message;
      if (message.includes("timeout")) {
        setGrError("Simulation took too long (>30s). Try again.");
      } else if (message.includes("aborted")) {
        setGrError(null); // Silently clear if aborted
      } else {
        setGrError(message || "Unknown error");
      }
      setGrResult(null);
    } finally {
      setGrLoading(false);
    }
  };

  const onSimulateDeliveryTarget = async () => {
    setDtLoading(true);
    setDtError(null);

    // Reset abort controller for new request
    abortControllerRef.current = new AbortController();

    try {
      const result = await resilienceAPI.deliveryTarget(
        {
          target_delivery_days: targetDeliveryDays,
          items: bomItems,
        },
        abortControllerRef.current.signal
      );
      setDtResult(result);
    } catch (e) {
      const message = (e as Error).message;
      if (message.includes("timeout")) {
        setDtError("Simulation took too long (>30s). Try again.");
      } else if (message.includes("aborted")) {
        setDtError(null); // Silently clear if aborted
      } else {
        setDtError(message || "Unknown error");
      }
      setDtResult(null);
    } finally {
      setDtLoading(false);
    }
  };

  const onAnalyzeRecommendations = async () => {
    setRecLoading(true);
    setRecError(null);

    // Reset abort controller for new request
    abortControllerRef.current = new AbortController();
    const { signal } = abortControllerRef.current;

    try {
      const [sweep, dualSourcing, tornado] = await Promise.all([
        resilienceAPI.criticalitySweep({}, signal), // network-wide by default
        resilienceAPI.dualSourcingPlan({}, signal), // network-wide by default
        resilienceAPI.sensitivity({ bom_component_ids: bomComponentIds, metric: 'cost' }, signal),
      ]);
      setSweepResult(sweep);
      setDualSourcingResult(dualSourcing);
      setTornadoResult(tornado);
      setRecHasRun(true);
    } catch (e) {
      const message = (e as Error).message;
      if (message.includes('timeout')) {
        setRecError('Analysis took too long (>30s). Try again.');
      } else if (message.includes('aborted')) {
        setRecError(null); // Silently clear if aborted
      } else {
        setRecError(message || 'Unknown error');
      }
    } finally {
      setRecLoading(false);
    }
  };

  // Auto-run the flagship scenario on mount, so /resilience never lands as an empty
  // page behind a button the visitor has to find. Same pattern as FrontierPage: the
  // first result arrives on its own, and the loading state is what a *changed* input
  // looks like afterwards. It waits for both inputs, and both are derived from real
  // data — the BOM from the cart (or the catalogue's own single-source exposure) and
  // the distributor the BOM leans on hardest — so nothing is fabricated to make the
  // page fill up.
  const autoRanRef = useRef(false);
  useEffect(() => {
    if (autoRanRef.current) return;
    if (bomComponentIds.length === 0 || selectedDistributorId == null) return;
    autoRanRef.current = true;
    void onSimulateDistributorFailure();
  }, [bomComponentIds, selectedDistributorId, onSimulateDistributorFailure]);

  // Auto-trigger the recommendations analysis the first time the tab is opened,
  // once the BOM (needed for the tornado's bom_component_ids) has loaded.
  useEffect(() => {
    if (activeTab === 'recommendations' && !recHasRun && !recLoading && bomComponentIds.length > 0) {
      onAnalyzeRecommendations();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, bomComponentIds]);

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
        {/* Be explicit about which BOM the numbers below describe — an interviewer
            should never have to guess whether they're looking at their own cart. */}
        {bomComponentIds.length > 0 && (
          <p className="text-xs text-slate-500 mt-2">
            {usingDefaultBom ? (
              <>
                Running on a demo BOM of {bomComponentIds.length} components, seeded from the
                network's real single-source exposure so a distributor failure has a visible
                effect. Add items to your cart to run these scenarios on your own BOM.
              </>
            ) : (
              <>Running on your cart: {bomComponentIds.length} components.</>
            )}
          </p>
        )}
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
        <button
          onClick={() => setActiveTab('recommendations')}
          className={`px-4 py-2 font-semibold border-b-2 transition ${
            activeTab === 'recommendations'
              ? 'text-white border-blue-500'
              : 'text-slate-400 border-transparent hover:text-white hover:border-blue-500'
          }`}
        >
          Recommendations
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

            {/* Skeleton while the very first (auto-run) scenario is solving. */}
            {!dfResult && dfLoading && (
              <div className="flex flex-col items-center justify-center h-56 gap-4">
                <div className="w-8 h-8 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
                <p className="text-sm text-slate-500">
                  Running the Monte Carlo cascade on this BOM…
                </p>
              </div>
            )}

            {/* Nothing to show and not loading: the BOM is still loading, or the
                first solve errored (the error itself is rendered in the card above). */}
            {!dfResult && !dfLoading && !dfError && (
              <div className="text-sm text-slate-500">
                {bomComponentIds.length === 0
                  ? 'Loading the BOM these scenarios run on…'
                  : 'Pick a distributor to fail and run the scenario.'}
              </div>
            )}

            <AnimatePresence>
              {dfResult && (
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4 }}
                  className="space-y-6"
                >
                  {/* Procurement spend at risk (CVaR-95 → $) */}
                  <SpendAtRiskBanner result={dfResult} />

                  {/* Delta cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <DeltaCard
                      label="Total Cost"
                      baseline={dfResult.baseline_cost_usd}
                      scenario={dfResult.scenario_cost_usd}
                      delta={dfResult.cost_delta_pct}
                      deltaUnit="%"
                      unit=" USD"
                      isBad={true}
                      tooltip={COST_TOOLTIP}
                      subline={fulfilmentCaveat(dfResult)}
                    />
                    <DeltaCard
                      label="Delivery ETA"
                      baseline={dfResult.baseline_eta_days}
                      scenario={dfResult.scenario_eta_days}
                      // eta_delta_days is DAYS, not a percentage.
                      delta={dfResult.eta_delta_days}
                      deltaUnit=" d"
                      unit=" days"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Risk Score"
                      baseline={dfResult.baseline_risk_score}
                      scenario={dfResult.scenario_risk_score}
                      // risk_delta is a raw 0–1 score difference, not a percentage.
                      delta={dfResult.risk_delta}
                      deltaUnit=""
                      deltaDecimals={3}
                      decimals={3}
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
                    affectedComponents={impactRows(dfResult, mpnById)}
                    title="Affected Components & Rerouting Options"
                    emptyMessage={
                      'No BOM line loses every supplier when this distributor goes dark. ' +
                      'The cost impact is the substitution to the next-cheapest surviving ' +
                      'offer, priced line by line below.'
                    }
                  />

                  {/* Per-line base-vs-scenario cost breakdown — the one idea worth
                      keeping from the deleted Digital Twin page, rebuilt on real
                      offer prices with actual re-sourcing. */}
                  {selectedDistributorId != null && (
                    <BomCostBreakdownTable
                      bomComponentIds={bomComponentIds}
                      mpnById={mpnById}
                      quantityById={quantityById}
                      failedDistributorId={selectedDistributorId}
                      failedDistributorName={
                        distributors.find((d) => d.id === selectedDistributorId)?.name ??
                        `Distributor ${selectedDistributorId}`
                      }
                    />
                  )}
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
                  {/* Procurement spend at risk (CVaR-95 → $) */}
                  <SpendAtRiskBanner result={grResult} />

                  {/* Delta cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <DeltaCard
                      label="Total Cost"
                      baseline={grResult.baseline_cost_usd}
                      scenario={grResult.scenario_cost_usd}
                      delta={grResult.cost_delta_pct}
                      deltaUnit="%"
                      unit=" USD"
                      isBad={true}
                      tooltip={COST_TOOLTIP}
                      subline={fulfilmentCaveat(grResult)}
                    />
                    <DeltaCard
                      label="Delivery ETA"
                      baseline={grResult.baseline_eta_days}
                      scenario={grResult.scenario_eta_days}
                      delta={grResult.eta_delta_days}
                      deltaUnit=" d"
                      unit=" days"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Risk Score"
                      baseline={grResult.baseline_risk_score}
                      scenario={grResult.scenario_risk_score}
                      delta={grResult.risk_delta}
                      deltaUnit=""
                      deltaDecimals={3}
                      decimals={3}
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
                    affectedComponents={impactRows(grResult, mpnById)}
                    title="Affected Components & Rerouting Options"
                    emptyMessage={
                      'No BOM line crosses into a higher risk tier at this multiplier. ' +
                      'The spike still flows through the emergency-procurement premium ' +
                      'in the cards above.'
                    }
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
                  {/* Procurement spend at risk (CVaR-95 → $) */}
                  <SpendAtRiskBanner result={dtResult} />

                  {/* Delta cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <DeltaCard
                      label="Total Cost"
                      baseline={dtResult.baseline_cost_usd}
                      scenario={dtResult.scenario_cost_usd}
                      delta={dtResult.cost_delta_pct}
                      deltaUnit="%"
                      unit=" USD"
                      isBad={true}
                      tooltip={COST_TOOLTIP}
                      subline={fulfilmentCaveat(dtResult)}
                    />
                    <DeltaCard
                      label="Delivery ETA"
                      baseline={dtResult.baseline_eta_days}
                      scenario={dtResult.scenario_eta_days}
                      delta={dtResult.eta_delta_days}
                      deltaUnit=" d"
                      unit=" days"
                      isBad={true}
                    />
                    <DeltaCard
                      label="Risk Score"
                      baseline={dtResult.baseline_risk_score}
                      scenario={dtResult.scenario_risk_score}
                      delta={dtResult.risk_delta}
                      deltaUnit=""
                      deltaDecimals={3}
                      decimals={3}
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
                    affectedComponents={impactRows(dtResult, mpnById)}
                    title="Lines That Miss the Delivery Window"
                    emptyMessage={
                      `Every BOM line has at least one supplier that can deliver inside ` +
                      `the ${targetDeliveryDays}-day window.`
                    }
                  />

                  {/* Suppliers capable and cannot meet */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Suppliers capable */}
                    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 backdrop-blur-sm">
                      <h3 className="text-lg font-semibold text-white mb-1">
                        Suppliers Capable
                        <span className="ml-2 text-sm font-normal text-slate-500">
                          {dtResult.suppliers_capable.length}
                        </span>
                      </h3>
                      <p className="text-[11px] text-slate-500 mb-4">
                        Can hit the {targetDeliveryDays}-day window. Lead time is derived from real
                        distributor geography; the premium is the expedite surcharge required, 0%
                        where the supplier already meets the window.
                      </p>
                      <div className="space-y-3 max-h-[420px] overflow-y-auto">
                        {dtResult.suppliers_capable.length === 0 && (
                          <div className="text-sm text-slate-400">
                            No supplier in the catalogue can meet a {targetDeliveryDays}-day window
                            for this BOM.
                          </div>
                        )}
                        {dtResult.suppliers_capable.map((sup, idx) => (
                          <div
                            key={idx}
                            className="bg-slate-800/50 border border-green-700 rounded p-3 flex justify-between items-center gap-3"
                          >
                            <div className="min-w-0">
                              <div className="text-white font-medium truncate">{sup.name}</div>
                              {/* The API returns {name, lead_time_days, cost_adjustment_pct}.
                                  It has never returned a per-component average cost — reading
                                  `cost_per_component_avg` here white-screened the whole app. */}
                              <div className="text-sm text-slate-400">
                                Lead time: {sup.lead_time_days.toFixed(1)} days
                                {' | '}
                                {sup.cost_adjustment_pct > 0
                                  ? `Expedite premium: +${sup.cost_adjustment_pct.toFixed(1)}%`
                                  : 'No expedite premium'}
                              </div>
                            </div>
                            <div className="bg-green-500/20 text-green-300 px-3 py-1 rounded text-sm font-semibold shrink-0">
                              Viable
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Suppliers cannot meet */}
                    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 backdrop-blur-sm">
                      <h3 className="text-lg font-semibold text-white mb-1">
                        Cannot Meet Target
                        <span className="ml-2 text-sm font-normal text-slate-500">
                          {dtResult.suppliers_cannot_meet.length}
                        </span>
                      </h3>
                      <p className="text-[11px] text-slate-500 mb-4">
                        Ruled out for the {targetDeliveryDays}-day window.
                      </p>
                      <div className="space-y-3 max-h-[420px] overflow-y-auto">
                        {dtResult.suppliers_cannot_meet.length === 0 && (
                          <div className="text-sm text-slate-400">
                            Every supplier in the catalogue can meet this window.
                          </div>
                        )}
                        {dtResult.suppliers_cannot_meet.map((sup, idx) => (
                          <div
                            key={idx}
                            className="bg-slate-800/50 border border-red-700 rounded p-3 flex justify-between items-center gap-3"
                          >
                            <div className="min-w-0">
                              <div className="text-white font-medium truncate">{sup.name}</div>
                              <div className="text-sm text-slate-400">
                                Min lead time: {sup.min_lead_time_days.toFixed(1)} days |{' '}
                                {sup.reason.replace(/_/g, ' ')}
                              </div>
                            </div>
                            <div className="bg-red-500/20 text-red-300 px-3 py-1 rounded text-sm font-semibold shrink-0">
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

        {/* Scenario 4: Recommendations */}
        {activeTab === 'recommendations' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <ScenarioCard title="Recommendation Engine" loading={recLoading} error={recError}>
                <div className="space-y-4">
                  <p className="text-sm text-slate-400">
                    Ranks network-wide single-source exposure, dual-sourcing payoff, and this
                    BOM's cost sensitivity to the key model levers.
                  </p>
                  <button
                    onClick={onAnalyzeRecommendations}
                    disabled={recLoading}
                    className="w-full px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold transition"
                  >
                    {recLoading ? 'Analyzing...' : recHasRun ? 'Re-analyze' : 'Analyze'}
                  </button>
                </div>
              </ScenarioCard>
            </div>

            <AnimatePresence>
              {sweepResult && dualSourcingResult && tornadoResult && (
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4 }}
                  className="space-y-6"
                >
                  <CriticalitySweepTable
                    entries={sweepResult.entries}
                    maxSpendAtRisk={sweepResult.max_spend_at_risk_usd}
                    networkWide={sweepResult.network_wide}
                  />

                  <DualSourcingTable
                    entries={dualSourcingResult.entries}
                    noRegretCount={dualSourcingResult.no_regret_count}
                    hedgeCount={dualSourcingResult.hedge_count}
                    supplierDevelopmentCount={dualSourcingResult.supplier_development_count}
                  />

                  <TornadoChart
                    baselineOutput={tornadoResult.baseline_output}
                    metric={tornadoResult.metric}
                    bars={tornadoResult.bars}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  );
}
