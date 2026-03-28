from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

"""
TAKI game interfaces.

IMPORTANT SCOPE NOTE:
This code models a reduced TAKI variant, not the full official game.

Currently supported card kinds:
- NUMBER
- STOP
- CHANGE_COLOR
- TAKI
- SUPER_TAKI

Currently supported action types:
- PLAY_CARD
- DRAW_CARD
- CLOSE_TAKI
- SELECT_COLOR

Not currently modeled:
- PLUS
- PLUS_2
- PLUS_3
- PLUS_3_BREAKER
- KING
- CHANGE_DIRECTION
- "last card" announcement penalties
- full official tournament / pyramid rules

Any implementation based on this API should target this reduced variant
unless the interface is explicitly extended.

The reference semantics for this variant are defined by
RuleBasedTakiGameAdapter. Implementations should match the externally
observable semantics of RuleBasedTakiGameAdapter unless explicitly documented otherwise.
"""


class TakiGame(ABC):
    """
    Abstract interface for a TAKI game engine.

    State is a plain ``Dict[str, Any]`` with the following keys:
        hands         : List[List[str]] — each player's hand as card descriptors
        draw_pile     : List[str]
        discard_pile  : List[str]
        current_player: int
        top_card      : Optional[str] — card descriptor, or None
        active_color  : Optional[str] — "red" | "blue" | "green" | None
        phase         : str — "turn" | "taki_sequence" | "change_color" | "terminal"
        taki_color    : Optional[str]
        winner        : Optional[int]

    Observations are plain ``Dict[str, str]`` with the same keys as those
    documented on ``TakiAgent.get_action``.

    Action names are prefix-free card descriptors or non-card action strings:
        Number card : card_{number}_{color}   e.g. card_4_blue
        Stop card   : stop_{color}
        TAKI card   : taki_{color}
        Super TAKI  : super_taki
        Change color: change_color
        Draw card   : draw_card
        Close TAKI  : closed_taki
        Select color: selected_{color}
    """

    @abstractmethod
    def reset(
        self,
        seed: Optional[int] = None,
        num_players: int = 2,
        hand_size: int = 8,
    ) -> Dict[str, Any]:
        """Initialize and return a fresh game state."""
        raise NotImplementedError

    @abstractmethod
    def observe(self, state: Dict[str, Any], player_index: int) -> Dict[str, str]:
        """Build the player-facing observation for the requested player."""
        raise NotImplementedError

    @abstractmethod
    def legal_action_names_from_observation(self, observation: Dict[str, str]) -> List[str]:
        """Return the legal action names for the given player observation."""
        raise NotImplementedError

    @abstractmethod
    def step(self, state: Dict[str, Any], action_name: str) -> Dict[str, Any]:
        """Apply one action and return the next game state."""
        raise NotImplementedError

    @abstractmethod
    def is_terminal(self, state: Dict[str, Any]) -> bool:
        """Return True when the state is terminal."""
        raise NotImplementedError
