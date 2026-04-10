import random
import unittest
from collections import Counter
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from python_taki_api.reduced_taki_game import ReducedTakiGame, _build_reduced_deck


EXPECTED_DECK_COUNTS = Counter(
    {
        "card_1_red": 1,
        "card_1_blue": 1,
        "card_1_green": 1,
        "card_3_red": 1,
        "card_3_blue": 1,
        "card_3_green": 1,
        "card_4_red": 1,
        "card_4_blue": 1,
        "card_4_green": 1,
        "card_5_red": 1,
        "card_5_blue": 1,
        "card_5_green": 1,
        "stop_red": 2,
        "stop_blue": 2,
        "stop_green": 2,
        "taki_red": 2,
        "taki_blue": 2,
        "taki_green": 2,
        "change_color": 2,
        "super_taki": 2,
    }
)
EXPECTED_OPENING_CARDS = {c for c in EXPECTED_DECK_COUNTS if c.startswith("card_")}


def _make_state(
    hands: List[List[str]],
    top_card: str = "card_1_red",
    active_color: str = "red",
    phase: str = "turn",
    rule_mode: str = "match_color_or_type",
    current_player: int = 0,
    draw_pile: Optional[List[str]] = None,
    discard_pile: Optional[List[str]] = None,
    taki_color: Optional[str] = None,
    winner: Optional[int] = None,
    rng_state: object = None,
) -> Dict[str, Any]:
    """Build a minimal game state for unit tests."""
    return {
        "hands": [list(h) for h in hands],
        "draw_pile": draw_pile if draw_pile is not None else [],
        "discard_pile": discard_pile if discard_pile is not None else [top_card],
        "current_player": current_player,
        "top_card": top_card,
        "active_color": active_color,
        "phase": phase,
        "taki_color": taki_color,
        "winner": winner,
        "rule_mode": rule_mode,
        "rng_state": rng_state,
    }


class DeckTests(unittest.TestCase):
    def test_build_reduced_deck_matches_requested_distribution(self) -> None:
        deck = _build_reduced_deck()

        self.assertEqual(Counter(deck), EXPECTED_DECK_COUNTS)
        self.assertEqual(len(deck), sum(EXPECTED_DECK_COUNTS.values()))

    def test_reset_preserves_requested_distribution_across_all_piles(self) -> None:
        game = ReducedTakiGame()
        state = game.reset(seed=7, num_players=2, hand_size=8)

        all_cards = []
        for hand in state["hands"]:
            all_cards.extend(hand)
        all_cards.extend(state["draw_pile"])
        all_cards.extend(state["discard_pile"])

        self.assertEqual(Counter(all_cards), EXPECTED_DECK_COUNTS)
        self.assertEqual([len(hand) for hand in state["hands"]], [8, 8])
        self.assertEqual(len(state["discard_pile"]), 1)
        self.assertIn(state["top_card"], EXPECTED_OPENING_CARDS)

    def test_reset_is_reproducible_with_same_seed(self) -> None:
        game = ReducedTakiGame()
        state_a = game.reset(seed=42, num_players=2, hand_size=4)
        state_b = game.reset(seed=42, num_players=2, hand_size=4)
        self.assertEqual(state_a["hands"], state_b["hands"])
        self.assertEqual(state_a["top_card"], state_b["top_card"])

    def test_reset_raises_for_insufficient_deck(self) -> None:
        game = ReducedTakiGame()
        with self.assertRaises(ValueError):
            game.reset(num_players=2, hand_size=100)

    def test_reset_3x8_can_fail_when_no_valid_opening_card_remains(self) -> None:
        game = ReducedTakiGame()
        with self.assertRaises(RuntimeError):
            game.reset(seed=8838, num_players=3, hand_size=8)

    def test_reset_preserves_opener_skip_order_in_draw_pile(self) -> None:
        deck = [
            "card_1_red",
            "card_4_blue",
            "super_taki",
            "change_color",
            "card_5_green",
            "card_3_red",
        ]

        def no_shuffle(self, items: List[str]) -> None:
            return None

        with patch("python_taki_api.reduced_taki_game._build_reduced_deck", return_value=list(deck)):
            with patch("python_taki_api.reduced_taki_game.random.Random.shuffle", new=no_shuffle):
                state = ReducedTakiGame().reset(seed=11, num_players=2, hand_size=1)

        self.assertEqual(state["hands"], [["card_3_red"], ["card_5_green"]])
        self.assertEqual(state["top_card"], "card_4_blue")
        self.assertEqual(state["draw_pile"], ["card_1_red", "super_taki", "change_color"])


class StepNumberCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = ReducedTakiGame()

    def test_playing_same_color_card_advances_turn(self) -> None:
        state = _make_state(
            hands=[["card_3_red", "card_1_blue"], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
        )
        next_state = self.game.step(state, "card_3_red")

        self.assertEqual(next_state["top_card"], "card_3_red")
        self.assertEqual(next_state["active_color"], "red")
        self.assertEqual(next_state["current_player"], 1)
        self.assertNotIn("card_3_red", next_state["hands"][0])

    def test_playing_same_number_card_advances_turn(self) -> None:
        state = _make_state(
            hands=[["card_1_blue", "card_3_red"], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
        )
        next_state = self.game.step(state, "card_1_blue")

        self.assertEqual(next_state["top_card"], "card_1_blue")
        self.assertEqual(next_state["active_color"], "blue")
        self.assertEqual(next_state["current_player"], 1)

    def test_playing_illegal_card_raises(self) -> None:
        state = _make_state(
            hands=[["card_3_blue"], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
        )
        with self.assertRaises(ValueError):
            self.game.step(state, "card_3_blue")

    def test_draw_card_adds_to_hand_and_advances_turn(self) -> None:
        state = _make_state(
            hands=[["card_3_blue"], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
            draw_pile=["card_4_green"],
        )
        next_state = self.game.step(state, "draw_card")

        self.assertEqual(len(next_state["hands"][0]), 2)
        self.assertEqual(next_state["current_player"], 1)

    def test_refill_uses_rng_state_from_state(self) -> None:
        seeded_rng = random.Random(23)
        initial_state = _make_state(
            hands=[["card_1_red"], ["card_5_green"]],
            top_card="stop_red",
            active_color="red",
            draw_pile=[],
            discard_pile=["card_1_blue", "card_4_green", "stop_red"],
            rng_state=seeded_rng.getstate(),
        )

        expected_rng = random.Random()
        expected_rng.setstate(initial_state["rng_state"])
        expected_recycled = ["card_1_blue", "card_4_green"]
        expected_rng.shuffle(expected_recycled)
        expected_drawn_card = expected_recycled.pop()

        game_a = ReducedTakiGame()
        game_a.reset(seed=1, num_players=2, hand_size=1)
        next_state_a = game_a.step(initial_state, "draw_card")

        game_b = ReducedTakiGame()
        game_b.reset(seed=2, num_players=2, hand_size=1)
        next_state_b = game_b.step(initial_state, "draw_card")

        self.assertEqual(next_state_a, next_state_b)
        self.assertEqual(next_state_a["hands"][0], ["card_1_red", expected_drawn_card])
        self.assertEqual(next_state_a["draw_pile"], expected_recycled)
        self.assertEqual(next_state_a["discard_pile"], ["stop_red"])
        self.assertEqual(next_state_a["current_player"], 1)


class StepStopCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = ReducedTakiGame()

    def test_stop_card_skips_next_player(self) -> None:
        state = _make_state(
            hands=[["stop_red", "card_3_blue"], ["card_5_green"], ["card_4_red"]],
            top_card="card_1_red",
            active_color="red",
        )
        next_state = self.game.step(state, "stop_red")

        # player 1 is skipped; player 2 should be next
        self.assertEqual(next_state["current_player"], 2)

    def test_stop_card_same_type_is_legal(self) -> None:
        state = _make_state(
            hands=[["stop_blue", "card_3_red"], ["card_5_green"]],
            top_card="stop_red",
            active_color="red",
        )
        next_state = self.game.step(state, "stop_blue")
        self.assertEqual(next_state["top_card"], "stop_blue")


class StepTakiSequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = ReducedTakiGame()

    def test_taki_card_enters_taki_sequence_phase(self) -> None:
        state = _make_state(
            hands=[["taki_red", "card_3_red"], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
        )
        next_state = self.game.step(state, "taki_red")

        self.assertEqual(next_state["phase"], "taki_sequence")
        self.assertEqual(next_state["taki_color"], "red")
        self.assertEqual(next_state["current_player"], 0)

    def test_playing_card_in_taki_sequence_stays_with_same_player(self) -> None:
        state = _make_state(
            hands=[["card_3_red", "card_1_blue"], ["card_5_green"]],
            top_card="taki_red",
            active_color="red",
            phase="taki_sequence",
            taki_color="red",
            rule_mode="taki",
        )
        next_state = self.game.step(state, "card_3_red")

        self.assertEqual(next_state["phase"], "taki_sequence")
        self.assertEqual(next_state["current_player"], 0)

    def test_closed_taki_ends_sequence_and_advances_turn(self) -> None:
        state = _make_state(
            hands=[["card_1_blue"], ["card_5_green"]],
            top_card="taki_red",
            active_color="red",
            phase="taki_sequence",
            taki_color="red",
            rule_mode="taki",
        )
        next_state = self.game.step(state, "closed_taki")

        self.assertEqual(next_state["phase"], "turn")
        self.assertEqual(next_state["taki_color"], None)
        self.assertEqual(next_state["current_player"], 1)

    def test_wrong_color_card_illegal_in_taki_sequence(self) -> None:
        state = _make_state(
            hands=[["card_3_blue"], ["card_5_green"]],
            top_card="taki_red",
            active_color="red",
            phase="taki_sequence",
            taki_color="red",
            rule_mode="taki",
        )
        with self.assertRaises(ValueError):
            self.game.step(state, "card_3_blue")


class StepChangeColorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = ReducedTakiGame()

    def test_change_color_card_enters_change_color_phase(self) -> None:
        state = _make_state(
            hands=[["change_color", "card_3_blue"], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
        )
        next_state = self.game.step(state, "change_color")

        self.assertEqual(next_state["phase"], "change_color")
        self.assertIsNone(next_state["active_color"])

    def test_selected_color_resumes_turn_with_new_color(self) -> None:
        state = _make_state(
            hands=[["card_3_red"], ["card_5_green"]],
            top_card="change_color",
            active_color=None,
            phase="change_color",
            rule_mode="",
        )
        next_state = self.game.step(state, "selected_blue")

        self.assertEqual(next_state["phase"], "turn")
        self.assertEqual(next_state["active_color"], "blue")
        self.assertEqual(next_state["current_player"], 1)

    def test_only_same_color_legal_after_change_color(self) -> None:
        """After a color selection, type-matching must not apply (color_only mode)."""
        state = _make_state(
            hands=[["stop_red", "stop_blue"], ["card_5_green"]],
            top_card="change_color",
            active_color="blue",
            phase="turn",
            rule_mode="color_only",
            current_player=0,
        )
        obs = self.game.observe(state, 0)
        legal = self.game.legal_action_names_from_observation(obs)

        self.assertIn("stop_blue", legal)
        self.assertNotIn("stop_red", legal)


class WinConditionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = ReducedTakiGame()

    def test_playing_last_card_marks_winner(self) -> None:
        state = _make_state(
            hands=[["card_1_red"], ["card_5_green"]],
            top_card="card_3_red",
            active_color="red",
        )
        next_state = self.game.step(state, "card_1_red")

        self.assertTrue(self.game.is_terminal(next_state))
        self.assertEqual(next_state["winner"], 0)
        self.assertEqual(next_state["phase"], "terminal")

    def test_is_terminal_false_when_game_ongoing(self) -> None:
        state = _make_state(
            hands=[["card_1_red", "card_3_blue"], ["card_5_green"]],
            top_card="card_3_red",
            active_color="red",
        )
        self.assertFalse(self.game.is_terminal(state))

    def test_step_raises_on_terminal_state(self) -> None:
        state = _make_state(
            hands=[[], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
            phase="terminal",
            winner=0,
        )
        with self.assertRaises(ValueError):
            self.game.step(state, "draw_card")


class LegalActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = ReducedTakiGame()

    def test_terminal_phase_returns_empty(self) -> None:
        state = _make_state(hands=[[], []], phase="terminal", winner=0)
        obs = self.game.observe(state, 0)
        self.assertEqual(self.game.legal_action_names_from_observation(obs), [])

    def test_change_color_phase_returns_color_selections(self) -> None:
        state = _make_state(
            hands=[["card_1_red"], ["card_5_green"]],
            phase="change_color",
            active_color=None,
            top_card="change_color",
            rule_mode="",
        )
        obs = self.game.observe(state, 0)
        legal = self.game.legal_action_names_from_observation(obs)
        self.assertEqual(sorted(legal), ["selected_blue", "selected_green", "selected_red"])

    def test_draw_card_always_included_in_turn_phase(self) -> None:
        state = _make_state(
            hands=[["card_3_blue"], ["card_5_green"]],
            top_card="card_1_red",
            active_color="red",
        )
        obs = self.game.observe(state, 0)
        legal = self.game.legal_action_names_from_observation(obs)
        self.assertIn("draw_card", legal)

    def test_no_duplicates_in_legal_actions(self) -> None:
        state = _make_state(
            hands=[["card_1_red", "card_1_red"], ["card_5_green"]],
            top_card="card_1_blue",
            active_color="blue",
        )
        obs = self.game.observe(state, 0)
        legal = self.game.legal_action_names_from_observation(obs)
        self.assertEqual(len(legal), len(set(legal)))


if __name__ == "__main__":
    unittest.main()
