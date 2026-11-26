#!/usr/bin/env python3
"""Reproduce the significance tests reported in the paper. Uses only the standard library.

- Python configurations against SBP-Random: exact McNemar tests, pairing games by seed.
- SBP-Native against each Python configuration: exact two-sided binomial tests against 50%.
- Holm adjustment within each group of three.
"""
import csv
import json
import math
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"


def exact_two_sided(b, c):
    """Exact two-sided binomial test with p = 0.5 (the exact McNemar test on discordant pairs)."""
    n, k = b + c, min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def holm(p_values):
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted, running = [0.0] * len(p_values), 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def load():
    with open(RESULTS / "manifest.csv", newline="", encoding="utf-8") as handle:
        return {
            (r["table"], r["row"]): json.loads((RESULTS / r["file"]).read_text(encoding="utf-8"))["results"]
            for r in csv.DictReader(handle)
        }


def main():
    runs = load()
    names = ["Py-Base", "Py-SBP-Core", "Py-SBP-Strategies"]
    # In these files the Python player is player 1.
    wins = {n: {g["seed"]: g["winner"] == 1 for g in runs[("Table 3", n + " vs SBP-Random")]} for n in names}

    pairs, p_values = [], []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            only_a = sum(wins[a][s] and not wins[b][s] for s in wins[a])
            only_b = sum(wins[b][s] and not wins[a][s] for s in wins[a])
            pairs.append("%s vs %s (only first wins: %d, only second: %d)" % (a, b, only_a, only_b))
            p_values.append(exact_two_sided(only_a, only_b))
    print("Exact McNemar tests, Holm-adjusted")
    for label, p in zip(pairs, holm(p_values)):
        print("  %-70s p = %.2g" % (label, p))

    labels, p_values = [], []
    for n in names:
        games = runs[("Table 4", n + " vs SBP-Native")]
        native = sum(g["winner"] == 0 for g in games)  # SBP-Native is player 0 in these files
        labels.append("SBP-Native vs %s (%d of %d wins)" % (n, native, len(games)))
        p_values.append(exact_two_sided(native, len(games) - native))
    print("Exact binomial tests against 50%, Holm-adjusted")
    for label, p in zip(labels, holm(p_values)):
        print("  %-70s p = %.2g" % (label, p))

    games = runs[("Table 2", "SBP-Random vs Py-Random")]
    first = sum(g["winner"] == 0 for g in games)
    print("Random baselines: SBP-Random wins %d of %d, two-sided p = %.2g"
          % (first, len(games), exact_two_sided(first, len(games) - first)))


if __name__ == "__main__":
    main()
