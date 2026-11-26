import random
from typing import Dict, List, Optional
from .taki_agent import TakiAgent


def _card_color(descriptor: str) -> Optional[str]:
    """Return the color suffix of a card descriptor, or None for colorless cards."""
    # card_{number}_{color}, stop_{color}, taki_{color}
    parts = descriptor.split("_")
    if descriptor.startswith("card_") and len(parts) == 3:
        return parts[2]
    if descriptor.startswith("stop_") and len(parts) == 2:
        return parts[1]
    if descriptor.startswith("taki_") and len(parts) == 2:
        return parts[1]
    # super_taki, change_color — no color suffix
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
    # These cards are always legal in a normal turn.
    if kind in ("super_taki", "change_color"):
        return True
    color = _card_color(card)
    # Color match is always sufficient (covers match_color_or_type and color_only).
    if color and color == active_color:
        return True
    # Under match_color_or_type, same kind/number as the top card is also legal.
    if rule_mode == "match_color_or_type" and top_card:
        if _card_kind(card) == _card_kind(top_card) and kind != "number":
            return True
        if kind == "number" and _card_number(card) == _card_number(top_card):
            return True
    return False


def _is_legal_in_taki_sequence(card: str, taki_color: str) -> bool:
    """Return True if *card* is a legal play inside a TAKI sequence.

    Note: ``change_color`` is NOT legal during a TAKI sequence — the BP engine
    blocks it explicitly (only the color of the TAKI card governs the sequence).
    ``super_taki`` has no color constraint and is always legal.
    """
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
    # normal turn
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
