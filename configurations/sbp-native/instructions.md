# TAKI Agent Prompt — Design Document

**Date:** 02/05/2026
**Author:** Adiel Ashrov & Claude
**Purpose:** Document the design decisions, rationale, and changelog behind the LLM prompt for generating an optimal TAKI-playing strategy as BP b-threads in bp_taki.py.

## Task: Implement a TAKI-Playing Strategy as BP B-Threads - Use bp_taki.py

## PART 1 — Background: The TAKI Card Game

TAKI is a competitive 2-player card game. The **objective** is to be the first player to empty your hand. Players alternate turns. On each turn, a player must play a legal card from their hand onto the discard pile, or draw a card if no legal play exists.

**Card types and their effects:**

| Card         | Format                  | Effect                                                                                                          |
| ------------ | ----------------------- | --------------------------------------------------------------------------------------------------------------- |
| Number card  | `card_{number}_{color}` | Basic card. Played to match color or number.                                                                    |
| Stop         | `stop_{color}`          | Skips the opponent's next turn entirely.                                                                        |
| Change Color | `change_color`          | Lets you choose the new active color (any of red, blue, green). Always legal to play.                           |
| TAKI         | `taki_{color}`          | Opens a TAKI sequence: you may chain as many same-color cards as you like before closing. Always legal to play. |
| Super TAKI   | `super_taki`            | Like TAKI, but color-agnostic — inherits the current active color. Always legal to play.                        |

**Placement rules:**

- In a normal turn (`rule_mode = "match_color_or_type"`): a card is legal if it matches the **active color** OR matches the **type/number** of the top card.
- After a `change_color` card (`rule_mode = "color_only"`): only cards matching the **active color** are legal (plus `change_color` and `super_taki` which are always legal).
- During a TAKI sequence (`rule_mode = "taki"`): only cards matching the **TAKI color** are legal, plus `super_taki`. `change_color` is **not** legal inside a TAKI sequence.

---

## PART 2 — Game Rules Reference

Two reference files are attached for context:

#### 2a. Official Rulebook (`SuperTaki_Web_Eng_2018.pdf`)

The official Super TAKI rulebook describes the complete game including all card types and mechanics.

**Important:** The implementation you are targeting supports only a **subset** of the full game. Treat the following as the authoritative card set — ignore all other card types mentioned in the rulebook:

- Number cards (`card_{number}_{color}`)
- Stop (`stop_{color}`)
- Change Color (`change_color`)
- TAKI (`taki_{color}`)
- Super TAKI (`super_taki`)

Specifically, the following cards from the rulebook **do not exist** in this implementation and must be ignored entirely: `+2`, `+3`, `+3 Breaker`, `King`, `Plus`, `Change Direction`.

#### 2b. BP Game Engine (`bp_taki.py`)

The attached file `bp_taki.py` is the complete implementation of the TAKI game engine in Behavioral Programming (BP) using the BPpy framework. Unlike the previous experiment, your task here is to implement your strategy **directly as BP b-threads** that integrate into this file.

Reading this file carefully is essential. It will give you precise, authoritative answers to questions such as:

- **Exact deck composition**: which card types exist, how many of each, and which number values are used — see `init_cards_events()`
- **Turn and sequence lifecycle**: how the engine drives a player's turn, how a TAKI sequence is entered and exited, and when `done_post_action` signals the end of a sequence — see `player_behavior()` and `enforce_turns()`
- **Placement rule enforcement**: exactly which cards are blocked or allowed in each game state — see `enforce_card_placement_rules()`, `init_selected_color_or_type_event_set()`, `create_block_set_color_only()`, and `create_taki_color_block()`
- **Post-TAKI state**: what color and type rule are in effect after a TAKI sequence ends — see the post-sequence logic in `enforce_card_placement_rules()`
- **How strategy b-threads work**: `bp_taki.py` already contains three strategy b-threads — `basic_strategy_taki`, `basic_strategy_taki_and_super_taki`, and `strategy_block_super_taki_during_regular_taki` — which serve as your primary reference implementations. Study them carefully before designing your own.
- **Available helpers**: see `add_event_to_card_events_according_to_basic_strategy_taki`, `remove_deal_prefix_and_add_player_index`, `is_regular_card_event`, `is_action_card_event`, `is_any_taki_event`, `is_taki_card_event`, `is_super_taki_event`, `is_change_color_event`, `is_draw_card_event`, `extract_card_color_and_type`, and `DealCardsEventSet`.
- **`BPEvent` class**: the `BPEvent` class used throughout `bp_taki.py` is defined in the attached `b_priority_event.py`. Read it to understand the constructor signature (`name`, `data`, `priority`), the default priority value, and how equality and hashing are defined (by `name` and `data` only — not by `priority`).

Use this file as a ground-truth reference for game mechanics and BP idioms. Ignore all logging, testing, deadlock/livelock detection, and infrastructure code — these are irrelevant to your strategy. For simulation and evaluation infrastructure, see `taki_simulation.py` — this is not needed for your implementation.

---

## PART 3 — Behavioral Programming Concepts

Your strategy must be implemented as one or more **b-threads** using the BPpy framework. Here is what you need to know:

### The synchronization model

A b-thread is a Python generator function decorated with `@bp.thread`. At each step it calls:

```python
result = yield bp.sync(
    request=<events to propose>,   # events this b-thread wants to trigger
    waitFor=<events to observe>,   # events this b-thread wants to be notified of (without proposing)
    block=<events to forbid>,      # events this b-thread prevents from being selected
)
```

All b-threads synchronize at each `yield`. The runtime selects one event that is **requested** by at least one b-thread and **not blocked** by any b-thread. All b-threads that requested or waited for that event are resumed.

### The priority system

This codebase uses `BPEvent` objects with a numeric `priority` field:

```python
BPEvent("event_name", priority=5.0)
```

**Lower priority number = higher selection preference.** Default priority is `10.0`. A strategy b-thread influences which card gets played by requesting all cards in the player's hand simultaneously, but assigning lower priority numbers to preferred cards — the runtime then selects the lowest-priority non-blocked event.

Priority conventions used in this codebase:
- `4.0` → highest strategic preference (e.g., regular TAKI)
- `6.0` → elevated preference (e.g., Super TAKI)
- `8.0` → `no_more_cards`
- `10.0` → default / neutral
- `15.0` → `closed_taki` (deliberately deprioritized to keep TAKI sequences open)
- `20.0` → `draw_card` (last resort)

### Compositional safety

A strategy b-thread runs **alongside** all existing game b-threads — it does not replace them. This means:

- **Do not** request or block lifecycle events (`next_turn`, `start_game`, `end_game`, `done_post_action`) — these are owned by `player_behavior` and `enforce_turns`.
- **Do not** use `block=` unless you fully understand the consequences for all other b-threads. Blocking can prevent legal events from being selected and cause deadlocks.
- Your b-thread must track the player's hand independently — it cannot query external state directly.

---

## PART 4 — Reference Implementations

Three strategy b-threads are already implemented in `bp_taki.py`. Study them carefully — they are your primary reference.

### `basic_strategy_taki`
Boosts the priority of any TAKI or Super TAKI card to `5.0`, leaving all other cards at their default priority. During a TAKI sequence it uses `waitFor=card_events` (passive observation), so it does not impose priority during the sequence.

### `basic_strategy_taki_and_super_taki`
Differentiates between regular TAKI (`4.0`) and Super TAKI (`6.0`), making regular TAKI the most preferred card overall. During a TAKI sequence it uses `request=card_events` (active prioritization), so Super TAKI is still preferred over regular cards within the sequence.

### `strategy_block_super_taki_during_regular_taki`
A **separate, compositional b-thread** that does not manage the hand — instead it watches for a regular TAKI card being played, then **blocks** `super_taki` for the duration of that TAKI sequence. This encodes the strategic insight that Super TAKI should be saved as a wildcard and not consumed inside a regular-color TAKI run. This b-thread is designed to run **alongside** `basic_strategy_taki_and_super_taki`, not as a standalone strategy.

---

## PART 5 — Your Task

**Step 1 — Strategy proposal (prose):** Before writing any code, describe in plain language the strategy you will implement. Explain:

- What strategic principles guide your card selection and why
- How your strategy interacts with TAKI sequences, Stop cards, and Change Color cards
- Whether your strategy uses a single b-thread or multiple composed b-threads, and why
- What tradeoffs you considered and why you made the choices you did

**Step 2 — Implementation:** Implement your strategy as one or more `@bp.thread` decorated generator functions. Requirements:

- Follow the same turn lifecycle as the reference implementations: deal phase → `start_game` → turn loop → termination on `no_more_cards`
- Influence card selection **only through priority values** — do not request or block lifecycle events
- Handle all card types correctly: regular cards, stop, change_color, TAKI sequences (including `closed_taki`), and draw events
- You may add private helper functions alongside your b-thread(s) if needed
- Do not include import statements — your code will be added directly to `bp_taki.py` where all dependencies are already imported

---

## PART 6 — Constraints & Notes

- `block=` is a powerful BP feature and is permitted in your strategy. Use it when you want to actively prevent certain cards from being played in specific game situations — `strategy_block_super_taki_during_regular_taki` is a good example of this. However, use it carefully: blocking an event that no other b-thread can unblock, or blocking a lifecycle event, will cause a deadlock.
- After playing any non-TAKI action card (`stop`, `change_color`), you **must** `yield bp.sync(waitFor=BPEvent("done_post_action", priority=10.0))` before continuing. Skipping this causes a deadlock.
- Inside a TAKI sequence, keep looping with `waitFor=card_events` or `request=card_events` until `card_event.name == f"p_{index}_closed_taki"`. Do not break early.
- After every played card (regular, action, or `closed_taki`), call `card_events.remove(card_event)`.
- `draw_card` is requested by `player_behavior` — your strategy should observe it with `waitFor=[draw_card_event]`, not request it.
- Card event names in your b-thread use the **player-prefixed** format: `p_{index}_card_4_blue`, `p_{index}_taki_red`, etc. — not the prefix-free format used by `TakiAgent`.
- If your strategy uses multiple b-threads, each must independently follow the game lifecycle. Shared mutable state between b-threads is not supported — each b-thread maintains its own local variables.