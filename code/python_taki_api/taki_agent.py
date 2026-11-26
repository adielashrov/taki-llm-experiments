from abc import ABC, abstractmethod
from typing import Dict, Optional


class TakiAgent(ABC):
    """
    Abstract interface for a TAKI-playing agent.

    Expected call lifecycle:
        while not terminal:
            action_name = agent.get_action(state)  # called on every turn

    The state passed to both methods is a flat ``Dict[str, str]`` produced by
    ``GameObservation.to_str_dict()``.  See that method for the full key/value
    documentation.
    """

    @abstractmethod
    def get_action(self, state: Dict[str, str]) -> Optional[str]:
        """
        Choose and return a legal action name for the current turn.

        ``state`` is a flat ``Dict[str, str]`` with the following keys
        (all values are strings):

        player_index : ``"0"``, ``"1"``, …
        phase        : ``"turn"`` | ``"taki_sequence"`` | ``"change_color"`` | ``"terminal"``
        hand         : comma-separated player-scoped card names,
                       e.g. ``"card_4_blue,stop_red"``
        top_card     : player-prefix-free top-card descriptor, e.g. ``"card_3_blue"``
                       (empty string when there is no top card)
        active_color : ``"red"`` | ``"blue"`` | ``"green"`` | ``""``
                       (empty string during the CHANGE_COLOR phase)
        rule_mode    : ``"match_color_or_type"`` | ``"color_only"`` | ``"taki"``
        taki_color   : ``"red"`` | ``"blue"`` | ``"green"`` | ``""``
                       (empty string outside a TAKI_SEQUENCE)

        Non-card actions available per phase (always legal):

            TURN          : ``draw_card``
            TAKI_SEQUENCE : ``closed_taki``
            CHANGE_COLOR  : ``selected_red``, ``selected_blue``, ``selected_green``

        Action name format (``{color}`` ∈ {red, blue, green}):

            Number card : ``card_{number}_{color}``   e.g. ``card_4_blue``
            Stop card   : ``stop_{color}``            e.g. ``stop_green``
            TAKI card   : ``taki_{color}``            e.g. ``taki_red``
            Super TAKI  : ``super_taki``
            Change color: ``change_color``
            Draw card   : ``draw_card``
            Close TAKI  : ``closed_taki``
            Select color: ``selected_{color}``        e.g. ``selected_red``
        """
        raise NotImplementedError
