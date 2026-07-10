"""
core/event_log/enums.py
────────────────────────
EventSource enum for the event_log.source column.

Paper connection (§III.B — Event Log Memory ℰ):
  The paper distinguishes three event producers:
    - System:   Hardware sensors via the DataObserver (e.g. "BG51 detects...")
    - Operator: Commands issued by an OperatorAgent (e.g. "calls function: ...")
    - Manager:  Task assignments from the ManagerAgent (e.g. "Task assigned: ...")

  These map exactly to the bracketed source label in the paper's event format:
    [Inspection Station][System][00:01:41] BG51 detects a workpiece...
                        ^^^^^^
"""

import enum


class EventSource(str, enum.Enum):
    """
    Identifies the producer of an event within a scope.

    Using str-enum means the value stored in event_log.source is the
    human-readable string ("System", "Operator", "Manager") — matching
    the paper's bracketed format exactly.
    """
    SYSTEM = "System"
    OPERATOR = "Operator"
    MANAGER = "Manager"