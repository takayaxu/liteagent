#!/usr/bin/env python3
"""Inspect or configure the shared repair pool (no guest/model mutations)."""
import argparse
import json

from repair_resources import RepairResources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    configure = commands.add_parser("configure")
    configure.add_argument("--slots", type=int, required=True)
    args = parser.parse_args()
    pool = RepairResources()
    result = pool.status() if args.command == "status" else pool.configure(args.slots)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
