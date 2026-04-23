from collections import Counter
from typing import Dict, List, Optional

from .python_agent import (
    _card_color,
    _card_kind,
    _card_number,
    _legal_cards,
)
from .taki_agent import TakiAgent


class TakiStrategyAgent(TakiAgent):
    """Deterministic TAKI agent using hand-reduction and color-control heuristics."""

    COLORS = ("red", "blue", "green")

    def __init__(self) -> None:
        self.last_state: Optional[Dict[str, str]] = None

    def get_action(self, state: Dict[str, str]) -> Optional[str]:
        self.last_state = state
        phase = state.get("phase", "")
        hand = self._parse_hand(state)

        if phase == "change_color":
            return f"selected_{self._choose_color(hand)}"

        if phase == "taki_sequence":
            legal = _legal_cards(hand, state)
            if not legal:
                return "closed_taki"
            return max(legal, key=lambda card: self._taki_sequence_score(card, hand))

        if phase == "turn":
            legal = _legal_cards(hand, state)
            if not legal:
                return "draw_card"
            return max(legal, key=lambda card: self._turn_score(card, state, hand))

        return None

    def _parse_hand(self, state: Dict[str, str]) -> List[str]:
        return [name for name in state.get("hand", "").split(",") if name]

    def _choose_color(self, hand: List[str]) -> str:
        scores = {color: 0.0 for color in self.COLORS}
        for card in hand:
            color = _card_color(card)
            kind = _card_kind(card)
            if color is None:
                if kind == "super_taki":
                    for candidate in self.COLORS:
                        scores[candidate] += 0.5
                continue

            scores[color] += 1.0
            if kind == "stop":
                scores[color] += 0.5
            elif kind == "taki":
                scores[color] += self._same_color_count(hand, color)

        return max(self.COLORS, key=lambda color: (scores[color], -self.COLORS.index(color)))

    def _turn_score(self, card: str, state: Dict[str, str], hand: List[str]) -> float:
        if len(hand) == 1:
            return 1000.0

        kind = _card_kind(card)
        color = _card_color(card)
        score = 10.0

        score += self._handoff_color_score(card, state, hand)

        if kind == "taki":
            taki_color = color or state.get("active_color", "")
            score += 30.0 + (4.0 * self._taki_followup_count(hand, taki_color, exclude=card))
        elif kind == "super_taki":
            active_color = state.get("active_color", "")
            score += 22.0 + (4.0 * self._taki_followup_count(hand, active_color, exclude=card))
        elif kind == "stop":
            score += 24.0
            if len(hand) <= 3:
                score += 8.0
        elif kind == "number":
            score += 12.0
            score += self._duplicate_number_bonus(card, hand)
        elif kind == "change_color":
            chosen_color = self._choose_color(self._remaining_hand(hand, card))
            score += 16.0 + (3.0 * self._same_color_count(hand, chosen_color))

        if self._is_wild(card) and self._has_non_wild_legal_alternative(card, state, hand):
            score -= 12.0

        return score

    def _taki_sequence_score(self, card: str, hand: List[str]) -> float:
        if len(hand) == 1:
            return 1000.0

        kind = _card_kind(card)
        color = _card_color(card)
        score = 10.0

        if kind == "number":
            score += 30.0
            score += self._duplicate_number_bonus(card, hand)
        elif kind == "stop":
            score += 26.0
        elif kind == "taki":
            score += 18.0
        elif kind == "super_taki":
            score += 5.0

        if color:
            score += self._same_color_count(hand, color)

        return score

    def _handoff_color_score(self, card: str, state: Dict[str, str], hand: List[str]) -> float:
        kind = _card_kind(card)
        if kind == "change_color":
            color = self._choose_color(self._remaining_hand(hand, card))
        elif kind == "super_taki":
            color = state.get("active_color", "")
        else:
            color = _card_color(card) or ""

        if not color:
            return 0.0
        return 2.0 * self._same_color_count(self._remaining_hand(hand, card), color)

    def _same_color_count(self, hand: List[str], color: str) -> int:
        if not color:
            return 0
        return sum(1 for card in hand if _card_color(card) == color)

    def _taki_followup_count(self, hand: List[str], color: str, exclude: str) -> int:
        remaining = self._remaining_hand(hand, exclude)
        return sum(
            1
            for card in remaining
            if _card_kind(card) == "super_taki" or _card_color(card) == color
        )

    def _duplicate_number_bonus(self, card: str, hand: List[str]) -> float:
        number = _card_number(card)
        if number is None:
            return 0.0
        counts = Counter(_card_number(candidate) for candidate in hand)
        return float(counts[number] - 1)

    def _remaining_hand(self, hand: List[str], played_card: str) -> List[str]:
        remaining = list(hand)
        try:
            remaining.remove(played_card)
        except ValueError:
            pass
        return remaining

    def _is_wild(self, card: str) -> bool:
        return _card_kind(card) in ("change_color", "super_taki")

    def _has_non_wild_legal_alternative(
        self,
        card: str,
        state: Dict[str, str],
        hand: List[str],
    ) -> bool:
        if not self._is_wild(card):
            return False
        return any(not self._is_wild(candidate) for candidate in _legal_cards(hand, state))
