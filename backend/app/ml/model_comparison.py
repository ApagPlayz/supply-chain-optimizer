"""Multiple-comparison and predictive-accuracy tests for forecast leaderboards.

A leaderboard is a ranking of noisy estimates. Without a test, "TSB beats Croston"
is a claim about 2,658 series that could easily be a coin flip. This module
provides the three tests the forecasting literature actually uses, and is generic
over the loss matrix — it knows nothing about demand.

1. MCB — Multiple Comparisons with the Best
   Friedman's rank test for an overall difference, then Nemenyi critical
   differences for the pairwise post-hoc, presented as a critical-difference (CD)
   diagram: methods are plotted on the mean-rank axis and joined by a bar wherever
   their mean ranks differ by less than the CD, i.e. wherever the data cannot
   separate them.

   Why ranks and not mean losses: mean MASE over thousands of series is dominated
   by a handful of series with a near-zero scaling denominator, which is exactly
   the failure the M3 organisers hit. Ranking within each series first makes the
   comparison robust to that and to the scale of individual series.

   Koning, Franses, Hibon & Stekler (2005), "The M3 competition: Statistical tests
   of the results", *International Journal of Forecasting* 21(3):397-409 — the
   paper that introduced MCB to forecast-competition evaluation.
   Iman & Davenport (1980) for the F-corrected Friedman statistic (the raw chi^2
   form is known to be conservative). Demsar (2006), *JMLR* 7:1-30, for the
   Nemenyi post-hoc and the CD-diagram presentation.

2. Diebold-Mariano, Harvey-Leybourne-Newbold corrected
   For NON-nested pairs. Diebold & Mariano (1995), *JBES* 13(3):253-263;
   Harvey, Leybourne & Newbold (1997), *IJF* 13(2):281-291 for the small-sample
   correction (the uncorrected statistic over-rejects badly at small n).

3. Clark-West
   For NESTED pairs — and using DM there instead is a real error, not a
   technicality. Under the null that the small model generates the data, the large
   model's extra parameters are pure estimation noise, so its MSPE is *larger* in
   population; the DM statistic is therefore centred below zero and is
   under-sized, systematically failing to detect a genuinely better large model.
   Clark & West add back the estimation-noise term (f_hat_1 - f_hat_2)^2, which
   recentres the statistic, and show standard-normal critical values are adequate.

   Clark & West (2007), "Approximately normal tests for equal predictive accuracy
   in nested models", *Journal of Econometrics* 138(1):291-311.

Panel convention
----------------
Every test here treats the SERIES as the independent replication unit: losses are
averaged within a series first, then compared across series. That matches the
cross-sectional design of a forecast competition (different SKUs are separate
draws) and sidesteps the serial dependence that would otherwise require a HAC
variance within each series' short test window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import numpy as np
from scipy import stats

__all__ = [
    "ClarkWestResult",
    "DieboldMarianoResult",
    "McbResult",
    "clark_west",
    "diebold_mariano",
    "mcb_test",
    "nemenyi_critical_difference",
]


@dataclass
class McbResult:
    """Friedman + Nemenyi over an (n_series x n_methods) loss matrix."""

    method_names: List[str]
    n_series: int
    n_methods: int
    mean_ranks: Dict[str, float]
    friedman_chi2: float
    friedman_p: float
    iman_davenport_f: float
    iman_davenport_p: float
    alpha: float
    critical_difference: float
    #: Groups of methods whose mean ranks span less than the CD — the horizontal
    #: bars of a critical-difference diagram. A method may appear in several.
    cliques: List[List[str]] = field(default_factory=list)
    #: Every pair, with rank gap and whether the CD separates them.
    pairwise: List[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "test": "friedman_rank_test_with_nemenyi_post_hoc",
            "reference": (
                "Koning, Franses, Hibon & Stekler (2005), IJF 21(3):397-409; "
                "Iman & Davenport (1980); Demsar (2006), JMLR 7:1-30"
            ),
            "n_series": self.n_series,
            "n_methods": self.n_methods,
            "alpha": self.alpha,
            "mean_ranks": {k: round(v, 4) for k, v in self.mean_ranks.items()},
            "friedman_chi2": round(self.friedman_chi2, 4),
            "friedman_p": self.friedman_p,
            "iman_davenport_f": round(self.iman_davenport_f, 4),
            "iman_davenport_p": self.iman_davenport_p,
            "critical_difference": round(self.critical_difference, 4),
            "cliques": self.cliques,
            "pairwise": self.pairwise,
        }


@dataclass
class DieboldMarianoResult:
    baseline: str
    candidate: str
    n: int
    mean_loss_difference: float
    statistic: float
    p_value: float
    corrected: bool

    def as_dict(self) -> dict:
        return {
            "test": "diebold_mariano_hln_corrected" if self.corrected else "diebold_mariano",
            "reference": "Diebold & Mariano (1995), JBES 13(3):253-263; Harvey, Leybourne & Newbold (1997), IJF 13(2):281-291",
            "baseline": self.baseline,
            "candidate": self.candidate,
            "n_series": self.n,
            "mean_loss_difference": round(self.mean_loss_difference, 6),
            "statistic": round(self.statistic, 4),
            "p_value": self.p_value,
            "alternative": "two-sided",
        }


@dataclass
class ClarkWestResult:
    restricted: str
    unrestricted: str
    n: int
    mean_adjusted_difference: float
    statistic: float
    p_value: float

    def as_dict(self) -> dict:
        return {
            "test": "clark_west",
            "reference": "Clark & West (2007), Journal of Econometrics 138(1):291-311",
            "restricted_model": self.restricted,
            "unrestricted_model": self.unrestricted,
            "n_series": self.n,
            "mean_adjusted_difference": round(self.mean_adjusted_difference, 6),
            "statistic": round(self.statistic, 4),
            "p_value": self.p_value,
            "alternative": "one-sided (unrestricted model has lower MSPE)",
        }


def nemenyi_critical_difference(n_methods: int, n_series: int, alpha: float = 0.05) -> float:
    """Nemenyi critical difference for mean ranks.

        CD = q_alpha * sqrt( k (k + 1) / (6 N) )

    where q_alpha is the studentised-range quantile at k treatments and infinite
    degrees of freedom, divided by sqrt(2). Two methods whose mean ranks differ by
    less than CD are not significantly different at level `alpha`.
    """
    if n_methods < 2:
        raise ValueError("need at least 2 methods")
    if n_series < 1:
        raise ValueError("need at least 1 series")
    q = float(stats.studentized_range.ppf(1.0 - alpha, n_methods, np.inf)) / math.sqrt(2.0)
    return q * math.sqrt(n_methods * (n_methods + 1) / (6.0 * n_series))


def mcb_test(
    losses: np.ndarray,
    method_names: Sequence[str],
    alpha: float = 0.05,
) -> McbResult:
    """Friedman rank test + Nemenyi post-hoc over a loss matrix.

    Args:
        losses: (n_series, n_methods) array of per-series losses, LOWER IS BETTER.
            Must contain no NaN — drop incomplete series before calling, so every
            method is ranked on an identical set of series (an unbalanced panel
            would make the mean ranks incomparable).
        method_names: column labels, same length as `losses.shape[1]`.
        alpha: family-wise level for the Nemenyi critical difference.
    """
    arr = np.asarray(losses, dtype=float)
    if arr.ndim != 2:
        raise ValueError("losses must be 2-D (n_series x n_methods)")
    if arr.shape[1] != len(method_names):
        raise ValueError("method_names length must match the number of columns")
    if not np.all(np.isfinite(arr)):
        raise ValueError("losses contain NaN/inf — drop incomplete series first")
    n, k = arr.shape
    if k < 2:
        raise ValueError("need at least 2 methods")

    # Rank WITHIN each series, 1 = best (lowest loss); ties get the average rank.
    ranks = np.apply_along_axis(stats.rankdata, 1, arr)
    mean_ranks = ranks.mean(axis=0)

    rank_sum_sq = float(np.sum(mean_ranks ** 2))
    chi2 = (12.0 * n / (k * (k + 1.0))) * (rank_sum_sq - k * (k + 1.0) ** 2 / 4.0)
    chi2 = max(chi2, 0.0)
    chi2_p = float(stats.chi2.sf(chi2, k - 1))

    # Iman-Davenport F correction — the raw chi^2 form is conservative.
    denom = n * (k - 1.0) - chi2
    if denom <= 0:
        f_stat, f_p = math.inf, 0.0
    else:
        f_stat = (n - 1.0) * chi2 / denom
        f_p = float(stats.f.sf(f_stat, k - 1, (k - 1) * (n - 1)))

    cd = nemenyi_critical_difference(k, n, alpha)

    names = list(method_names)
    pairwise: List[dict] = []
    for i in range(k):
        for j in range(i + 1, k):
            gap = abs(float(mean_ranks[i] - mean_ranks[j]))
            pairwise.append(
                {
                    "a": names[i],
                    "b": names[j],
                    "rank_gap": round(gap, 4),
                    "significant": bool(gap > cd),
                }
            )

    # CD-diagram cliques: maximal runs of rank-ordered methods spanning < CD.
    order = list(np.argsort(mean_ranks))
    cliques: List[List[str]] = []
    for start in range(len(order)):
        end = start
        while end + 1 < len(order) and (
            float(mean_ranks[order[end + 1]] - mean_ranks[order[start]]) <= cd
        ):
            end += 1
        if end > start:
            group = [names[idx] for idx in order[start:end + 1]]
            if not any(set(group).issubset(set(g)) for g in cliques):
                cliques.append(group)

    return McbResult(
        method_names=names,
        n_series=n,
        n_methods=k,
        mean_ranks={names[i]: float(mean_ranks[i]) for i in range(k)},
        friedman_chi2=float(chi2),
        friedman_p=chi2_p,
        iman_davenport_f=float(f_stat),
        iman_davenport_p=f_p,
        alpha=alpha,
        critical_difference=float(cd),
        cliques=cliques,
        pairwise=pairwise,
    )


def diebold_mariano(
    loss_baseline: Sequence[float],
    loss_candidate: Sequence[float],
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
    horizon: int = 1,
) -> DieboldMarianoResult:
    """Two-sided DM test on per-series mean losses, HLN small-sample corrected.

    Args:
        loss_baseline / loss_candidate: per-series losses (one entry per series),
            LOWER IS BETTER. Positive `mean_loss_difference` favours the candidate.
        horizon: forecast horizon, used only by the HLN correction factor. Pass 1
            when the inputs are already averaged within a series (the panel
            convention documented at the top of this module), because the
            autocorrelation the correction targets has then been averaged out.

    Not valid for nested model pairs — use `clark_west` there.
    """
    a = np.asarray(loss_baseline, dtype=float)
    b = np.asarray(loss_candidate, dtype=float)
    if a.shape != b.shape:
        raise ValueError("loss vectors must have the same length")
    d = a - b                      # > 0 => candidate has lower loss => candidate better
    d = d[np.isfinite(d)]
    n = d.size
    if n < 3:
        raise ValueError("need at least 3 paired observations")
    mean_d = float(d.mean())
    sd = float(d.std(ddof=1))
    if sd == 0:
        stat, p = (0.0, 1.0) if mean_d == 0 else (math.inf * math.copysign(1.0, mean_d), 0.0)
        return DieboldMarianoResult(baseline_name, candidate_name, n, mean_d, stat, p, True)

    dm = mean_d / (sd / math.sqrt(n))
    h = max(1, int(horizon))
    correction = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    stat = dm * correction
    p = float(2.0 * stats.t.sf(abs(stat), df=n - 1))
    return DieboldMarianoResult(baseline_name, candidate_name, n, mean_d, float(stat), p, True)


def clark_west(
    actuals: Sequence[float],
    forecast_restricted: Sequence[float],
    forecast_unrestricted: Sequence[float],
    series_index: Sequence[int] | None = None,
    restricted_name: str = "restricted",
    unrestricted_name: str = "unrestricted",
) -> ClarkWestResult:
    """One-sided Clark-West test that the UNRESTRICTED (nesting) model forecasts better.

    Per observation:

        f_hat = (y - f_1)^2 - [ (y - f_2)^2 - (f_1 - f_2)^2 ]

    with model 1 restricted (nested inside) and model 2 unrestricted. The bracketed
    third term is the adjustment: it removes the extra estimation noise the larger
    model necessarily carries under the null, which is what makes the plain DM
    statistic under-sized in nested comparisons.

    `f_hat` is averaged within each series (via `series_index`) before the
    cross-sectional t-statistic, following the panel convention at the top of this
    module. The alternative is one-sided — H1 is that the unrestricted model is
    better — and standard-normal critical values are used, as Clark & West show
    they are adequate.
    """
    y = np.asarray(actuals, dtype=float)
    f1 = np.asarray(forecast_restricted, dtype=float)
    f2 = np.asarray(forecast_unrestricted, dtype=float)
    if not (y.shape == f1.shape == f2.shape):
        raise ValueError("actuals and both forecast vectors must have the same length")

    f_hat = (y - f1) ** 2 - ((y - f2) ** 2 - (f1 - f2) ** 2)

    if series_index is not None:
        idx = np.asarray(series_index)
        if idx.shape != y.shape:
            raise ValueError("series_index must have the same length as actuals")
        uniq, inv = np.unique(idx, return_inverse=True)
        sums = np.bincount(inv, weights=f_hat, minlength=uniq.size)
        counts = np.bincount(inv, minlength=uniq.size)
        unit = sums / counts
    else:
        unit = f_hat

    unit = unit[np.isfinite(unit)]
    n = unit.size
    if n < 3:
        raise ValueError("need at least 3 units")
    mean_f = float(unit.mean())
    sd = float(unit.std(ddof=1))
    if sd == 0:
        stat = 0.0 if mean_f == 0 else math.inf * math.copysign(1.0, mean_f)
        p = 1.0 if mean_f <= 0 else 0.0
        return ClarkWestResult(restricted_name, unrestricted_name, n, mean_f, stat, p)

    stat = mean_f / (sd / math.sqrt(n))
    p = float(stats.norm.sf(stat))          # one-sided
    return ClarkWestResult(restricted_name, unrestricted_name, n, mean_f, float(stat), p)
