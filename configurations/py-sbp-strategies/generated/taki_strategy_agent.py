from typing import Dict, List, Optional, Sequence, Tuple

from .python_agent import _card_color, _card_kind, _card_number, _legal_cards
from .taki_agent import TakiAgent


COLORS: Sequence[str] = ("red", "blue", "green")


def _remove_one(cards: Sequence[str], target: str) -> List[str]:
    remaining = list(cards)
    remaining.remove(target)
    return remaining


def _matches_type_or_number(card: str, top_card: str) -> bool:
    card_kind = _card_kind(card)
    top_kind = _card_kind(top_card)
    if card_kind == "number" and top_kind == "number":
        return _card_number(card) == _card_number(top_card)
    return card_kind == top_kind and card_kind != "number"


class TakiStrategyAgent(TakiAgent):
    """
    Deterministic heuristic agent for the reduced TAKI rules used in this repo.

    Strategy summary:
    - Prefer plays that reduce hand size quickly without spending flexible wildcards
      too early.
    - Open a TAKI sequence aggressively only when it is likely to unload multiple
      additional cards.
    - Preserve `change_color` and `super_taki` as recovery tools unless they are the
      best tempo play or improve an endgame position.
    - Inside a TAKI sequence, dump expendable same-color cards first and keep a
      stronger finisher such as `stop_{color}` for later when possible.
    """

    def __init__(self) -> None:
        self.last_state: Optional[Dict[str, str]] = None

    def get_action(self, state: Dict[str, str]) -> Optional[str]:
        self.last_state = state
        phase = state.get("phase", "")
        hand = [name for name in state.get("hand", "").split(",") if name]

        if phase == "change_color":
            return self._choose_color_action(hand)

        if phase == "taki_sequence":
            return self._choose_taki_sequence_action(hand, state)

        legal = _legal_cards(hand, state)
        if not legal:
            return "draw_card"
        return max(legal, key=lambda card: self._score_turn_card(card, hand, state))

    def _choose_color_action(self, hand: Sequence[str]) -> str:
        ranked_colors = [
            (
                self._color_control_score(color, hand),
                self._color_counts(color, hand),
                -COLORS.index(color),
                color,
            )
            for color in COLORS
        ]
        best_color = max(ranked_colors)[3]
        return f"selected_{best_color}"

    def _choose_taki_sequence_action(self, hand: Sequence[str], state: Dict[str, str]) -> str:
        legal = _legal_cards(list(hand), state)
        if not legal:
            return "closed_taki"

        non_super_cards = [card for card in legal if card != "super_taki"]
        if non_super_cards:
            return min(
                non_super_cards,
                key=lambda card: self._sequence_keep_value(card, hand),
            )

        if len(hand) <= 2:
            return "super_taki"
        return "closed_taki"

    def _score_turn_card(self, card: str, hand: Sequence[str], state: Dict[str, str]) -> Tuple[int, int, int, int]:
        remaining = _remove_one(hand, card)
        kind = _card_kind(card)

        if not remaining:
            return (10_000, 0, 0, 0)

        score = 0
        if kind == "stop":
            score += 55
            if len(remaining) <= 2:
                score += 18
        elif kind == "number":
            score += 40
        elif kind == "taki":
            score += 22
            score += self._taki_sequence_value(card, hand, state)
        elif kind == "super_taki":
            score += 18
            score += self._taki_sequence_value(card, hand, state) - 18
        elif kind == "change_color":
            score += 10
            score += max(self._color_control_score(color, remaining) for color in COLORS) * 3

        score += self._future_followup_value(card, remaining, state)

        flexibility_penalty = 0
        if kind == "change_color":
            flexibility_penalty = 20
        elif kind == "super_taki":
            flexibility_penalty = 14

        return (
            score - flexibility_penalty,
            -len(remaining),
            -self._color_fragmentation(remaining),
            -self._card_specificity(card),
        )

    def _taki_sequence_value(self, card: str, hand: Sequence[str], state: Dict[str, str]) -> int:
        kind = _card_kind(card)
        if kind not in ("taki", "super_taki"):
            return 0

        if kind == "taki":
            taki_color = _card_color(card) or ""
        else:
            taki_color = state.get("active_color", "")

        remaining = _remove_one(hand, card)
        same_color_cards = [c for c in remaining if _card_color(c) == taki_color]
        extra_super_takis = remaining.count("super_taki")

        value = len(same_color_cards) * 28 + extra_super_takis * 8
        if not same_color_cards and len(remaining) > 2:
            value -= 24
        if len(same_color_cards) + extra_super_takis >= len(remaining):
            value += 25
        return value

    def _future_followup_value(self, card: str, remaining: Sequence[str], state: Dict[str, str]) -> int:
        if not remaining:
            return 0

        kind = _card_kind(card)
        if kind == "change_color":
            return max(self._color_control_score(color, remaining) for color in COLORS)

        if kind == "super_taki":
            result_color = state.get("active_color", "")
            pseudo_top = f"card_0_{result_color}" if result_color else ""
            return self._next_turn_matching_value(remaining, pseudo_top, result_color)

        result_color = _card_color(card) or state.get("active_color", "")
        return self._next_turn_matching_value(remaining, card, result_color)

    def _next_turn_matching_value(self, remaining: Sequence[str], top_card: str, active_color: str) -> int:
        value = 0
        for card in remaining:
            kind = _card_kind(card)
            if kind in ("super_taki", "change_color"):
                value += 6
                continue
            if _card_color(card) == active_color:
                value += 5
            elif top_card and _matches_type_or_number(card, top_card):
                value += 2
        return value

    def _sequence_keep_value(self, card: str, hand: Sequence[str]) -> Tuple[int, int, int]:
        remaining = _remove_one(hand, card)
        kind = _card_kind(card)

        keep_value = 0
        if kind == "stop":
            keep_value += 40
        elif kind == "taki":
            keep_value += 22
        elif kind == "number":
            keep_value += 10

        if kind == "number":
            keep_value += sum(
                1
                for other in remaining
                if _card_kind(other) == "number" and _card_number(other) == _card_number(card)
            ) * 3

        keep_value += self._future_followup_value(card, remaining, self.last_state or {})
        return (keep_value, -len(remaining), -self._card_specificity(card))

    def _color_control_score(self, color: str, hand: Sequence[str]) -> int:
        taki_count, stop_count, number_count = self._color_counts(color, hand)
        return taki_count * 6 + stop_count * 4 + number_count * 3

    def _color_counts(self, color: str, hand: Sequence[str]) -> Tuple[int, int, int]:
        taki_count = 0
        stop_count = 0
        number_count = 0
        for card in hand:
            if _card_color(card) != color:
                continue
            kind = _card_kind(card)
            if kind == "taki":
                taki_count += 1
            elif kind == "stop":
                stop_count += 1
            elif kind == "number":
                number_count += 1
        return taki_count, stop_count, number_count

    def _color_fragmentation(self, hand: Sequence[str]) -> int:
        return len({_card_color(card) for card in hand if _card_color(card)})

    def _card_specificity(self, card: str) -> int:
        kind = _card_kind(card)
        if kind in ("change_color", "super_taki"):
            return 0
        if kind in ("stop", "taki"):
            return 1
        return 2
