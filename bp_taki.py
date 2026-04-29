from typing import Any, Dict, Optional, Union
import bppy as bp
from bppy.model.b_priority_event import BPEvent
from bppy.model.event_selection.event_priority_selection_strategy import EventPrioritySelectionStrategy
from bppy.analysis.dfs_bprogram_verifier import DFSBProgramVerifier
import random
import re
import logging
from datetime import datetime
from log_b_program_runner_listener import LogBProgramRunnerListener
from python_taki_api.python_agent import PythonAgent
from external_bridge_state import (
    build_external_observation,
    init_external_bridge_state,
    update_external_bridge_state_from_event,
)

NUM_OF_CARDS = 8 # Maybe the bug is related to number of cards?
NUM_OF_PLAYERS = 2
COLORS = ["red", "blue", "green"]

# Control the randomness of card dealing
SEED = 136 # good seeds for change color: 2, 4, a bug in 5

LOG_LEVEL = logging.INFO


current_time = datetime.now().strftime("%d_%m_%Y-%H_%M_%S")
log_filename = f"taki_game_{current_time}.log"
logger = logging.getLogger("TakiGame")
logger.setLevel(LOG_LEVEL)

random.seed(SEED)
logger.info(f"Random seed for card dealing: {SEED}")

leading_card_event_set = bp.EventSet(lambda e: e.name.startswith('leading_'))

# TODO: document this important event set
pattern = r"^(p_\d+_(draw_card|card_\d+_\w+|stop_\w+|change_color|taki_\w+|super_taki|closed_taki|no_more_cards)|end_game)$"
general_player_event_set = bp.EventSet(
    lambda e: hasattr(e, "name") and re.match(pattern, e.name) is not None
)


def all_player_events():
    def match_event_name(e):
        if hasattr(e, 'name') and 'p_' in e.name:
            return True
        return False
    return bp.EventSet(match_event_name)

def all_player_index_events(index):
    return bp.EventSet(lambda e: f'p_{index}' in e.name)

all_player_0_events = bp.EventSet(lambda e: 'p_0' in e.name)
all_player_1_events = bp.EventSet(lambda e: 'p_1' in e.name)


def all_other_player_cards_besides_special_cards(index):
    def predicate(e: BPEvent):
        if f'p_{index}' not in e.name and 'p_' in e.name and not 'no_more_cards' in e.name\
                and not 'deal_p_' in e.name:
            return True
        return False

    return bp.EventSet(predicate)


def init_selected_color_or_type_event_set(card_color: str, card_type: str):
    def predicate(e: BPEvent):
        # 🔍 DEBUG: Track what gets allowed/blocked (VERY VERBOSE)
        allowed = False
        reason = ""

        # System events that are always allowed regardless of placement rules
        if e.name.startswith("deal_p_"):
            allowed = True
            reason = "deal events always allowed"
        elif e.name.startswith("p_") and "draw_card" in e.name:
            allowed = True
            reason = "draw_card always allowed"
        elif "no_more_cards" in e.name:
            allowed = True
            reason = "no_more_cards always allowed"
        elif "change_color" in e.name:
            allowed = True
            reason = "change_color is wild card"
        elif "super_taki" in e.name:
            allowed = True
            reason = "super_taki is wild card"
        elif "closed_taki" in e.name:  # Fifth edge case - allow closing TAKI sequences
            allowed = True
            reason = "closed_taki always allowed"
        elif card_type == "TAKI" and re.match(r"^p_\d+_taki_\w+$", e.name) is not None:
            allowed = True
            reason = "TAKI-on-TAKI allowed by type (any color)"
        elif (card_type == "STOP" and "stop_" in e.name) or card_color in e.name:
            # Any STOP (any color) matches a leading STOP card by type.
            # But also allow matching by color.
            allowed = True
            reason =  f"matches color={card_color} or type={card_type}"
        elif f"card_{card_type}" in e.name or card_color in e.name:
            allowed = True
            reason = f"matches color={card_color} or type={card_type}"

        # If execution reaches this point, the event is about to be blocked.
        # We check if it is a "taki" card to verify if we are accidentally blocking a valid Taki-on-Taki move.
        if (not allowed) and (card_type == "TAKI") and re.match(r"^p_\d+_taki_\w+$", e.name):
            logger.debug(f"[RULES] Blocking TAKI play: {e.name} on top of {card_type}/{card_color}")


        # 🔍 DEBUG: logger.debug only when checking TAKI cards (reduce noise)
        # if "taki" in e.name.lower() or allowed:
            # symbol = "v" if allowed else "x"
            # logger.debug(f"[PLACEMENT_CHECK] {symbol} {e.name:30} | Reason: {reason if allowed else 'no match'}")

        return allowed

    return bp.EventSet(predicate)



any_player_no_more_cards = bp.EventSet(lambda e: 'no_more_cards' in e.name)

announce_color_event_set = bp.EventSet(lambda e: 'announce_color' in e.name)


def get_player_id(name: str):
    player_reg_exp = re.compile(r"^p_(\d+)_")
    m = player_reg_exp.match(name)
    if m:
        id = int(m.group(1))
    else:
        id = None
    return id


def create_block_set_color_only(color: str):
    """
    Creates an EventSet that blocks cards of colors different from the specified color.

    Used after a change_color card is played to enforce that the next card played
    must match the newly selected color. However, special cards like change_color
    and super_taki can bypass this color restriction.

    Parameters
    ----------
    color : str
        The required color that cards must match. Must be one of: "red", "green", "blue"

    Returns
    -------
    bp.EventSet
        An EventSet that returns True for play events that should be blocked
        (i.e., cards that don't match the required color and aren't special bypass cards)

    Examples
    --------
    After a change_color card selects "blue":
    block_set = create_block_set_color_only("blue")
    # Blocks: p_0_card_5_red, p_0_stop_green, p_0_plus_2_red
    # Allows: p_0_card_3_blue, p_0_stop_blue, p_0_super_taki, p_0_change_color

    Notes
    -----
    This function is specifically designed for use after change_color cards,
    where color matching is enforced but special cards can still be played.
    """

    def is_play_event(e):
        """
        Determines if an event is a card play event (as opposed to system events
        like draw_card, next_turn, etc.).

        Recognizes two categories of play events:
        1. Colored cards: regular cards, stop, and plus_2 with color suffixes
        2. Super Taki: special card without a color suffix

        Parameters
        ----------
        e : BPEvent
            The event to check

        Returns
        -------
        bool or Match object
            Returns a truthy value (Match object) if the event is a play event,
            None (falsy) otherwise

        Examples
        --------
        is_play_event(BPEvent("p_0_card_5_blue"))  # Returns Match object (truthy)
        is_play_event(BPEvent("p_0_super_taki"))   # Returns Match object (truthy)
        is_play_event(BPEvent("p_0_draw_card"))    # Returns None (falsy)
        is_play_event(BPEvent("next_turn"))        # Returns None (falsy)

        Notes
        -----
        The regex patterns are:
        - "^p_\\d+_(card_\\d+|stop|plus_2)_(red|green|blue)$" for colored cards
        - "^p_\\d+_super_taki$" for super_taki (no color suffix)
        """
        # Match colored cards OR super_taki (which has no color suffix)
        return (
                isinstance(e, BPEvent)
                and (re.match(r"^p_\d+_(card_\d+|stop|plus_2|taki)_(red|green|blue)$", e.name) is not None
                     or re.match(r"^p_\d+_super_taki$", e.name) is not None)
        )

    def to_block(e):
        """
        Determines if a play event should be blocked based on color mismatch.

        The blocking logic follows these rules:
        1. Non-play events (e.g., draw_card, next_turn) are never blocked
        2. change_color cards bypass color restrictions (can be played on any color)
        3. super_taki cards bypass color restrictions (can be played on any color)
        4. All other play events are blocked if their color doesn't match the required color

        Parameters
        ----------
        e : BPEvent
            The event to evaluate for blocking

        Returns
        -------
        bool
            True if the event should be blocked (color mismatch), False otherwise

        Examples
        --------
        When the required color is "blue":
        to_block(BPEvent("p_0_card_5_red"))      # True - wrong color
        to_block(BPEvent("p_0_card_3_blue"))     # False - correct color
        to_block(BPEvent("p_0_super_taki"))      # False - bypass card
        to_block(BPEvent("p_0_change_color"))    # False - bypass card
        to_block(BPEvent("p_0_draw_card"))       # False - not a play event

        Notes
        -----
        This function is called by the EventSet for each event to determine
        if it should be included in the blocked set. The EventSet will then
        prevent any blocked events from being selected during event selection.
        """
        # Ignore non-play events (like draw_card, next_turn, etc.)
        if not is_play_event(e):
            return False

        # change_color cards can be played regardless of current color requirement
        if is_change_color_event(e):
            return False

        # Super Taki can be played on any card regardless of color
        if "super_taki" in e.name:
            return False

        # For all other play events, block if color doesn't match
        c, _ = extract_card_color_and_type(e)
        return c is not None and c != color

    return bp.EventSet(to_block)


def create_taki_color_block(color: str) -> bp.EventSet:
    """
    During a TAKI sequence of color `color`, block any *colored* card
    whose color is different from `color`.

    Cards with no color (draw_card, done_post_action, super_taki, etc.)
    are untouched by this block.
    """
    def to_block(e: BPEvent) -> bool:
        if not isinstance(e, BPEvent):
            return False

        if is_change_color_event(e):
            # GAME implementation selection - We do not allow change_color during TAKI
            return True

        card_color, _ = extract_card_color_and_type(e)

        # If the event has no color (None or ""), don't constrain it here
        # These are events like: draw_card, done_post_action, deadlock, super_taki and closed_taki.
        if not card_color:
            # logger.debug(f"[TAKI_BLOCK] ALLOW non-colored event: {e.name} during TAKI({color})")
            return False

        # Block any colored card with a different color than the TAKI color
        should_block = (card_color != color)

        # Core debug line: every colored card checked against TAKI color
        if should_block:
            logger.debug(
                f"[TAKI_BLOCK] CHECK event={e.name} "
                f"(card_color={card_color}, TAKI_color={color}) "
                f"-> {'BLOCK' if should_block else 'allow'}"
            )

        return should_block

    return bp.EventSet(to_block)


class DealCardsEventSet(bp.EventSet):
    def __init__(self):
        super().__init__(lambda event: event.name.startswith(f"deal_p_"))

    def __contains__(self, item):
        if isinstance(item, BPEvent):
            return item.name.startswith(f"deal_p_")
        else:
            raise TypeError(
                f"DealCardsEventSet: Expected item of type BPEvent, got {type(item)}")


def init_cards_events():

    all_cards = []
    # Init regular cards
    colors = COLORS
    numbers = ["1", "3", "4", "5"]
    for color in colors: # Add regular cards - 1 of each number and color
        for number in numbers:
            all_cards.append(BPEvent(name=f"card_{number}_{color}", priority=10.0))

    for color in colors: # Add stop cards - 2 of each color
        all_cards.append(BPEvent(name=f"stop_{color}", priority=10.0))
        all_cards.append(BPEvent(name=f"stop_{color}", priority=10.0))

    all_cards.append(BPEvent(name=f"change_color", priority=10.0))
    all_cards.append(BPEvent(name=f"change_color", priority=10.0))

    # Add Regular Taki cards - 2 of each color
    for color in colors:
        all_cards.append(BPEvent(name=f"taki_{color}", priority=10.0))
        all_cards.append(BPEvent(name=f"taki_{color}", priority=10.0))

    all_cards.append(BPEvent(name=f"super_taki", priority=10.0))
    all_cards.append(BPEvent(name=f"super_taki", priority=10.0))

    return all_cards


def is_taki_card_event(event: BPEvent) -> bool:
    """Check if event is a regular taki card (not super taki)"""
    result =  isinstance(event, BPEvent) and re.match(r"^p_\d+_taki_(red|blue|green)$", event.name) is not None
    # if result:
    #     logger.debug(f"[DEBUG is_taki_card_event] Regular TAKI detected: {event.name}")
    return result

def is_any_taki_event(e):
    """Check if event is any type of TAKI card (regular or super)"""
    result = is_taki_card_event(e) or is_super_taki_event(e)
    return result


def is_change_color_event(event: BPEvent) -> bool:
    """Check if event is a change color card"""
    return "change_color" in event.name





@bp.thread
def game_manager():
    yield bp.sync(request=BPEvent("start_dealing_cards_to_players", priority=10.0))
    yield bp.sync(waitFor=BPEvent("finished_dealing_cards_to_players", priority=10.0))
    yield bp.sync(request=BPEvent("deal_leading_card", priority=10.0))
    yield bp.sync(waitFor=BPEvent("finished_leading_card", priority=10.0))
    yield bp.sync(request=BPEvent("start_game", priority=10.0))
    yield bp.sync(waitFor=any_player_no_more_cards)
    # End the game, the only event allowed is end_game
    yield bp.sync(request=BPEvent("end_game", priority=7.0),
                           block=bp.AllExcept(BPEvent("end_game", priority=7.0)))
    yield bp.sync(block=bp.All())


def create_deal_events(card_events_list):
    deal_cards_events = []
    for index, card_event in enumerate(card_events_list):
        deal_player_card_event = BPEvent("deal_p_" + card_event.name, priority=card_event.priority)
        deal_cards_events.append(deal_player_card_event)

    return deal_cards_events

# A regular card is a card with a number (1-9) and a color (red, blue, green).
# a possible input event to this method is deal_p_card_5_blue
def is_deal_regular_card_event(event: BPEvent) -> bool:
    pattern = r"deal_p_card_\d+_\w+"
    if re.match(pattern, event.name) is not None:
        return True
    return False


def create_regular_leading_card_events():
    """Create the pool of regular numbered cards that may be used as a leading card."""
    return [
        deal_event
        for deal_event in create_deal_events(init_cards_events())
        if is_deal_regular_card_event(deal_event)
    ]

@bp.thread
def deal_cards(num_of_players=2, num_of_cards=2, starting_player=0):
    """
    Deal random cards to players with fair distribution.
    
    IMPORTANT: Cards are dealt in STARTING-PLAYER ORDER to ensure symmetry.
    When starting_player=1, P1 receives cards first, then P0.
    
    Parameters
    ----------
    num_of_players : int
        Number of players (typically 2)
    num_of_cards : int
        Number of cards each player receives
    starting_player : int, optional
        Which player goes first (0 or 1). Default is 0.
        Cards are dealt to starting player FIRST for symmetry.
    
    Protocol
    --------
    1. Wait for "start_dealing_cards_to_players"
    2. Deal cards alternating, but starting with starting_player
    3. Signal "finished_dealing_cards_to_players"
    4. Deal the leading card
    5. Handle draw requests during gameplay
    """
    yield bp.sync(waitFor=BPEvent("start_dealing_cards_to_players", priority=10.0))
    cards_events = init_cards_events()
    deal_cards_events = create_deal_events(cards_events)
    
    if starting_player == 0:
        player_order = list(range(num_of_players))  # [0, 1]
    else:
        player_order = list(range(starting_player, num_of_players)) + list(range(starting_player))
    
    logger.debug(f"[DEAL_CARDS] Dealing order: {player_order} (starting_player={starting_player})")
    
    # Deal cards one at a time, alternating between players in the determined order
    for j in range(num_of_cards):
        for player_idx in player_order:
            yield bp.sync(request=BPEvent(f"deal_cards_to_player_{player_idx}", priority=10.0))
            last_event = yield bp.sync(request=deal_cards_events)
            deal_cards_events.remove(last_event)
    yield bp.sync(request=BPEvent("finished_dealing_cards_to_players", priority=10.0))

    # Deal the leading card
    yield bp.sync(waitFor=BPEvent("deal_leading_card", priority=10.0))

    # Filter to only regular numbered cards
    regular_cards = [card for card in deal_cards_events
                     if is_deal_regular_card_event(card)]
    if not regular_cards:
        logger.debug(
            "[DEAL_CARDS] No regular cards left for the leading card after initial deal. "
            "Falling back to a fresh regular leading-card pool."
        )
        regular_cards = create_regular_leading_card_events()
    # We want that the leading card will be a regular card.
    last_event = yield bp.sync(request=regular_cards)  # possible pattern here?
    if last_event in deal_cards_events:
        deal_cards_events.remove(last_event)
    yield bp.sync(request=BPEvent(f"leading_{last_event.name}", priority=10.0))
    yield bp.sync(request=BPEvent("finished_leading_card", priority=10.0))

    while True:
        last_event = yield bp.sync(waitFor=[BPEvent("p_0_draw_card"), BPEvent("p_1_draw_card")])
        player_id = "0" if "p_0" in last_event.name else "1"
        
        if not deal_cards_events:  # imagine an infinite pile of cards.
            deal_cards_events = create_deal_events(init_cards_events())
        
        yield bp.sync(request=BPEvent(f"deal_cards_to_player_{player_id}", priority=10.0))
        last_event = yield bp.sync(request=deal_cards_events)
        deal_cards_events.remove(last_event)


def remove_deal_prefix_and_add_player_index(event, player_index):
    card_name = event.name.removeprefix("deal_p_")
    card_name = f"p_{player_index}_" + card_name
    return card_name


def list_does_not_contain_card_events(events: list[BPEvent]) -> bool:
    """
    Return True iff there are no more real card events in the list, i.e.,
    the only remaining actions are 'draw_card' and/or 'closed_taki'.

    This lets the player declare 'no_more_cards' when they have no playable
    cards left in hand (other than drawing).
    """
    if not events: # Defensive: shouldn't really happen, but treat as "no cards"
        return True

    for e in events:
        if "_draw_card" in e.name or "_closed_taki" in e.name:
            continue
        # Any other event means there is still at least one card in hand
        return False

    # We saw only draw/closed_taki
    return True


# A regular card is a card with a number (1-9) and a color (red, blue, green).
# a possible input event to this method is p_1_card_4_blue
REGULAR_PLAYED_RE = r"^p_\d+_card_\d+_\w+$"

def is_regular_card_event(event: BPEvent) -> bool:
    return hasattr(event, "name") and re.match(REGULAR_PLAYED_RE, event.name) is not None

played_regular_cards_event_set = bp.EventSet(is_regular_card_event)

def is_draw_card_event(event: BPEvent) -> bool:
    draw_card_pattern = r"p_\d+_draw_card"
    if re.match(draw_card_pattern, event.name) is not None:
            return True
    return False

def is_action_card_event(event: BPEvent) -> bool:
    action_card_pattern = r"p_\d+_(change_color|plus_2_\w+|stop_\w+|taki_\w+|super_taki)"
    if re.match(action_card_pattern, event.name) is not None:
            return True
    return False

def is_stop_card_event(event: BPEvent) -> bool:
    stop_card_pattern = r"p_\d+_stop_\w+"
    if re.match(stop_card_pattern, event.name) is not None:
            return True
    return False


def is_super_taki_event(e):
    ans = isinstance(e, BPEvent) and re.match(r"^p_\d+_super_taki$", e.name) is not None
    return ans




@bp.thread
def player_behavior(index, num_of_cards=2):
    yield bp.sync(waitFor=BPEvent(f"start_dealing_cards_to_players", priority=10.0))
    card_events = []
    deal_player_cards_event_set = DealCardsEventSet()
    for i in range(num_of_cards):
        yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
        deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
        card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
        card_events.append(BPEvent(card_name, priority=deal_card_event.priority))

    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))

    # Add draw_card_event to the cards events(Possible actions of player)
    draw_card_event = BPEvent(f"p_{index}_draw_card", priority=20.0)
    card_events.append(draw_card_event)

    while True:
        card_event = yield bp.sync(request=card_events)

        if is_regular_card_event(card_event):
            card_events.remove(card_event)
        # If there is a draw card event, wait for a card to be dealt.
        elif is_draw_card_event(card_event):
            yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
            deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
            card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
            card_events.append(BPEvent(card_name, priority=deal_card_event.priority))
        # If this is an action card - wait for done_post_action event.
        elif is_action_card_event(card_event):
            if is_any_taki_event(card_event):
                # 🔍 DEBUG: TAKI sequence start
                taki_type = "Regular TAKI" if is_taki_card_event(card_event) else "Super TAKI"
                logger.debug(f"{'=' * 60}")
                logger.debug(f"[PLAYER_{index}] {taki_type} SEQUENCE STARTING: {card_event.name}")
                logger.debug(f"[PLAYER_{index}] Removing TAKI from hand")
                logger.debug(f"[PLAYER_{index}] Adding closed_taki to possible actions")
                logger.debug(f"{'=' * 60}")

                card_events.remove(card_event) # Remove TAKI / Super_TAKI from player hand
                
                # Add closed_taki event to the possible actions of the player, the correct priority here is crucial!
                closed_taki_event = BPEvent(f"p_{index}_closed_taki", priority=15.0)
                card_events.append(closed_taki_event)

                cards_played_in_taki = []

                while True:
                    card_event = yield bp.sync(request=card_events)

                    if card_event.name != f"p_{index}_closed_taki":
                        cards_played_in_taki.append(card_event.name)
                        logger.debug(f"[PLAYER_{index}] Card played in TAKI: {card_event.name}")

                    card_events.remove(card_event)
                    if card_event.name == f"p_{index}_closed_taki":
                        # 🔍 DEBUG: TAKI sequence end
                        logger.debug(f"{'=' * 60}")
                        logger.debug(f"[PLAYER_{index}] TAKI SEQUENCE ENDING")
                        logger.debug(f"[PLAYER_{index}] Cards played: {cards_played_in_taki}")
                        logger.debug(f"[PLAYER_{index}] Total cards in sequence: {len(cards_played_in_taki)}")
                        logger.debug(f"{'=' * 60}")
                        break

                yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
            elif is_change_color_event(card_event):
                card_events.remove(card_event)
                selected_color_events = [BPEvent(f"selected_{c}", priority=5.0) for c in COLORS]
                selected_color_event = yield bp.sync(request=selected_color_events)
                yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
            else:
                yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                card_events.remove(card_event)

        # If the only event left is draw_card, break and end the game.
        if list_does_not_contain_card_events(card_events):
            yield bp.sync(request=BPEvent(f"p_{index}_no_more_cards", priority=8.0))
            break
        else: # else announce that you have finished your turn.
            yield bp.sync(request=BPEvent("next_turn", priority=10.0))


def is_selected_color_event(event: BPEvent) -> bool:
    return hasattr(event, "name") and event.name.startswith("selected_")


def is_external_hand_card_event(event: BPEvent) -> bool:
    return (
        is_regular_card_event(event)
        or is_action_card_event(event)
    )


def _action_name_to_bp_event_name(action_name: str, player_index: str) -> str:
    """Reconstruct the full BP event name from a prefix-free action name.

    Selected-color events (e.g. ``selected_red``) have no player prefix and
    are returned unchanged.  All other actions are player-scoped and get the
    ``p_{player_index}_`` prefix prepended.
    """
    if action_name.startswith("selected_"):
        return action_name
    return f"p_{player_index}_{action_name}"


def resolve_external_action_event(
    action_name,
    observation: Dict[str, str],
    candidate_events: list[BPEvent],
) -> BPEvent:
    bp_event_name = _action_name_to_bp_event_name(action_name, observation["player_index"])
    for event in candidate_events:
        if event.name == bp_event_name:
            logger.info(
                f"[PLAYER_EXTERNAL_API] player={observation['player_index']} "
                f"phase={observation['phase']} action={action_name}"
            )
            return event

    candidate_action_names = [event.name for event in candidate_events]
    if not candidate_events:
        raise RuntimeError(
            f"[PLAYER_EXTERNAL_API] No candidate actions available for "
            f"player={observation['player_index']} phase={observation['phase']}"
        )
    logger.warning(
        f"[PLAYER_EXTERNAL_API] Agent returned unknown action '{action_name}' "
        f"for player={observation['player_index']} phase={observation['phase']}. "
        f"Candidate actions={candidate_action_names}. "
        f"Falling back to '{candidate_events[0].name}'"
    )
    return candidate_events[0]


@bp.thread
def player_behavior_external(index, num_of_cards=2, starting_player=0, num_of_players=2, agent=None):
    """
    Bridge between the BP TAKI runtime and a Python policy with a Gym-like
    observation -> action loop.
    """
    python_agent = agent if agent is not None else PythonAgent(seed=SEED)
    state = init_external_bridge_state(index, starting_player, num_of_players)

    yield bp.sync(waitFor=BPEvent(f"start_dealing_cards_to_players", priority=10.0))
    card_events = []
    deal_player_cards_event_set = DealCardsEventSet()

    for i in range(num_of_cards):
        yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
        deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
        card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
        card_events.append(BPEvent(card_name, priority=deal_card_event.priority))

    yield bp.sync(waitFor=BPEvent("finished_dealing_cards_to_players", priority=10.0))
    yield bp.sync(waitFor=BPEvent("deal_leading_card", priority=10.0))
    leading_event = yield bp.sync(waitFor=leading_card_event_set)
    update_external_bridge_state_from_event(state, leading_event, num_of_players)
    yield bp.sync(waitFor=BPEvent("finished_leading_card", priority=10.0))
    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))

    # Add draw_card_event to the cards events(Possible actions of player)
    draw_card_event = BPEvent(f"p_{index}_draw_card", priority=20.0)
    card_events.append(draw_card_event)

    while True:
        if state["current_player"] != index:
            observed_event = yield bp.sync(waitFor=bp.All())
            update_external_bridge_state_from_event(state, observed_event, num_of_players)
            continue

        observation = build_external_observation(index, "turn", card_events, state)
        action_name = python_agent.get_action(observation)
        requested_event = resolve_external_action_event(action_name, observation, card_events)
        card_event = yield bp.sync(request=requested_event)
        update_external_bridge_state_from_event(state, card_event, num_of_players)

        if is_regular_card_event(card_event):
            card_events.remove(card_event)
        # If there is a draw card event, wait for a card to be dealt.
        elif is_draw_card_event(card_event):
            yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
            deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
            card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
            card_events.append(BPEvent(card_name, priority=deal_card_event.priority))
        # If this is an action card - wait for done_post_action event.
        elif is_action_card_event(card_event):
            if is_any_taki_event(card_event):
                logger.debug(f"{'=' * 60}")
                logger.debug(f"[PLAYER_EXTERNAL_{index}] TAKI SEQUENCE STARTING: {card_event.name}")
                logger.debug(f"[PLAYER_EXTERNAL_{index}] Removing TAKI from hand")
                logger.debug(f"[PLAYER_EXTERNAL_{index}] Adding closed_taki to possible actions")
                logger.debug(f"{'=' * 60}")

                card_events.remove(card_event)  # Remove TAKI / Super_TAKI from player hand

                # Add closed_taki event to the possible actions of the player, the correct priority here is crucial!
                closed_taki_event = BPEvent(f"p_{index}_closed_taki", priority=15.0)
                card_events.append(closed_taki_event) # Not sure if this should be forwarded to the agent.

                cards_played_in_taki = []

                while True:
                    observation = build_external_observation(index, "taki_sequence", card_events, state)
                    action_name = python_agent.get_action(observation)
                    requested_event = resolve_external_action_event(action_name, observation, card_events)
                    taki_event = yield bp.sync(request=requested_event)
                    update_external_bridge_state_from_event(state, taki_event, num_of_players)

                    if taki_event.name != f"p_{index}_closed_taki":
                        cards_played_in_taki.append(taki_event.name)
                        if taki_event in card_events:
                            card_events.remove(taki_event)
                        logger.debug(f"[PLAYER_EXTERNAL_{index}] Card played in TAKI: {taki_event.name}")
                    else:
                        card_events.remove(taki_event)
                        logger.debug(f"{'=' * 60}")
                        logger.debug(f"[PLAYER_EXTERNAL_{index}] TAKI SEQUENCE ENDING")
                        logger.debug(f"[PLAYER_EXTERNAL_{index}] Cards played: {cards_played_in_taki}")
                        logger.debug(f"[PLAYER_EXTERNAL_{index}] Total cards in sequence: {len(cards_played_in_taki)}")
                        logger.debug(f"{'=' * 60}")
                        break

                done_post_action_event = yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                update_external_bridge_state_from_event(state, done_post_action_event, num_of_players)
            elif is_change_color_event(card_event):
                card_events.remove(card_event)
                selected_color_events = [BPEvent(f"selected_{c}", priority=5.0) for c in COLORS]
                observation = build_external_observation(index, "change_color", selected_color_events, state)
                action_name = python_agent.get_action(observation)
                requested_color_event = resolve_external_action_event(action_name, observation, selected_color_events)
                selected_color_event = yield bp.sync(request=requested_color_event)
                update_external_bridge_state_from_event(state, selected_color_event, num_of_players)
                done_post_action_event = yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                update_external_bridge_state_from_event(state, done_post_action_event, num_of_players)
            else:
                done_post_action_event = yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                update_external_bridge_state_from_event(state, done_post_action_event, num_of_players)
                card_events.remove(card_event)

        if list_does_not_contain_card_events(card_events):
            no_more_cards_event = BPEvent(f"p_{index}_no_more_cards", priority=8.0)
            final_event = yield bp.sync(request=no_more_cards_event)
            update_external_bridge_state_from_event(state, final_event, num_of_players)
            break

        next_turn_event = BPEvent("next_turn", priority=10.0)
        observed_next_turn = yield bp.sync(request=next_turn_event)
        update_external_bridge_state_from_event(state, observed_next_turn, num_of_players)


def add_event_to_card_events_according_to_basic_strategy_taki(index, card_name, original_priority, card_events):
    """
    Add a card event to player's hand with priority adjustment for TAKI cards.

    TAKI cards receive priority 5.0 (lower number = higher priority) to encourage playing them,
    while other cards keep their original priority (typically 10.0).
    """
    if "taki" in card_name:
        adjusted_priority = 5.0
        logger.debug(
            f"[STRATEGY_TAKI] Player {index}: Adding TAKI card '{card_name}' with BOOSTED priority {adjusted_priority} (original: {original_priority})")
        card_events.append(BPEvent(card_name, priority=adjusted_priority))
    else:
        logger.debug(
            f"[STRATEGY_TAKI] Player {index}: Adding regular card '{card_name}' with standard priority {original_priority}")
        card_events.append(BPEvent(card_name, priority=original_priority))

    # Summary log of current hand composition
    taki_count = sum(1 for e in card_events if "taki" in e.name)
    logger.debug(
        f"[STRATEGY_TAKI] Player {index}: Hand now contains {len(card_events)} cards ({taki_count} TAKI cards)")


@bp.thread
def basic_strategy_taki(index, num_of_cards=2):
    """
    B-thread implementing basic TAKI strategy: prioritize playing TAKI cards.

    This strategy adjusts event priorities so TAKI/Super TAKI cards are preferred
    over regular cards during event selection.
    """
    # logger.debug(f"[STRATEGY_TAKI] Player {index}: B-thread started, waiting for initial deal")

    card_events = []
    deal_player_cards_event_set = DealCardsEventSet()

    # Receive initial hand
    for i in range(num_of_cards):
        yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
        deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
        card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
        # logger.debug(f"[STRATEGY_TAKI] Player {index}: Received card #{i + 1}/{num_of_cards}: {card_name}")
        add_event_to_card_events_according_to_basic_strategy_taki(index, card_name, deal_card_event.priority,
                                                                  card_events)

    # logger.debug(f"[STRATEGY_TAKI] Player {index}: Initial hand complete. Total cards: {len(card_events)}")

    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))
    # logger.debug(f"[STRATEGY_TAKI] Player {index}: Game started! Beginning play with strategy-adjusted priorities")

    draw_card_event = BPEvent(f"p_{index}_draw_card", priority=20.0)
    no_more_cards_event = BPEvent(f"p_{index}_no_more_cards", priority=8.0)
    next_turn = BPEvent("next_turn", priority=10.0)

    turn_number = 0
    while True:
        turn_number += 1

        taki_cards = [e.name for e in card_events if "taki" in e.name]
        regular_cards = [e.name for e in card_events if "taki" not in e.name]
        logger.debug(f"[STRATEGY_TAKI] P{index} Turn #{turn_number} | Hand: {len(card_events)} cards ({len(taki_cards)} TAKI)")

        # Request a card to play (or wait-for draw_card)
        card_event = yield bp.sync(request=card_events, waitFor=[draw_card_event])

        logger.debug(f"[STRATEGY_TAKI] P{index} → {card_event.name} (priority {card_event.priority})")

        if is_regular_card_event(card_event):
            # logger.debug(f"[STRATEGY_TAKI] Player {index}: Played regular card: {card_event.name}")
            card_events.remove(card_event)

        elif is_action_card_event(card_event):
            if is_any_taki_event(card_event):
                taki_type = "Regular TAKI" if is_taki_card_event(card_event) else "Super TAKI"
                logger.debug(f"[STRATEGY_TAKI] Player {index}: {taki_type} PLAYED! Strategy success - prioritized TAKI card was selected")
                # logger.debug(f"[STRATEGY_TAKI] Player {index}: Entering TAKI sequence handling")

                # Remove TAKI from hand
                card_events.remove(card_event)

                # Add closed_taki event
                closed_taki_event = BPEvent(f"p_{index}_closed_taki", priority=15.0)
                card_events.append(closed_taki_event)

                cards_played_in_taki = []

                # Handle TAKI sequence
                while True:
                    card_event = yield bp.sync(waitFor=card_events) # if we want to prefer other cards during taki, change to request=card_events

                    if card_event.name != f"p_{index}_closed_taki":
                        cards_played_in_taki.append(card_event.name)
                        logger.debug(f"[STRATEGY_TAKI] Player {index}: 🃏 Card played in TAKI: {card_event.name}")

                    card_events.remove(card_event)

                    if card_event.name == f"p_{index}_closed_taki":
                        # logger.debug(f"[STRATEGY_TAKI] Player {index}: 🛑 TAKI sequence closed")
                        logger.debug(f"[STRATEGY_TAKI] Player {index}: Cards played in sequence: {cards_played_in_taki}")
                        # logger.debug(f"[STRATEGY_TAKI] Player {index}: Total cards in TAKI: {len(cards_played_in_taki)}")
                        break

                yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                # logger.debug(f"[STRATEGY_TAKI] Player {index}: done_post_action received after TAKI sequence")
            else:
                # Other action cards (stop, change_color, etc.)
                logger.debug(f"[STRATEGY_TAKI] Player {index}: Played action card: {card_event.name}")
                yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                card_events.remove(card_event)

        elif is_draw_card_event(card_event):
            logger.debug(f"[STRATEGY_TAKI] Player {index}: Drawing a card (no playable cards available)")
            yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
            deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
            card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
            # logger.debug(f"[STRATEGY_TAKI] Player {index}: Drew card: {card_name}")
            add_event_to_card_events_according_to_basic_strategy_taki(index, card_name, deal_card_event.priority,
                                                                      card_events)

        # Wait for turn to complete
        last_event = yield bp.sync(waitFor=[ no_more_cards_event, next_turn ])

        if "next_turn" in last_event.name:
            taki_count = sum(1 for e in card_events if "taki" in e.name)
            logger.debug(f"[STRATEGY_TAKI] P{index} | Remaining: {len(card_events)} cards ({taki_count} TAKI)")
            continue
        elif "no_more_cards" in last_event.name:
            logger.debug(f"[STRATEGY_TAKI] Player {index}: 🏆 NO MORE CARDS! Game over for this player")
            break

    logger.debug(f"[STRATEGY_TAKI] Player {index}: B-thread terminated after {turn_number} turns")


def add_event_to_card_events_according_to_basic_strategy_taki_2(index, card_name, original_priority, card_events):
    """
    Add a card event to player's hand with priority adjustment for TAKI cards.
    If you have both TAKI and Super TAKI cards, prioritize TAKI higher.
    TAKI will receive a priority of 4.0, Super TAKI 6.0, and
    other cards keep their original priority.
    """
    if "super_taki" in card_name :
        adjusted_priority = 6.0
        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Adding SUPER TAKI card '{card_name}' with BOOSTED priority {adjusted_priority} (original: {original_priority})")
        card_events.append(BPEvent(card_name, priority=adjusted_priority))
    elif "taki_" in card_name:
        adjusted_priority = 4.0
        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Adding TAKI card '{card_name}' with BOOSTED priority {adjusted_priority} (original: {original_priority})")
        card_events.append(BPEvent(card_name, priority=adjusted_priority))
    else:
        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Adding regular card '{card_name}' with standard priority {original_priority}")
        card_events.append(BPEvent(card_name, priority=original_priority))


@bp.thread
def basic_strategy_taki_and_super_taki(index, num_of_cards=2):
    """
      B-thread implementing TAKI/SuperTAKI priority strategy.

      Priority hierarchy (lower number = higher priority):
      - Regular TAKI: 4.0 (highest - start sequences with these)
      - Super TAKI: 6.0 (medium - prefer during sequences)
      - Regular cards: 10.0 (lowest - play when no TAKI available)

      This means:
      1. When choosing which TAKI to play: prefer Regular TAKI
      2. During TAKI sequence: prefer Super TAKI over regular cards
      """
    # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: B-thread started, waiting for initial deal")

    card_events = []
    deal_player_cards_event_set = DealCardsEventSet()

    # Receive initial hand
    for i in range(num_of_cards):
        yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
        deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
        card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Received card #{i + 1}/{num_of_cards}: {card_name}")
        add_event_to_card_events_according_to_basic_strategy_taki_2(index, card_name, deal_card_event.priority,
                                                                    card_events)
    taki_count = sum(1 for e in card_events if "taki" in e.name)
    logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Initial hand contains {len(card_events)} cards ({taki_count} TAKI cards)")
    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))
    # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Game started! Beginning play with strategy-adjusted priorities")

    draw_card_event = BPEvent(f"p_{index}_draw_card", priority=20.0)
    no_more_cards_event = BPEvent(f"p_{index}_no_more_cards", priority=8.0)
    next_turn = BPEvent("next_turn", priority=10.0)

    turn_number = 0
    while True:
        turn_number += 1

        taki_cards = [e.name for e in card_events if "taki" in e.name]
        regular_cards = [e.name for e in card_events if "taki" not in e.name]
        logger.debug(f"[STRATEGY_TAKI_2] P{index} Turn #{turn_number} | Hand: {len(card_events)} cards ({len(taki_cards)} TAKI)")

        card_event = yield bp.sync(request=card_events, waitFor=[draw_card_event])

        logger.debug(f"[STRATEGY_TAKI_2] P{index} -> {card_event.name} (priority {card_event.priority})")

        if is_regular_card_event(card_event):
            # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Played regular card: {card_event.name}")
            card_events.remove(card_event)

        elif is_action_card_event(card_event):
            if is_any_taki_event(card_event):
                taki_type = "Regular TAKI" if is_taki_card_event(card_event) else "Super TAKI"
                logger.debug(
                    f"[STRATEGY_TAKI_2] Entering TAKI sequence "
                    f"Player{index} chose {taki_type}: {card_event.name} "
                    f"(prio={getattr(card_event, 'priority', None)})"
                )

                # Remove TAKI from hand
                card_events.remove(card_event)

                # Add closed_taki event
                closed_taki_event = BPEvent(f"p_{index}_closed_taki", priority=15.0)
                card_events.append(closed_taki_event)

                cards_played_in_taki = []

                # Handle TAKI sequence
                while True:
                    card_event = yield bp.sync(request=card_events) # We want to keep the priority of SUPER TAKI, change to request=card_events

                    if card_event.name != f"p_{index}_closed_taki":
                        cards_played_in_taki.append(card_event.name)
                        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}:  Card played in TAKI: {card_event.name}")

                    card_events.remove(card_event) # this removes also closed_taki when played

                    if card_event.name == f"p_{index}_closed_taki":
                        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}:  TAKI sequence closed")
                        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Cards played in sequence: {cards_played_in_taki}")
                        # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Total cards in TAKI: {len(cards_played_in_taki)}")
                        break

                yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: done_post_action received after TAKI sequence")
            else:
                # logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Played action card: {card_event.name}")
                yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))
                card_events.remove(card_event)

        elif is_draw_card_event(card_event):
            logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Drawing a card...")
            yield bp.sync(waitFor=BPEvent(f"deal_cards_to_player_{index}", priority=10.0))
            deal_card_event = yield bp.sync(waitFor=deal_player_cards_event_set)
            card_name = remove_deal_prefix_and_add_player_index(deal_card_event, index)
            logger.debug(f"[STRATEGY_TAKI_2] Player {index}: Drew card: {card_name}")
            add_event_to_card_events_according_to_basic_strategy_taki_2(index, card_name, deal_card_event.priority,
                                                                      card_events)

        # Wait for turn to complete
        last_event = yield bp.sync(waitFor=[ no_more_cards_event, next_turn ])

        if "next_turn" in last_event.name:
            taki_count = sum(1 for e in card_events if "taki" in e.name)
            logger.debug(f"[STRATEGY_TAKI_2] P{index} | Remaining: {len(card_events)} cards ({taki_count} TAKI)")
            continue
        elif "no_more_cards" in last_event.name:
            logger.debug(f"[STRATEGY_TAKI_2] Player {index}: NO MORE CARDS! Game over for this player")
            break

    logger.debug(f"[STRATEGY_TAKI_2] Player {index}: B-thread terminated after {turn_number} turns")

def is_no_more_cards_event(event: BPEvent) -> bool:
    return isinstance(event, BPEvent) and re.match(r"^p_\d+_no_more_cards$", event.name) is not None

@bp.thread
def strategy_block_super_taki_during_regular_taki(index):

    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))
    logger.debug(f"[STRATEGY_BLOCK_SUPER_TAKI] Player {index}: Game started! Beginning play with Super TAKI blocking strategy")

    closed_taki_event = BPEvent(f"p_{index}_closed_taki", priority=15.0)
    super_taki_event = BPEvent(f"p_{index}_super_taki")
    player_index_event_set_or_no_more_cards = bp.EventSetList([all_player_index_events(index), bp.EventSet(is_no_more_cards_event)])

    while True:
        last_event = yield bp.sync(waitFor=player_index_event_set_or_no_more_cards)
        if is_taki_card_event(last_event):
            logger.debug(f"[STRATEGY_BLOCK_SUPER_TAKI] Player {index}:  Regular TAKI played, blocking Super TAKI until closed_taki")
            last_event = yield bp.sync(waitFor=closed_taki_event, block=super_taki_event)
            if last_event.name == f"p_{index}_closed_taki":
                logger.debug(f"[STRATEGY_BLOCK_SUPER_TAKI] Player {index}:  TAKI sequence closed")
        elif is_no_more_cards_event(last_event):
            logger.debug(f"[STRATEGY_BLOCK_SUPER_TAKI]: NO MORE CARDS! Game over.")
            break


@bp.thread
def block_next_turn_during_open_taki(index):
    taki_start_event_set = bp.EventSet(
        lambda e: is_any_taki_event(e) and get_player_id(e.name) == index
    )
    closed_taki_event = BPEvent(f"p_{index}_closed_taki", priority=15.0)
    done_post_action_event = BPEvent("done_post_action", priority=10.0)
    next_turn_event_set = bp.EventSet(lambda e: hasattr(e, "name") and e.name == "next_turn")

    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))

    while True:
        last_event = yield bp.sync(waitFor=bp.EventSetList([taki_start_event_set, BPEvent("end_game", priority=10.0)]))
        if last_event.name == "end_game":
            break

        logger.debug(f"[TAKI_TURN_GUARD] Player {index}: TAKI opened, blocking next_turn until done_post_action")
        last_event = yield bp.sync(
            waitFor=bp.EventSetList([closed_taki_event, BPEvent("end_game", priority=10.0)]),
            block=next_turn_event_set,
        )
        if last_event.name == "end_game":
            break
        logger.debug(f"[TAKI_TURN_GUARD] Player {index}: closed_taki observed, keeping next_turn blocked until done_post_action")
        last_event = yield bp.sync(
            waitFor=bp.EventSetList([done_post_action_event, BPEvent("end_game", priority=10.0)]),
            block=next_turn_event_set,
        )
        if last_event.name == "end_game":
            break
        logger.debug(f"[TAKI_TURN_GUARD] Player {index}: done_post_action observed, next_turn unblocked")


def extract_card_color_and_type(event: BPEvent) -> Union[tuple[str, str], tuple[None, None]]:
    """
    Extracts the color and number from a card or stop event name.

    Args:
        event (BPEvent): The event whose name encodes card or stop information.

    Returns:
        tuple[str, str]: (color, number) if the event is a card event.
        tuple[str, str]: (color, "STOP") if the event is a stop event.
        tuple[str, str]: (color, "PLUS_2") if the event is a plus_2 event.
        tuple[str, str]: ("", "CHANGE_COLOR") if the event is a change_color event.
        tuple[None, None]: (None, None) if neither card nor stop information is found.

    Example:
        - For event.name == "card_5_blue", returns ("blue", "5")
        - For event.name == "stop_red", returns ("red", "STOP")
        - For event.name == "plus_2_red", returns ("red", "PLUS_2")
        - For event.name == "change_color", returns ("", "CHANGE_COLOR")
        - For event.name == "super_taki", returns (None, "SUPER_TAKI")
        - For other event names, returns (None, None)
    """
    card_str_index = event.name.find("card")
    if card_str_index != -1:
        card_color = event.name[card_str_index + 7:]
        card_number = event.name[card_str_index + 5:card_str_index + 6]
        return card_color, card_number
    else:
        stop_str_index = event.name.find("stop")
        if stop_str_index != -1:
            card_color = event.name[stop_str_index + 5:]
            return card_color, "STOP"
        else:
            change_color_index = event.name.find("change_color") # to handle the abstract change color card
            if change_color_index != -1 and "selected_" not in event.name:
                return "", "CHANGE_COLOR"
            else:
                selected_change_color_index = event.name.find("selected_") # to handle the selected changed color
                if selected_change_color_index != -1:
                    # Extract color from patterns like "selected_red" or "selected_blue"
                    color = [c for c in COLORS if c in event.name][0] if any(c in event.name for c in COLORS) else None
                    if color in COLORS:
                        return color, "CHANGE_COLOR"
                    else:
                         # Invalid color selection - this should never happen in a correct game
                        error_msg = (f"Invalid color selection in event '{event.name}'. "
                                    f"Expected 'selected_{{color}}' where color is one of {COLORS}, "
                                    f"but extracted color was '{color}'")
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                else:
                    super_taki_index = event.name.find("super_taki")
                    if super_taki_index != -1:
                        return None, "SUPER_TAKI"
                    else:
                        taki_str_index = event.name.find("taki_")
                        if taki_str_index != -1:
                            parts = event.name.split("_")
                            color = parts[-1]
                            if color in COLORS:
                                # logger.debug(f"[DEBUG extract_card_color_and_type] Regular TAKI: {event.name} -> Color: {color}, Type: TAKI")
                                return color, "TAKI"
                        else: # card is unmatched - return None, None
                            # logger.debug(f"[DEBUG extract_card_color_and_type] card was unmatched! {event.name}")
                            return None, None





@bp.thread
def enforce_turns(num_of_players=2, starting_player=0):
    next_or_stop_or_taki_lst = [BPEvent("next_turn", priority=10.0), bp.EventSet(is_stop_card_event), bp.EventSet(is_any_taki_event)]
    next_turn_or_stop_or_taki_event_set = bp.EventSetList(next_or_stop_or_taki_lst)

    yield bp.sync(waitFor=BPEvent("start_game"))

    current_player = starting_player
    next_player = (current_player + 1) % num_of_players
    while True: # We should block the other player from playing out of turn in all the while loop.
        last_event = yield bp.sync(waitFor=next_turn_or_stop_or_taki_event_set,
                      block=all_other_player_cards_besides_special_cards(current_player))

        logger.debug(f"[ENFORCE_TURNS] Event received: {last_event.name}")

        if last_event.name.startswith("next_turn"): # 🔍 DEBUG: Turn change
            logger.debug(f"[ENFORCE_TURNS] Turn change: Player {current_player} -> Player {next_player}")
            current_player = next_player
            next_player = (next_player + 1) % num_of_players

        if last_event.name.startswith(f"p_{current_player}_stop"): # stop_card
            next_player = (next_player + 1) % num_of_players
            logger.debug(f"[ENFORCE_TURNS] Stop card played by Player {current_player}, next player is: {next_player}")
            yield bp.sync(
                request=BPEvent("done_post_action", priority=10.0),
                block=general_player_event_set,
            )

        if is_any_taki_event(last_event):# Super TAKI or TAKI played
            taki_type = "Regular TAKI" if is_taki_card_event(last_event) else "Super TAKI"
            closed_taki_event = BPEvent(f"p_{current_player}_closed_taki", priority=15.0)
            logger.debug(f"[ENFORCE_TURNS] {taki_type} by Player {current_player}, waiting for closed_taki")
            yield bp.sync(
                waitFor=closed_taki_event,
                block=all_other_player_cards_besides_special_cards(current_player),
            )
            logger.debug(f"[ENFORCE_TURNS] closed_taki received for {taki_type}, requesting done_post_action")
            yield bp.sync(
                request=BPEvent("done_post_action", priority=10.0),
                block=general_player_event_set,
            )
            logger.debug(f"[ENFORCE_TURNS] done_post_action completed for {taki_type}")

def get_taki_mode_color(last_event, card_color):

    # If it's a regular Taki, the color is determined by the card itself.
    # Note that the TAKI color is relevant when TAKI is played on top of another TAKI (TAKI,"yellow") on top of (TAKI,"green").
    # If it's Super Taki, it inherits the previous color (which is already in card_color).
    if is_taki_card_event(last_event):
        card_color, card_type = extract_card_color_and_type(last_event)
        logger.debug(f"{'=' * 60}")
        logger.debug(f"[ENFORCE_RULES] Regular TAKI detected: {last_event.name}")
        logger.debug(f"[ENFORCE_RULES] Color determined by TAKI card: {card_color}")
        logger.debug(f"[ENFORCE_RULES] Blocking all non-{card_color} cards")
        logger.debug(f"{'=' * 60}")
    else:
        logger.debug(f"{'=' * 60}")
        logger.debug(f"[ENFORCE_RULES] Super TAKI detected: {last_event.name}")
        logger.debug(f"[ENFORCE_RULES] Color inherited from previous card: {card_color}")
        logger.debug(f"[ENFORCE_RULES] Blocking all non-{card_color} cards")
        logger.debug(f"{'=' * 60}")

    return card_color


@bp.thread
def enforce_card_placement_rules():
    yield bp.sync(waitFor=BPEvent("deal_leading_card", priority=10.0))
    last_event = yield bp.sync(waitFor=leading_card_event_set)
    yield bp.sync(waitFor=BPEvent("finished_leading_card", priority=10.0))
    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))
    card_color, card_type = extract_card_color_and_type(event=last_event)
    different_colors_or_types_event_set = bp.EventSetsDifference(all_player_events(),
                                                                 init_selected_color_or_type_event_set(card_color,
                                                                                                       card_type))
    last_event = yield bp.sync(waitFor=general_player_event_set, block=different_colors_or_types_event_set)

    while True:
        if is_regular_card_event(last_event):
            card_color, card_type = extract_card_color_and_type(event=last_event)
            different_colors_or_types_event_set = bp.EventSetsDifference(all_player_events(),
                                                                         init_selected_color_or_type_event_set(
                                                                             card_color, card_type))

        elif is_change_color_event(last_event):
            selected_color_events = [BPEvent(f"selected_{c}", priority=5.0) for c in COLORS]
            selected_color_event = yield bp.sync(waitFor=selected_color_events)
            card_color, _ = extract_card_color_and_type(event=selected_color_event)
            different_colors_or_types_event_set = create_block_set_color_only(card_color)
            yield bp.sync(
                request=BPEvent("done_post_action", priority=10.0),
                block=general_player_event_set,
            )

        elif is_stop_card_event(last_event):
            card_color, card_type = extract_card_color_and_type(event=last_event)
            logger.debug(f"[ENFORCE_RULES] Stop card played: updating rules to match color={card_color} OR type={card_type}")
            different_colors_or_types_event_set = bp.EventSetsDifference(
                all_player_events(),
                init_selected_color_or_type_event_set(card_color, card_type)
            )
            # Note: We do NOT request done_post_action here.
            # The 'enforce_turns' threads handle the game logic (skipping/drawing)
            # and they will request done_post_action. We just updated the blocking set.

        elif is_any_taki_event(last_event):

            logger.debug(f"{'=' * 60}")
            logger.debug(f"[ENFORCE_RULES] ENTER TAKI MODE, last_event={last_event.name}")
            logger.debug(f"[ENFORCE_RULES] Previous placement color={card_color}")
            logger.debug(f"{'=' * 60}")

            _, taki_start_type = extract_card_color_and_type(last_event) # We only need the type to track last_taki_card_type

            card_color = get_taki_mode_color(last_event, card_color) # Get the color for the TAKI mode
            strict_color_block = create_taki_color_block(card_color)

            last_taki_card_color = card_color
            last_taki_card_type = taki_start_type

            taki_sequence_cards = []

            taki_wait_events = bp.EventSetList([general_player_event_set, BPEvent("done_post_action", priority=17.5)])

            while True:
                # Note: we do NOT handle `closed_taki` here.
                # The TAKI sequence is considered finished when `done_post_action`
                # (requested by `enforce_turns`) occurs. This keeps turn lifecycle
                # centralized in `enforce_turns`, and this b-thread only enforces
                # placement rules and tracks the last TAKI card.
                logger.debug(f"[ENFORCE_RULES] Waiting for card (must be {card_color}) or done_post_action.")

                taki_event = yield bp.sync(waitFor=taki_wait_events, block=strict_color_block)

                logger.debug(f"[ENFORCE_RULES] Event received: {taki_event.name}")

                # Check if TAKI sequence ended
                if taki_event.name == "done_post_action":
                    logger.debug(f"{'=' * 60}")
                    logger.debug(f"[ENFORCE_RULES] TAKI sequence ended")
                    logger.debug(f"[ENFORCE_RULES] Cards played in sequence: {taki_sequence_cards}")
                    logger.debug(f"[ENFORCE_RULES] Last card color: {last_taki_card_color}, type: {last_taki_card_type}")
                    logger.debug(f"{'=' * 60}")
                    break
                
                # _closed_taki may appear before done_post_action; ignore it so it doesn't trigger warnings.
                if taki_event.name.endswith("_closed_taki"):
                    logger.debug("[ENFORCE_RULES] closed_taki received; ignoring for last-card tracking.")
                    continue

                # Update tracking with each card played during TAKI
                if is_super_taki_event(taki_event):
                    taki_sequence_cards.append(taki_event.name)
                    # Color remains unchanged for Super TAKI
                    _, last_taki_card_type = extract_card_color_and_type(taki_event)
                    logger.debug(
                        f"[ENFORCE_RULES] SuperTAKI Card accepted during TAKI: {taki_event.name} "
                        f"(color={last_taki_card_color}, type={last_taki_card_type})"
                    )
                elif is_taki_card_event(taki_event):
                    taki_sequence_cards.append(taki_event.name)
                    last_taki_card_color, last_taki_card_type = extract_card_color_and_type(taki_event)
                    logger.debug(
                        f"[ENFORCE_RULES] TAKI Card accepted during TAKI: {taki_event.name} "
                        f"(color={last_taki_card_color}, type={last_taki_card_type})"
                    )
                elif is_regular_card_event(taki_event) or is_change_color_event(taki_event) or is_stop_card_event(taki_event):
                    taki_sequence_cards.append(taki_event.name)
                    last_taki_card_color, last_taki_card_type = extract_card_color_and_type(taki_event)
                    logger.debug(
                        f"[ENFORCE_RULES] Card accepted during TAKI: {taki_event.name} "
                        f"(color={last_taki_card_color}, type={last_taki_card_type})"
                    )
                else:
                    logger.info( # Catch untracked cards!
                        f"\n[ENFORCE_RULES] ⚠️ WARNING: Event '{taki_event.name}' was allowed in TAKI sequence but NOT TRACKED!")
                    logger.info(f"[ENFORCE_RULES] The 'last_card' state was NOT updated. Next player might face wrong rules.\n")

            # Update placement rules based on the last card from the TAKI sequence
            card_color, card_type = last_taki_card_color, last_taki_card_type
            different_colors_or_types_event_set = bp.EventSetsDifference(all_player_events(),
                                                                         init_selected_color_or_type_event_set(
                                                                             card_color, card_type))
            logger.debug(f"[ENFORCE_RULES] Post-TAKI placement rules: must match color={card_color} OR type={card_type}")

        last_event = yield bp.sync(waitFor=general_player_event_set, block=different_colors_or_types_event_set)


@bp.thread
def identify_livelock():
    yield bp.sync(waitFor=BPEvent("start_game", priority=10.0))
    livelock_event = BPEvent("livelock", priority=5.0)
    game_draw_event = BPEvent("game_draw", priority=5.0)
    end_game_event = BPEvent("end_game", priority=10.0)

    move_count = 0
    while True:
        last_event = yield bp.sync(waitFor=bp.All())
        if last_event.name == "end_game":
            break
        
        if last_event.name.startswith(("p_0_", "p_1_")):
            move_count += 1
        
        if move_count > 1000:
            yield bp.sync(request=livelock_event, block=bp.AllExcept(livelock_event))
            yield bp.sync(request=game_draw_event, block=bp.AllExcept(game_draw_event))
            logger.debug(f"[Livelock Verifier] livelock detected, blocking execution. {move_count}")
            # Initiatiate a deadlock event to terminate the game
            yield bp.sync(block=bp.All())


@bp.thread
def identify_deadlock():
    last_event = yield bp.sync(request=BPEvent("deadlock"), waitFor=BPEvent("end_game", priority=10.0))
    if last_event.name.startswith("deadlock"):
        assert False
    else:
        assert True


@bp.thread
def verify_turn_alternation():
    yield bp.sync(waitFor=BPEvent("start_game"))

    active_player_id = None  # ID of the player currently allowed to act
    turn_boundary_cleared = True  # Has 'next_turn' been seen since the last turn began?

    while True:
        event = yield bp.sync(waitFor=bp.EventSet(lambda e: True))

        if event.name == "end_game":
            break

        if event.name == "next_turn":
            if turn_boundary_cleared and active_player_id is None:
                logger.debug("verify_turn_alternation: duplicate next_turn (noop)")
            # Ready for a new turn
            turn_boundary_cleared = True
            active_player_id = None
            continue

        # Get the player who triggered the event
        event_player_id = get_player_id(event.name)
        if event_player_id is None:
            continue

        # --- Check Turn Logic ---

        # 1. Start of a turn (active_player_id is None)
        if active_player_id is None:
            # Check for illegal player switch (e.g., P0 acts, then P1 acts immediately without next_turn)
            # This check is complex in the original, relying on saw_next_turn
            if not turn_boundary_cleared:  # This case should ideally not be reachable if logic is sound elsewhere
                raise AssertionError(
                    f"[Verifier] Player {event_player_id} acted before 'next_turn': {event}"
                )

            # Establish the active player for this turn
            active_player_id = event_player_id
            turn_boundary_cleared = False
            continue

        # 2. Mid-turn action (active_player_id is defined)
        if event_player_id != active_player_id:
            # Another player acted without a 'next_turn' in between → violation
            raise AssertionError(
                f"[Verifier] Player {event_player_id} acted during Player "
                f"{active_player_id}'s turn without 'next_turn'. Event={event}, "
                f"turn_boundary_cleared={turn_boundary_cleared}"
            )
        # else: same active_player_id again within the same turn → OK (multi-action turn)



@bp.thread
def test_consecutive_regular_cards_matching():
    card_event_1 = yield bp.sync(waitFor=played_regular_cards_event_set)
    while True:
        wait_events = bp.EventSetList([
            played_regular_cards_event_set,
            bp.EventSet(is_action_card_event),
        ])
        card_event_2 = yield bp.sync(waitFor=wait_events)
        if is_regular_card_event(card_event_2):
            card_1_color, card_1_type = extract_card_color_and_type(card_event_1)
            card_2_color, card_2_type = extract_card_color_and_type(card_event_2)
            assert card_1_color == card_2_color or card_1_type == card_2_type, f"Illegal card placement: {card_event_1.name} followed by {card_event_2.name}"
            card_event_1 = card_event_2
        else:
            # Any action card can change the effective top-card semantics, so
            # restart the regular-card chain from the next regular placement.
            card_event_1 = yield bp.sync(waitFor=played_regular_cards_event_set)


@bp.thread
def test_first_card_matches_leading_card():
    yield bp.sync(waitFor=BPEvent("deal_leading_card"))
    leading_event = yield bp.sync(waitFor=leading_card_event_set)
    leading_color, leading_type = extract_card_color_and_type(leading_event)
    yield bp.sync(waitFor=BPEvent("start_game"))

    first_event = yield bp.sync(waitFor=general_player_event_set)
    # We only validate the first card if it's a regular card - 
    # if the first event is a special card (like stop or change_color), 
    # we don't enforce matching rules on it.
    if not is_regular_card_event(first_event):
        return

    first_color, first_type = extract_card_color_and_type(first_event)
    assert first_color == leading_color or first_type == leading_type, \
        f"First card {first_event.name} doesn't match leading card {leading_event.name}"


@bp.thread
def test_no_game_events_before_start():
    event = yield bp.sync(waitFor=bp.EventSetList([general_player_event_set, BPEvent("start_game")]))
    assert event.name == "start_game", \
        f"[test_no_game_events_before_start] X FAILED: game event fired before start_game: {event.name}"


@bp.thread
def test_no_game_events_after_end():
    yield bp.sync(waitFor=BPEvent("end_game"))
    event = yield bp.sync(waitFor=general_player_event_set)
    assert False, f"[test_no_game_events_after_end] X FAILED: game event fired after end_game: {event.name}"


@bp.thread
def test_no_more_cards_before_end_game():
    event = yield bp.sync(waitFor=bp.EventSetList([any_player_no_more_cards, BPEvent("end_game")]))
    assert "no_more_cards" in event.name, \
        f"[test_no_more_cards_before_end_game] X FAILED: end_game fired without no_more_cards"


def setup_logger():

    # Console Handler
    c_handler = logging.StreamHandler()
    c_handler.stream.reconfigure(encoding='utf-8')  # For console
    c_handler.setLevel(LOG_LEVEL)
    c_format = logging.Formatter('%(asctime)s.%(msecs)03d - %(message)s', datefmt='%H:%M:%S')
    c_handler.setFormatter(c_format)

    # File Handler
    f_handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    f_handler.setLevel(LOG_LEVEL)
    f_format = logging.Formatter('%(asctime)s.%(msecs)03d - %(message)s', datefmt='%H:%M:%S')
    f_handler.setFormatter(f_format)

    if not logger.handlers:
        logger.addHandler(c_handler)
        logger.addHandler(f_handler)
        logger.debug(f"--> Logger configured. Saving to: {log_filename}")


def init_b_program(starting_player=1):
    enable_tests = True

    game_threads = [
        game_manager(),
        deal_cards(2, NUM_OF_CARDS, starting_player),
        player_behavior(0, NUM_OF_CARDS),
        player_behavior_external(1, NUM_OF_CARDS, starting_player, NUM_OF_PLAYERS, PythonAgent(seed=SEED)),
        basic_strategy_taki(0, NUM_OF_CARDS),
        block_next_turn_during_open_taki(0),
        block_next_turn_during_open_taki(1),
        enforce_turns(2, starting_player),
        enforce_card_placement_rules(),
        identify_deadlock(),
        identify_livelock(),
        verify_turn_alternation(),
    ]

    test_threads = []
    if enable_tests:
        test_threads = [
            test_consecutive_regular_cards_matching(),
            test_first_card_matches_leading_card(),
            test_no_game_events_before_start(),
            test_no_game_events_after_end(),
            test_no_more_cards_before_end_game(),
        ]
        logger.info(f"[INIT] Regression tests enabled: {len(test_threads)} test(s)")

    b_program = bp.BProgram(
        bthreads=game_threads + test_threads,
        event_selection_strategy=EventPrioritySelectionStrategy(),
        listener=LogBProgramRunnerListener(logger=logger),
    )

    return b_program

def build_b_program(
    bthreads,
    event_selection_strategy,
    listener,
):
    return bp.BProgram(
        bthreads=bthreads,
        event_selection_strategy=event_selection_strategy,
        listener=listener,
    )


def run_bp_program(b_program, configure_logger: bool = True):
    if configure_logger:
        setup_logger()
        logger.info("Starting Taki Game BProgram Execution")
    b_program.run()


def regular_execution_of_bp_program():
    b_program = init_b_program()
    run_bp_program(b_program, configure_logger=True)


def verify_with_dfs():
    # initialize DFS verifier with the b-program generator and specify max_trace_length
    ver = DFSBProgramVerifier(init_b_program, max_trace_length=100)
    ok, counter_example = ver.verify()

    # check the verification results and print accordingly
    if ok:
        print("OK")
    else:
        print("Violation Found")
        print("Counterexample:")
        print(counter_example)


if __name__ == "__main__":
    regular_execution_of_bp_program()
    # verify_with_dfs()
