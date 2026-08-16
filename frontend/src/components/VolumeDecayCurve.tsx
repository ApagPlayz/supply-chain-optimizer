/**
 * VolumeDecayCurve — the benchmark retraction, drawn.
 *
 * Shows how the MILP's measured cost advantage over a greedy baseline decays as
 * order volume rises. The published headline was measured at 1× — the benchmark's
 * own toy order size — where a fixed per-supplier freight fee is nearly the whole
 * cost being optimized. Buy real quantities and the fee amortises away.
 *
 * Data, provenance and the API-vs-fallback logic live in
 * `../lib/volumeDecayCurveData` (kept out of this file so Fast Refresh works).
 * This module renders; it does not invent numbers.
 */
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceArea, ReferenceLine,
} from 'recharts';
import {
  PRODUCTION_VOLUME_MIN_MULTIPLIER,
  productionVolumeRange,
} from '../lib/volumeDecayCurveData';
import type { VolumeCurvePoint } from '../lib/volumeDecayCurveData';

interface TooltipPayloadItem { payload?: VolumeCurvePoint }

function signedUsd(x: number): string {
  return `${x >= 0 ? '+' : '−'}$${Math.abs(x).toLocaleString()}`;
}

function CurveTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  const pt = active && payload && payload.length > 0 ? payload[0].payload : undefined;
  if (!pt) return null;

  const units = pt.units_min !== undefined && pt.units_max !== undefined
    ? (pt.units_min === pt.units_max
        ? `${pt.units_min.toLocaleString()} units/BOM`
        : `${pt.units_min.toLocaleString()}–${pt.units_max.toLocaleString()} units/BOM`)
    : null;

  return (
    <div className="bg-slate-950/95 border border-slate-600 rounded-lg px-3 py-2.5 text-xs text-slate-300 shadow-xl">
      <div className="text-white font-semibold mb-1">{pt.multiplier.toLocaleString()}× order size</div>
      <div className="tabular-nums text-base font-semibold text-indigo-300">
        {pt.savings_pct.toFixed(2)}% pooled cost edge
      </div>
      {units && <div className="text-slate-400 mt-1">{units}</div>}
      {pt.n_boms !== undefined && (
        <div className="text-slate-500">
          {pt.n_boms} BOM{pt.n_boms === 1 ? '' : 's'} feasible at this volume
        </div>
      )}
      {pt.fee_share_of_saving_pct !== undefined && (
        <div className="mt-1.5 pt-1.5 border-t border-slate-700 text-slate-400">
          Avoided fixed fees ={' '}
          <span className="text-amber-300 tabular-nums font-semibold">
            {pt.fee_share_of_saving_pct.toFixed(0)}%
          </span>{' '}
          of the saving
        </div>
      )}
      {(pt.fixed_fee_usd !== undefined
        || pt.component_usd !== undefined
        || pt.variable_freight_usd !== undefined) && (
        <div className="mt-1 text-[11px] text-slate-500 tabular-nums space-y-0.5">
          {pt.fixed_fee_usd !== undefined && <div>fixed fees {signedUsd(pt.fixed_fee_usd)}</div>}
          {pt.component_usd !== undefined && <div>component {signedUsd(pt.component_usd)}</div>}
          {pt.variable_freight_usd !== undefined && <div>variable freight {signedUsd(pt.variable_freight_usd)}</div>}
        </div>
      )}
    </div>
  );
}

export default function VolumeDecayCurve({
  points,
  headlineValue,
  headlineLabel = 'Withdrawn headline',
  source,
}: {
  points: VolumeCurvePoint[];
  /** The retracted headline, drawn as a dashed reference line for contrast. */
  headlineValue?: number | null;
  headlineLabel?: string;
  /** Where the data came from. Always rendered — no unattributed numbers. */
  source: string;
}) {
  if (points.length === 0) {
    return (
      <div className="h-52 flex items-center justify-center text-slate-500 text-sm">
        Volume-decay curve unavailable — neither the API nor the checked-in sweep returned points.
      </div>
    );
  }

  const maxMultiplier = points[points.length - 1].multiplier;
  const bandStart = Math.min(PRODUCTION_VOLUME_MIN_MULTIPLIER, maxMultiplier);
  const range = productionVolumeRange(points);
  const showHeadline = typeof headlineValue === 'number' && Number.isFinite(headlineValue);

  return (
    <div>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={points} margin={{ top: 12, right: 20, left: 0, bottom: 28 }}>
          <defs>
            <linearGradient id="volumeDecayFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />

          {/* Production-volume band — where the honest number lives. */}
          <ReferenceArea
            x1={bandStart}
            x2={maxMultiplier}
            fill="#10b981"
            fillOpacity={0.08}
            stroke="#10b981"
            strokeOpacity={0.25}
            label={{ value: 'production volume', position: 'insideTopRight', fill: '#34d399', fontSize: 11 }}
          />

          {showHeadline && (
            <ReferenceLine
              y={headlineValue as number}
              stroke="#f59e0b"
              strokeDasharray="6 4"
              strokeWidth={1.5}
              label={{
                value: `${headlineLabel}: ${(headlineValue as number).toFixed(1)}%`,
                position: 'insideTopLeft',
                fill: '#fbbf24',
                fontSize: 11,
              }}
            />
          )}

          <XAxis
            dataKey="multiplier"
            type="number"
            scale="log"
            domain={[1, maxMultiplier]}
            ticks={points.map((p) => p.multiplier)}
            tickFormatter={(v: number) => (v >= 1000 ? `${v / 1000}k×` : `${v}×`)}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            label={{
              value: 'Order size multiplier (log scale) — 1× is the size the headline was measured at',
              position: 'insideBottom',
              offset: -18,
              fill: '#94a3b8',
              fontSize: 11,
            }}
          />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickFormatter={(v: number) => `${v}%`}
            label={{
              value: 'Pooled cost edge vs greedy',
              angle: -90,
              position: 'insideLeft',
              fill: '#94a3b8',
              fontSize: 11,
            }}
          />
          <Tooltip content={<CurveTooltip />} cursor={{ stroke: '#475569', strokeDasharray: '3 3' }} />

          <Area
            type="monotone"
            dataKey="savings_pct"
            stroke="none"
            fill="url(#volumeDecayFill)"
            isAnimationActive={false}
            activeDot={false}
          />
          <Line
            type="monotone"
            dataKey="savings_pct"
            name="Pooled cost edge"
            stroke="#818cf8"
            strokeWidth={2.5}
            dot={{ r: 3.5, fill: '#818cf8', stroke: 'none' }}
            activeDot={{ r: 6, fill: '#a5b4fc' }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="mt-3 space-y-1.5">
        {range && (
          <p className="text-xs text-slate-400">
            Inside the shaded production-volume band ({PRODUCTION_VOLUME_MIN_MULTIPLIER.toLocaleString()}× and
            above) the pooled edge sits between{' '}
            <span className="text-emerald-400 font-semibold tabular-nums">{range.low.toFixed(2)}%</span> and{' '}
            <span className="text-emerald-400 font-semibold tabular-nums">{range.high.toFixed(2)}%</span>.
          </p>
        )}
        <p className="text-xs text-slate-500 leading-relaxed">
          <span className="text-amber-400 font-semibold">Cohort caveat:</span> the BOM set shrinks as volume rises —
          stock ceilings make BOMs infeasible, so the right-hand points are a smaller, different cohort than the
          left-hand ones (hover any point for the count). This is not a like-for-like series and must not be read
          as one. Points where the greedy baseline would have to order more units than exist in stock are excluded
          entirely, so greedy never "wins" with an unexecutable plan.
        </p>
        <p className="text-xs text-slate-600">Source: {source}</p>
      </div>
    </div>
  );
}
