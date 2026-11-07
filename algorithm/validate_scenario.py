"""Check that a seven-day simulation matches a versioned graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .seven_day import validate_seven_day_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("scenario", type=Path)
    args = parser.parse_args(argv)
    try:
        graph = json.loads(args.graph.read_text(encoding="utf-8"))
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        validate_seven_day_scenario(graph, scenario)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Scenario validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Seven-day scenario matches graph {graph['graph_version']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
