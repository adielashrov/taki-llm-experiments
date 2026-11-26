from bppy.model.event_selection.simple_event_selection_strategy import SimpleEventSelectionStrategy
from bppy.model.event_set import EventSet
from collections.abc import Iterable
from bppy.model.b_event import BEvent


class StatementPriorityBasedEventSelectionStrategy(SimpleEventSelectionStrategy):
    def __init__(self, default_request_priority=0, default_block_priority=0):
        super().__init__()
        self.default_request_priority = default_request_priority
        self.default_block_priority = default_block_priority

    def selectable_events(self, statements):
        # Use hash-based dictionaries for O(1) lookups
        requested_events = {}  # hash -> (event, priority)
        blocked_hashes = set()  # set of hashes for individual events (hard blocked)
        soft_blocked_events = {}  # hash -> (event, priority)

        # Collections for EventSet blocking
        blocked_eventsets = []  # list of EventSet objects (hard blocked)
        soft_blocked_eventsets = []  # list of (EventSet, priority) tuples

        # First pass - collect using hashes
        for statement in statements:
            # Handle multiSync statements - expand them into individual statements
            if 'multiSync' in statement:
                multi_statements = statement['multiSync']
                for multi_statement in multi_statements:
                    self._process_statement(multi_statement, requested_events, blocked_hashes,
                                            soft_blocked_events, blocked_eventsets, soft_blocked_eventsets)
            else:
                # Process regular statement
                self._process_statement(statement, requested_events, blocked_hashes,
                                        soft_blocked_events, blocked_eventsets, soft_blocked_eventsets)

        # Filter using hash comparisons and EventSet checks
        final_events = {}  # event -> (priority, block_priority)
        # Track the softBlocked event with the lowest block priority
        min_blocked_event = None
        min_block_priority = float('inf')

        for event_hash, (event, req_priority) in requested_events.items():
            # Skip hard blocked individual events
            if event_hash in blocked_hashes:
                continue

            # Skip hard blocked by EventSets
            if self._is_blocked_by_eventsets(event, blocked_eventsets):
                continue

            # Check if the event is softBlocked by individual events
            block_priority = 0
            is_soft_blocked = False

            if event_hash in soft_blocked_events:
                block_priority = soft_blocked_events[event_hash][1]
                is_soft_blocked = True

            # Check if softBlocked by EventSets
            eventset_block_priority = self._get_eventset_block_priority(event, soft_blocked_eventsets)
            if eventset_block_priority is not None:
                if is_soft_blocked:
                    # Take maximum if blocked by both individual events and EventSets
                    block_priority = max(block_priority, eventset_block_priority)
                else:
                    block_priority = eventset_block_priority
                    is_soft_blocked = True

            if is_soft_blocked:
                # Only include if request priority is higher than block priority
                if req_priority > block_priority:
                    final_events[event] = (req_priority, block_priority)
                # Otherwise, track it as a potential fallback if it has the lowest block priority
                elif block_priority < min_block_priority:
                    min_blocked_event = event
                    min_block_priority = block_priority
            else:
                # Not blocked at all, add to final events
                final_events[event] = (req_priority, 0)

        # If no events made it to final_events, use the softBlocked event with the lowest block priority
        if not final_events and min_blocked_event is not None:
            final_events[min_blocked_event] = (-1, min_block_priority)

        # If we have any final events, find the maximum priority
        if final_events:
            max_priority = max(priority for priority, _ in final_events.values())

            # Get all events with the max priority
            max_priority_events = {event: (priority, block_priority)
                                   for event, (priority, block_priority) in final_events.items()
                                   if priority == max_priority}

            # Find the lowest block priority among max priority events
            min_block_priority = min(block_priority for _, block_priority in max_priority_events.values())

            # Return only those events with max priority and min block priority
            return {event for event, (_, block_priority) in max_priority_events.items()
                    if block_priority == min_block_priority}

        # No events available
        return set()

    def _process_statement(self, statement, requested_events, blocked_hashes,
                           soft_blocked_events, blocked_eventsets, soft_blocked_eventsets):
        """
        Process a single sync statement and update the event collections.
        Supports: request, block (hard), softBlock
        """
        # Handle requests
        if 'request' in statement:
            rs = statement['request']
            request_priority = statement.get('requestPriority', self.default_request_priority)
            events = rs if isinstance(rs, Iterable) else [rs]
            for event in events:
                if isinstance(event, BEvent):  # Only process BEvent objects
                    event_hash = hash(event)
                    curr_priority = requested_events.get(event_hash, (None, -1))[1]
                    requested_events[event_hash] = (event, max(curr_priority, request_priority))

        # Handle hard blocking with 'block' (legacy compatible)
        if 'block' in statement:
            self._process_block_field(statement['block'], blocked_hashes, blocked_eventsets)

        # Handle soft blocking
        if 'softBlock' in statement:
            block_priority = statement.get('blockPriority', self.default_block_priority)
            sb = statement['softBlock']
            events = sb if isinstance(sb, Iterable) else [sb]
            for event in events:
                if isinstance(event, BEvent):
                    event_hash = hash(event)
                    curr_priority = soft_blocked_events.get(event_hash, (None, -1))[1]
                    soft_blocked_events[event_hash] = (event, max(curr_priority, block_priority))
                elif isinstance(event, EventSet):
                    soft_blocked_eventsets.append((event, block_priority))

    def _process_block_field(self, block_field, blocked_hashes, blocked_eventsets):
        """Helper method to process block field that handles both BEvent and EventSet."""
        if isinstance(block_field, list):
            for item in block_field:
                if isinstance(item, BEvent):
                    blocked_hashes.add(hash(item))
                elif isinstance(item, EventSet):
                    blocked_eventsets.append(item)
        elif isinstance(block_field, BEvent):
            blocked_hashes.add(hash(block_field))
        elif isinstance(block_field, EventSet):
            blocked_eventsets.append(block_field)

    def _is_blocked_by_eventsets(self, event, blocked_eventsets):
        """Check if an event is blocked by any EventSet."""
        return any(event in eventset for eventset in blocked_eventsets)

    def _get_eventset_block_priority(self, event, soft_blocked_eventsets):
        """Get the maximum block priority from EventSets that contain this event."""
        max_priority = None
        for eventset, priority in soft_blocked_eventsets:
            if event in eventset:
                if max_priority is None:
                    max_priority = priority
                else:
                    max_priority = max(max_priority, priority)
        return max_priority

    def is_satisfied(self, event, statement):
        """
        Checks whether a bthread should advance based on the selected event
        and its current sync statement.
        Handles EventSet objects in request and waitFor.
        """
        # Handle multiSync statements
        if 'multiSync' in statement:
            multi_statements = statement['multiSync']
            for multi_statement in multi_statements:
                if self._is_statement_satisfied(event, multi_statement):
                    return True
            return False
        else:
            # Handle regular statement
            return self._is_statement_satisfied(event, statement)

    def _is_statement_satisfied(self, event, statement):
        """
        Checks whether a single sync statement is satisfied by the event.
        Handles EventSet objects in request and waitFor.
        """
        # Retrieve statement values once
        request = statement.get('request')
        waitFor = statement.get('waitFor')

        # Check if the event is requested
        if request:
            if isinstance(request, BEvent):
                if request == event:
                    return True
            elif isinstance(request, EventSet):
                if event in request:
                    return True
            elif isinstance(request, Iterable):
                for item in request:
                    if isinstance(item, BEvent) and item == event:
                        return True
                    elif isinstance(item, EventSet) and event in item:
                        return True
            else:
                if event in request:
                    return True

        # Check if the event is waited for
        if waitFor:
            if isinstance(waitFor, BEvent):
                if waitFor == event:
                    return True
            elif isinstance(waitFor, EventSet):
                if event in waitFor:
                    return True
            elif isinstance(waitFor, Iterable):
                for item in waitFor:
                    if isinstance(item, BEvent) and item == event:
                        return True
                    elif isinstance(item, EventSet) and event in item:
                        return True
            else:
                if event in waitFor:
                    return True

        # If none of the above, return False
        return False


