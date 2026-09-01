"""Build identity — the one place that answers "which code is running?".

`/version` publishes ``build_commit()``; the scenario cache keys on
``code_version()``. They are deliberately the same mechanism, so a cached
response can always be traced back to the build that produced it.

Why the cache needs this at all
-------------------------------
``CacheManager.generate_key`` used to hash only ``scenario_type`` + params. The
cache lives in the TRACKED ``backend/supply_chain.db`` with a 1-hour TTL, so a
deploy that changed a served string or a computed value kept serving the OLD
body for up to an hour from a cache that could not tell the code had changed.
That was hit for real on 2026-09-01: after ``_hedging_summary`` /
``_fulfilment_clause`` in ``app/api/resilience.py`` stopped claiming "Zero
fulfillment impact" when the fulfilment fields disagreed, the first boot served
the retired sentence out of cache with ``baseline_fulfillment_p50 = null``.
CI cannot see this — it builds a fresh DB with an empty cache.

The signal, in priority order
-----------------------------
1. ``RENDER_GIT_COMMIT`` — set by Render on every deploy. This is what
   ``/version`` reports in production.
2. ``git rev-parse HEAD`` — a local checkout or CI.
3. ``"unknown"`` — no env, no git.

Step 3 is exactly the case that would silently disable the guard: every build
would collapse to the same token. So ``code_version()`` never uses the commit
alone. It mixes the commit with a content fingerprint of ``backend/app/**/*.py``
— a hash that changes whenever the served Python actually changes, in every
environment, committed or not. That also closes the local-dev hole the commit
alone leaves open: editing a file does not move ``HEAD``, but it does move the
fingerprint.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path

#: ``backend/app`` — the package whose source decides what the API serves.
APP_ROOT = Path(__file__).resolve().parent.parent

#: Length of the token prefixed onto every cache key. 12 hex chars = 48 bits;
#: a collision between two builds is not a realistic failure mode, and a short
#: prefix keeps the key inside ``ScenarioCache.cache_key``'s 512 chars without
#: a migration.
_TOKEN_CHARS = 12


@lru_cache(maxsize=1)
def _git_head() -> str:
    """``git rev-parse HEAD`` for this checkout, or ``""`` when there is none."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(APP_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001 - no git, no repo, no PATH: all the same answer
        return ""
    return out.strip()


def build_commit() -> str:
    """The commit this build came from.

    ``RENDER_GIT_COMMIT`` first (production), then the local checkout's HEAD,
    then the literal ``"unknown"``. This is the value ``/version`` publishes.
    """
    commit = os.getenv("RENDER_GIT_COMMIT", "").strip()
    if commit:
        return commit
    return _git_head() or "unknown"


def fingerprint_of(root: Path) -> str:
    """SHA-256 over the *content* of every ``*.py`` under ``root``.

    Path-and-content, sorted, so it is deterministic across machines and
    checkouts: the same source always fingerprints the same, and any edit,
    addition or deletion changes it. Deliberately not mtime-based — a git
    checkout rewrites mtimes without changing the code.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            # Unreadable file: record that it exists and move on rather than
            # crashing a request. Its disappearance still changes the hash.
            digest.update(b"<unreadable>")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def source_fingerprint() -> str:
    """``fingerprint_of(APP_ROOT)``, computed once per process (~76 files)."""
    return fingerprint_of(APP_ROOT)


def code_version() -> str:
    """Short token identifying the running code. Changes when the code changes.

    Used as the leading component of every scenario cache key, so entries
    written by one build can never be read back by another.
    """
    combined = f"{build_commit()}|{source_fingerprint()}"
    return hashlib.sha256(combined.encode()).hexdigest()[:_TOKEN_CHARS]
