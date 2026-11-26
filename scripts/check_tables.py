#!/usr/bin/env python3
"""Recompute the win rates in the paper's tables from the stored per-game results.

Uses only the standard library. Run from anywhere:  python scripts/check_tables.py
"""
import csv
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"


def rates(games, player):
    """Return (overall, when starting, when second) win rates, rounded as in the paper."""
    groups = (
        games,
        [g for g in games if g["starting_player"] == player],
        [g for g in games if g["starting_player"] != player],
    )
    return tuple(round(100.0 * sum(g["winner"] == player for g in grp) / len(grp) + 1e-9, 1) for grp in groups)


def main():
    failures = 0
    with open(RESULTS / "manifest.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        data = json.loads((RESULTS / row["file"]).read_text(encoding="utf-8"))
        games = data["results"]
        problems = []
        if [g["seed"] for g in games] != list(range(10000)):
            problems.append("seeds are not 0..9999")
        if data.get("errors") or any(g["ended_in_draw"] or g["ended_in_deadlock"] for g in games):
            problems.append("contains errors, draws, or deadlocks")
        for player, column in ((0, "paper_p0"), (1, "paper_p1")):
            if row[column]:
                expected = tuple(float(v) for v in row[column].split("/"))
                if rates(games, player) != expected:
                    problems.append("P%d is %s, paper reports %s" % (player, rates(games, player), expected))
        failures += bool(problems)
        print("%-4s %-8s %-44s %s" % ("FAIL" if problems else "ok", row["table"], row["row"], "; ".join(problems)))
    print("\n%d of %d rows match." % (len(rows) - failures, len(rows)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
