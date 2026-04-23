This package provides the interface for implementing a TAKI-playing agent that integrates with the BP-TAKI bridge.

It models a reduced TAKI variant. Supported cards: NUMBER, STOP, CHANGE_COLOR, TAKI, SUPER_TAKI.

## Key classes

**`TakiAgent`** — abstract base class for all agents. Implement `get_action` to create your own agent.

**`PythonAgent`** — a minimal concrete agent that picks the first legal-looking card from its hand. Intended as a placeholder and starting point for custom implementations.

**`TakiStrategyAgent`** - deterministic heuristic agent that prioritizes legal hand reduction, useful TAKI sequences, stop cards, and color control.

**`TakiGame`** — abstract interface for a game engine. Implement this if you want to run standalone Python episodes outside of BP.

## Implementing an agent

Subclass `TakiAgent` and implement `get_action`:

```python
from python_taki_api import TakiAgent

class MyAgent(TakiAgent):
    def get_action(self, state: dict) -> str:
        ...
```

`get_action` receives a flat `dict[str, str]` and returns an action name string.

### Observation keys

| Key | Values |
|-----|--------|
| `player_index` | `"0"`, `"1"`, … |
| `phase` | `"turn"` \| `"taki_sequence"` \| `"change_color"` \| `"terminal"` |
| `hand` | comma-separated card names, e.g. `"card_4_blue,stop_red"` |
| `top_card` | descriptor e.g. `"card_3_blue"`, or `""` at game start |
| `active_color` | `"red"` \| `"blue"` \| `"green"` \| `""` (empty during CHANGE_COLOR) |
| `rule_mode` | `"match_color_or_type"` \| `"color_only"` \| `"taki"` |
| `taki_color` | `"red"` \| `"blue"` \| `"green"` \| `""` (non-empty only during TAKI_SEQUENCE) |

### Action name format

| Card | Format | Example |
|------|--------|---------|
| Number card | `card_{number}_{color}` | `card_4_blue` |
| Stop | `stop_{color}` | `stop_red` |
| TAKI | `taki_{color}` | `taki_green` |
| Super TAKI | `super_taki` | |
| Change color | `change_color` | |
| Draw card | `draw_card` | |
| Close TAKI | `closed_taki` | |
| Select color | `selected_{color}` | `selected_blue` |
