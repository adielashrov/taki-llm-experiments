"""
BP-Taki Game Simulation Module

This module provides functionality to run multiple simulations of the Taki game
with different random seeds and track statistics about player wins.
"""

import bppy as bp
import random
import logging
import math
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass, field
import json
from bppy.model.event_selection.event_priority_selection_strategy import EventPrioritySelectionStrategy

# Import from bp_taki
import bp_taki
from bp_taki import (
    game_manager,
    deal_cards,
    player_behavior,
    player_behavior_external,
    basic_strategy_taki,
    basic_strategy_taki_and_super_taki,
    block_next_turn_during_open_taki,
    strategy_block_super_taki_during_regular_taki,
    change_color_strategy,
    most_popular_color_selection_strategy,
    prefer_stop_over_regular_cards_strategy,
    enforce_turns,
    enforce_card_placement_rules,
    identify_deadlock,
    identify_livelock,
    verify_turn_alternation,
    NUM_OF_CARDS,
    NUM_OF_PLAYERS,
    COLORS,
)
from python_taki_api.python_agent import PythonAgent


@dataclass
class PlayerStrategyConfig:
    """Configuration for a single player's BP strategies."""
    base_strategy: str = "basic"  # "basic", "taki", "taki_and_super_taki"
    block_super_taki: bool = False
    change_color: bool = False
    most_popular_color: bool = False
    prefer_stop: bool = False

    def label(self) -> str:
        parts = [self.base_strategy]
        if self.block_super_taki:
            parts.append("block_super_taki")
        if self.change_color:
            parts.append("change_color")
        if self.most_popular_color:
            parts.append("most_popular_color")
        if self.prefer_stop:
            parts.append("prefer_stop")
        return "+".join(parts)


@dataclass
class GameResult:
    """Represents the result of a single game."""
    game_number: int
    seed: int
    winner: Optional[int]  # 0 or 1, None for draws/deadlocks
    event_count: int
    starting_player: int = 0  # Which player went first (0 or 1)
    duration_seconds: float = 0.0
    ended_in_deadlock: bool = False
    ended_in_draw: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'game_number': self.game_number,
            'seed': self.seed,
            'winner': self.winner,
            'event_count': self.event_count,
            'starting_player': self.starting_player,
            'duration_seconds': self.duration_seconds,
            'ended_in_deadlock': self.ended_in_deadlock,
            'ended_in_draw': self.ended_in_draw,
        }


@dataclass
class SimulationStats:
    """Tracks statistics across multiple games."""
    total_attempted: int = 0
    total_completed: int = 0
    player_0_wins: int = 0
    player_1_wins: int = 0
    draws: int = 0
    deadlocks: int = 0
    errors: int = 0
    average_events_per_game: float = 0.0
    results: List[GameResult] = field(default_factory=list)
    
    def add_result(self, result: GameResult):
        """Add a game result and update statistics."""
        self.results.append(result)
        self.total_attempted += 1
        self.total_completed += 1
        
        if result.ended_in_deadlock:
            self.deadlocks += 1
        if result.ended_in_draw:
            self.draws += 1
        
        if result.winner == 0:
            self.player_0_wins += 1
        elif result.winner == 1:
            self.player_1_wins += 1
        
        # Update average events
        total_events = sum(r.event_count for r in self.results)
        self.average_events_per_game = total_events / self.total_completed if self.total_completed > 0 else 0
    
    def record_error(self):
        """Record a game that ended in error."""
        self.total_attempted += 1
        self.errors += 1
    
    def win_rate(self, player: int) -> float:
        denom = self.total_completed
        if denom == 0:
            return 0.0
        wins = self.player_0_wins if player == 0 else self.player_1_wins
        return wins / denom * 100
    
    def starting_player_advantage(self) -> Dict[str, any]:
        """
        Calculate statistics about first-player advantage.
        
        Returns
        -------
        dict
            Statistics about starting player wins, including:
            - 'starting_player_0_count': Games where player 0 started
            - 'starting_player_1_count': Games where player 1 started
            - 'wins_when_starting': How often the starting player won
            - 'starter_win_rate': Percentage of games won by whoever started
        """
        if not self.results:
            return {
                'starting_player_0_count': 0,
                'starting_player_1_count': 0,
                'wins_when_starting': 0,
                'starter_win_rate': 0.0
            }
        
        p0_started = sum(1 for r in self.results if r.starting_player == 0)
        p1_started = sum(1 for r in self.results if r.starting_player == 1)
        
        # Count how many times the starting player won
        starter_wins = sum(1 for r in self.results if r.winner == r.starting_player)
        starter_win_rate = (starter_wins / self.total_completed * 100) if self.total_completed else 0.0
        
        return {
            'starting_player_0_count': p0_started,
            'starting_player_1_count': p1_started,
            'wins_when_starting': starter_wins,
            'starter_win_rate': starter_win_rate
        }

    
    @staticmethod
    def wilson_ci(successes: int, trials: int, z: float = 1.96) -> Tuple[float, float]:
        if trials == 0:
            return (0.0, 0.0)

        p_hat = successes / trials
        denom = 1 + (z**2) / trials
        center = (p_hat + (z**2) / (2 * trials)) / denom
        margin = (
            z * math.sqrt((p_hat * (1 - p_hat) / trials) + (z**2) / (4 * trials**2))
        ) / denom
        return (center - margin, center + margin)


    def player_0_2x2_table(self) -> dict:
        """
        Return a 2x2 contingency table for Player 0:
        
            ┌────────────────────┬──────────┬──────────────┐
            │                    │ P0 Wins  │ P0 Not Win   │
            ├────────────────────┼──────────┼──────────────┤
            │ P0 started         │    A     │      B       │
            │ P0 started second  │    C     │      D       │
            └────────────────────┴──────────┴──────────────┘
        """
        A = B = C = D = 0

        for r in self.results:
            if r.starting_player == 0:  # P0 started
                if r.winner == 0:
                    A += 1
                else:
                    B += 1
            elif r.starting_player == 1:  # P0 second
                if r.winner == 0:
                    C += 1
                else:
                    D += 1

        return {
            "p0_started_p0_wins": A,
            "p0_started_p0_not_win": B,
            "p0_second_p0_wins": C,
            "p0_second_p0_not_win": D,
            "row_totals": {
                "p0_started": A + B,
                "p0_second": C + D,
            },
            "col_totals": {
                "p0_wins": A + C,
                "p0_not_win": B + D,
            }
        }


    def player_1_2x2_table(self) -> dict:
        """
        Return a 2x2 contingency table for Player 1:
        
            ┌────────────────────┬──────────┬──────────────┐
            │                    │ P1 Wins  │ P1 Not Win   │
            ├────────────────────┼──────────┼──────────────┤
            │ P1 started         │    A     │      B       │
            │ P1 started second  │    C     │      D       │
            └────────────────────┴──────────┴──────────────┘
        """
        A = B = C = D = 0

        for r in self.results:
            if r.starting_player == 1:  # P1 started
                if r.winner == 1:
                    A += 1
                else:
                    B += 1
            elif r.starting_player == 0:  # P1 second
                if r.winner == 1:
                    C += 1
                else:
                    D += 1

        return {
            "p1_started_p1_wins": A,
            "p1_started_p1_not_win": B,
            "p1_second_p1_wins": C,
            "p1_second_p1_not_win": D,
            "row_totals": {
                "p1_started": A + B,
                "p1_second": C + D,
            },
            "col_totals": {
                "p1_wins": A + C,
                "p1_not_win": B + D,
            }
        }

    
    def player_0_ci(self):
        tbl = self.player_0_2x2_table()

        A = tbl["p0_started_p0_wins"]
        B = tbl["p0_started_p0_not_win"]
        C = tbl["p0_second_p0_wins"]
        D = tbl["p0_second_p0_not_win"]

        ci_start = SimulationStats.wilson_ci(A, A + B)
        ci_second = SimulationStats.wilson_ci(C, C + D)


        return {
            "start_win_rate": A / (A + B) if (A + B) else 0.0,
            "start_ci": ci_start,
            "second_win_rate": C / (C + D) if (C + D) else 0.0,
            "second_ci": ci_second,
    }

    def player_1_ci(self):
        tbl = self.player_1_2x2_table()

        A = tbl["p1_started_p1_wins"]
        B = tbl["p1_started_p1_not_win"]
        C = tbl["p1_second_p1_wins"]
        D = tbl["p1_second_p1_not_win"]

        ci_start = SimulationStats.wilson_ci(A, A + B)
        ci_second = SimulationStats.wilson_ci(C, C + D)

        return {
            "start_win_rate": A / (A + B) if (A + B) else 0.0,
            "start_ci": ci_start,
            "second_win_rate": C / (C + D) if (C + D) else 0.0,
            "second_ci": ci_second,
        }

    def summary(self, player_0_strategy: str = None, player_1_strategy: str = None) -> str:
        """Generate a summary string of the statistics."""
        lines = [
            "=" * 60,
            "TAKI GAME SIMULATION RESULTS",
            "=" * 60,
        ]
        
        # Add strategies if provided
        if player_0_strategy is not None or player_1_strategy is not None:
            lines.extend([
                "",
                "Strategies:",
            ])
            if player_0_strategy is not None:
                lines.append(f"  Player 0: {player_0_strategy}")
            if player_1_strategy is not None:
                lines.append(f"  Player 1: {player_1_strategy}")
        
        lines.extend([
            "",
            f"Total Games Attempted: {self.total_attempted}",
            f"Completed: {self.total_completed} | Errors/Incomplete: {self.errors}",
            "",
            "Player 0 Wins: {:4d} ({:5.1f}%)".format(
                self.player_0_wins, self.win_rate(0)
            ),
            "Player 1 Wins: {:4d} ({:5.1f}%)".format(
                self.player_1_wins, self.win_rate(1)
            ),
            "",
            f"Draws: {self.draws} | Deadlocks: {self.deadlocks} | Errors: {self.errors}",
            "",
            f"Average Events per Game: {self.average_events_per_game:.1f}",
        ])
        
        # Add starting player advantage analysis if games have varied starting players
        adv = self.starting_player_advantage()
        if adv['starting_player_0_count'] > 0 and adv['starting_player_1_count'] > 0:
            lines.extend([
                "",
                "Starting Player Analysis:",
                f"  Games where P0 started: {adv['starting_player_0_count']}",
                f"  Games where P1 started: {adv['starting_player_1_count']}",
                f"  Starting player won: {adv['wins_when_starting']}/{self.total_completed} ({adv['starter_win_rate']:.1f}%)",
            ])
        elif adv['starting_player_0_count'] > 0:
            lines.extend([
                "",
                "[!] Note: Player 0 started ALL games (first-player advantage present!)",
            ])

        tbl = self.player_0_2x2_table()

        lines.extend([
            "",
            "Player 0 — Starting Position vs Outcome (2x2):",
            "",
            "                 |  P0 Wins | P0 Not Win",
            "-----------------+----------+------------",
            f"P0 started       | {tbl['p0_started_p0_wins']:8d} | {tbl['p0_started_p0_not_win']:10d}",
            f"P0 started second| {tbl['p0_second_p0_wins']:8d} | {tbl['p0_second_p0_not_win']:10d}",
        ])

        tbl = self.player_1_2x2_table()

        lines.extend([
            "",
            "Player 1 — Starting Position vs Outcome (2x2):",
            "",
            "                 |  P1 Wins | P1 Not Win",
            "-----------------+----------+------------",
            f"P1 started       | {tbl['p1_started_p1_wins']:8d} | {tbl['p1_started_p1_not_win']:10d}",
            f"P1 started second| {tbl['p1_second_p1_wins']:8d} | {tbl['p1_second_p1_not_win']:10d}",
        ])
        
        p0_ci = self.player_0_ci()
        lines.extend([
            "",
            "Player 0 — Win Rates with 95% CI:",
            f"  When starting: {p0_ci['start_win_rate']*100:5.1f}% "
            f"[{p0_ci['start_ci'][0]*100:5.1f}%, {p0_ci['start_ci'][1]*100:5.1f}%]",
            f"  When second:  {p0_ci['second_win_rate']*100:5.1f}% "
            f"[{p0_ci['second_ci'][0]*100:5.1f}%, {p0_ci['second_ci'][1]*100:5.1f}%]",
        ])

        p1_ci = self.player_1_ci()
        lines.extend([
            "",
            "Player 1 — Win Rates with 95% CI:",
            f"  When starting: {p1_ci['start_win_rate']*100:5.1f}% "
            f"[{p1_ci['start_ci'][0]*100:5.1f}%, {p1_ci['start_ci'][1]*100:5.1f}%]",
            f"  When second:  {p1_ci['second_win_rate']*100:5.1f}% "
            f"[{p1_ci['second_ci'][0]*100:5.1f}%, {p1_ci['second_ci'][1]*100:5.1f}%]",
        ])

        lines.append("=" * 60)
        return "\n".join(lines)
    

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'total_completed': self.total_completed,
            'total_attempted': self.total_attempted,
            'player_0_wins': self.player_0_wins,
            'player_1_wins': self.player_1_wins,
            'player_0_win_rate': self.win_rate(0),
            'player_1_win_rate': self.win_rate(1),
            'errors': self.errors,
            'draws': self.draws,
            'deadlocks': self.deadlocks,
            'average_events_per_game': self.average_events_per_game,
            'starting_player_advantage': self.starting_player_advantage(),
            'results': [r.to_dict() for r in self.results]
        }
    
    def test_results(self):
        assert self.total_attempted == self.total_completed + self.errors, (
            f"Inconsistent stats: attempted={self.total_attempted}, "
            f"completed={self.total_completed}, errors={self.errors}"
        )


class SimulationListener:
    """Listener that tracks game events and determines the winner."""
    
    def __init__(self):
        self.events = []
        self.winner = None
        self.ended_in_deadlock = False
        self.ended_in_draw = False
        
    def starting(self, b_program): pass
    def started(self, b_program): pass
    def super_step_done(self, b_program): pass
    def ended(self, b_program): pass
    def assertion_failed(self, b_program): pass
    def halted(self, b_program): pass
    
    def event_selected(self, b_program, event):
        """Record each selected event."""
        self.events.append(event.name)
        
        # Check if this is a winning event
        if event.name == "p_0_no_more_cards":
            self.winner = 0
        elif event.name == "p_1_no_more_cards":
            self.winner = 1
        elif event.name == "deadlock":
            self.ended_in_deadlock = True
        elif event.name == "game_draw":
            self.ended_in_draw = True
    
    def get_winner(self) -> Optional[int]:
        """Return the winner (0 or 1) or None if no winner yet."""
        return self.winner
    
    def get_deadlock(self) -> bool:
        """Return True if the game ended in deadlock."""
        return self.ended_in_deadlock
    
    def get_draw(self) -> bool:
        """Return True if the game ended in a draw."""
        return self.ended_in_draw
    
    def get_event_count(self) -> int:
        """Return the total number of events that occurred."""
        return len(self.events)


def build_game_schedule(
    num_games: int,
    start_seed: int = 0,
    starting_player: int = -1,
    balanced_starting_players: bool = False,
    mirrored_starting_players: bool = False,
) -> List[Tuple[int, int]]:
    """
    Build a deterministic schedule of ``(seed, starting_player)`` pairs.

    Parameters
    ----------
    num_games : int
        Number of scheduled entries to create. When ``mirrored_starting_players``
        is enabled, this is the number of unique seeds and the returned schedule
        contains ``2 * num_games`` entries.
    start_seed : int
        First seed in the schedule.
    starting_player : int
        Fixed starting player (0 or 1), or -1 to let the scheduler decide.
    balanced_starting_players : bool
        If True, distribute starts as evenly as possible between players while
        still using each seed exactly once.
    mirrored_starting_players : bool
        If True, run each seed twice: once with player 0 starting and once with
        player 1 starting.
    """
    if num_games < 1:
        raise ValueError("num_games must be at least 1")

    if starting_player not in (-1, 0, 1):
        raise ValueError("starting_player must be 0, 1, or -1")

    if mirrored_starting_players and balanced_starting_players:
        raise ValueError("mirrored and balanced starting-player modes are mutually exclusive")

    if starting_player != -1 and (balanced_starting_players or mirrored_starting_players):
        raise ValueError("balanced/mirrored scheduling requires starting_player=-1")

    schedule: List[Tuple[int, int]] = []

    if mirrored_starting_players:
        for i in range(num_games):
            seed = start_seed + i
            schedule.append((seed, 0))
            schedule.append((seed, 1))
        return schedule

    if balanced_starting_players:
        schedule_rng = random.Random(start_seed)
        starters = [0, 1] * (num_games // 2)
        if num_games % 2:
            starters.append(schedule_rng.randint(0, 1))

        schedule_rng.shuffle(starters)

        for i, scheduled_starting_player in enumerate(starters):
            schedule.append((start_seed + i, scheduled_starting_player))
        return schedule

    for i in range(num_games):
        schedule.append((start_seed + i, starting_player))

    return schedule


def _apply_strategy_config(bthreads: list, index: int, config: PlayerStrategyConfig, num_cards: int):
    """Append strategy b-threads for one player based on their config."""
    if config.base_strategy == "taki":
        bthreads.append(basic_strategy_taki(index, num_cards))
    elif config.base_strategy == "taki_and_super_taki":
        bthreads.append(basic_strategy_taki_and_super_taki(index, num_cards))
    elif config.base_strategy != "basic":
        raise ValueError(f"Unknown base_strategy for player {index}: {config.base_strategy}")

    if config.block_super_taki:
        bthreads.append(strategy_block_super_taki_during_regular_taki(index))
    if config.change_color:
        bthreads.append(change_color_strategy(index, num_cards))
    if config.most_popular_color:
        bthreads.append(most_popular_color_selection_strategy(index, num_cards))
    if config.prefer_stop:
        for color in COLORS:
            bthreads.append(prefer_stop_over_regular_cards_strategy(index, color))


def create_simulation_bprogram(
    seed: int,
    listener: SimulationListener,
    num_cards: int = NUM_OF_CARDS,
    starting_player: int = 0,
    player_0_config: PlayerStrategyConfig = None,
    player_1_config: PlayerStrategyConfig = None,
) -> Tuple[bp.BProgram, int]:
    """
    Create a BProgram configured for simulation.

    Parameters
    ----------
    seed : int
        Random seed for this game
    listener : SimulationListener
        Listener to track game events
    num_cards : int
        Number of cards to deal to each player
    starting_player : int
        Which player goes first (0 or 1). Use -1 for random selection based on seed.
        Cards are dealt to the starting player first to ensure fairness.
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).
    player_1_config : PlayerStrategyConfig
        Strategy configuration for player 1. Defaults to PlayerStrategyConfig() (basic).

    Returns
    -------
    tuple[bp.BProgram, int]
        Configured behavioral program and the actual starting player.

    Notes
    -----
    The starting_player parameter controls both:
    1. Which player receives cards first from the deck (via deal_cards)
    2. Which player takes the first turn (via enforce_turns)

    This ensures complete symmetry when starting_player varies.
    """
    if player_0_config is None:
        player_0_config = PlayerStrategyConfig()
    if player_1_config is None:
        player_1_config = PlayerStrategyConfig()

    random.seed(seed)

    if starting_player == -1:
        actual_starting_player = random.randint(0, 1)
    else:
        actual_starting_player = starting_player

    bthreads = [
        game_manager(),
        deal_cards(2, num_cards, actual_starting_player),
        player_behavior(0, num_cards),
        player_behavior(1, num_cards),
        block_next_turn_during_open_taki(0),
        block_next_turn_during_open_taki(1),
        enforce_turns(2, actual_starting_player),
        enforce_card_placement_rules(),
        identify_deadlock(),
        identify_livelock(),
        verify_turn_alternation(),
    ]

    _apply_strategy_config(bthreads, 0, player_0_config, num_cards)
    _apply_strategy_config(bthreads, 1, player_1_config, num_cards)

    b_program = bp.BProgram(
        bthreads=bthreads,
        event_selection_strategy=EventPrioritySelectionStrategy(),
        listener=listener,
    )

    return b_program, actual_starting_player


def create_simulation_bprogram_basic_vs_external(
    seed: int,
    listener: SimulationListener,
    num_cards: int = NUM_OF_CARDS,
    starting_player: int = -1,
    player_0_config: PlayerStrategyConfig = None,
) -> Tuple[bp.BProgram, int]:
    """
    Create a BProgram with player 0 using BP strategies and player 1
    using the external Python agent (player_behavior_external).

    Parameters
    ----------
    seed : int
        Random seed for card dealing and the external agent's PythonAgent.
    listener : SimulationListener
        Listener to track game events.
    num_cards : int
        Number of cards to deal to each player.
    starting_player : int
        Which player goes first (0 or 1). Use -1 for random selection based on seed.
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).

    Returns
    -------
    tuple[bp.BProgram, int]
        Configured behavioral program and the actual starting player.
    """
    if player_0_config is None:
        player_0_config = PlayerStrategyConfig()

    random.seed(seed)

    if starting_player == -1:
        actual_starting_player = random.randint(0, 1)
    else:
        actual_starting_player = starting_player

    # Propagate seed to the external agent (reads bp_taki.SEED at b-thread start)
    bp_taki.SEED = seed

    bthreads = [
        game_manager(),
        deal_cards(NUM_OF_PLAYERS, num_cards, actual_starting_player),
        player_behavior(0, num_cards),
        player_behavior_external(1, num_cards, actual_starting_player, NUM_OF_PLAYERS),
        block_next_turn_during_open_taki(0),
        # block_next_turn_during_open_taki(1), not sure if this guard is necassery
        enforce_turns(NUM_OF_PLAYERS, actual_starting_player),
        enforce_card_placement_rules(),
        identify_deadlock(),
        identify_livelock(),
        verify_turn_alternation(),
    ]

    _apply_strategy_config(bthreads, 0, player_0_config, num_cards)

    b_program = bp.BProgram(
        bthreads=bthreads,
        event_selection_strategy=EventPrioritySelectionStrategy(),
        listener=listener,
    )

    return b_program, actual_starting_player


def run_single_game_basic_vs_external(
    game_number: int,
    seed: int,
    num_cards: int = NUM_OF_CARDS,
    player_0_config: PlayerStrategyConfig = None,
    starting_player: int = -1,
    silent: bool = True,
) -> Optional[GameResult]:
    """
    Run a single game: player 0 (BP) vs player 1 (external agent).

    Parameters
    ----------
    game_number : int
        The game number in the simulation.
    seed : int
        Random seed for reproducibility.
    num_cards : int
        Number of cards per player.
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).
    starting_player : int
        Which player goes first (0 or 1). Use -1 for random (based on seed).
    silent : bool
        If True, suppress logging output.

    Returns
    -------
    GameResult or None
        Result of the game, or None if an error occurred.
    """
    if silent:
        original_level = logging.getLogger("TakiGame").level
        logging.getLogger("TakiGame").setLevel(logging.CRITICAL)

    try:
        listener = SimulationListener()

        start_time = datetime.now()
        b_program, actual_starting_player = create_simulation_bprogram_basic_vs_external(
            seed=seed,
            listener=listener,
            num_cards=num_cards,
            starting_player=starting_player,
            player_0_config=player_0_config,
        )
        try:
            b_program.run()
        except AssertionError:
            if not (listener.get_deadlock() or listener.get_draw()):
                raise
        end_time = datetime.now()

        winner = listener.get_winner()
        ended_in_deadlock = listener.get_deadlock()
        ended_in_draw = listener.get_draw()

        if winner is None and not (ended_in_deadlock or ended_in_draw):
            print(f"Warning: Game {game_number} (seed={seed}) ended without a winner")
            return None

        if ended_in_deadlock:
            print(f"Game {game_number} (seed={seed}) ended in deadlock.")

        if ended_in_draw:
            print(f"Game {game_number} (seed={seed}) ended in a draw.")

        duration = (end_time - start_time).total_seconds()
        return GameResult(
            game_number=game_number,
            seed=seed,
            winner=winner,
            event_count=listener.get_event_count(),
            starting_player=actual_starting_player,
            duration_seconds=duration,
            ended_in_deadlock=ended_in_deadlock,
            ended_in_draw=ended_in_draw,
        )

    except Exception as e:
        print(f"Error in game {game_number} (seed={seed}): {type(e).__name__}: {e}")
        return None

    finally:
        if silent:
            logging.getLogger("TakiGame").setLevel(original_level)


def run_simulation_basic_vs_external(
    num_games: int,
    start_seed: int = 0,
    num_cards: int = NUM_OF_CARDS,
    starting_player: int = -1,
    balanced_starting_players: bool = False,
    mirrored_starting_players: bool = False,
    player_0_config: PlayerStrategyConfig = None,
    silent: bool = True,
    progress_interval: int = 10,
) -> SimulationStats:
    """
    Run multiple games of a BP player (player 0) vs external agent (player 1).

    Parameters
    ----------
    num_games : int
        Number of games to simulate. When ``mirrored_starting_players`` is
        enabled, this is the number of unique seeds and the total number of
        games played will be ``2 * num_games``.
    start_seed : int
        Starting random seed (each game increments by 1).
    num_cards : int
        Number of cards per player.
    starting_player : int
        Which player goes first (0 or 1). Use -1 to let the scheduler decide.
    balanced_starting_players : bool
        If True, assign starts as evenly as possible across the run.
    mirrored_starting_players : bool
        If True, run each seed twice: once with P0 starting and once with P1
        starting. In this mode, ``num_games`` is the number of unique seeds.
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).
    silent : bool
        If True, suppress game logging.
    progress_interval : int
        Print progress every N games.

    Returns
    -------
    SimulationStats
        Statistics about all games.
    """
    if player_0_config is None:
        player_0_config = PlayerStrategyConfig()

    schedule = build_game_schedule(
        num_games=num_games,
        start_seed=start_seed,
        starting_player=starting_player,
        balanced_starting_players=balanced_starting_players,
        mirrored_starting_players=mirrored_starting_players,
    )
    total_scheduled_games = len(schedule)

    print(f"Starting simulation of {total_scheduled_games} games (BP vs external agent)...")
    print(f"Player 0 strategy: {player_0_config.label()}")
    print(f"Player 1 strategy: external agent")
    print(f"Cards per player: {num_cards}")
    print(f"Starting seed: {start_seed}")

    if mirrored_starting_players:
        print(f"[+] Mirrored starting-player schedule enabled across {num_games} seeds.")
    elif balanced_starting_players:
        print("[+] Starting player will be balanced as evenly as possible across the run.")
    elif starting_player == -1:
        print("[+] Starting player will be randomized per game.")
    else:
        print(f"Starting player: {starting_player}")

    print("-" * 60)

    stats = SimulationStats()

    for game_number, (seed, scheduled_starting_player) in enumerate(schedule, start=1):
        result = run_single_game_basic_vs_external(
            game_number=game_number,
            seed=seed,
            num_cards=num_cards,
            player_0_config=player_0_config,
            starting_player=scheduled_starting_player,
            silent=silent,
        )

        if result is not None:
            stats.add_result(result)
        else:
            stats.record_error()

        if game_number % progress_interval == 0:
            print(f"Progress: {game_number}/{total_scheduled_games} games completed")

    stats.test_results()
    return stats


def create_simulation_bprogram_basic_vs_strategy(
    seed: int,
    listener: SimulationListener,
    num_cards: int = NUM_OF_CARDS,
    starting_player: int = -1,
    player_0_config: PlayerStrategyConfig = None,
    player_1_agent=None,
) -> Tuple[bp.BProgram, int]:
    """
    Create a BProgram with player 0 using BP strategies and player 1
    using a Python agent (defaults to PythonAgent random policy).

    Parameters
    ----------
    seed : int
        Random seed for card dealing.
    listener : SimulationListener
        Listener to track game events.
    num_cards : int
        Number of cards to deal to each player.
    starting_player : int
        Which player goes first (0 or 1). Use -1 for random selection based on seed.
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).
    player_1_agent : optional
        The Python agent for player 1. Defaults to PythonAgent(seed=seed) if None.

    Returns
    -------
    tuple[bp.BProgram, int]
        Configured behavioral program and the actual starting player.
    """
    if player_0_config is None:
        player_0_config = PlayerStrategyConfig()

    random.seed(seed)

    if starting_player == -1:
        actual_starting_player = random.randint(0, 1)
    else:
        actual_starting_player = starting_player

    if player_1_agent is None:
        player_1_agent = PythonAgent(seed=seed)

    bthreads = [
        game_manager(),
        deal_cards(NUM_OF_PLAYERS, num_cards, actual_starting_player),
        player_behavior(0, num_cards),
        player_behavior_external(1, num_cards, actual_starting_player, NUM_OF_PLAYERS, player_1_agent),
        block_next_turn_during_open_taki(0),
        enforce_turns(NUM_OF_PLAYERS, actual_starting_player),
        enforce_card_placement_rules(),
        identify_deadlock(),
        identify_livelock(),
        verify_turn_alternation(),
    ]

    _apply_strategy_config(bthreads, 0, player_0_config, num_cards)

    b_program = bp.BProgram(
        bthreads=bthreads,
        event_selection_strategy=EventPrioritySelectionStrategy(),
        listener=listener,
    )

    return b_program, actual_starting_player


def run_single_game_basic_vs_strategy(
    game_number: int,
    seed: int,
    num_cards: int = NUM_OF_CARDS,
    player_0_config: PlayerStrategyConfig = None,
    starting_player: int = -1,
    silent: bool = True,
    player_1_agent=None,
) -> Optional[GameResult]:
    """
    Run a single game: player 0 (BP) vs player 1 (Python agent, defaults to PythonAgent random policy).
    """
    if silent:
        original_level = logging.getLogger("TakiGame").level
        logging.getLogger("TakiGame").setLevel(logging.CRITICAL)

    try:
        listener = SimulationListener()

        start_time = datetime.now()
        b_program, actual_starting_player = create_simulation_bprogram_basic_vs_strategy(
            seed=seed,
            listener=listener,
            num_cards=num_cards,
            starting_player=starting_player,
            player_0_config=player_0_config,
            player_1_agent=player_1_agent,
        )
        try:
            b_program.run()
        except AssertionError:
            if not (listener.get_deadlock() or listener.get_draw()):
                raise
        end_time = datetime.now()

        winner = listener.get_winner()
        ended_in_deadlock = listener.get_deadlock()
        ended_in_draw = listener.get_draw()

        if winner is None and not (ended_in_deadlock or ended_in_draw):
            print(f"Warning: Game {game_number} (seed={seed}) ended without a winner")
            return None

        if ended_in_deadlock:
            print(f"Game {game_number} (seed={seed}) ended in deadlock.")

        if ended_in_draw:
            print(f"Game {game_number} (seed={seed}) ended in a draw.")

        duration = (end_time - start_time).total_seconds()
        return GameResult(
            game_number=game_number,
            seed=seed,
            winner=winner,
            event_count=listener.get_event_count(),
            starting_player=actual_starting_player,
            duration_seconds=duration,
            ended_in_deadlock=ended_in_deadlock,
            ended_in_draw=ended_in_draw,
        )

    except Exception as e:
        print(f"Error in game {game_number} (seed={seed}): {type(e).__name__}: {e}")
        return None

    finally:
        if silent:
            logging.getLogger("TakiGame").setLevel(original_level)


def run_simulation_basic_vs_strategy(
    num_games: int,
    start_seed: int = 0,
    num_cards: int = NUM_OF_CARDS,
    starting_player: int = -1,
    balanced_starting_players: bool = False,
    mirrored_starting_players: bool = False,
    player_0_config: PlayerStrategyConfig = None,
    player_1_agent=None,
    player_1_strategy_name: str = "PythonAgent (random policy)",
    silent: bool = True,
    progress_interval: int = 10,
) -> SimulationStats:
    """
    Run multiple games of a BP player (player 0) vs a Python agent (player 1).

    Parameters
    ----------
    num_games : int
        Number of games to simulate. When ``mirrored_starting_players`` is
        enabled, this is the number of unique seeds and the total number of
        games played will be ``2 * num_games``.
    start_seed : int
        Starting random seed (each game increments by 1).
    num_cards : int
        Number of cards per player.
    starting_player : int
        Which player goes first (0 or 1). Use -1 to let the scheduler decide.
    balanced_starting_players : bool
        If True, assign starts as evenly as possible across the run.
    mirrored_starting_players : bool
        If True, run each seed twice: once with P0 starting and once with P1
        starting. In this mode, ``num_games`` is the number of unique seeds.
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).
    player_1_agent : optional
        The Python agent for player 1. Defaults to PythonAgent(seed=seed) if None.
    player_1_strategy_name : str
        Display name for player 1's strategy, used in printed output.
    silent : bool
        If True, suppress game logging.
    progress_interval : int
        Print progress every N games.

    Returns
    -------
    SimulationStats
        Statistics about all games.
    """
    if player_0_config is None:
        player_0_config = PlayerStrategyConfig()

    schedule = build_game_schedule(
        num_games=num_games,
        start_seed=start_seed,
        starting_player=starting_player,
        balanced_starting_players=balanced_starting_players,
        mirrored_starting_players=mirrored_starting_players,
    )
    total_scheduled_games = len(schedule)

    print(f"Starting simulation of {total_scheduled_games} games (BP vs {player_1_strategy_name})...")
    print(f"Player 0 strategy: {player_0_config.label()}")
    print(f"Player 1 strategy: {player_1_strategy_name}")
    print(f"Cards per player: {num_cards}")
    print(f"Starting seed: {start_seed}")

    if mirrored_starting_players:
        print(f"[+] Mirrored starting-player schedule enabled across {num_games} seeds.")
    elif balanced_starting_players:
        print("[+] Starting player will be balanced as evenly as possible across the run.")
    elif starting_player == -1:
        print("[+] Starting player will be randomized per game.")
    else:
        print(f"Starting player: {starting_player}")

    print("-" * 60)

    stats = SimulationStats()

    for game_number, (seed, scheduled_starting_player) in enumerate(schedule, start=1):
        result = run_single_game_basic_vs_strategy(
            game_number=game_number,
            seed=seed,
            num_cards=num_cards,
            player_0_config=player_0_config,
            starting_player=scheduled_starting_player,
            silent=silent,
            player_1_agent=player_1_agent,
        )

        if result is not None:
            stats.add_result(result)
        else:
            stats.record_error()

        if game_number % progress_interval == 0:
            print(f"Progress: {game_number}/{total_scheduled_games} games completed")

    stats.test_results()
    return stats


def run_single_game(
    game_number: int,
    seed: int,
    num_cards: int = NUM_OF_CARDS,
    player_0_config: PlayerStrategyConfig = None,
    player_1_config: PlayerStrategyConfig = None,
    starting_player: int = 0,
    silent: bool = True,
) -> Optional[GameResult]:
    """
    Run a single game with the given seed.

    Parameters
    ----------
    game_number : int
        The game number in the simulation
    seed : int
        Random seed for reproducibility
    num_cards : int
        Number of cards per player
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).
    player_1_config : PlayerStrategyConfig
        Strategy configuration for player 1. Defaults to PlayerStrategyConfig() (basic).
    starting_player : int
        Which player goes first (0 or 1). Use -1 for seed-based random choice.
    silent : bool
        If True, suppress logging output

    Returns
    -------
    GameResult or None
        Result of the game, or None if an error occurred
    """
    if silent:
        original_level = logging.getLogger("TakiGame").level
        logging.getLogger("TakiGame").setLevel(logging.CRITICAL)

    try:
        listener = SimulationListener()

        start_time = datetime.now()
        b_program, actual_starting_player = create_simulation_bprogram(
            seed=seed,
            listener=listener,
            num_cards=num_cards,
            starting_player=starting_player,
            player_0_config=player_0_config,
            player_1_config=player_1_config,
        )
        try:
            b_program.run()
        except AssertionError:
            # identify_deadlock fires `assert False` after the deadlock event is
            # selected. The listener has already recorded it, so treat this as a
            # normal deadlock termination rather than an error.
            if not (listener.get_deadlock() or listener.get_draw()):
                raise
        end_time = datetime.now()

        # Get terminal state
        winner = listener.get_winner()
        ended_in_deadlock = listener.get_deadlock()
        ended_in_draw = listener.get_draw()

        if winner is None and not (ended_in_deadlock or ended_in_draw):
            print(f"Warning: Game {game_number} (seed={seed}) ended without a winner")
            return None

        if ended_in_deadlock:
            print(f"Game {game_number} (seed={seed}) ended in deadlock.")

        if ended_in_draw:
            print(f"Game {game_number} (seed={seed}) ended in a draw.")

        # Create result
        duration = (end_time - start_time).total_seconds()
        result = GameResult(
            game_number=game_number,
            seed=seed,
            winner=winner,
            event_count=listener.get_event_count(),
            starting_player=actual_starting_player,
            duration_seconds=duration,
            ended_in_deadlock=ended_in_deadlock,
            ended_in_draw=ended_in_draw,
        )

        return result

    except Exception as e:
        print(f"Error in game {game_number} (seed={seed}): {type(e).__name__}: {e}")
        return None

    finally:
        if silent:
            logging.getLogger("TakiGame").setLevel(original_level)


def run_simulation(
    num_games: int,
    start_seed: int = 0,
    num_cards: int = NUM_OF_CARDS,
    starting_player: int = -1,
    balanced_starting_players: bool = False,
    mirrored_starting_players: bool = False,
    player_0_config: PlayerStrategyConfig = None,
    player_1_config: PlayerStrategyConfig = None,
    silent: bool = True,
    progress_interval: int = 10,
) -> SimulationStats:
    """
    Run multiple games and collect statistics.

    Parameters
    ----------
    num_games : int
        Number of games to simulate. When ``mirrored_starting_players`` is
        enabled, this is the number of unique seeds and the total number of
        games played will be ``2 * num_games``.
    start_seed : int
        Starting random seed (each game increments by 1)
    num_cards : int
        Number of cards per player
    starting_player : int
        Which player goes first (0 or 1). Use -1 to let the scheduler decide.
    balanced_starting_players : bool
        If True, assign starts as evenly as possible across the run.
    mirrored_starting_players : bool
        If True, run each seed twice: once with P0 starting and once with P1
        starting. In this mode, ``num_games`` is the number of unique seeds.
    player_0_config : PlayerStrategyConfig
        Strategy configuration for player 0. Defaults to PlayerStrategyConfig() (basic).
    player_1_config : PlayerStrategyConfig
        Strategy configuration for player 1. Defaults to PlayerStrategyConfig() (basic).
    silent : bool
        If True, suppress game logging
    progress_interval : int
        Print progress every N games

    Returns
    -------
    SimulationStats
        Statistics about all games
    """
    if player_0_config is None:
        player_0_config = PlayerStrategyConfig()
    if player_1_config is None:
        player_1_config = PlayerStrategyConfig()

    schedule = build_game_schedule(
        num_games=num_games,
        start_seed=start_seed,
        starting_player=starting_player,
        balanced_starting_players=balanced_starting_players,
        mirrored_starting_players=mirrored_starting_players,
    )
    total_scheduled_games = len(schedule)

    print(f"Starting simulation of {total_scheduled_games} games...")
    print(f"Player 0 strategy: {player_0_config.label()}")
    print(f"Player 1 strategy: {player_1_config.label()}")
    print(f"Cards per player: {num_cards}")
    print(f"Starting seed: {start_seed}")

    if mirrored_starting_players:
        print(f"[+] Mirrored starting-player schedule enabled across {num_games} seeds.")
    elif balanced_starting_players:
        print("[+] Starting player will be balanced as evenly as possible across the run.")
    elif starting_player == -1:
        print("[+] Starting player will be randomized per game.")
    else:
        print(f"Starting player: {starting_player}")

    print("-" * 60)

    stats = SimulationStats()

    for game_number, (seed, scheduled_starting_player) in enumerate(schedule, start=1):
        result = run_single_game(
            game_number=game_number,
            seed=seed,
            num_cards=num_cards,
            player_0_config=player_0_config,
            player_1_config=player_1_config,
            starting_player=scheduled_starting_player,
            silent=silent,
        )

        if result is not None:
            stats.add_result(result)
        else:
            stats.record_error()

        if game_number % progress_interval == 0:
            print(f"Progress: {game_number}/{total_scheduled_games} games completed")

    stats.test_results()

    return stats


def save_results(stats: SimulationStats, filename: str = None, player_0_strategy: str = None, player_1_strategy: str = None, timestamp: str = None):
    """
    Save simulation results to a JSON file.
    
    Parameters
    ----------
    stats : SimulationStats
        Statistics to save
    filename : str, optional
        Output filename. If None, generates a timestamped name.
    player_0_strategy : str, optional
        Strategy used by player 0
    player_1_strategy : str, optional
        Strategy used by player 1
    timestamp : str, optional
        Timestamp of the simulation
    """
    if filename is None:
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"taki_simulation_results_{timestamp}.json"
    
    # Add metadata to the output
    output_data = stats.to_dict()
    if player_0_strategy is not None:
        output_data['player_0_strategy'] = player_0_strategy
    if player_1_strategy is not None:
        output_data['player_1_strategy'] = player_1_strategy
    if timestamp is not None:
        output_data['timestamp'] = timestamp
    
    with open(filename, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nResults saved to: {filename}")


def run_bp_vs_bp_simulation():
    num_seed_pairs = 5000
    player_0_config = PlayerStrategyConfig(base_strategy="taki")
    player_1_config = PlayerStrategyConfig(base_strategy="basic")

    stats = run_simulation(
        num_games=num_seed_pairs,
        start_seed=0,
        starting_player=-1,
        balanced_starting_players=True,
        mirrored_starting_players=False,
        player_0_config=player_0_config,
        player_1_config=player_1_config,
        silent=False,
        progress_interval=500,
    )

    p0_label = player_0_config.label()
    p1_label = player_1_config.label()
    summary_text = stats.summary(player_0_strategy=p0_label, player_1_strategy=p1_label)
    print("\n" + summary_text)

    timestamp = datetime.now().strftime("%H-%M_%d-%m-%Y")
    summary_filename = f"{p0_label}_vs_{p1_label}_{timestamp}_stats_summary.txt"
    with open(summary_filename, 'w', encoding='utf-8') as f:
        f.write(summary_text + '\n')
    print(f"Summary saved to: {summary_filename}")

    json_filename = f"{p0_label}_vs_{p1_label}_{timestamp}_seeds_test.json"
    save_results(stats, json_filename, player_0_strategy=p0_label, player_1_strategy=p1_label, timestamp=timestamp)

def run_bp_vs_external_player_simulation():
    num_seed_pairs = 10000
    player_1_label = "external"

    player_0_config = PlayerStrategyConfig(
        base_strategy="taki_and_super_taki",
        block_super_taki=True,
        change_color=True,
        most_popular_color=True,
        prefer_stop=True,
    )

    stats = run_simulation_basic_vs_external(
        num_games=num_seed_pairs,
        start_seed=0,
        starting_player=-1,
        balanced_starting_players=True,
        mirrored_starting_players=False,
        player_0_config=player_0_config,
        silent=False,
        progress_interval=500,
    )

    p0_label = player_0_config.label()
    summary_text = stats.summary(player_0_strategy=p0_label, player_1_strategy=player_1_label)
    print("\n" + summary_text)

    timestamp = datetime.now().strftime("%H-%M_%d-%m-%Y")
    summary_filename = f"{p0_label}_vs_{player_1_label}_{timestamp}_stats_summary.txt"
    with open(summary_filename, 'w', encoding='utf-8') as f:
        f.write(summary_text + '\n')
    print(f"Summary saved to: {summary_filename}")

    json_filename = f"{p0_label}_vs_{player_1_label}_{timestamp}_seeds_test.json"
    save_results(stats, json_filename, player_0_strategy=p0_label, player_1_strategy=player_1_label, timestamp=timestamp)

def run_bp_vs_strategy_player_simulation():
    num_seed_pairs = 10000
    player_1_strategy_name = "random"

    player_0_config = PlayerStrategyConfig(
        base_strategy="basic",
    )

    stats = run_simulation_basic_vs_strategy(
        num_games=num_seed_pairs,
        start_seed=0,
        starting_player=-1,
        balanced_starting_players=True,
        mirrored_starting_players=False,
        player_0_config=player_0_config,
        player_1_agent=None,
        player_1_strategy_name=player_1_strategy_name,
        silent=True,
        progress_interval=500,
    )

    p0_label = player_0_config.label()
    summary_text = stats.summary(player_0_strategy=p0_label, player_1_strategy=player_1_strategy_name)
    print("\n" + summary_text)

    timestamp = datetime.now().strftime("%H-%M_%d-%m-%Y")
    summary_filename = f"{p0_label}_vs_{player_1_strategy_name}_{timestamp}_stats_summary.txt"
    with open(summary_filename, 'w', encoding='utf-8') as f:
        f.write(summary_text + '\n')
    print(f"Summary saved to: {summary_filename}")

    json_filename = f"{p0_label}_vs_{player_1_strategy_name}_{timestamp}_seeds_test.json"
    save_results(stats, json_filename, player_0_strategy=p0_label, player_1_strategy=player_1_strategy_name, timestamp=timestamp)


def run_players_simulation():
    num_seed_pairs = 10000

    player_0_config = PlayerStrategyConfig(
        base_strategy="taki_and_super_taki",
        block_super_taki=True,
        change_color=True,
        most_popular_color=True,
        prefer_stop=True,
    )
    player_1_config = PlayerStrategyConfig(
        base_strategy="taki_and_super_taki",
        block_super_taki=True,
        change_color=True,
        most_popular_color=True,
        prefer_stop=True,
    )

    stats = run_simulation(
        num_games=num_seed_pairs,
        start_seed=0,
        starting_player=-1,
        balanced_starting_players=True,
        mirrored_starting_players=False,
        player_0_config=player_0_config,
        player_1_config=player_1_config,
        silent=True,
        progress_interval=500,
    )

    p0_label = player_0_config.label()
    p1_label = player_1_config.label()

    summary_text = stats.summary(player_0_strategy=p0_label, player_1_strategy=p1_label)
    print("\n" + summary_text)

    timestamp = datetime.now().strftime("%H-%M_%d-%m-%Y")
    summary_filename = f"{p0_label}_vs_{p1_label}_{timestamp}_stats_summary.txt"
    with open(summary_filename, 'w', encoding='utf-8') as f:
        f.write(summary_text + '\n')
    print(f"Summary saved to: {summary_filename}")

    json_filename = f"{p0_label}_vs_{p1_label}_{timestamp}_seeds_test.json"
    save_results(stats, json_filename, player_0_strategy=p0_label, player_1_strategy=p1_label, timestamp=timestamp)


if __name__ == "__main__":
    # run_bp_vs_bp_simulation()
    # run_bp_vs_external_player_simulation()
    # run_bp_vs_strategy_player_simulation()
    run_players_simulation()

    
