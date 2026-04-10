import random
from typing import Any, Dict, List, Optional, Sequence

from .taki_game import TakiGame


COLORS: Sequence[str] = ("red", "blue", "green")
NUMBERS: Sequence[int] = (1, 3, 4, 5)


def _card_color(descriptor: str) -> Optional[str]:
    parts = descriptor.split("_")
    if descriptor.startswith("card_") and len(parts) == 3:
        return parts[2]
    if descriptor.startswith("stop_") and len(parts) == 2:
        return parts[1]
    if descriptor.startswith("taki_") and len(parts) == 2:
        return parts[1]
    return None


def _card_number(descriptor: str) -> Optional[str]:
    parts = descriptor.split("_")
    if descriptor.startswith("card_") and len(parts) == 3:
        return parts[1]
    return None


def _card_kind(descriptor: str) -> str:
    if descriptor.startswith("card_"):
        return "number"
    if descriptor.startswith("stop_"):
        return "stop"
    if descriptor.startswith("taki_"):
        return "taki"
    return descriptor


def _is_legal_in_turn(card: str, top_card: str, active_color: str, rule_mode: str) -> bool:
    kind = _card_kind(card)
    if kind in ("super_taki", "change_color"):
        return True
    color = _card_color(card)
    if color and color == active_color:
        return True
    # After a change_color selection only same-color cards are legal (handled above).
    if rule_mode == "color_only":
        return False
    if rule_mode == "match_color_or_type" and top_card:
        if _card_kind(card) == _card_kind(top_card) and kind != "number":
            return True
        if kind == "number" and _card_number(card) == _card_number(top_card):
            return True
    return False


def _is_legal_in_taki_sequence(card: str, taki_color: str) -> bool:
    kind = _card_kind(card)
    if kind == "super_taki":
        return True
    return _card_color(card) == taki_color


def _build_reduced_deck() -> List[str]:
    deck: List[str] = []
    for color in COLORS:
        for number in NUMBERS:
            deck.append(f"card_{number}_{color}")
        deck.extend([f"stop_{color}"] * 2)
        deck.extend([f"taki_{color}"] * 2)
    deck.extend(["super_taki"] * 2)
    deck.extend(["change_color"] * 2)
    return deck


def _is_valid_opening_card(card: str) -> bool:
    """Return True only for number cards.

    By design, only number cards may start the discard pile.  This avoids
    special-casing STOP/TAKI/CHANGE_COLOR effects that would need to fire
    before any player has taken a turn.
    """
    return _card_kind(card) == "number"


def _copy_state(state: Dict[str, Any]) -> Dict[str, Any]:
    copied = dict(state)
    copied["hands"] = [list(hand) for hand in state["hands"]]
    copied["draw_pile"] = list(state["draw_pile"])
    copied["discard_pile"] = list(state["discard_pile"])
    return copied


class ReducedTakiGame(TakiGame):
    """
    Concrete reduced TAKI engine aligned with the repository skeleton.

    Scope is intentionally limited to the card types already documented by the
    API: number cards, STOP, CHANGE_COLOR, TAKI, and SUPER_TAKI.

    Opening card rule: only number cards may be placed face-up to start the
    discard pile.  STOP, TAKI, CHANGE_COLOR, and SUPER_TAKI are never used as
    the first card; any such cards drawn during setup are returned to the draw
    pile before the first player acts.
    """

    def reset(
        self,
        seed: Optional[int] = None,
        num_players: int = 2,
        hand_size: int = 8,
    ) -> Dict[str, Any]:
        if num_players < 2:
            raise ValueError("TAKI requires at least 2 players.")
        if hand_size <= 0:
            raise ValueError("hand_size must be positive.")

        deck = _build_reduced_deck()
        dealt_cards = num_players * hand_size
        if len(deck) < dealt_cards + 1:
            raise ValueError("Not enough cards to deal the requested hands.")
        # Guard against a deck that contains no valid openers at all (e.g. after
        # a future change to _build_reduced_deck).  The retry loop below can only
        # succeed if at least one valid opener exists somewhere in the deck.
        if not any(_is_valid_opening_card(card) for card in deck):
            raise ValueError("Deck does not contain any valid opening cards.")

        rng = random.Random(seed)

        # With a large hand_size it is possible (though rare) that every valid
        # opening card ends up in a player's hand after dealing, leaving none
        # available to start the discard pile.  We reshuffle and re-deal in that
        # case; 1000 attempts is an astronomically safe upper bound.
        draw_pile = list(deck)
        rng.shuffle(draw_pile)

        hands: List[List[str]] = [[] for _ in range(num_players)]
        for _ in range(hand_size):
            for player_hand in hands:
                player_hand.append(draw_pile.pop())

        deferred_openers: List[str] = []
        top_card: Optional[str] = None
        while draw_pile and top_card is None:
            candidate = draw_pile.pop()
            if not _is_valid_opening_card(candidate):
                deferred_openers.append(candidate)
                continue
            top_card = candidate

        if top_card is None:
            raise RuntimeError("Failed to choose a valid opening card.")

        if deferred_openers:
            draw_pile.extend(reversed(deferred_openers))

        discard_pile = [top_card]
        return {
            "hands": hands,
            "draw_pile": draw_pile,
            "discard_pile": discard_pile,
            "current_player": 0,
            "top_card": top_card,
            "active_color": _card_color(top_card),
            "phase": "turn",
            "taki_color": None,
            "winner": None,
            "rule_mode": "match_color_or_type",
            "rng_state": rng.getstate(),
        }

    def observe(self, state: Dict[str, Any], player_index: int) -> Dict[str, str]:
        if player_index < 0 or player_index >= len(state["hands"]):
            raise IndexError("player_index is out of range.")
        return {
            "player_index": str(player_index),
            "phase": state.get("phase", "turn"),
            "hand": ",".join(state["hands"][player_index]),
            "top_card": state.get("top_card") or "",
            "active_color": state.get("active_color") or "",
            "rule_mode": state.get("rule_mode", "match_color_or_type"),
            "taki_color": state.get("taki_color") or "",
        }

    def legal_action_names_from_observation(self, observation: Dict[str, str]) -> List[str]:
        def unique(names: List[str]) -> List[str]:
            return list(dict.fromkeys(names))

        phase = observation.get("phase", "")
        if phase == "terminal":
            return []
        if phase == "change_color":
            return [f"selected_{color}" for color in COLORS]

        hand = [name for name in observation.get("hand", "").split(",") if name]
        if phase == "taki_sequence":
            legal_cards = [
                card for card in hand if _is_legal_in_taki_sequence(card, observation.get("taki_color", ""))
            ]
            return unique(legal_cards + ["closed_taki"])

        legal_cards = [
            card
            for card in hand
            if _is_legal_in_turn(
                card,
                observation.get("top_card", ""),
                observation.get("active_color", ""),
                observation.get("rule_mode", "match_color_or_type"),
            )
        ]
        return unique(legal_cards + ["draw_card"])

    def step(self, state: Dict[str, Any], action_name: str) -> Dict[str, Any]:
        if self.is_terminal(state):
            raise ValueError("Cannot act in a terminal state.")

        next_state = _copy_state(state)
        phase = next_state["phase"]
        current_player = next_state["current_player"]
        hand = next_state["hands"][current_player]

        if phase == "change_color":
            self._apply_selected_color(next_state, action_name)
            return next_state

        if phase == "taki_sequence":
            self._apply_taki_action(next_state, action_name)
            return next_state

        if action_name == "draw_card":
            self._refill_draw_pile_if_needed(next_state)
            if next_state["draw_pile"]:
                hand.append(next_state["draw_pile"].pop())
            self._advance_turn(next_state, skipped_players=0)
            return next_state

        if action_name not in hand:
            raise ValueError(f"Player {current_player} does not hold card '{action_name}'.")
        if not _is_legal_in_turn(
            action_name,
            next_state.get("top_card") or "",
            next_state.get("active_color") or "",
            next_state.get("rule_mode", "match_color_or_type"),
        ):
            raise ValueError(f"Illegal action '{action_name}' for the current turn.")

        hand.remove(action_name)
        next_state["discard_pile"].append(action_name)
        next_state["top_card"] = action_name

        kind = _card_kind(action_name)
        if kind == "change_color":
            next_state["active_color"] = None
            next_state["phase"] = "change_color"
            next_state["rule_mode"] = ""
            return next_state

        if kind in ("taki", "super_taki"):
            taki_color = _card_color(action_name) or next_state.get("active_color")
            if not taki_color:
                raise ValueError("Cannot open a TAKI sequence without an active color.")
            next_state["active_color"] = taki_color
            next_state["phase"] = "taki_sequence"
            next_state["taki_color"] = taki_color
            next_state["rule_mode"] = "taki"
            return next_state

        next_state["active_color"] = _card_color(action_name)
        next_state["phase"] = "turn"
        next_state["taki_color"] = None
        next_state["rule_mode"] = "match_color_or_type"

        if not hand:
            self._mark_winner(next_state, current_player)
            return next_state

        skipped_players = 1 if kind == "stop" else 0
        self._advance_turn(next_state, skipped_players=skipped_players)
        return next_state

    def is_terminal(self, state: Dict[str, Any]) -> bool:
        return state.get("phase") == "terminal" or state.get("winner") is not None

    def _apply_selected_color(self, state: Dict[str, Any], action_name: str) -> None:
        if action_name not in {f"selected_{color}" for color in COLORS}:
            raise ValueError(f"Illegal color selection '{action_name}'.")

        selected_color = action_name.split("_", 1)[1]
        current_player = state["current_player"]
        state["active_color"] = selected_color
        state["phase"] = "turn"
        state["rule_mode"] = "color_only"
        state["taki_color"] = None

        if not state["hands"][current_player]:
            self._mark_winner(state, current_player)
            return

        self._advance_turn(state, skipped_players=0)

    def _apply_taki_action(self, state: Dict[str, Any], action_name: str) -> None:
        current_player = state["current_player"]
        hand = state["hands"][current_player]
        taki_color = state.get("taki_color") or ""

        if action_name == "closed_taki":
            state["phase"] = "turn"
            state["rule_mode"] = "match_color_or_type"
            state["taki_color"] = None
            if not hand:
                self._mark_winner(state, current_player)
                return
            self._advance_turn(state, skipped_players=0)
            return

        if action_name not in hand:
            raise ValueError(f"Player {current_player} does not hold card '{action_name}'.")
        if not _is_legal_in_taki_sequence(action_name, taki_color):
            raise ValueError(f"Illegal TAKI sequence action '{action_name}'.")

        hand.remove(action_name)
        state["discard_pile"].append(action_name)
        state["top_card"] = action_name
        # super_taki played mid-sequence is colorless; taki_color from the
        # opening TAKI card continues to govern what may follow.
        state["active_color"] = taki_color
        state["rule_mode"] = "taki"

    def _advance_turn(self, state: Dict[str, Any], skipped_players: int) -> None:
        player_count = len(state["hands"])
        state["current_player"] = (state["current_player"] + 1 + skipped_players) % player_count

    def _mark_winner(self, state: Dict[str, Any], player_index: int) -> None:
        state["winner"] = player_index
        state["phase"] = "terminal"

    def _refill_draw_pile_if_needed(self, state: Dict[str, Any]) -> None:
        if state["draw_pile"] or len(state["discard_pile"]) <= 1:
            return

        top_card = state["discard_pile"].pop()
        recycled = state["discard_pile"]
        rng = random.Random()
        rng_state = state.get("rng_state")
        if rng_state is not None:
            # Restore the RNG to the point it was at after the last shuffle so
            # that refills are fully reproducible for a given seed.  States
            # constructed manually (e.g. in tests) that omit rng_state fall back
            # to a fresh unseeded RNG and are therefore non-reproducible.
            rng.setstate(rng_state)
        rng.shuffle(recycled)
        state["rng_state"] = rng.getstate()
        state["draw_pile"] = recycled
        state["discard_pile"] = [top_card]
