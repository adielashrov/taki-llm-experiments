# Codex Conversation - BP TAKI Strategy Work

Date: 2026-06-06
Repository: `C:\Users\adiel\Documents\Research\python-taki`

## Context

The user asked whether Codex had access to prior threads and repository files. Codex confirmed that previous threads are not automatically available, but the current repo files and git history are accessible. Codex verified the following files exist in the workspace:

- `instructions.md`
- `README.md`
- `bp_taki.py`
- `taki_simulation.py`
- `SuperTaki_Web_Eng_2018.pdf`

## Initial Task

The user asked Codex to follow `instructions.md` and develop a BP TAKI strategy according to those instructions.

Codex read:

- `instructions.md`
- `README.md`
- `bp_taki.py`
- `taki_simulation.py`
- `bppy/model/b_priority_event.py`

The instruction file required:

1. A prose strategy proposal before code changes.
2. Additive BP b-thread strategy implementation in `bp_taki.py`.
3. Explicit deadlock analysis.
4. No external bridge state usage for the strategy.
5. Correct handling of regular cards, stop cards, change color, TAKI, Super TAKI, draw, and closed TAKI.

## Strategy Proposal

Codex proposed a composed strategy rather than a monolithic replacement:

1. `color_density_card_strategy`
   - Tracks the player's hand from deal/draw/play events.
   - Requests hand events with calculated priorities.
   - Prefers cards in the player's densest color group.
   - Keeps regular TAKI and Super TAKI priorities compatible with existing conventions.
   - Slightly favors Stop over regular numbered cards of the same color.
   - Treats `change_color` as a fallback.

2. `preserve_wildcards_when_colored_card_available`
   - Tracks hand and placement state from the event stream.
   - Blocks `change_color` and `super_taki` only when a legal non-wild colored card is available.
   - Does not block lifecycle events.
   - Lifts blocking during TAKI sequences and when no legal colored card is available.

## Implementation

Codex added helper functions and two b-threads to `bp_taki.py`:

- `_remove_card_event_from_hand`
- `_colored_strategy_card_events`
- `_card_color_counts`
- `_color_density_priority`
- `_prioritized_color_density_events`
- `_is_legal_non_wild_colored_card`
- `_wildcards_to_preserve`
- `_add_dealt_card_to_strategy_hand`
- `color_density_card_strategy`
- `preserve_wildcards_when_colored_card_available`

Codex also updated `taki_simulation.py`:

- Imported the new strategy b-threads.
- Added `color_density: bool = False` to `PlayerStrategyConfig`.
- Added `preserve_wildcards: bool = False` to `PlayerStrategyConfig`.
- Updated `PlayerStrategyConfig.label()`.
- Updated `_apply_strategy_config()` to register the new strategies when enabled.

## Initial Verification

Codex ran:

```powershell
python -m py_compile bp_taki.py taki_simulation.py
```

Then smoke-tested:

```powershell
python -c "from taki_simulation import PlayerStrategyConfig, run_simulation; cfg=PlayerStrategyConfig(base_strategy='taki_and_super_taki', block_super_taki=True, change_color=True, most_popular_color=True, prefer_stop=True, color_density=True, preserve_wildcards=True); stats=run_simulation(num_games=20, start_seed=0, starting_player=-1, balanced_starting_players=True, player_0_config=cfg, player_1_config=cfg, silent=True, progress_interval=20); print(stats.summary(cfg.label(), cfg.label()))"
```

Result:

- 20 completed games
- 0 errors
- 0 deadlocks
- 0 draws

Codex also ran a thinner test:

```powershell
python -c "from taki_simulation import PlayerStrategyConfig, run_simulation; p0=PlayerStrategyConfig(color_density=True, preserve_wildcards=True); p1=PlayerStrategyConfig(); stats=run_simulation(num_games=20, start_seed=100, starting_player=-1, balanced_starting_players=True, player_0_config=p0, player_1_config=p1, silent=True, progress_interval=20); print(stats.summary(p0.label(), p1.label()))"
```

Result:

- 20 completed games
- 0 errors
- 0 deadlocks
- 0 draws

Then a 100-game composed smoke test:

```powershell
python -c "from taki_simulation import PlayerStrategyConfig, run_simulation; cfg=PlayerStrategyConfig(base_strategy='taki_and_super_taki', block_super_taki=True, change_color=True, most_popular_color=True, prefer_stop=True, color_density=True, preserve_wildcards=True); stats=run_simulation(num_games=100, start_seed=0, starting_player=-1, balanced_starting_players=True, player_0_config=cfg, player_1_config=cfg, silent=True, progress_interval=100); print('completed', stats.total_completed, 'errors', stats.errors, 'deadlocks', stats.deadlocks, 'draws', stats.draws)"
```

Result:

- 100 completed games
- 0 errors
- 0 deadlocks
- 0 draws

## How to Run the New Strategies

Codex explained that the new flags are:

```python
color_density=True
preserve_wildcards=True
```

Example full composed strategy:

```powershell
python -c "from taki_simulation import PlayerStrategyConfig, run_simulation; cfg=PlayerStrategyConfig(base_strategy='taki_and_super_taki', block_super_taki=True, change_color=True, most_popular_color=True, prefer_stop=True, color_density=True, preserve_wildcards=True); stats=run_simulation(num_games=100, start_seed=0, starting_player=-1, balanced_starting_players=True, player_0_config=cfg, player_1_config=cfg, silent=True, progress_interval=20); print(stats.summary(cfg.label(), cfg.label()))"
```

Example new-only strategy against basic:

```powershell
python -c "from taki_simulation import PlayerStrategyConfig, run_simulation; p0=PlayerStrategyConfig(color_density=True, preserve_wildcards=True); p1=PlayerStrategyConfig(); stats=run_simulation(num_games=100, start_seed=0, starting_player=-1, balanced_starting_players=True, player_0_config=p0, player_1_config=p1, silent=True, progress_interval=20); print(stats.summary(p0.label(), p1.label()))"
```

## Review of `run_simulation` Parameters

The user asked whether the parameters in `run_simulation()` were being called accurately.

Codex inspected the signature:

```python
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
```

Codex confirmed the call was accurate:

```python
run_simulation(
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
```

Notes:

- `num_seed_pairs` was a misleading name when `mirrored_starting_players=False`, because it means number of games rather than seed pairs.
- `progress_interval=500` means no progress output appears during a 100-game run.

## Deadlock Report

The user later reported that the current `bp_taki.py` configuration with the added strategies led to a deadlock and provided an event trace.

Relevant trace ending:

```text
p_1_taki_yellow
deadlock
```

Codex reproduced the deadlock with:

```powershell
python bp_taki.py
```

The trace matched the user's reported deadlock.

## Deadlock Investigation

Codex manually stepped the BProgram and dumped active sync statements immediately after `p_1_taki_yellow`.

The key observation:

- `player_behavior(1)` was waiting for `done_post_action`.
- `enforce_turns()` had not entered TAKI handling.
- No b-thread was requesting `p_1_closed_taki` or `done_post_action`.

Root cause:

- The current deck/settings included `yellow` in `COLORS`.
- The event was `p_1_taki_yellow`.
- `is_action_card_event()` recognized it as an action card.
- But `is_taki_card_event()` only matched:

```python
r"^p_\d+_taki_(red|blue|green)$"
```

So `p_1_taki_yellow` was not treated as a TAKI card.

This caused:

1. `player_behavior(1)` handled it as a non-TAKI action and waited for `done_post_action`.
2. `enforce_turns()` did not recognize it as TAKI and therefore did not wait for `closed_taki` or request `done_post_action`.
3. The system deadlocked.

## Deadlock Fix

Codex updated `bp_taki.py` so TAKI recognition uses the dynamic `COLORS` list rather than hardcoded RGB.

Changes:

```python
def is_taki_card_event(event: BPEvent) -> bool:
    """Check if event is a regular taki card (not super taki)"""
    if not isinstance(event, BPEvent):
        return False
    match = re.match(r"^p_\d+_taki_(\w+)$", event.name)
    result = match is not None and match.group(1) in COLORS
    return result
```

Codex also changed the color-only play-event matcher inside `create_block_set_color_only()` to use `COLORS` dynamically:

```python
color_pattern = "|".join(re.escape(c) for c in COLORS)
re.match(rf"^p_\d+_(card_\d+|stop|plus_2|taki)_({color_pattern})$", e.name)
```

After the user asked whether regex matching was the only issue, Codex searched for more hardcoded RGB matches and found another related issue in `external_bridge_state.py`.

Codex updated:

```python
_COLORS = ["red", "blue", "green", "yellow"]
```

and:

```python
def _is_taki_card_event(event: BPEvent) -> bool:
    match = re.match(r"^p_\d+_taki_(\w+)$", event.name)
    return match is not None and match.group(1) in _COLORS
```

## Post-Fix Verification

Codex ran:

```powershell
python -m py_compile bp_taki.py taki_simulation.py external_bridge_state.py
```

Result: passed.

Codex reran:

```powershell
python bp_taki.py
```

Result:

- The exact trace advanced past `p_1_taki_yellow`.
- `p_1_closed_taki` was selected.
- The run eventually reached `end_game`.

Codex ran a 200-game simulation:

```powershell
python -c "from taki_simulation import PlayerStrategyConfig, run_simulation; p0=PlayerStrategyConfig(base_strategy='taki_and_super_taki', block_super_taki=True, change_color=True, most_popular_color=True, prefer_stop=True, color_density=True, preserve_wildcards=True); p1=PlayerStrategyConfig(base_strategy='basic'); stats=run_simulation(num_games=200, start_seed=0, starting_player=-1, balanced_starting_players=True, mirrored_starting_players=False, player_0_config=p0, player_1_config=p1, silent=True, progress_interval=50); print('completed', stats.total_completed, 'errors', stats.errors, 'deadlocks', stats.deadlocks, 'draws', stats.draws)"
```

Result:

- 200 completed games
- 0 errors
- 0 deadlocks
- 0 draws

Codex ran a 20-game external-agent path:

```powershell
python -c "from taki_simulation import PlayerStrategyConfig, run_simulation_basic_vs_external; p0=PlayerStrategyConfig(base_strategy='taki_and_super_taki', block_super_taki=True, change_color=True, most_popular_color=True, prefer_stop=True, color_density=True, preserve_wildcards=True); stats=run_simulation_basic_vs_external(num_games=20, start_seed=0, starting_player=-1, balanced_starting_players=True, mirrored_starting_players=False, player_0_config=p0, silent=True, progress_interval=10); print('completed', stats.total_completed, 'errors', stats.errors, 'deadlocks', stats.deadlocks, 'draws', stats.draws)"
```

Result:

- 20 completed games
- 0 errors
- 0 deadlocks
- 0 draws

## Current Caveats

- The regex/color fix definitely solves the provided `p_1_taki_yellow` deadlock trace.
- It does not mathematically prove no other deadlock paths exist.
- Stronger confidence would require broader seed testing or DFS verification.
- `python taki_simulation.py` currently runs 1000 games in `run_players_simulation()`, so it can appear quiet for a long time when `progress_interval` is large.

## Files Modified During This Conversation

- `bp_taki.py`
- `taki_simulation.py`
- `external_bridge_state.py`

