import { useEffect, useState } from 'react';
import { API_BASE_URL } from './api';

/**
 * Cold-start warm-up.
 *
 * The UI is a Render *static site* — it never sleeps and paints in ~0.3s. The API is a
 * Render *free web service* and spins down after ~15 minutes idle; the first request
 * against a spun-down instance takes 50-120s. So the page appears instantly and then the
 * visitor sits on a spinner for up to two minutes after their first click.
 *
 * This does not make the wake faster — nothing in the browser can. It moves the wake
 * EARLIER: a single cheap GET /health leaves the browser the moment the bundle executes,
 * so the container starts booting while the visitor is still reading the landing page.
 * Whatever they spend reading is subtracted from what they spend on a spinner.
 *
 * Rules it obeys:
 *   - Exactly once per page load. Module-level guard, so a route change, a re-render or
 *     StrictMode's double-invoke cannot fire a second one.
 *   - Never blocks rendering: fire-and-forget, called before render() but never awaited.
 *   - Never surfaces an error. Every failure path — offline, CORS, DNS, 502 while the
 *     container boots, abort — resolves to a recorded phase and nothing else.
 *   - Renders no data. It reads only its own timing; the response body is discarded.
 *
 * The recorded phase is what lets the wake banner tell the truth instead of guessing:
 * a slow request when the probe already came back fast is NOT a cold start, and saying
 * so beats showing a "waking up" notice that happens to be wrong.
 */

/** Probe answers under this are a live container; over it, we waited for a boot. */
const WAS_AWAKE_UNDER_MS = 4000;

/** Same ceiling the axios client gives a cold start — see COLD_START_TIMEOUT_MS. */
const PROBE_TIMEOUT_MS = 150000;

export type WarmupPhase =
  /** Nothing fired yet (e.g. a component rendered in isolation). */
  | 'idle'
  /** The ping is in flight — the container may be booting right now. */
  | 'probing'
  /** Answered fast: the API was already up, so a slow request is not a cold start. */
  | 'was-awake'
  /** Answered slowly: it was asleep and this ping is what woke it. */
  | 'woke-it'
  /** Never answered (offline, blocked, aborted). We know nothing — say nothing. */
  | 'unreachable';

export interface WarmupState {
  phase: WarmupPhase;
  /** performance.now() at which the ping left the browser; null until it does. */
  startedAt: number | null;
  /** How long the ping took, once it settled; null while in flight. */
  durationMs: number | null;
}

let state: WarmupState = { phase: 'idle', startedAt: null, durationMs: null };
const listeners = new Set<(s: WarmupState) => void>();

function setState(next: WarmupState): void {
  state = next;
  for (const fn of listeners) {
    try {
      fn(state);
    } catch {
      /* a broken subscriber must not break the warm-up */
    }
  }
}

export function getWarmupState(): WarmupState {
  return state;
}

export function subscribeToWarmup(fn: (s: WarmupState) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/**
 * Where the liveness probe lives.
 *
 * `/health` is mounted on the FastAPI app root, NOT under the `/api/v1` prefix, and it
 * returns 15 bytes with no DB access — the cheapest thing on the service. In production
 * VITE_API_URL is absolute (`https://…onrender.com/api/v1`), so we resolve `/health`
 * against its origin. In local dev the base is the relative `/api/v1` behind Vite's
 * proxy, which only forwards `/api`; the probe then 404s against the dev server, which
 * is harmless and swallowed like any other failure.
 */
export function healthUrl(base: string = API_BASE_URL): string {
  try {
    return new URL('/health', base).toString();
  } catch {
    return '/health';
  }
}

let started = false;

/**
 * Fire the warm-up ping. Safe to call any number of times; only the first does anything.
 * Returns immediately — the caller must not await it.
 */
export function startWarmup(): void {
  if (started) return;
  started = true;

  const startedAt = performance.now();
  setState({ phase: 'probing', startedAt, durationMs: null });

  const settle = (phase: WarmupPhase) => {
    setState({ phase, startedAt, durationMs: performance.now() - startedAt });
  };

  let signal: AbortSignal | undefined;
  try {
    signal = AbortSignal.timeout(PROBE_TIMEOUT_MS);
  } catch {
    /* older browser without AbortSignal.timeout — run without a deadline */
  }

  // No `await`, no `.then` chain the caller can join: the promise is consumed here and
  // its rejection is swallowed, so this can never reject into the app.
  void fetch(healthUrl(), { method: 'GET', cache: 'no-store', credentials: 'omit', signal })
    .then(() => {
      // Any answer at all — even a 502 from the proxy mid-boot — proves the request
      // reached Render and started the container, which is the entire point.
      settle(performance.now() - startedAt < WAS_AWAKE_UNDER_MS ? 'was-awake' : 'woke-it');
    })
    .catch(() => {
      settle('unreachable');
    });
}

/** Test seam: reset the module so a fresh page load can be simulated. */
export function __resetWarmupForTests(): void {
  started = false;
  setState({ phase: 'idle', startedAt: null, durationMs: null });
}

/**
 * Subscribe a component to the warm-up, with a live elapsed counter.
 *
 * `elapsedSec` ticks once a second while the probe is in flight and is a real measured
 * duration, not a simulated progress bar: it is wall-clock time since the ping left the
 * browser, which for a cold start is exactly how long the container has been booting.
 */
export function useWarmupState(): WarmupState & { elapsedSec: number } {
  const [snapshot, setSnapshot] = useState<WarmupState>(getWarmupState);
  const [now, setNow] = useState<number>(() => performance.now());

  useEffect(() => subscribeToWarmup(setSnapshot), []);

  const ticking = snapshot.phase === 'probing';
  useEffect(() => {
    if (!ticking) return;
    const id = setInterval(() => setNow(performance.now()), 1000);
    return () => clearInterval(id);
  }, [ticking]);

  const elapsedMs =
    snapshot.startedAt === null
      ? 0
      : snapshot.durationMs !== null
        ? snapshot.durationMs
        : Math.max(0, now - snapshot.startedAt);

  return { ...snapshot, elapsedSec: Math.floor(elapsedMs / 1000) };
}

/**
 * A 1 Hz counter of real seconds since `startedAt` (a performance.now() reading), or 0
 * when nothing is running. Used to put an elapsed time next to a long spinner so a
 * 60-second wait reads as "still going" rather than "hung". It reports measured time
 * only — it never estimates how much is left.
 */
export function useElapsedSeconds(startedAt: number | null): number {
  // The clock is the state; the elapsed count is derived from it. Storing the count
  // directly would mean resetting it from inside the effect on every start/stop, which
  // is exactly the cascading-render pattern react-hooks/set-state-in-effect forbids.
  const [now, setNow] = useState<number>(() => performance.now());

  useEffect(() => {
    if (startedAt === null) return;
    const id = setInterval(() => setNow(performance.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  if (startedAt === null) return 0;
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}
