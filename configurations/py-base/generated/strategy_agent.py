from typing import Dict, List, Optional

from .python_agent import (
    _card_color,
    _card_kind,
    _is_legal_in_taki_sequence,
    _is_legal_in_turn,
    _legal_cards,
)
from .taki_agent import TakiAgent


_COLORS = ("red", "blue", "green")
_KIND_WEIGHT = {
    "number": 1,
    "stop": 3,
    "taki": 4,
    "super_taki": 4,
    "change_color": 2,
}
_TURN_BASE_SCORE = {
    "number": 30,
    "stop": 55,
    "taki": 70,
    "super_taki": 65,
    "change_color": 45,
}
_TAKI_SEQUENCE_SCORE = {
    "number": 20,
    "stop": 45,
    "taki": 35,
    "super_taki": 25,
    "change_color": -999,
}


class TakiStrategyAgent(TakiAgent):
    """Deterministic heuristic agent for the reduced 2-player TAKI variant."""

    def __init__(self) -> None:
        self.last_state: Optional[Dict[str, str]] = None

    def get_action(self, state: Dict[str, str]) -> Optional[str]:
        self.last_state = state
        phase = state.get("phase", "")
        hand = self._parse_hand(state)

        if phase == "change_color":
            return f"selected_{self._best_color(hand)}"

        if phase == "taki_sequence":
            legal = _legal_cards(hand, state)
            return self._choose_taki_sequence_action(legal, state, hand) if legal else "closed_taki"

        legal = _legal_cards(hand, state)
        return self._choose_turn_action(legal, state, hand) if legal else "draw_card"

    @staticmethod
    def _parse_hand(state: Dict[str, str]) -> List[str]:
        return [name for name in state.get("hand", "").split(",") if name]

    def _choose_turn_action(self, legal: List[str], state: Dict[str, str], hand: List[str]) -> str:
        best_card = legal[0]
        best_score = self._score_turn_card(best_card, state, hand)
        for card in legal[1:]:
            score = self._score_turn_card(card, state, hand)
            if score > best_score or (score == best_score and card < best_card):
                best_card = card
                best_score = score
        return best_card

    def _choose_taki_sequence_action(
        self,
        legal: List[str],
        state: Dict[str, str],
        hand: List[str],
    ) -> str:
        best_card = legal[0]
        best_score = self._score_taki_sequence_card(best_card, state, hand)
        for card in legal[1:]:
            score = self._score_taki_sequence_card(card, state, hand)
            if score > best_score or (score == best_score and card < best_card):
                best_card = card
                best_score = score
        return best_card

    def _score_turn_card(self, card: str, state: Dict[str, str], hand: List[str]) -> int:
        remaining = self._remove_one(hand, card)
        kind = _card_kind(card)
        score = _TURN_BASE_SCORE[kind]

        if not remaining:
            return 10_000

        score += self._future_mobility_score(card, state, remaining)

        card_color = _card_color(card)
        if card_color:
            score += self._color_strength(remaining, card_color)

        if kind == "change_color":
            chosen_color = self._best_color(remaining)
            score += 10 + self._color_strength(remaining, chosen_color)
        elif kind == "super_taki":
            active_color = state.get("active_color", "")
            if active_color:
                score += 15 + self._sequence_potential(remaining, active_color)
        elif kind == "taki":
            taki_color = _card_color(card)
            if taki_color:
                score += 20 + self._sequence_potential(remaining, taki_color)

        top_card = state.get("top_card", "")
        active_color = state.get("active_color", "")
        rule_mode = state.get("rule_mode", "match_color_or_type")
        if card_color and card_color == active_color:
            score += 6
        elif top_card and _is_legal_in_turn(card, top_card, active_color, rule_mode):
            score -= 3

        return score

    def _score_taki_sequence_card(self, card: str, state: Dict[str, str], hand: List[str]) -> int:
        remaining = self._remove_one(hand, card)
        kind = _card_kind(card)
        score = _TAKI_SEQUENCE_SCORE[kind]

        if not remaining:
            return 10_000

        taki_color = state.get("taki_color", "")
        if taki_color:
            score += self._sequence_potential(remaining, taki_color)
            score += self._color_strength(remaining, taki_color)

        if kind == "super_taki":
            # Keep the colorless wildcard for later unless it clearly improves the sequence.
            score -= 8

        continuation = [c for c in remaining if _is_legal_in_taki_sequence(c, taki_color)]
        score += len(continuation) * 4
        return score

    def _future_mobility_score(self, card: str, state: Dict[str, str], remaining: List[str]) -> int:
        simulated = {
            "phase": "turn",
            "top_card": card,
            "active_color": self._resulting_active_color(card, state),
            "rule_mode": self._resulting_rule_mode(card),
            "taki_color": "",
        }
        return len(_legal_cards(remaining, simulated)) * 8

    @staticmethod
    def _resulting_rule_mode(card: str) -> str:
        return "color_only" if card == "change_color" else "match_color_or_type"

    @staticmethod
    def _resulting_active_color(card: str, state: Dict[str, str]) -> str:
        if card == "change_color":
            current_hand = [name for name in state.get("hand", "").split(",") if name]
            remaining_hand = TakiStrategyAgent._remove_one(current_hand, card)
            return TakiStrategyAgent._best_color(remaining_hand)
        if card == "super_taki":
            return state.get("active_color", "")
        return _card_color(card) or state.get("active_color", "")

    @staticmethod
    def _remove_one(hand: List[str], card: str) -> List[str]:
        removed = False
        remaining: List[str] = []
        for item in hand:
            if not removed and item == card:
                removed = True
                continue
            remaining.append(item)
        return remaining

    @staticmethod
    def _color_strength(hand: List[str], color: str) -> int:
        score = 0
        for card in hand:
            if _card_color(card) == color:
                score += _KIND_WEIGHT[_card_kind(card)]
        return score

    @staticmethod
    def _sequence_potential(hand: List[str], color: str) -> int:
        total = 0
        for card in hand:
            kind = _card_kind(card)
            if _card_color(card) == color:
                total += 2 + _KIND_WEIGHT[kind]
            elif kind == "super_taki":
                total += 3
        return total

    @staticmethod
    def _best_color(hand: List[str]) -> str:
        best_color = _COLORS[0]
        best_weighted = -1
        best_count = -1
        for color in _COLORS:
            weighted = TakiStrategyAgent._color_strength(hand, color)
            count = sum(1 for card in hand if _card_color(card) == color)
            if weighted > best_weighted or (weighted == best_weighted and count > best_count):
                best_color = color
                best_weighted = weighted
                best_count = count
        return best_color
