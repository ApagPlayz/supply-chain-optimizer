/**
 * One 95% confidence interval drawn against a zero line on a domain shared by
 * every row, so "excludes zero" is a thing you SEE rather than a thing you
 * work out from five decimal places. Purely positional — the accompanying
 * table cell states the verdict in words as well.
 *
 * Extracted from NewsvendorPage (2026-08-28) so the Benchmark page's
 * diversification frontier draws its intervals with the SAME component rather
 * than a second, subtly different one. Both pages import this; there is one
 * definition.
 */

const COLOR = {
  slate: '#64748b',
  amber: '#f59e0b',
  emerald: '#10b981',
  red: '#ef4444',
};

export default function CiStrip({
  low,
  high,
  mean,
  domainMin,
  domainMax,
  excludesZero,
  favourable,
}: {
  low: number;
  high: number;
  mean: number;
  domainMin: number;
  domainMax: number;
  excludesZero: boolean;
  favourable: boolean;
}) {
  const span = domainMax - domainMin || 1;
  const pos = (v: number) => ((v - domainMin) / span) * 100;
  const left = Math.max(0, pos(Math.min(low, high)));
  const right = Math.min(100, pos(Math.max(low, high)));
  const barColor = !excludesZero ? COLOR.amber : favourable ? COLOR.emerald : COLOR.red;
  return (
    <div className="relative h-6 w-full min-w-[120px]" aria-hidden="true">
      <div className="absolute inset-x-0 top-1/2 h-px bg-slate-700" />
      <div className="absolute top-0 bottom-0 w-px bg-slate-400" style={{ left: `${pos(0)}%` }} />
      <div
        className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full"
        style={{ left: `${left}%`, width: `${Math.max(right - left, 0.8)}%`, backgroundColor: barColor }}
      />
      <div
        className="absolute top-1/2 -translate-y-1/2 w-1 h-3.5 rounded-sm"
        style={{ left: `${pos(mean)}%`, backgroundColor: '#e2e8f0' }}
      />
    </div>
  );
}

export { COLOR as CI_STRIP_COLOR };
