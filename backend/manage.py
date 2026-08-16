#!/usr/bin/env python
"""Management CLI for the Supply Chain Intelligence Platform.

Usage
-----
    python manage.py db-status              # what's in the DB right now
    python manage.py seed                   # reseed, then auto-restore the backfill
    python manage.py seed --yes             # same, no interactive confirmation
    python manage.py seed --no-restore      # reseed and leave the DB stripped
    python manage.py restore-backfill       # panel CSV -> DB (alias: sync-lead-times)
    python manage.py list-scripts           # the other seeds/ entry points
    python manage.py run <script> [args...] # run one of them

Why `seed` needs a wrapper
--------------------------
``seeds.seed_db.seed()`` is destructive by design: it ``DELETE``s
``distributor_offers``, ``cart_items``, ``orders``, ``components`` and
``distributors`` before reloading them from the HuggingFace dataset.

The part that is *not* by design is the collateral damage. The reloaded
``components`` rows are brand new, so every column the DigiKey collector
backfilled onto the old rows — the eight migration-0006 columns and the seven
migration-0007 columns — comes back NULL. A run that reports "Seed complete!"
therefore silently destroys weeks of accumulated real catalogue data, and
nothing in the output says so.

That data is recoverable: the observed lead-time panel CSV is the system of
record, and ``app.ml.lead_time_collector.sync_db_from_panel()`` pushes it back
into the DB in well under a second. The recovery just was not wired to anything,
was undocumented, and was not a subcommand.

So this wrapper:

1. **Warns loudly, with real numbers, before it runs** — it prints how many rows
   are populated in each backfilled column *right now*, and which of them are
   about to be zeroed, then asks for confirmation.
2. **Automatically restores afterwards** — it re-runs the panel -> DB sync and
   re-seeds ``cross_dock_hubs`` as soon as ``seed()`` returns.
3. **Reports before / after / restored counts** so the damage and the repair are
   both visible instead of assumed.

Known un-restorable casualty: ``users``. No seed script creates users — the demo
account is created on demand by ``POST /auth/demo`` — so if the seed clears it,
this CLI says so plainly rather than pretending the restore was total.

This module also pins its own working directory to ``backend/``. The configured
``DATABASE_URL`` default is ``sqlite:///./supply_chain.db``, which is relative to
the *process CWD*: running the seeder from the repo root would quietly target a
different (empty) SQLite file and look like a total data loss. Every command here
prints the absolute database file it resolved before touching it.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parent

# `DATABASE_URL=sqlite:///./supply_chain.db` resolves against the CWD, so pin it.
# Without this, `python backend/manage.py seed` from the repo root seeds a
# different file than `cd backend && python manage.py seed`.
os.chdir(BACKEND_DIR)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ── what the seed destroys ───────────────────────────────────────────────────
#
# Table -> the columns a successful seed() blanks, because it deletes and
# recreates the rows those columns hang off. Sourced from migrations 0006 and
# 0007; kept as literal constants so the SQL below has no injection surface.

_BACKFILL_COLUMNS: Dict[str, List[str]] = {
    "components": [
        # migration 0006 — DigiKey catalogue attributes
        "lifecycle_status",
        "normally_stocked",
        "discontinued",
        "end_of_life",
        "digikey_category",
        "digikey_subcategory",
        "observed_lead_time_weeks",
        "lead_time_observed_at",
        # migration 0007 — lead-time model features
        "parameter_count",
        "package_case",
        "htsus_code",
        "rohs_status",
        "digikey_unit_price",
        "max_break_qty",
        "price_break_count",
    ],
    "distributor_offers": [
        # migration 0006 — offer-level packaging
        "standard_pack",
        "packaging",
    ],
}

#: Row counts worth watching across a seed even though seed_db.py never names
#: these tables in its DELETE loop.
_WATCHED_TABLES = ["components", "distributors", "distributor_offers",
                   "cross_dock_hubs", "users", "cart_items", "orders"]

#: Tables the automatic restore CAN rebuild, and how.
_RESTORABLE = {
    "backfill columns": "app.ml.lead_time_collector.sync_db_from_panel()",
    "cross_dock_hubs": "seeds.seed_cross_dock_hubs",
}
#: Tables nothing in the repo can rebuild.
_UNRESTORABLE = {
    "users": "created on demand by POST /auth/demo — no seed script makes one",
    "cart_items / orders": "user activity; seed_demo_cart can recreate a demo cart",
}


# ── DB introspection ─────────────────────────────────────────────────────────

def _db_target() -> str:
    """The absolute database the app is configured to talk to, for printing."""
    from app.core.config import settings
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        return f"{url}   ->   {Path(url[len('sqlite:///'):]).resolve()}"
    # Never print a Postgres password.
    if "@" in url:
        scheme, _, tail = url.partition("://")
        return f"{scheme}://***@{tail.rpartition('@')[2]}"
    return url


def _fingerprint() -> Dict[str, Any]:
    """
    Snapshot of everything a seed can destroy: row counts for the watched
    tables, plus populated (non-NULL) counts for every backfilled column.

    Returns ``{"tables": {name: rows}, "columns": {"table.col": (filled, total)}}``.
    Missing tables/columns are simply absent, so this works on a DB that has not
    had migrations 0006/0007 applied.
    """
    import sqlalchemy as sa
    from app.core.database import engine

    inspector = sa.inspect(engine)
    present = set(inspector.get_table_names())
    tables: Dict[str, int] = {}
    columns: Dict[str, Tuple[int, int]] = {}

    with engine.connect() as conn:
        for table in _WATCHED_TABLES:
            if table in present:
                tables[table] = int(
                    conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
                )
        for table, cols in _BACKFILL_COLUMNS.items():
            if table not in present:
                continue
            total = tables.get(table, 0)
            have = {c["name"] for c in inspector.get_columns(table)}
            for col in cols:
                if col not in have:
                    continue
                # COUNT(col) counts non-NULL only — that is the "populated" number.
                filled = int(
                    conn.execute(sa.text(f'SELECT COUNT("{col}") FROM {table}')).scalar() or 0
                )
                columns[f"{table}.{col}"] = (filled, total)
    return {"tables": tables, "columns": columns}


def _populated_total(fp: Dict[str, Any]) -> int:
    return sum(filled for filled, _ in fp["columns"].values())


# ── reporting ────────────────────────────────────────────────────────────────

def _print_fingerprint(fp: Dict[str, Any], title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for name, rows in fp["tables"].items():
        print(f"  {name:<22} {rows:>7,} rows")
    if fp["columns"]:
        print("  backfilled columns (populated / total):")
        for name, (filled, total) in fp["columns"].items():
            print(f"    {name:<46} {filled:>6,} / {total:,}")


def _print_delta_table(before: Dict[str, Any], after: Dict[str, Any],
                       restored: Optional[Dict[str, Any]]) -> None:
    """The whole point of the wrapper: show what the seed cost and what came back."""
    cols = ["before", "after seed"] + (["after restore"] if restored else [])
    header = f"{'':<48}" + "".join(f"{c:>15}" for c in cols)
    print("\n" + "=" * len(header))
    print("SEED IMPACT — populated (non-NULL) row counts")
    print("=" * len(header))
    print(header)

    def _row(label: str, b: Any, a: Any, r: Any) -> None:
        cells = [b, a] + ([r] if restored else [])
        print(f"  {label:<46}" + "".join(f"{str(c):>15}" for c in cells))

    print("\n  table row counts")
    for name in before["tables"]:
        _row(name,
             f"{before['tables'].get(name, 0):,}",
             f"{after['tables'].get(name, 0):,}",
             f"{restored['tables'].get(name, 0):,}" if restored else None)

    print("\n  backfilled columns  (populated / total)")
    for name in before["columns"]:
        bf, bt = before["columns"].get(name, (0, 0))
        af, at = after["columns"].get(name, (0, 0))
        cell = None
        if restored:
            rf, rt = restored["columns"].get(name, (0, 0))
            cell = f"{rf:,}/{rt:,}"
        _row(name, f"{bf:,}/{bt:,}", f"{af:,}/{at:,}", cell)

    b_tot = _populated_total(before)
    a_tot = _populated_total(after)
    print("\n" + "-" * len(header))
    print(f"  TOTAL populated backfill cells: {b_tot:,} before -> {a_tot:,} after seed"
          + (f" -> {_populated_total(restored):,} after restore" if restored else ""))

    if restored:
        r_tot = _populated_total(restored)
        if r_tot >= b_tot:
            print(f"  ✅ backfill fully restored ({r_tot:,} >= {b_tot:,}).")
        else:
            print(f"  ⚠️  backfill NOT fully restored: {r_tot:,} of {b_tot:,} cells "
                  f"({b_tot - r_tot:,} still missing). The panel CSV only covers "
                  f"parts it has observed rows for.")
        lost = [t for t, n in before["tables"].items()
                if n > 0 and restored["tables"].get(t, 0) == 0]
        if lost:
            print(f"  ⚠️  emptied and NOT restored: {', '.join(lost)}")
            for table, why in _UNRESTORABLE.items():
                print(f"       - {table}: {why}")
    print("=" * len(header))


def _warn(before: Dict[str, Any]) -> None:
    bar = "!" * 78
    print("\n" + bar)
    print("!!  DESTRUCTIVE OPERATION — `seeds.seed_db.seed()`")
    print(bar)
    print(f"  target database: {_db_target()}")
    print("\n  seed() DELETEs, then reloads from HuggingFace:")
    print("      distributor_offers, cart_items, orders, components, distributors")
    print("\n  Because the component rows are recreated from scratch, EVERYTHING")
    print("  the DigiKey collector backfilled onto them is lost:")
    n_cols = len(before["columns"])
    n_cells = _populated_total(before)
    print(f"      {n_cols} backfilled columns, {n_cells:,} populated cells -> 0")
    for name, (filled, total) in before["columns"].items():
        if filled:
            print(f"        {name:<46} {filled:>6,} / {total:,}  ->  0")
    for table in ("cross_dock_hubs", "users", "cart_items", "orders"):
        rows = before["tables"].get(table)
        if rows:
            print(f"        {table:<46} {rows:>6,} rows      ->  at risk")
    print("\n  Recoverable automatically after the seed:")
    for what, how in _RESTORABLE.items():
        print(f"      + {what:<20} via {how}")
    print("  NOT recoverable by any script in this repo:")
    for what, why in _UNRESTORABLE.items():
        print(f"      - {what:<20} {why}")
    print(bar)


# ── restore ──────────────────────────────────────────────────────────────────

def _restore_backfill(include_hubs: bool = True) -> Dict[str, Any]:
    """
    Push the observed lead-time panel back into the DB, and re-seed the static
    cross-dock hubs. This is the previously-undocumented recovery path
    (`python -m app.ml.lead_time_collector --sync-only`) made first-class.
    """
    from app.ml.lead_time_collector import PANEL_PATH, sync_db_from_panel

    out: Dict[str, Any] = {}
    print(f"\n→ restoring backfill from panel: {PANEL_PATH}")
    if not PANEL_PATH.exists():
        print("  ⚠️  panel CSV does not exist — nothing to restore from.")
        out["panel_sync"] = {"status": "no_panel"}
    else:
        sync = sync_db_from_panel()
        out["panel_sync"] = sync
        status = sync.get("status")
        if status == "synced":
            print(f"  ✓ panel -> DB: {sync.get('components_updated', 0)} components, "
                  f"{sync.get('offers_updated', 0)} offers updated "
                  f"(of {sync.get('components_total', 0)} components in DB)")
        else:
            print(f"  ⚠️  panel sync returned status={status!r} — nothing written.")

    if include_hubs:
        print("→ re-seeding cross_dock_hubs")
        try:
            from seeds.seed_cross_dock_hubs import main as seed_hubs  # type: ignore[import]
            seed_hubs()
            out["cross_dock_hubs"] = "reseeded"
        except Exception as exc:  # noqa: BLE001 — a hub failure must not mask the sync
            print(f"  ⚠️  cross-dock hub reseed failed: {exc}")
            print("     run it yourself with: python -m seeds.seed_cross_dock_hubs")
            out["cross_dock_hubs"] = f"error: {exc}"
    return out


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_db_status(_args: argparse.Namespace) -> int:
    print(f"database: {_db_target()}")
    _print_fingerprint(_fingerprint(), "Current contents")
    return 0


def cmd_restore_backfill(args: argparse.Namespace) -> int:
    print(f"database: {_db_target()}")
    before = _fingerprint()
    result = _restore_backfill(include_hubs=not args.no_hubs)
    after = _fingerprint()
    print(f"\npopulated backfill cells: {_populated_total(before):,} "
          f"-> {_populated_total(after):,}")
    _print_fingerprint(after, "After restore")
    ok = result.get("panel_sync", {}).get("status") == "synced"
    if not ok:
        print("\n✗ restore did not write anything.")
    return 0 if ok else 1


def cmd_seed(args: argparse.Namespace) -> int:
    # Fail before the DELETEs, not after. seed_db.py imports `datasets` as the
    # first statement of seed(), so a missing dependency aborts harmlessly —
    # but only if it aborts. Say so clearly instead of raising a bare traceback.
    try:
        import datasets  # noqa: F401
    except ModuleNotFoundError:
        print("✗ the `datasets` package is not installed.", file=sys.stderr)
        print("  seeds/seed_db.py imports it unconditionally (it is a hard "
              "requirement, not a fallback).", file=sys.stderr)
        print("  fix: pip install -r requirements.txt", file=sys.stderr)
        return 1

    before = _fingerprint()
    _warn(before)

    if not args.yes:
        try:
            answer = input("\nType 'seed' to proceed (anything else aborts): ")
        except (EOFError, KeyboardInterrupt):
            print("\naborted.")
            return 1
        if answer.strip().lower() != "seed":
            print("aborted — nothing was changed.")
            return 1

    from seeds.seed_db import seed  # type: ignore[import]
    seed()
    after = _fingerprint()

    restored = None
    if args.restore:
        _restore_backfill(include_hubs=True)
        restored = _fingerprint()
    else:
        print("\n⚠️  --no-restore given: the backfill is still wiped. Recover with:")
        print("       python manage.py restore-backfill")

    _print_delta_table(before, after, restored)
    return 0


# ── the other seeds/ entry points ────────────────────────────────────────────
#
# `seed` used to be the only subcommand while seventeen other runnable scripts
# in seeds/ had no entry point at all. These two commands expose them without
# duplicating their argument parsing: `run` just execs `python -m seeds.<name>`.

def _seed_scripts() -> List[str]:
    return sorted(
        p.stem for p in (BACKEND_DIR / "seeds").glob("*.py")
        if p.stem not in ("__init__", "seed_db") and not p.stem.startswith("_")
    )


def cmd_list_scripts(_args: argparse.Namespace) -> int:
    print("Runnable scripts in seeds/ (use: python manage.py run <name> [args...])\n")
    for name in _seed_scripts():
        doc = ""
        try:
            text = (BACKEND_DIR / "seeds" / f"{name}.py").read_text(encoding="utf-8")
            for quote in ('"""', "'''"):
                if quote in text:
                    body = text.split(quote, 2)[1].strip()
                    doc = body.splitlines()[0].strip() if body else ""
                    break
        except Exception:  # noqa: BLE001 — a listing must never crash
            pass
        print(f"  {name:<28} {doc[:88]}")
    print("\n  seed_db is deliberately excluded — use `manage.py seed`, which "
          "warns and restores.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.script == "seed_db":
        print("✗ refusing: run `python manage.py seed` instead — it warns before "
              "the wipe and restores the backfill afterwards.", file=sys.stderr)
        return 1
    available = _seed_scripts()
    if args.script not in available:
        print(f"✗ unknown script {args.script!r}. Try: python manage.py list-scripts",
              file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, "-m", f"seeds.{args.script}", *args.args],
                           cwd=str(BACKEND_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supply Chain Platform management commands",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_seed = sub.add_parser(
        "seed",
        help="Reload seed data (DESTRUCTIVE: wipes the DigiKey backfill, then "
             "restores it automatically)",
    )
    p_seed.add_argument("-y", "--yes", action="store_true",
                        help="Skip the interactive confirmation.")
    p_seed.add_argument("--no-restore", dest="restore", action="store_false",
                        help="Do NOT re-run the backfill restore after seeding.")
    p_seed.set_defaults(func=cmd_seed)

    for name in ("restore-backfill", "sync-lead-times"):
        p_restore = sub.add_parser(
            name,
            help="Push the observed lead-time panel back into the DB "
                 "(repairs a seed; also re-seeds cross_dock_hubs)",
        )
        p_restore.add_argument("--no-hubs", action="store_true",
                               help="Skip re-seeding cross_dock_hubs.")
        p_restore.set_defaults(func=cmd_restore_backfill)

    sub.add_parser(
        "db-status", help="Show row counts and backfill fill levels",
    ).set_defaults(func=cmd_db_status)

    sub.add_parser(
        "list-scripts", help="List the other runnable scripts in seeds/",
    ).set_defaults(func=cmd_list_scripts)

    p_run = sub.add_parser("run", help="Run a seeds/ script: manage.py run <name>")
    p_run.add_argument("script")
    p_run.add_argument("args", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        sys.exit(1)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
