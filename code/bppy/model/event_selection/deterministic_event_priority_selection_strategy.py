# deterministic_event_priority_selection_strategy.py

from __future__ import annotations

from typing import Iterable, Optional, Tuple, Any

from bppy.model.b_priority_event import BPEvent
from bppy.model.event_selection.event_priority_selection_strategy import (
    EventPrioritySelectionStrategy,
)


class DeterministicEventPrioritySelectionStrategy(EventPrioritySelectionStrategy):
    """
    Like EventPrioritySelectionStrategy, but deterministic:
    - picks the lowest numeric priority (highest priority)
    - if multiple events share the same priority, breaks ties deterministically by:
        (event.name, sorted(event.data.items()))
    """

    @staticmethod
    def _tie_break_key(event: BPEvent) -> Tuple[Any, ...]:
        # Priority first is harmless (all events passed in are already same priority),
        # but keeps the key robust if used elsewhere.
        data_items = ()
        if getattr(event, "data", None):
            # Sort items for stable ordering across runs
            data_items = tuple(sorted(event.data.items()))
        return (event.get_priority(), event.name, data_items)

    def select(self, statements, external_events_queue=None):
        # Avoid mutable default arg pitfalls
        if external_events_queue is None:
            external_events_queue = []

        selectable_events = self.selectable_events(statements)
        if selectable_events:
            # selectable_events is typically a list of BPEvents (same priority)
            return min(selectable_events, key=self._tie_break_key)

        # Fallback: deterministic FIFO from external queue
        if len(external_events_queue) > 0:
            return external_events_queue.pop(0)
        return None
