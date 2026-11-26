from bppy.model.event_selection.simple_event_selection_strategy import SimpleEventSelectionStrategy
from collections.abc import Iterable
from bppy.model.b_event import BEvent


class Connect4PriorityBasedEventSelectionStrategy(SimpleEventSelectionStrategy):
    def __init__(self, fixed_sequence_number=0, win_color="red", default_request_priority=0, default_block_priority=0):
        # super().__init__(fixed_sequence_number, win_color)
        super().__init__()  # Fixed: Added parentheses around super
        self.default_request_priority = default_request_priority
        self.default_block_priority = default_block_priority

    # Rest of the class remains the same
    def selectable_events(self, statements):
        # Use hash-based dictionaries for O(1) lookups
        requested_events = {}  # hash -> (event, priority)
        hard_blocked_hashes = set()  # set of hashes
        soft_blocked_events = {}  # hash -> (event, priority)

        # First pass - collect using hashes
        for statement in statements:
            # Handle multiSync statements - expand them into individual statements
            if 'multiSync' in statement:
                multi_statements = statement['multiSync']
                for multi_statement in multi_statements:
                    self._process_statement(multi_statement, requested_events, hard_blocked_hashes, soft_blocked_events)
            else:
                # Process regular statement
                self._process_statement(statement, requested_events, hard_blocked_hashes, soft_blocked_events)

        # Filter using hash comparisons
        final_events = {}  # event -> (priority, block_priority)
        # Track the softBlocked event with the lowest block priority
        min_blocked_event = None
        min_block_priority = float('inf')

        for event_hash, (event, req_priority) in requested_events.items():
            # Skip hardBlocked events
            if event_hash in hard_blocked_hashes:
                continue

            # Check if the event is softBlocked
            if event_hash in soft_blocked_events:
                event_block_info = soft_blocked_events[event_hash]
                block_priority = event_block_info[1]

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
            # print(f"min_block_priority: {min_block_priority}")
            final_events[min_blocked_event] = (-1, min_block_priority)  # Use a negative priority as this is a fallback
            # print(f"min_block_priority: {min_block_priority}")

        # If we have any final events, find the maximum priority
        if final_events:
            max_priority = max(priority for priority, _ in final_events.values())
            # print(f"max_priority: {max_priority}")

            # Get all events with the max priority
            max_priority_events = {event: (priority, block_priority)
                                   for event, (priority, block_priority) in final_events.items()
                                   if priority == max_priority}

            # Otherwise, find the lowest block priority among max priority events
            min_block_priority = min(block_priority for _, block_priority in max_priority_events.values())

            # Return only those events with max priority and min block priority
            return {event for event, (_, block_priority) in max_priority_events.items()
                    if block_priority == min_block_priority}

        # No events available
        return set()

    def _process_statement(self, statement, requested_events, hard_blocked_hashes, soft_blocked_events):
        """
        Process a single sync statement and update the event collections.

        Parameters:
        -----------
        statement : dict
            The sync statement to process
        requested_events : dict
            Dictionary of requested events (hash -> (event, priority))
        hard_blocked_hashes : set
            Set of hashes for hard-blocked events
        soft_blocked_events : dict
            Dictionary of soft-blocked events (hash -> (event, priority))
        """
        if 'request' in statement:
            rs = statement['request']
            request_priority = statement.get('requestPriority', self.default_request_priority)
            events = rs if isinstance(rs, Iterable) else [rs]
            for event in events:
                event_hash = hash(event)  # Use hash function instead of _hash attribute
                curr_priority = requested_events.get(event_hash, (None, -1))[1]
                requested_events[event_hash] = (event, max(curr_priority, request_priority))

        if 'hardBlock' in statement:
            hb = statement['hardBlock']
            if isinstance(hb, list):
                hard_blocked_hashes.update(hash(event) for event in hb)
            else:
                hard_blocked_hashes.add(hash(hb))

        if 'softBlock' in statement:
            block_priority = statement.get('blockPriority', self.default_block_priority)
            sb = statement['softBlock']
            events = sb if isinstance(sb, Iterable) else [sb]
            for event in events:
                event_hash = hash(event)
                curr_priority = soft_blocked_events.get(event_hash, (None, -1))[1]
                soft_blocked_events[event_hash] = (event, max(curr_priority, block_priority))

    def is_satisfied(self, event, statement):
        """
        Checks whether a bthread should advance based on the selected event
        and its current sync statement.
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

        Parameters:
        -----------
        event : BEvent
            The event to check
        statement : dict
            The sync statement to check against

        Returns:
        --------
        bool
            True if the statement is satisfied by the event, False otherwise
        """
        # Retrieve statement values once
        request = statement.get('request')
        waitFor = statement.get('waitFor')

        # Check if the event is requested
        if request:
            if isinstance(request, BEvent):
                if request == event:
                    return True
            else:
                if event in request:
                    return True

        # Check if the event is waited for
        if waitFor:
            if isinstance(waitFor, BEvent):
                if waitFor == event:
                    return True
            else:
                if event in waitFor:
                    return True

        # If none of the above, return False
        return False