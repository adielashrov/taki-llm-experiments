# taki-llm-experiments

Replication package for the paper *"From Domain Knowledge to Composable
Reactive Code: LLM-Assisted Development with Scenario-Based Programming"*
(accepted to MODELSWARD 2027). The paper and its supplementary material are in
[`paper/`](./paper).

The main TAKI implementation is maintained in
[`bp-taki`](https://github.com/adielashrov/bp-taki), in Scenario-Based
Programming (SBP), also known as Behavioral Programming (BP). That
implementation continues to evolve. To reproduce the paper, use the files in
this repository.

## Repository contents

| Folder | Contents |
|---|---|
| [`configurations/`](./configurations) | For each configuration: the prompt (`instructions.md`), the main code context, the generated Python strategy where there is one, and the source commit |
| [`code/`](./code) | The evaluation code: the TAKI game, the hand-authored and generated SBP strategies, the generated Python strategies, the simulation script, and the modified BPpy package it needs |
| [`results/`](./results) | Per-game results behind every row of the result tables, with [`manifest.csv`](./results/manifest.csv) linking each row to its file |
| [`scripts/`](./scripts) | Scripts that check the tables, run the significance tests, and replay games |
| [`paper/`](./paper) | The paper and the supplementary material |

## Configurations

| Configuration | Folder | Generated artifact | Name in `code/` |
|---|---|---|---|
| Py-Base | `configurations/py-base` | Python player | `TakiStrategyAgentV1` |
| Py-SBP-Core | `configurations/py-sbp-core` | Python player | `TakiStrategyAgentV2` |
| Py-SBP-Strategies | `configurations/py-sbp-strategies` | Python player | `TakiStrategyAgentV3` |
| SBP-Native | `configurations/sbp-native` | SBP strategy b-thread | `strategic_taki_strategy` |

The three Python players in `code/` are the generated files with only the
class name changed.

Each configuration was developed on its own branch of this repository. The
files visible to the model were those in the commit named in the folder's
`SOURCE.md`; the folder holds the main ones. In the result files and older
branches, `basic` is SBP-Random, `strategic` is SBP-Native, and
`heuristic_v1`, `_v2`, and `_v3` are the three Python players.

## How the strategies were generated

The prompts were written by the authors and refined with Claude Sonnet 4.6.
The context and prompt were then given to Codex, using GPT-5.4. The four
evaluated strategies were generated in April and May 2026. The model could
read the source files, run tests, and revise its code, without further human
guidance. Generation is not deterministic, so running the prompts again is not
expected to produce the same code.

## Reproducing the results

The code was tested with Python 3.9.5. Install the one dependency:

```bash
pip install -r requirements.txt
```

BPpy is included in `code/bppy`. It differs from the version on PyPI, which
does not run this code.

Check every table row against the per-game results:

```bash
python scripts/check_tables.py
```

Reproduce the significance tests:

```bash
python scripts/significance.py
```

Replay games and compare their winners and lengths with the stored results:

```bash
python scripts/replay.py --games 100
python scripts/replay.py --games 10000
```

Each run uses seeds 0 to 9999, with balanced starting players. Each stored game
records its seed, starting player, winner, and number of events.

### Notes

- **Table 4, Py-Random vs. SBP-Native:** the random Python player was not
  seeded in this run. The stored results give the reported rates, but these
  games cannot be replayed exactly. `replay.py` skips this row.
- **Appendix Table 1, both players blocked:** the result file comes from a
  re-run with the code in this package. An earlier stored run for this setting
  was identical, game for game, to the run without the blocking b-threads.

## Game variant and Python player interface

The implemented variant supports number cards, Stop, Change Color, TAKI, and
Super TAKI. A Python player subclasses `TakiAgent` and implements
`get_action`:

```python
from python_taki_api import TakiAgent

class MyAgent(TakiAgent):
    def get_action(self, state: dict) -> str:
        ...
```

The observation schema and action names are described in
[`code/python_taki_api/readme.md`](./code/python_taki_api/readme.md).

## License

MIT. See [`LICENSE`](./LICENSE).
