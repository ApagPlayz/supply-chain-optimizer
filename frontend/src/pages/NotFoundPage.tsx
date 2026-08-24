/**
 * 404.
 *
 * Replaces the router's old silent `<Route path="*" element={<Navigate to="/dashboard" />} />`.
 * Redirecting an unknown URL to the dashboard is worse than useless: a typo, a
 * stale bookmark and a genuinely broken link all render as "you are on the
 * dashboard now", so nobody — visitor or author — ever finds out the link was
 * wrong. This says so, and offers the way back rather than taking it for you.
 */
import { Link, useLocation } from 'react-router-dom';
import { Compass } from 'lucide-react';

export default function NotFoundPage() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full flex items-center justify-center px-6">
      <div className="flex flex-col items-center text-center gap-4 max-w-md -mt-12">
        <Compass className="w-10 h-10 text-slate-600" aria-hidden="true" />
        <p className="text-6xl font-semibold text-slate-700 tabular-nums leading-none">404</p>
        <h1 className="text-2xl font-semibold text-white">This page doesn't exist</h1>
        <p className="text-sm text-slate-400 leading-relaxed">
          Nothing is routed at{' '}
          <code className="bg-slate-800 px-1.5 py-0.5 rounded text-slate-300 break-all">
            {location.pathname}
          </code>
          . The link is probably stale or mistyped — the app didn't quietly send you somewhere
          else.
        </p>
        <Link
          to="/dashboard"
          className="mt-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm transition focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-950"
        >
          Back to the dashboard
        </Link>
      </div>
    </div>
  );
}
