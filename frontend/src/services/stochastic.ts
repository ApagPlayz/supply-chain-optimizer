/**
 * Stochastic-program API client — SEPARATE axios instance, on purpose.
 * =====================================================================
 *
 * WHY THIS FILE EXISTS AT ALL
 * ---------------------------
 * `services/api.ts` creates one shared axios instance with a GLOBAL
 * `timeout: 30000`. That is the right default for every other endpoint in this
 * app, which answer in tens of milliseconds warm.
 *
 * `POST /stochastic/frontier` is not one of those endpoints. It runs a lambda
 * sweep of a two-stage stochastic program — one OR-Tools CP-SAT solve per
 * lambda point, then an exact recourse re-solve per scenario atom per point to
 * score the plan. The backend's own budget for the sweep is
 * `SWEEP_TIME_BUDGET_S = 45.0` (app/api/stochastic.py), and a cold container
 * adds Render's ~2-minute spin-up on top of that.
 *
 * Called through the shared 30s instance, the failure mode is the worst kind:
 * axios aborts with `ECONNABORTED`, the UI shows an error — and the server
 * finishes the solve successfully anyway and writes it to the results cache.
 * The user is told it failed while it in fact succeeded.
 *
 * So this module owns its own instance with a 90s timeout, comfortably above
 * the server's own 45s sweep ceiling. `services/api.ts` is deliberately NOT
 * modified: raising the global timeout to 90s would make every other page in
 * the app hang for a minute and a half on a genuinely dead backend.
 *
 * Auth behaviour is not re-implemented here, it is IMPORTED from
 * `services/api.ts` — `tokenStorage` (cookie with a localStorage fallback, so
 * auth survives a browser that blocks `document.cookie`) and `isTimeoutError`.
 * Copy-pasting that logic would have quietly rotted the moment the shared
 * client changed, which is exactly the failure this file is meant to avoid.
 * Importing costs nothing — api.ts creates its instance at module load either
 * way — and leaves the timeout as the only real difference between the two
 * clients. (`/stochastic/*` is in fact a public, unauthenticated router, but
 * attaching the token keeps the two behaving identically if that ever changes.)
 *
 * EVERY TYPE BELOW WAS VERIFIED AGAINST THE LIVE API, not inferred from the
 * router source: https://supply-chain-api-qy8x.onrender.com/api/v1, 2026-08-24.
 */
import axios from 'axios';
import { isTimeoutError, tokenStorage } from './api';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

export { isTimeoutError };

/**
 * Long-solve budget. The server caps its own sweep at 45s; 90s leaves room for
 * network, cold-ish workers and the exact-support scoring pass without ever
 * aborting a request the server is about to answer.
 */
export const FRONTIER_TIMEOUT_MS = 90_000;

const stochasticApi = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: FRONTIER_TIMEOUT_MS,
});

// Same token read as the shared client, via the same helper.
stochasticApi.interceptors.request.use((config) => {
  const token = tokenStorage.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Same 401 handling as the shared client, including the "don't hard-reload the
// login page itself" guard.
stochasticApi.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      tokenStorage.clear();
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// NOTE: deliberately NO cold-start GET retry here. The shared client retries a
// timed-out GET once at 150s; replaying the frontier POST could kick off a
// second 45s CP-SAT sweep on a backend that is already busy with the first.
// The page surfaces the timeout and lets the user press Re-solve, which by then
// usually hits the server's result cache.

// ── Request ──────────────────────────────────────────────────────────────────

export interface FrontierBomItem {
  component_id: number;
  quantity: number;
}

export interface FrontierRequest {
  items: FrontierBomItem[];
  /** Annual per-supplier outage probability. Server default 0.236827. */
  base_annual_prob?: number;
  /** Exposure window for one purchase order, days. Server default 60. */
  horizon_days?: number;
  /** How far betweenness rank moves a supplier off the base rate. 1.0 = off. */
  centrality_spread?: number;
  us_only?: boolean;
  strategy?: string;
  /**
   * Freight origin. NOT cosmetic — it sets every distributor's
   * `dist_km_from_depot`, which drives the freight model, which changes the
   * optimum. The server defaults to the Memphis reference hub
   * (35.1495 / -90.0490); docs/cvar_frontier.json was generated at San
   * Francisco. Pass SF to reproduce the published numbers.
   */
  depot_lat?: number;
  depot_lng?: number;
}

// ── Response ─────────────────────────────────────────────────────────────────

/** One lambda point. `lambda` is a reserved word in JS, but it is fine as a key. */
export interface FrontierPoint {
  lambda: number;
  expected_cost_usd: number;
  cvar_95_usd: number;
  var_95_usd: number;
  tail_premium_usd: number;
  first_stage_cost_usd: number;
  expected_recourse_usd: number;
  n_suppliers: number;
  supplier_ids: number[];
  solver_status: string;
  mip_gap_pct: number;
  solve_seconds: number;
  evaluate_seconds: number;
  /** 'exact' when the whole 2**|D| support was enumerated, else sampled. */
  evaluation_kind: string;
  n_atoms_in_tail: number;
  n_variables: number;
  /** True when some other lambda attains a lower cost AND a lower CVaR. */
  dominated: boolean;
}

export interface UnsolvedPoint {
  lambda: number;
  reason: string;
  solver_status: string;
  detail: string;
  time_limit_s: number;
  n_scenarios: number;
}

export interface FrontierShape {
  kind: string;
  distinct_plans: number;
  has_tradeoff: boolean;
  expected_cost_span_usd: number;
  expected_cost_span_pct: number;
  cvar_span_usd: number;
  cvar_span_pct: number;
  statement: string;
}

/**
 * The knee, or an explanation of why there isn't one. The backend deliberately
 * never returns a bare `null` here — a flat frontier is a finding, and it says
 * so in `statement`. Discriminate on `available`.
 */
export interface Recommendation {
  available: boolean;
  knee_lambda: number | null;
  statement: string;
  /** Present only when available === true. */
  expected_cost_usd?: number;
  cvar_95_usd?: number;
  n_suppliers?: number;
  supplier_ids?: number[];
  extra_expected_cost_usd?: number;
  extra_expected_cost_pct?: number;
  cvar_reduction_usd?: number;
  cvar_reduction_pct?: number;
  cvar_removed_per_dollar_spent?: number | null;
  cvar_removed_per_dollar_spent_beyond_knee?: number | null;
  /** Present only when available === false. */
  reason?: string;
  distinct_non_dominated_points?: number;
}

export interface FrontierInstance {
  depot_lat: number;
  depot_lng: number;
  depot_note: string;
  total_units: number;
  n_lines: number;
  strategy: string;
  us_only: boolean;
}

/**
 * Probability summary for THIS BOM'S SUPPLIER POOL only — the rank transform is
 * computed over the pool, so these are not the same numbers as the network-wide
 * `/stochastic/calibration` endpoint returns. See the note on
 * `CalibrationResponse`.
 */
export interface FrontierCalibration {
  base_annual_prob: number;
  horizon_days: number;
  centrality_spread: number;
  p_disruption_min: number;
  p_disruption_median: number;
  p_disruption_max: number;
  n_distributors_in_pool: number;
}

export interface ScenarioSetSummary {
  kind: string;
  n_atoms: number;
  support_size_log2: number;
  support_size: number | null;
  note: string;
}

export interface SolveSetSummary {
  n_draws: number;
  n_distinct: number;
  second_stage_variables: number;
  variable_budget: number;
  thinned: boolean;
  note: string;
  /**
   * The solver now optimises on the ENUMERATED support when it fits the
   * second-stage variable budget, rather than on random draws. `exact` says
   * which path ran; `residual_mass` is the probability dropped by integer
   * quantization of the objective weights — a deterministic rounding artefact,
   * NOT sampling error, so it carries no confidence interval and does not
   * shrink with more draws. Do not describe it as sampling error.
   */
  kind?: string;
  exact?: boolean;
  n_atoms_weighted?: number;
  weight_denominator?: number;
  residual_mass?: number;
}

export interface FrontierScenarios {
  kind?: string;
  n_draws: number;
  n_distinct: number;
  seed: number;
  p_no_disruption: number;
  mean_failures_per_scenario: number;
  solve_set: SolveSetSummary;
  evaluation_set: ScenarioSetSummary;
}

export interface FrontierSolver {
  engine: string;
  num_search_workers: number;
  max_time_in_seconds_per_point: number;
  sweep_time_budget_s: number;
  sweep_wall_seconds: number;
  worst_mip_gap_pct: number;
  any_point_hit_time_limit: boolean;
  points_requested: number;
  points_solved: number;
  points_unsolved: number;
}

export interface FrontierResponse {
  /** True when the server returned a hit from its results cache (1h TTL). */
  cached: boolean;
  frontier: FrontierPoint[];
  /** True when some lambda points ran out of solver budget. */
  partial: boolean;
  unsolved_points: UnsolvedPoint[];
  frontier_shape: FrontierShape;
  recommendation: Recommendation;
  instance: FrontierInstance;
  calibration: FrontierCalibration;
  scenarios: FrontierScenarios;
  solver: FrontierSolver;
  caveats: string[];
}

export interface CalibratedDistributor {
  distributor_id: number;
  distributor_name: string;
  betweenness_normalized: number;
  p_disruption_over_horizon: number;
  /** The raw betweenness graph/simulation.py reads straight in as a probability. */
  legacy_simulator_p_fail: number;
}

/**
 * `GET /stochastic/calibration`.
 *
 * IMPORTANT SCOPE DIFFERENCE, verified live 2026-08-24: this endpoint ranks
 * every distributor in the whole graph (92 of them), so its per-distributor
 * probabilities are NOT the ones the frontier used. The frontier computes the
 * same rank transform over the requested BOM's supplier pool only (6
 * distributors on the headline BOM), which spreads the probabilities much
 * further apart. Both are correct; they answer different questions, and the UI
 * must label which is which rather than presenting one as the other.
 */
export interface CalibrationResponse {
  method: string;
  parameters: {
    base_annual_prob: number;
    horizon_days: number;
    centrality_spread: number;
    base_horizon_prob: number;
    max_failure_prob: number;
  };
  base_rate_source: {
    citation: string;
    quote: string;
    derivation: string;
    known_weakness: string;
  };
  contrast_with_existing_simulator: {
    what_it_does: string;
    why_that_breaks: string;
    max_legacy_p_fail: number;
    max_calibrated_p_fail: number;
    note: string;
  };
  distributors: CalibratedDistributor[];
}

// ── Calls ────────────────────────────────────────────────────────────────────

export const stochasticAPI = {
  /** The expensive one. 90s timeout; server caches the result for ~1h. */
  frontier: (body: FrontierRequest) =>
    stochasticApi.post<FrontierResponse>('/stochastic/frontier', body),

  /** Cheap and always warm — safe on the default instance timeout. */
  calibration: (params?: {
    base_annual_prob?: number;
    horizon_days?: number;
    centrality_spread?: number;
  }) => stochasticApi.get<CalibrationResponse>('/stochastic/calibration', { params }),
};

export default stochasticApi;
