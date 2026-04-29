# TAKI Agent Prompt — Design Document

**Date:** 26/04/2026  
**Author:** Adiel Ashrov & Claude  
**Purpose:** Document the design decisions, rationale, and changelog behind the LLM prompt for generating a TAKI-playing agent as a concrete implementation of `TakiAgent`.

## PART 1 — Background: The TAKI Card Game

TAKI is a competitive 2-player card game. The **objective** is to be the first player to empty your hand. Players alternate turns. On each turn, a player must play a legal card from their hand onto the discard pile, or draw a card if no legal play exists.

**Card types and their effects:**

|Card|Format|Effect|
|---|---|---|
|Number card|`card_{number}_{color}`|Basic card. Played to match color or number.|
|Stop|`stop_{color}`|Skips the opponent's next turn entirely.|
|Change Color|`change_color`|Lets you choose the new active color (any of red, blue, green). Always legal to play.|
|TAKI|`taki_{color}`|Opens a TAKI sequence: you may chain as many same-color cards as you like before closing. Always legal to play.|
|Super TAKI|`super_taki`|Like TAKI, but color-agnostic — inherits the current active color. Always legal to play.|

**Placement rules:**

- In a normal turn (`rule_mode = "match_color_or_type"`): a card is legal if it matches the **active color** OR matches the **type/number** of the top card.
- After a `change_color` card (`rule_mode = "color_only"`): only cards matching the **active color** are legal (plus `change_color` and `super_taki` which are always legal).
- During a TAKI sequence (`rule_mode = "taki"`): only cards matching the **TAKI color** are legal, plus `super_taki`. `change_color` is **not** legal inside a TAKI sequence.

---

## PART 2 — Game Rules Reference

Two reference files are attached for context:

#### 2a. Official Rulebook (`SuperTaki_Web_Eng_2018.pdf`)

The official Super TAKI rulebook describes the complete game including all card types and mechanics.

**Important:** The implementation you are targeting supports only a **subset** of the full game. Treat the following as the authoritative card set — ignore all other card types mentioned in the rulebook:

- Number cards (`card_{number}_{color}`)
- Stop (`stop_{color}`)
- Change Color (`change_color`)
- TAKI (`taki_{color}`)
- Super TAKI (`super_taki`)

Specifically, the following cards from the rulebook **do not exist** in this implementation and must be ignored entirely: `+2`, `+3`, `+3 Breaker`, `King`, `Plus`, `Change Direction`.

#### 2b. BP Game Engine (`bp_taki.py`)

The attached file `bp_taki.py` is the complete implementation of the TAKI game engine in Behavioral Programming (BP) using the BPpy framework. You do not need to understand BP or replicate its idioms — your task is to implement a pure Python agent.

However, reading this file will give you precise, authoritative answers to questions such as:

- **Exact deck composition**: which card types exist, how many of each, and which number values are used — see `init_cards_events()`
- **Turn and sequence lifecycle**: how the engine drives a player's turn, how a TAKI sequence is entered and exited, and when `done_post_action` signals the end of a sequence — see `player_behavior()` and `enforce_turns()`
- **Placement rule enforcement**: exactly which cards are blocked or allowed in each game state — see `enforce_card_placement_rules()`, `init_selected_color_or_type_event_set()`, `create_block_set_color_only()`, and `create_taki_color_block()`
- **Post-TAKI state**: what color and type rule are in effect after a TAKI sequence ends — see the post-sequence logic in `enforce_card_placement_rules()`
- **How the external agent bridge works**: how your agent's `get_action` is called by the engine at each decision point — see `player_behavior_external()`
- **Existing strategies**: `bp_taki.py` contains strategy b-threads (`basic_strategy_taki`, `basic_strategy_taki_and_super_taki`, `strategy_block_super_taki_during_regular_taki`) that encode strategic intuitions about card prioritization expressed in BP idioms. These are not directly reusable — your task is to implement equivalent or superior strategic logic as a Python agent — but they may inspire your approach.

Use this file as a ground-truth reference for game mechanics. Ignore all logging, testing, deadlock/livelock detection, and infrastructure code — these are irrelevant to your strategy.

---

## PART 3 — The Agent Interface

Your agent must subclass `TakiAgent` and implement `get_action(state)`. The method receives a flat `Dict[str, str]` describing the current game state and must return a legal action name as a string.

```python
from abc import ABC, abstractmethod
from typing import Dict, Optional


class TakiAgent(ABC):
    @abstractmethod
    def get_action(self, state: Dict[str, str]) -> Optional[str]:
        raise NotImplementedError
```

**State dictionary — keys and values:**

| Key            | Type                                                              | Description                                                                |
| -------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `player_index` | `"0"` or `"1"`                                                    | Your player index                                                          |
| `phase`        | `"turn"` \| `"taki_sequence"` \| `"change_color"` \| `"terminal"` | Current game phase                                                         |
| `hand`         | comma-separated string                                            | Your current hand, e.g. `"card_4_blue,stop_red,taki_green"`                |
| `top_card`     | string                                                            | Top of the discard pile, e.g. `"card_3_blue"` (empty string if none)       |
| `active_color` | `"red"` \| `"blue"` \| `"green"` \| `""`                          | The currently active color (empty during `change_color` phase)             |
| `rule_mode`    | `"match_color_or_type"` \| `"color_only"` \| `"taki"`             | Current placement rule in effect                                           |
| `taki_color`   | `"red"` \| `"blue"` \| `"green"` \| `""`                          | Color constraint of the active TAKI sequence (empty outside TAKI sequence) |

**Legal non-card actions per phase:**

|Phase|Always-legal non-card actions|
|---|---|
|`turn`|`draw_card` (only if no legal card exists)|
|`taki_sequence`|`closed_taki` (ends the TAKI sequence and passes turn)|
|`change_color`|`selected_red`, `selected_blue`, `selected_green`|

---

## PART 4 — Reference Implementation: Random Agent

Below is a fully working agent (`PythonAgent`) that plays randomly. It includes helper functions for parsing card descriptors and checking legality. **You may reuse any of these helpers in your implementation.**

```python
import random
from typing import Dict, List, Optional
from .taki_agent import TakiAgent


def _card_color(descriptor: str) -> Optional[str]:
    """Return the color suffix of a card descriptor, or None for colorless cards."""
    parts = descriptor.split("_")
    if descriptor.startswith("card_") and len(parts) == 3:
        return parts[2]
    if descriptor.startswith("stop_") and len(parts) == 2:
        return parts[1]
    if descriptor.startswith("taki_") and len(parts) == 2:
        return parts[1]
    return None


def _card_number(descriptor: str) -> Optional[str]:
    """Return the number token of a number card, or None for non-number cards."""
    parts = descriptor.split("_")
    if descriptor.startswith("card_") and len(parts) == 3:
        return parts[1]
    return None


def _card_kind(descriptor: str) -> str:
    """Return a kind token: 'number', 'stop', 'taki', 'super_taki', 'change_color'."""
    if descriptor.startswith("card_"):
        return "number"
    if descriptor.startswith("stop_"):
        return "stop"
    if descriptor.startswith("taki_"):
        return "taki"
    return descriptor  # 'super_taki' or 'change_color'


def _is_legal_in_turn(card: str, top_card: str, active_color: str, rule_mode: str) -> bool:
    """Return True if *card* is a legal play during a normal turn."""
    kind = _card_kind(card)
    if kind in ("super_taki", "change_color"):
        return True
    color = _card_color(card)
    if color and color == active_color:
        return True
    if rule_mode == "match_color_or_type" and top_card:
        if _card_kind(card) == _card_kind(top_card) and kind != "number":
            return True
        if kind == "number" and _card_number(card) == _card_number(top_card):
            return True
    return False


def _is_legal_in_taki_sequence(card: str, taki_color: str) -> bool:
    """Return True if *card* is a legal play inside a TAKI sequence."""
    kind = _card_kind(card)
    if kind == "super_taki":
        return True
    color = _card_color(card)
    return color == taki_color


def _legal_cards(hand: List[str], state: Dict[str, str]) -> List[str]:
    phase = state.get("phase", "")
    top_card = state.get("top_card", "")
    active_color = state.get("active_color", "")
    rule_mode = state.get("rule_mode", "match_color_or_type")
    taki_color = state.get("taki_color", "")

    if phase == "taki_sequence":
        return [c for c in hand if _is_legal_in_taki_sequence(c, taki_color)]
    return [c for c in hand if _is_legal_in_turn(c, top_card, active_color, rule_mode)]


class PythonAgent(TakiAgent):
    def __init__(self, seed: Optional[int] = None):
        self.last_state: Optional[Dict[str, str]] = None
        self._rng = random.Random(seed)

    def get_action(self, state: Dict[str, str]) -> Optional[str]:
        self.last_state = state
        phase = state.get("phase", "")
        hand = [name for name in state.get("hand", "").split(",") if name]

        if phase == "change_color":
            return self._rng.choice(["selected_red", "selected_blue", "selected_green"])

        if phase == "taki_sequence":
            legal = _legal_cards(hand, state)
            return self._rng.choice(legal) if legal else "closed_taki"

        # Normal turn
        legal = _legal_cards(hand, state)
        return self._rng.choice(legal) if legal else "draw_card"
```

---

## PART 5 — Your Task

**Step 1 — Strategy proposal (prose):** Before writing any code, describe in plain language the strategy you will implement. Explain:

- What principles guide your card selection and why
- How you handle each phase (`turn`, `taki_sequence`, `change_color`)
- What tradeoffs you considered and why you made the choices you did

**Step 2 — Implementation:** Implement your strategy as a Python class named `TakiStrategyAgent` that subclasses `TakiAgent`. Requirements:

- Implement `get_action(self, state: Dict[str, str]) -> Optional[str]`
- Return only **legal** action names (use or adapt the legality helpers above)
- No external dependencies beyond the Python standard library
- Do not modify `TakiAgent` or the helper functions
- You may add private helper methods and class-level constants as needed

---

## PART 6 — Constraints & Notes

- The game is 2 players only
- `draw_card` should only be returned during a `turn` phase when no legal card exists; drawing ends your turn immediately — the drawn card cannot be played until your next turn
- `closed_taki` should only be returned during a `taki_sequence` phase
- `selected_{color}` should only be returned during a `change_color` phase
- During `change_color` phase, `hand` and other state fields still reflect the current game state and can inform your color choice
- The `phase = "terminal"` state will never be passed to `get_action` in practice; you do not need to handle it
- Do not include import statements for `TakiAgent` itself — it will be available in the same module
- Returning card names with player prefixes is incorrect: the `hand` field contains prefix-free names (e.g., `card_4_blue`, not `p_0_card_4_blue`), and your returned action must also be prefix-free