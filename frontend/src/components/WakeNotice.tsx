import { useWarmupState } from '../services/warmup';

/** "1.2 s" / "840 ms" — a measured duration, printed at the precision it deserves. */
const fmtDur = (ms: number) =>
  ms >= 1000 ? `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s` : `${Math.round(ms)} ms`;

/**
 * What to say while a request against the free-tier API is taking a long time.
 *
 * The page fires one cheap GET /health the moment the bundle executes (services/warmup.ts).
 * By the time this notice appears — three seconds into a request the user started — that
 * ping has usually settled, and its result is real evidence about WHY this is slow. Using
 * it means the notice can stop guessing: "the backend is waking up" is a lie when a health
 * check answered in 90 ms, and a bare spinner is worse than either.
 *
 * Every number here is measured elapsed wall-clock time. There is deliberately no progress
 * bar: we cannot know how far through a Render cold start we are, so we do not draw one.
 *
 * `requestSec` is how long the caller's own request has been running, so the two mechanisms
 * complement rather than duplicate — the warm-up supplies the diagnosis, the caller supplies
 * its own clock.
 */
export default function WakeNotice({ requestSec }: { requestSec: number }) {
  const warm = useWarmupState();

  const body = (() => {
    switch (warm.phase) {
      case 'probing':
        return (
          <>
            <span className="font-medium">Waking the free-tier API — {warm.elapsedSec}s so far.</span>{' '}
            A wake-up request was sent the moment this page loaded, so the server has been
            starting for that whole time, not only since this request began. A cold start takes
            up to ~2 minutes and only happens after ~15 minutes idle.
          </>
        );
      case 'woke-it':
        return (
          <>
            <span className="font-medium">
              The API was asleep — the wake-up request sent at page load took{' '}
              {fmtDur(warm.durationMs ?? 0)}.
            </span>{' '}
            It is up now, so this is the first real query against a freshly started server (
            {requestSec}s so far).
          </>
        );
      case 'was-awake':
        return (
          <>
            <span className="font-medium">Still working — {requestSec}s.</span> A health check sent
            when this page loaded answered in {fmtDur(warm.durationMs ?? 0)}, so the API is awake.
            This is not a cold start; the request is genuinely taking a while.
          </>
        );
      case 'unreachable':
        return (
          <>
            <span className="font-medium">Still working — {requestSec}s.</span> The health check
            sent at page load never came back, so we cannot tell whether the free-tier server is
            still starting or unreachable. A cold start takes up to ~2 minutes.
          </>
        );
      default:
        return (
          <>
            <span className="font-medium">Free-tier backend is waking up.</span> The server sleeps
            when idle and a cold start can take up to ~2 minutes. Hang tight — this only happens on
            the first request.
          </>
        );
    }
  })();

  return (
    <div
      className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-200 text-sm"
      role="status"
      aria-live="polite"
    >
      {body}
    </div>
  );
}
