// Shared risk utilities.
//
// ── Two DIFFERENT quantities live in this file. Do not mix them. ────────────
//
// 1. `catalogueRiskTier` / `formatRiskIndex` — for `Component.risk_score`, the
//    catalogue attribute served by `/api/v1/components`.
// 2. `riskLabel` / `RISK_COLORS` — a generic 0.4/0.7 tiering of an arbitrary
//    0–1 number, still used by MapPage (betweenness) and BenchmarkPage.
//    It is NOT valid for `risk_score`; see the support argument below.
//
// ── What `Component.risk_score` actually is ────────────────────────────────
//
// A verbatim passthrough of a HuggingFace dataset column (`seed_db.py:248`).
// Nothing in this repo computes it. It is an additive hand-weighted flag sum,
// roughly:
//
//     0.60·chinese_origin + 0.25·critical_category + 0.10·limited_suppliers
//
// Its entire support across the 791-part catalogue is SIX values:
//
//     0.00  189 parts  no flags
//     0.10   31 parts  ["limited_suppliers"]
//     0.20  387 parts  risk_factors = null   ← encodes nothing
//     0.25  170 parts  ["critical_category"]
//     0.60   13 parts  ["chinese_origin"]
//     0.70    1 part   ["chinese_origin", "limited_suppliers"]
//
// Three consequences that this module exists to enforce:
//
// (a) IT IS NOT A PROBABILITY. No base rate, no exposure window, no unit.
//     Rendering it with a `%` is a unit claim the data cannot support — the
//     same pathology already fixed three times in this repo (graph/builder.py,
//     graph/simulation.py, optimization/recommendations.py). Render it as an
//     index on its stated 0–1 scale: `0.17 / 1.0`, never `17%`.
//
// (b) NUMERIC THRESHOLDS ON IT ARE UNFALSIFIABLE. The old 0.4/0.7 bands (and
//     SchedulerPage's rival 0.3/0.6 set) all land inside the empty interval
//     between 0.25 and 0.60. Every cut in (0.25, 0.60) produces the exact same
//     partition, so no observation could ever distinguish them — and the two
//     pages disagreeing put the same 13 ESP8266 parts in different colours.
//     There is no honest cutoff to pick, so this module picks none.
//
// (c) 48.9% OF THE CATALOGUE IS A PLACEHOLDER. The 387 parts at 0.20 carry
//     `risk_factors = null`: no flag fired, yet the number is not 0.00. The
//     score is therefore not even a function of the flags it claims to sum.
//     Those parts are indistinguishable in evidence from the 189 at 0.00.
//
// So the tier is derived from `risk_factors` — the flags themselves, which ARE
// falsifiable (a part changes tier if and only if its flag set changes) and are
// strictly more informative than the number. The number stays visible as a raw
// index, labelled as such.

export const RISK_COLORS: Record<'low' | 'medium' | 'high', string> = {
  low:    '#10b981',
  medium: '#f59e0b',
  high:   '#ef4444',
};

/**
 * Generic 0.4/0.7 tiering of an arbitrary 0–1 number.
 *
 * NOT valid for `Component.risk_score` — see (b) above. Retained for the
 * callers that pass other quantities (MapPage's betweenness channel,
 * BenchmarkPage's tradeoff score). Use `catalogueRiskTier` for catalogue parts.
 */
export function riskLabel(score: number): 'low' | 'medium' | 'high' {
  if (score < 0.4) return 'low';
  if (score < 0.7) return 'medium';
  return 'high';
}

// ── Catalogue risk: the one definition both /dashboard and /components use ──

export type CatalogueRiskTier = 'unflagged' | 'flagged' | 'origin_flagged';

export const CATALOGUE_RISK_COLORS: Record<CatalogueRiskTier, string> = {
  // Deliberately NOT green/amber/red-as-severity: these are flag states, not
  // severity grades. Slate = the dataset said nothing about this part.
  unflagged:      '#64748b',
  flagged:        '#f59e0b',
  origin_flagged: '#ef4444',
};

export const CATALOGUE_RISK_LABELS: Record<CatalogueRiskTier, string> = {
  unflagged:      'no flags',
  flagged:        'flagged',
  origin_flagged: 'China-origin',
};

/**
 * The single band definition for `Component.risk_score`. Both Dashboard and
 * SchedulerPage import this, so a part cannot be red on one page and amber on
 * the other.
 *
 * Bands are on the FLAGS, not the number — there is no defensible numeric
 * cutoff (see (b) above). `chinese_origin` is separated out because it is the
 * only flag the rest of the system consumes downstream (`is_chinese_origin` in
 * `optimization/sourcing.py`) and the only one carrying a non-trivial weight.
 *
 * `score` is a fallback used ONLY when `risk_factors` is absent from the
 * response. Under the published weights a score of 0.60 or more is reachable
 * only with `chinese_origin` set (0.25 + 0.10 = 0.35 is the ceiling without
 * it), so the fallback is an exact inversion, not a threshold. In the current
 * catalogue it never fires: every null-flag part sits at 0.00 or 0.20.
 */
export function catalogueRiskTier(
  riskFactors: string[] | null | undefined,
  score?: number,
): CatalogueRiskTier {
  if (riskFactors && riskFactors.length > 0) {
    return riskFactors.includes('chinese_origin') ? 'origin_flagged' : 'flagged';
  }
  if (score != null && score >= 0.6) return 'origin_flagged';
  return 'unflagged';
}

/** Renders the score as what it is: a bare index on a 0–1 scale. Never a `%`. */
export function formatRiskIndex(score: number, digits = 2): string {
  return score.toFixed(digits);
}

/** The scale suffix for the headline renderings, so "/ 1.0" can't drift. */
export const RISK_INDEX_SCALE = '/ 1.0';

/** One line, used wherever the index is most prominent on a page. */
export const RISK_INDEX_NOTE =
  'Catalogue attribute from the source dataset, not modelled here: a weighted sum of ' +
  'three origin/sourcing flags on a 0–1 scale. Not a probability.';

/** `chinese_origin` → `China origin`. */
export function formatRiskFactor(factor: string): string {
  return factor === 'chinese_origin' ? 'China origin' : factor.replace(/_/g, ' ');
}
