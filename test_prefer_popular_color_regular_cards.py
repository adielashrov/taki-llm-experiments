import unittest

from bppy.model.b_priority_event import BPEvent
from bp_taki import _popular_color_regular_card_requests
from taki_simulation import PlayerStrategyConfig, run_simulation


class PreferPopularColorRegularCardsTests(unittest.TestCase):
    def test_prefers_dense_color_regular_card_when_regular_choices_exist(self):
        card_events = [
            BPEvent("p_1_card_1_red", priority=10.0),
            BPEvent("p_1_card_3_red", priority=10.0),
            BPEvent("p_1_stop_red", priority=10.0),
            BPEvent("p_1_card_1_blue", priority=10.0),
            BPEvent("p_1_card_4_blue", priority=10.0),
        ]

        requests = _popular_color_regular_card_requests(
            card_events,
            rule_mode="match_color_or_type",
            active_color="green",
            active_type="1",
        )

        self.assertEqual([event.name for event in requests], ["p_1_card_1_red"])
        self.assertEqual(requests[0].priority, 9.8)

    def test_stays_silent_when_legal_tactical_card_exists(self):
        card_events = [
            BPEvent("p_1_card_1_red", priority=10.0),
            BPEvent("p_1_card_3_red", priority=10.0),
            BPEvent("p_1_stop_red", priority=10.0),
            BPEvent("p_1_card_1_blue", priority=10.0),
        ]

        requests = _popular_color_regular_card_requests(
            card_events,
            rule_mode="match_color_or_type",
            active_color="red",
            active_type="1",
        )

        self.assertEqual(requests, [])

    def test_requires_two_same_color_cards_after_play(self):
        card_events = [
            BPEvent("p_1_card_1_red", priority=10.0),
            BPEvent("p_1_card_1_blue", priority=10.0),
        ]

        requests = _popular_color_regular_card_requests(
            card_events,
            rule_mode="match_color_or_type",
            active_color="green",
            active_type="1",
        )

        self.assertEqual(requests, [])

    def test_strategy_simulation_smoke(self):
        player_0_config = PlayerStrategyConfig()
        player_1_config = PlayerStrategyConfig(prefer_popular_color_regular_cards=True)

        stats = run_simulation(
            num_games=10,
            start_seed=0,
            starting_player=-1,
            balanced_starting_players=True,
            player_0_config=player_0_config,
            player_1_config=player_1_config,
            silent=True,
            progress_interval=10,
        )

        self.assertEqual(stats.total_completed, 10)
        self.assertEqual(stats.errors, 0)
        self.assertEqual(stats.deadlocks, 0)


if __name__ == "__main__":
    unittest.main()
