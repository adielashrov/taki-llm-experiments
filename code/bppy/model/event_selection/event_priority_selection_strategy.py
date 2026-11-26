from bppy.model.event_selection.simple_event_selection_strategy import SimpleEventSelectionStrategy
from bppy.model.b_priority_event import BPEvent
from collections.abc import Iterable

class EventPrioritySelectionStrategy(SimpleEventSelectionStrategy):
    """
    An EventSelectionStrategy that selects events based on priority.
    Events with lower priority values have higher priority (are selected first).
    For events with the same priority, selection is arbitrary/random.

    This strategy is specifically designed to work with BPEvent instances.
    Inherits from SimpleEventSelectionStrategy and only overrides the selectable_events method
    to implement priority-based event selection.
    """

    def filter_by_priority(self, selectable_events):

        events_list = list(selectable_events)
        for event in events_list:
            if not isinstance(event, BPEvent):
                raise TypeError(
                    f"EventPrioritySelectionStrategy requires BPEvent instances, got {type(event)}: {event}")

        events_list.sort(key=lambda event: event.get_priority())
        highest_priority = events_list[0].get_priority()

        highest_priority_events = [
            event for event in events_list
            if event.get_priority() == highest_priority
        ]

        return highest_priority_events

    def selectable_events(self, statements):
        """
        Extracts selectable events by:
        1. Collecting all requested events.
        2. Deduplicating by (name, data, priority).
        3. Removing blocked events (by equality).
        4. Returning only those with the highest priority (lowest number).
        """
        all_events = []

        # Step 1: Accumulate all requested events
        for statement in statements:
            requests = statement.get("request")
            if isinstance(requests, Iterable) and not isinstance(requests, (str, BPEvent)):
                all_events.extend(requests)
            elif isinstance(requests, BPEvent):
                all_events.append(requests)
            elif requests is not None:
                raise TypeError("request must be BPEvent or iterable of BPEvents")

        # Step 2: Deduplicate by (name, data, priority)
        seen_keys = set()
        unique_events = []
        for e in all_events:
            if not isinstance(e, BPEvent):
                raise TypeError(f"EventPrioritySelectionStrategy requires BPEvent instances, got {type(e)}: {e}")
            # This is the equals
            key = (e.name, tuple(sorted(e.data.items())), e.get_priority())
            if key not in seen_keys:
                seen_keys.add(key)
                unique_events.append(e)

        # Step 3: Filter out blocked events
        for statement in statements:
            blocks = statement.get("block")
            if isinstance(blocks, BPEvent):
                unique_events = [e for e in unique_events if e != blocks]
            elif blocks is not None:
                unique_events = [e for e in unique_events if e not in blocks]

        # Step 4: Keep only highest-priority events
        if unique_events:
            return self.filter_by_priority(unique_events)
        else:
            return [] # return empty list if there are no events to select.