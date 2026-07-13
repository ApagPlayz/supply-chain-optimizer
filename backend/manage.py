#!/usr/bin/env python
"""Management CLI for the Supply Chain Intelligence Platform.

Usage:
    python manage.py seed   # Load 791 components / 92 distributors / 8,176 offers

Seeding is always destructive: seed_db.seed() clears components, distributors,
offers, orders and cart items before reloading them from the source dataset.
"""
import sys
import argparse


def cmd_seed() -> None:
    from seeds.seed_db import seed  # type: ignore[import]
    seed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Supply Chain Platform management commands")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "seed",
        help="Reload seed data from the source dataset (clears existing data first)",
    )

    args = parser.parse_args()

    if args.command == "seed":
        cmd_seed()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
