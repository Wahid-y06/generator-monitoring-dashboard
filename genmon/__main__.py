"""Command-line entry point: ``python -m genmon --scenario overload``."""
from __future__ import annotations

import argparse
from pathlib import Path

from .alarms import peak_levels
from .simulation import SCENARIOS, load_config, run, write_csv

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "default.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="genmon",
                                 description="Generator monitoring and alarm simulator")
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="normal")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--dt", type=float, default=0.1, help="time step in seconds")
    ap.add_argument("--noise", type=float, default=0.0,
                    help="relative measurement noise, e.g. 0.002 for 0.2%%")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--csv", type=Path, help="write samples to this CSV file")
    ap.add_argument("--plot", type=Path, help="save the dashboard plot to this PNG")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = ap.parse_args(argv)

    if args.list:
        for s in SCENARIOS.values():
            print(f"{s.name:<15} {s.description}")
        return 0

    result = run(SCENARIOS[args.scenario], load_config(args.config),
                 dt=args.dt, noise=args.noise, seed=args.seed)

    print(f"Scenario: {result.scenario.name} - {result.scenario.description}")
    print(f"{len(result.samples)} samples, {len(result.events)} alarm events\n")
    for event in result.events:
        print(event)
    peaks = peak_levels(result.events)
    print("\nPeak level per channel: " + (", ".join(
        f"{ch}={lvl.name}" for ch, lvl in peaks.items()) or "all NORMAL"))

    if args.csv:
        write_csv(result, args.csv)
        print(f"CSV written to {args.csv}")
    if args.plot:
        from .plot import plot_result  # matplotlib only needed when plotting
        plot_result(result, args.plot)
        print(f"Plot written to {args.plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
