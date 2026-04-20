// Shared risk utilities — imported by Dashboard, BenchmarkPage, MapPage Network Risk view.
// RISK_COLORS and riskLabel were originally defined inline in Dashboard.tsx.
// Extracted per 04-UI-SPEC.md Import Contract to prevent duplication.

export const RISK_COLORS: Record<'low' | 'medium' | 'high', string> = {
  low:    '#10b981',
  medium: '#f59e0b',
  high:   '#ef4444',
};

export function riskLabel(score: number): 'low' | 'medium' | 'high' {
  if (score < 0.4) return 'low';
  if (score < 0.7) return 'medium';
  return 'high';
}
