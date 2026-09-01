import { Info } from 'lucide-react';

interface DeltaCardProps {
  label: string;
  baseline: number;
  scenario: number;
  /** The delta value itself. Its unit is NOT assumed — pass `deltaUnit`. */
  delta: number;
  /**
   * Unit suffix for the delta badge. The card used to hardcode "%", which rendered
   * an 11.1-day ETA change as "↑ 11.1%" and a raw 0-to-1 risk score as a percentage.
   * Pass "%" only when the value really is a percentage.
   */
  deltaUnit: string;
  /** Unit suffix for the baseline/scenario readouts. */
  unit?: string;
  /** Decimal places for the delta badge (risk scores need more than 1). */
  deltaDecimals?: number;
  /** Decimal places for the baseline/scenario readouts. */
  decimals?: number;
  accent?: string; // e.g., "border-blue-500", "border-green-500"
  isBad?: boolean; // if true, positive delta is red (cost increase); if false, positive delta is green (good)
  tooltip?: string; // optional plain-language $ interpretation shown on hover
  subline?: string; // optional always-visible sub-line (e.g. dollar framing)
}

export function DeltaCard({
  label,
  baseline,
  scenario,
  delta,
  deltaUnit,
  unit = "",
  deltaDecimals = 1,
  decimals = 1,
  accent = "border-slate-600",
  isBad = true,
  tooltip,
  subline,
}: DeltaCardProps) {
  // A delta that rounds to zero at the decimals actually shown is not a win — it's
  // "nothing changed." It used to fall through to the `delta > 0 ? red : green`
  // branch, so an exact-zero ETA delta (e.g. a target already beaten by 5x) rendered
  // as a confident green "win" badge. Judge zero-ness off the DISPLAYED value, not
  // the raw float, so a value that prints "0.0" can never wear a win/loss color.
  const isZero = Number(Math.abs(delta).toFixed(deltaDecimals)) === 0;

  const deltaColor = isZero
    ? "text-slate-400"
    : isBad
    ? delta > 0 ? "text-red-400" : "text-green-400"
    : delta > 0 ? "text-green-400" : "text-red-400";

  const badgeColor = isZero
    ? "bg-slate-500/10 text-slate-300 border-slate-500"
    : isBad
    ? delta > 0 ? "bg-red-500/20 text-red-300 border-red-400" : "bg-green-500/20 text-green-300 border-green-400"
    : delta > 0 ? "bg-green-500/20 text-green-300 border-green-400" : "bg-red-500/20 text-red-300 border-red-400";

  const arrow = isZero ? "→" : delta > 0 ? "↑" : "↓";

  return (
    <div className={`bg-slate-800/50 border ${accent} rounded-lg p-4 flex justify-between items-center`}>
      <div className="flex flex-col gap-1">
        <span className="text-slate-400 text-xs font-semibold uppercase flex items-center gap-1">
          {label}
          {tooltip && (
            <span title={tooltip} className="cursor-help text-slate-500 hover:text-slate-300">
              <Info size={12} />
            </span>
          )}
        </span>
        {/* A qualifier is never set smaller than the claim it qualifies. This line
            says the headline delta UNDERSTATES the impact, so it is body text at
            the card's largest prose size, not a footnote under it. */}
        {subline && (
          <span className="text-sm text-amber-200 font-medium leading-snug" title={tooltip}>
            {subline}
          </span>
        )}
        <div className="flex gap-4">
          <div>
            {/* slate-500 measured at 3.42:1 on this card background — below the 4.5:1
                floor for body text. slate-400 measures 5.96:1 here. */}
            <span className="text-slate-400 text-xs">Baseline</span>
            <span className="block text-xl font-semibold text-white">
              {baseline.toFixed(decimals)}{unit}
            </span>
          </div>
          <div>
            <span className="text-slate-400 text-xs">Scenario</span>
            <span className="block text-xl font-semibold text-white">
              {scenario.toFixed(decimals)}{unit}
            </span>
          </div>
        </div>
      </div>
      <div className={`border rounded-lg px-3 py-2 text-center ${badgeColor}`}>
        <div className={`text-2xl font-bold ${deltaColor}`}>
          {arrow} {Math.abs(delta).toFixed(deltaDecimals)}{deltaUnit}
        </div>
        <div className="text-xs font-semibold mt-1">Delta</div>
      </div>
    </div>
  );
}
