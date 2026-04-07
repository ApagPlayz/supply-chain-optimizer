#!/usr/bin/env python
"""Management CLI for the Supply Chain Intelligence Platform.

Usage:
    python manage.py seed          # Seed 25 hubs, 200 materials, 120 suppliers
    python manage.py seed --reset  # Drop all data first, then seed
"""
import sys
import argparse


def cmd_seed(reset: bool = False) -> None:
    from seeds.seed_db import run_seed  # type: ignore[import]
    run_seed(reset=reset)


def main() -> None:
    parser = argparse.ArgumentParser(description="Supply Chain Platform management commands")
    subparsers = parser.add_subparsers(dest="command")

    seed_parser = subparsers.add_parser("seed", help="Load seed data into the database")
    seed_parser.add_argument("--reset", action="store_true", help="Delete existing data before seeding")

    args = parser.parse_args()

    if args.command == "seed":
        cmd_seed(reset=getattr(args, "reset", False))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
