"""
Example behavioral program demonstrating EventPrioritySelectionStrategy.

This program simulates an emergency response system with different priority levels:
- Critical alerts (priority 1.0) - highest priority
- Warnings (priority 5.0) - medium priority
- Info messages (priority 10.0) - lowest priority

The EventPrioritySelectionStrategy ensures critical alerts are always handled first.
"""

import bppy as bp
import random
from bppy.model.b_priority_event import BPEvent
from bppy.model.event_selection.event_priority_selection_strategy import EventPrioritySelectionStrategy

# Set random seed for reproducible results
random.seed(10)

# Define events with different priorities
critical_alert = BPEvent("CRITICAL_SYSTEM_FAILURE", data={"severity": "critical"}, priority=1.0)
fire_alarm = BPEvent("FIRE_DETECTED", data={"location": "server_room"}, priority=1.0)
low_memory_warning = BPEvent("LOW_MEMORY", data={"threshold": "80%"}, priority=5.0)
disk_warning = BPEvent("DISK_SPACE_LOW", data={"drive": "/var"}, priority=5.0)
info_backup = BPEvent("BACKUP_COMPLETED", data={"status": "success"}, priority=10.0)
info_update = BPEvent("SOFTWARE_UPDATE_AVAILABLE", data={"version": "1.2.3"}, priority=10.0)

@bp.thread
def critical_alerts_thread():
    """B-thread that generates critical system alerts"""
    print("CriticalAlertsThread: Starting to generate critical alerts")

    # Request critical system failure alert
    yield bp.sync(request=critical_alert)

    # Request fire alarm
    yield bp.sync(request=fire_alarm)

    print("CriticalAlertsThread: All critical alerts requested")

@bp.thread
def warning_alerts_thread():
    """B-thread that generates warning-level alerts"""
    print("WarningAlertsThread: Starting to generate warnings")

    # Request low memory warning
    yield bp.sync(request=low_memory_warning)

    # Request disk space warning
    yield bp.sync(request=disk_warning)

    print("WarningAlertsThread: All warnings requested")

@bp.thread
def info_alerts_thread():
    """B-thread that generates informational messages"""
    print("InfoAlertsThread: Starting to generate info messages")

    # Request backup completion info
    yield bp.sync(request=info_backup)

    # Request software update info
    yield bp.sync(request=info_update)

    print("InfoAlertsThread: All info messages requested")

@bp.thread
def alert_handler_thread():
    """B-thread that handles all alerts and prints them in order of processing"""
    print("AlertHandlerThread: Starting to monitor alerts")

    handled_count = 0
    max_alerts = 6  # Total number of alerts we expect

    all_alerts = [critical_alert, fire_alarm, low_memory_warning,
                  disk_warning, info_backup, info_update]

    while handled_count < max_alerts:
        # Wait for any alert
        last_event = yield bp.sync(waitFor=all_alerts)

        if last_event:
            handled_count += 1
            print(f"[{handled_count}] HANDLED: {last_event.name} "
                  f"(Priority: {last_event.get_priority()}) - {last_event.data}")

    print("AlertHandlerThread: All alerts processed")

def init_b_program():
    """Initialize the behavioral program with priority-based event selection"""
    b_program = bp.BProgram(
        bthreads=[
            critical_alerts_thread(),
            warning_alerts_thread(),
            info_alerts_thread(),
            alert_handler_thread()
        ],
        event_selection_strategy=EventPrioritySelectionStrategy(),
        listener=bp.PrintBProgramRunnerListener()
    )
    return b_program

def regular_execution_of_bp_program():
    """Execute the behavioral program"""
    print("=== EventPrioritySelectionStrategy Demo ===")
    print("Expected order (by priority):")
    print("1. CRITICAL_SYSTEM_FAILURE (priority 1.0)")
    print("2. FIRE_DETECTED (priority 1.0)")
    print("3. LOW_MEMORY (priority 5.0)")
    print("4. DISK_SPACE_LOW (priority 5.0)")
    print("5. BACKUP_COMPLETED (priority 10.0)")
    print("6. SOFTWARE_UPDATE_AVAILABLE (priority 10.0)")
    print("\nActual execution order:")
    print("-" * 50)

    b_program = init_b_program()
    b_program.run()

    print("-" * 50)
    print("Demo completed!")
    print("\nNote: Events with the same priority may appear in random order")
    print("relative to each other, but higher priority events will always")
    print("be processed before lower priority ones.")

def compare_with_simple_strategy():
    """Compare execution with SimpleEventSelectionStrategy for demonstration"""
    print("\n" + "="*60)
    print("COMPARISON: Running the same program with SimpleEventSelectionStrategy")
    print("(Random selection - no priority consideration)")
    print("="*60)

    # Create the same program but with SimpleEventSelectionStrategy
    b_program_simple = bp.BProgram(
        bthreads=[
            critical_alerts_thread(),
            warning_alerts_thread(),
            info_alerts_thread(),
            alert_handler_thread()
        ],
        event_selection_strategy=bp.SimpleEventSelectionStrategy(),
        listener=bp.PrintBProgramRunnerListener()
    )

    b_program_simple.run()
    print("Note: With SimpleEventSelectionStrategy, events appear in random order")

if __name__ == '__main__':
    # Run with priority-based selection
    regular_execution_of_bp_program()

    # Optionally compare with simple selection
    # compare_with_simple_strategy()

"""
Expected Output with EventPrioritySelectionStrategy:
==================================================
=== EventPrioritySelectionStrategy Demo ===
Expected order (by priority):
1. CRITICAL_SYSTEM_FAILURE (priority 1.0)
2. FIRE_DETECTED (priority 1.0)
3. LOW_MEMORY (priority 5.0)
4. DISK_SPACE_LOW (priority 5.0)
5. BACKUP_COMPLETED (priority 10.0)
6. SOFTWARE_UPDATE_AVAILABLE (priority 10.0)

Actual execution order:
--------------------------------------------------
CriticalAlertsThread: Starting to generate critical alerts
WarningAlertsThread: Starting to generate warnings
InfoAlertsThread: Starting to generate info messages
AlertHandlerThread: Starting to monitor alerts
[1] HANDLED: CRITICAL_SYSTEM_FAILURE (Priority: 1.0) - {'severity': 'critical'}
[2] HANDLED: FIRE_DETECTED (Priority: 1.0) - {'location': 'server_room'}
CriticalAlertsThread: All critical alerts requested
[3] HANDLED: LOW_MEMORY (Priority: 5.0) - {'threshold': '80%'}
[4] HANDLED: DISK_SPACE_LOW (Priority: 5.0) - {'drive': '/var'}
WarningAlertsThread: All warnings requested
[5] HANDLED: BACKUP_COMPLETED (Priority: 10.0) - {'status': 'success'}
[6] HANDLED: SOFTWARE_UPDATE_AVAILABLE (Priority: 10.0) - {'version': '1.2.3'}
InfoAlertsThread: All info messages requested
AlertHandlerThread: All alerts processed
--------------------------------------------------
Demo completed!
"""