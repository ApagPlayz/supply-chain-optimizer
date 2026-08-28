"""Dump one benchmark run's rows to JSON, for before/after diffing across a re-run.

`optimization_runs` is APPEND-ONLY — a re-run writes a new run_id and leaves earlier
runs intact — so any run can be snapshotted at any time, before or after. Nothing is
lost by not saving one in advance.

    backend/venv/bin/python scripts/snapshot_run.py            # latest run
    backend/venv/bin/python scripts/snapshot_run.py 5 > r5.json
"""
import json
import os
import pathlib
import sys

# Two traps, both hit while writing this:
#   1. Python puts the SCRIPT's directory on sys.path, not the CWD, so `app` is not
#      importable just because you ran this from backend/.
#   2. DATABASE_URL is `sqlite:///./supply_chain.db` — RELATIVE TO CWD. Run this from
#      anywhere but backend/ and SQLite silently CREATES an empty database rather than
#      failing, so every query returns nothing and the error surfaces far downstream
#      (here it produced `SELECT  FROM optimization_runs`).
# Fixing both means chdir'ing to backend/, not just extending sys.path.
_BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))
os.chdir(_BACKEND)

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        cols = [r[1] for r in db.execute(text("PRAGMA table_info(optimization_runs)")).fetchall()]
        if not cols:
            raise SystemExit(
                "optimization_runs has no columns — the database is empty or missing. "
                f"Looked in {_BACKEND}. Do not proceed: an empty DB here means SQLite "
                "created one rather than finding yours."
            )
        run_id = int(sys.argv[1]) if len(sys.argv) > 1 else db.execute(
            text("SELECT MAX(run_id) FROM optimization_runs")
        ).scalar()
        rows = db.execute(
            text(f"SELECT {','.join(cols)} FROM optimization_runs WHERE run_id = :r"),
            {"r": run_id},
        ).fetchall()
        print(json.dumps([dict(zip(cols, r, strict=True)) for r in rows], indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
