import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList, Cell,
} from 'recharts';
import {
  Cpu, Database, GitBranch, Activity, ArrowLeft, CheckCircle2, XCircle, HelpCircle,
} from 'lucide-react';
import {
  mlAPI,
  type ModelInfoResponse,
  type ModelComparisonResponse,
  type StressResponse,
  type ModelMetrics,
} from '../services/api';

// ── Formatting helpers ──────────────────────────────────────────────────────
// Never round up, never silently drop a null into a fake "0" — a missing
// number is shown as "—", not invented.
const fmt = (v: number | null | undefined, digits = 3): string =>
  v === null || v === undefined ? '—' : v.toFixed(digits);
const pct = (v: number | null | undefined, digits = 1): string =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`;

function InfoTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-4 flex flex-col gap-1">
      <span className="text-slate-400 text-[10px] font-medium uppercase tracking-wider">{label}</span>
      <span className="text-xl font-bold text-white tabular-nums truncate" title={value}>{value}</span>
      {sub && <span className="text-slate-500 text-[10px]">{sub}</span>}
    </div>
  );
}

// A stat tile that carries an honesty framing note beneath the number instead
// of a color judgment — this page's whole point is presenting numbers as they
// are, not dressing a modest R² up as good or a real win down as marginal.
function HeroStat({
  label, value, note, accent,
}: { label: string; value: string; note: string; accent: 'neutral' | 'positive' }) {
  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-5 flex-1 min-w-[220px]">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-2">{label}</div>
      <div className={`text-3xl font-bold tabular-nums ${accent === 'positive' ? 'text-emerald-400' : 'text-sky-300'}`}>
        {value}
      </div>
      <p className="text-xs text-slate-400 mt-2 leading-relaxed">{note}</p>
    </div>
  );
}

function GatePill({ passed }: { passed: boolean | null }) {
  if (passed === null) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-slate-700/40 border border-slate-600/40 text-slate-400">
        <HelpCircle className="w-3 h-3" /> gate unknown
      </span>
    );
  }
  return passed ? (
    <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
      <CheckCircle2 className="w-3 h-3" /> ship gate passed
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-slate-700/40 border border-slate-600/40 text-slate-400">
      <XCircle className="w-3 h-3" /> ship gate failed
    </span>
  );
}

// Served model = blue (the entity a reader should track); every baseline
// stays a single neutral slate so "beats the field" reads at a glance without
// a legend key per baseline name (a table underneath carries the names).
const SERVED_COLOR = '#60a5fa';
const BASELINE_COLOR = '#64748b';

function R2Chart({ models, baselines }: { models: ModelMetrics[]; baselines: ModelMetrics[] }) {
  const rows = [...models, ...baselines]
    .filter((m) => m.cv_r2_mean !== null && m.cv_r2_mean !== undefined)
    .map((m) => ({
      name: m.name,
      r2: m.cv_r2_mean as number,
      served: m.is_served,
      kind: m.kind,
    }))
    .sort((a, b) => b.r2 - a.r2);

  if (rows.length === 0) {
    return <div className="py-8 text-center text-slate-500 text-sm">No CV metrics available.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(160, rows.length * 40)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 56, left: 8, bottom: 8 }} barCategoryGap={14}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
        <XAxis type="number" stroke="#94a3b8" tick={{ fontSize: 10 }} tickFormatter={(v) => v.toFixed(2)} />
        <YAxis type="category" dataKey="name" stroke="#94a3b8" width={150} tick={{ fontSize: 10 }} />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: 8, fontSize: 11 }}
          formatter={(v: any, _n: any, p: any) => [
            `${Number(v).toFixed(4)}${p?.payload?.served ? '  (served)' : ''}`,
            'CV R² mean',
          ]}
        />
        <Bar dataKey="r2" radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.served ? SERVED_COLOR : BASELINE_COLOR} />
          ))}
          <LabelList
            dataKey="r2"
            position="right"
            formatter={(v: any) => Number(v).toFixed(3)}
            style={{ fill: '#cbd5e1', fontSize: 10 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function BrierChart({ stress }: { stress: StressResponse }) {
  const rows = [
    { name: 'Model', value: stress.brier, primary: true },
    { name: 'Persistence', value: stress.baseline_brier, primary: false },
    { name: 'Climatology', value: stress.climatology_brier, primary: false },
  ].filter((r) => r.value !== null && r.value !== undefined) as Array<{ name: string; value: number; primary: boolean }>;

  if (rows.length === 0) {
    return <div className="py-8 text-center text-slate-500 text-sm">No Brier scores available.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 56, left: 8, bottom: 8 }} barCategoryGap={16}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
        <XAxis type="number" stroke="#94a3b8" tick={{ fontSize: 10 }} tickFormatter={(v) => v.toFixed(2)} />
        <YAxis type="category" dataKey="name" stroke="#94a3b8" width={90} tick={{ fontSize: 10 }} />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: 8, fontSize: 11 }}
          formatter={(v: any) => [Number(v).toFixed(4), 'Brier (lower = better)']}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.primary ? SERVED_COLOR : BASELINE_COLOR} />
          ))}
          <LabelList dataKey="value" position="right" formatter={(v: any) => Number(v).toFixed(3)} style={{ fill: '#cbd5e1', fontSize: 10 }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function ModelCardPage() {
  const navigate = useNavigate();
  const [info, setInfo] = useState<ModelInfoResponse | null>(null);
  const [comparison, setComparison] = useState<ModelComparisonResponse | null>(null);
  const [stress, setStress] = useState<StressResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([mlAPI.modelInfo(), mlAPI.modelComparison(), mlAPI.stress()]).then((results) => {
      if (cancelled) return;
      const [infoRes, cmpRes, stressRes] = results;
      if (infoRes.status === 'fulfilled') setInfo(infoRes.value.data);
      if (cmpRes.status === 'fulfilled') setComparison(cmpRes.value.data);
      if (stressRes.status === 'fulfilled') setStress(stressRes.value.data);
      if (infoRes.status === 'rejected' && cmpRes.status === 'rejected') {
        setError('ML models are not loaded on the server. Run seeds.train_ml_models to serve this page.');
      }
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
      </div>
    );
  }

  const served = comparison?.served_metrics ?? null;
  const paired = comparison?.paired_vs_toughest_baseline ?? {};

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 overflow-y-auto h-full">
      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              <Cpu className="w-5 h-5 text-sky-400" /> ML Model Card
            </h1>
            <p className="text-sm text-slate-400 mt-0.5">
              Served model, provenance, and grouped-CV performance vs baselines — reported as measured.
            </p>
          </div>
          <button onClick={() => navigate('/checkout')} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors">
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Optimizer
          </button>
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-4 text-sm text-red-300 mb-6">{error}</div>
        )}

        {/* ── Provenance strip ────────────────────────────────────────────── */}
        {info && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-8">
            <InfoTile label="Estimator" value={info.model_name ?? '—'} />
            <InfoTile
              label="Source"
              value={info.model_source === 'mlflow_registry' ? 'MLflow' : info.model_source === 'local_joblib' ? 'Local joblib' : 'None'}
              sub={info.alias ?? undefined}
            />
            <InfoTile label="Version" value={info.model_version ?? '—'} />
            <InfoTile label="Training rows" value={info.n_training_samples != null ? String(info.n_training_samples) : '—'} />
            <InfoTile label="Features" value={info.n_features != null ? String(info.n_features) : '—'} />
          </div>
        )}
        {info?.detail && (
          <p className="text-xs text-slate-500 -mt-6 mb-8 leading-relaxed flex items-start gap-1.5">
            <Database className="w-3.5 h-3.5 shrink-0 mt-0.5 text-slate-600" /> {info.detail}
          </p>
        )}

        {/* ── Lead-time bake-off ──────────────────────────────────────────── */}
        {comparison && (
          <section className="mb-10">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-1">
              <GitBranch className="w-4 h-4 text-sky-400" /> Factory Lead-Time Model — Bake-off
            </h2>
            <p className="text-xs text-slate-500 mb-4">{comparison.evaluation}</p>

            {comparison.beats_all_baselines !== null && (
              <div className="mb-3">
                <span className={`inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full ${
                  comparison.beats_all_baselines
                    ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400'
                    : 'bg-slate-700/40 border border-slate-600/40 text-slate-400'
                }`}>
                  {comparison.beats_all_baselines ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                  {comparison.beats_all_baselines
                    ? `Beats all ${comparison.baselines.length} naive baselines on ${comparison.selection_metric}`
                    : `Does not beat every baseline on ${comparison.selection_metric}`}
                </span>
              </div>
            )}

            <div className="flex flex-wrap gap-3 mb-5">
              <HeroStat
                label="CV R² (grouped by part family, median)"
                value={fmt(served?.cv_r2_median)}
                accent="neutral"
                note={
                  served
                    ? `Modest on its own, and noisy across folds — the mean is lower, ${fmt(served.cv_r2_mean)} ± ${fmt(served.cv_r2_std)} ` +
                      `over ${served.cv_splits ?? 'N'} grouped splits, and some individual folds land negative. A random ` +
                      `(ungrouped) split would score far higher and meaningless, since base_product alone explains R²≈0.95 ` +
                      `of the target. Read this next to the paired win, not on its own.`
                    : 'No served model metrics available.'
                }
              />
              <HeroStat
                label={`Paired win vs "${comparison.toughest_baseline ?? 'toughest baseline'}"`}
                value={
                  paired.mean_rmse_reduction_days !== undefined
                    ? `−${paired.mean_rmse_reduction_days} ± ${paired.std_error ?? '—'} d`
                    : '—'
                }
                accent="positive"
                note={
                  paired.folds_model_won !== undefined
                    ? `Won ${paired.folds_model_won}/${paired.n_folds} identical grouped CV folds (p=${paired.paired_t_p_value}). ` +
                      `${paired.caveat ? String(paired.caveat) : 'This paired comparison is the honest read — not the marginal R² above.'}`
                    : 'No paired comparison recorded.'
                }
              />
            </div>

            <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-5 mb-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">CV R² mean — served model vs every baseline</h3>
                <span className="text-[10px] text-slate-500">selection metric: {comparison.selection_metric}</span>
              </div>
              <R2Chart models={comparison.models} baselines={comparison.baselines} />
            </div>

            {comparison.feature_columns.length > 0 && (
              <details className="mb-4">
                <summary className="cursor-pointer text-xs font-semibold text-slate-300 uppercase tracking-wider hover:text-white transition-colors">
                  Feature schema v{comparison.feature_schema_version} ({comparison.feature_columns.length} columns — mostly one-hot)
                </summary>
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {comparison.feature_columns.map((f) => (
                    <span key={f} className="text-[10px] font-mono bg-slate-800 border border-slate-700 text-slate-300 px-2 py-1 rounded">
                      {f}
                    </span>
                  ))}
                </div>
              </details>
            )}

            {comparison.feature_exclusions.length > 0 && (
              <div className="mb-4">
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                  Declared candidates excluded ({comparison.feature_exclusions.length})
                </h3>
                <div className="space-y-1">
                  {comparison.feature_exclusions.map((ex, i) => (
                    <div key={i} className="text-[11px] text-slate-500 flex gap-2">
                      <span className="font-mono text-slate-400 shrink-0">{String(ex.feature ?? 'feature')}</span>
                      {ex.kind != null && <span className="text-slate-600 shrink-0">({String(ex.kind)})</span>}
                      <span className="truncate">— {String(ex.reason ?? '')}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-3">
              <p className="text-[11px] text-slate-400 leading-relaxed">{comparison.caveat}</p>
            </div>
            {!comparison.metrics_describe_served_model && (
              <p className="text-[11px] text-amber-400 mt-2">
                These metrics do NOT describe the currently deployed model — see caveat above.
              </p>
            )}
          </section>
        )}

        {/* ── Macro regime model ──────────────────────────────────────────── */}
        {stress && (
          <section>
            <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-1">
              <Activity className="w-4 h-4 text-sky-400" /> Macro Stress Regime Model
            </h2>
            <p className="text-xs text-slate-500 mb-4">
              Forecasts the NY Fed GSCPI regime one month ahead; judged on Brier score (a proper scoring rule),
              not accuracy — the optimizer consumes the probability directly.
            </p>

            <div className="flex flex-wrap items-center gap-3 mb-4">
              <GatePill passed={stress.ship_gate_passed} />
              {stress.ship_gate_policy && <span className="text-[11px] text-slate-500">{stress.ship_gate_policy}</span>}
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
              <InfoTile label="Current stress probability" value={stress.available ? pct(stress.stress_probability) : '—'} sub={stress.stress_level} />
              <InfoTile
                label="Accuracy vs persistence"
                value={pct(stress.val_accuracy, 1)}
                sub={stress.baseline_accuracy != null ? `baseline ${pct(stress.baseline_accuracy, 1)} — ties, not a win` : undefined}
              />
              <InfoTile label="Calibration slope" value={fmt(stress.calibration_slope, 3)} sub="1.0 = perfectly calibrated" />
              <InfoTile label="Shortage recall" value={pct(stress.shortage_recall, 1)} />
            </div>

            <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-5 mb-4">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
                Brier score — model vs baselines (lower is better; this is the metric that gates shipping)
              </h3>
              <BrierChart stress={stress} />
            </div>

            <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-3">
              <p className="text-[11px] text-slate-400 leading-relaxed">{stress.interpretation}</p>
              {stress.ship_gate_reason && (
                <p className="text-[11px] text-slate-500 leading-relaxed mt-1">{stress.ship_gate_reason}</p>
              )}
            </div>
          </section>
        )}

        {!comparison && !stress && !error && (
          <div className="text-center py-16 text-slate-500 text-sm">No ML data available.</div>
        )}
      </div>
    </div>
  );
}
