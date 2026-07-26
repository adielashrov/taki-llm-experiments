# taki-llm-experiments

This repository provides the replication package for the experiments presented
in the paper *"From Domain Knowledge to Composable Reactive Code:
LLM-Assisted Development with Scenario-Based Programming"*, currently under
review for ICECCS 2026.

It contains the code versions, experimental configurations, prompts, generated
strategies, and simulation setup used to produce the results reported in the
paper. Use this repository to reproduce the paper's experiments under the
evaluated conditions.

The main TAKI implementation is maintained in
[`bp-taki`](https://github.com/adielashrov/bp-taki). That repository contains
the evolving implementation of the TAKI card game in Scenario-Based
Programming (SBP), also known as Behavioral Programming (BP), together with
additional hand-authored strategies and implementation extensions.

Because the main implementation continues to evolve, the experiments reported
in the paper should be reproduced using the artifacts and configurations stored
in this repository.

## Repository contents

This replication package includes:

- the TAKI implementation version used in the experiments;
- the Python-agent interface used by the generated Python strategies;
- the prompts and context configurations provided to the target LLM;
- the generated Python and SBP strategies;
- the hand-authored SBP strategy examples;
- the simulation and evaluation scripts used to produce the reported results.

## Python-agent interface

The `python_taki_api` package defines the interface used by Python-based TAKI
agents. A custom agent subclasses `TakiAgent` and implements `get_action`:

```python
from python_taki_api import TakiAgent

class MyAgent(TakiAgent):
    def get_action(self, state: dict) -> str:
        ...
```

The implemented game variant supports number cards, Stop, Change Color, TAKI,
and Super TAKI. The complete observation schema, action-name format, and
agent-implementation instructions are provided in
[`python_taki_api/readme.md`](https://github.com/adielashrov/taki-llm-experiments/blob/main/python_taki_api/readme.md).

## Paper and supplementary material

The paper and its supplementary material are available in the
[`paper/`](https://github.com/adielashrov/taki-llm-experiments/blob/main/paper)
directory.
