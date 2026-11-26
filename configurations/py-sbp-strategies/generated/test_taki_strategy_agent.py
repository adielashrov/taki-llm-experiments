from python_taki_api import TakiStrategyAgent


def make_state(**overrides):
    state = {
        "player_index": "0",
        "phase": "turn",
        "hand": "",
        "top_card": "card_1_red",
        "active_color": "red",
        "rule_mode": "match_color_or_type",
        "taki_color": "",
    }
    state.update(overrides)
    return state


def test_returns_draw_card_when_no_legal_card_exists():
    agent = TakiStrategyAgent()
    state = make_state(
        hand="card_3_blue,stop_green,taki_blue",
        top_card="card_1_red",
        active_color="red",
    )

    assert agent.get_action(state) == "draw_card"


def test_prefers_regular_taki_when_it_can_unload_multiple_cards():
    agent = TakiStrategyAgent()
    state = make_state(
        hand="taki_red,card_3_red,stop_red,super_taki,change_color",
        top_card="card_1_red",
        active_color="red",
    )

    assert agent.get_action(state) == "taki_red"


def test_prefers_change_color_over_burning_super_taki_for_bad_sequence():
    agent = TakiStrategyAgent()
    state = make_state(
        hand="super_taki,change_color,card_1_red,stop_red,taki_red",
        top_card="card_5_green",
        active_color="green",
    )

    assert agent.get_action(state) == "change_color"


def test_change_color_selects_most_supported_color():
    agent = TakiStrategyAgent()
    state = make_state(
        phase="change_color",
        hand="card_1_blue,taki_blue,card_3_blue,stop_red",
        active_color="",
        top_card="change_color",
    )

    assert agent.get_action(state) == "selected_blue"


def test_taki_sequence_plays_expendable_card_before_stop():
    agent = TakiStrategyAgent()
    state = make_state(
        phase="taki_sequence",
        hand="card_1_red,stop_red,super_taki,card_3_blue",
        top_card="taki_red",
        active_color="red",
        rule_mode="taki",
        taki_color="red",
    )

    assert agent.get_action(state) == "card_1_red"


def test_taki_sequence_closes_instead_of_spending_super_taki_with_large_hand():
    agent = TakiStrategyAgent()
    state = make_state(
        phase="taki_sequence",
        hand="super_taki,card_1_blue,stop_green",
        top_card="taki_red",
        active_color="red",
        rule_mode="taki",
        taki_color="red",
    )

    assert agent.get_action(state) == "closed_taki"


def test_taki_sequence_uses_super_taki_to_go_out():
    agent = TakiStrategyAgent()
    state = make_state(
        phase="taki_sequence",
        hand="super_taki",
        top_card="taki_red",
        active_color="red",
        rule_mode="taki",
        taki_color="red",
    )

    assert agent.get_action(state) == "super_taki"
