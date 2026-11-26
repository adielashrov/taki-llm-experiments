#!/usr/bin/env python3
"""Replay the games behind a table row with the code in ../code and compare them one by one.

Examples:
    python scripts/replay.py --games 100            # first 100 games of every row
    python scripts/replay.py --games 10000          # complete replay (takes much longer)
"""
import argparse
import csv
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))

import taki_simulation as sim  # noqa: E402

AGENTS = {
    "py_base": sim.TakiStrategyAgentV1,
    "py_sbp_core": sim.TakiStrategyAgentV2,
    "py_sbp_strategies": sim.TakiStrategyAgentV3,
}


def replay(row, games):
    """Return the number of replayed games with the same winner and length as the stored ones."""
    stored = json.loads((ROOT / "results" / row["file"]).read_text(encoding="utf-8"))["results"][:games]
    # One agent object is used for a whole run, as in the original simulations.
    agent = AGENTS[row["python_player"]]() if row["python_player"] in AGENTS else None
    identical = 0
    for game in stored:
        if row["python_player"]:
            result = sim.run_single_game_basic_vs_strategy(
                game_number=game["game_number"], seed=game["seed"], player_0_strategy=row["sbp_p0"],
                starting_player=game["starting_player"], player_1_agent=agent, silent=True)
        else:
            result = sim.run_single_game(
                game_number=game["game_number"], seed=game["seed"], player_0_strategy=row["sbp_p0"],
                player_1_strategy=row["sbp_p1"], player_0_block_super_taki=row["block_p0"] == "yes",
                player_1_block_super_taki=row["block_p1"] == "yes",
                starting_player=game["starting_player"], silent=True)
        identical += bool(result) and (result.winner, result.event_count) == (game["winner"], game["event_count"])
    return identical, len(stored)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=100, help="games to replay per row (default: 100)")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with open(ROOT / "results" / "manifest.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["exact_replay"] != "yes":
            print("skip %-8s %-44s %s" % (row["table"], row["row"], row["note"]))
            continue
        identical, total = replay(row, args.games)
        print("%-4s %-8s %-44s %d/%d identical" % (
            "ok" if identical == total else "FAIL", row["table"], row["row"], identical, total), flush=True)


if __name__ == "__main__":
    main()
