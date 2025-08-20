from enum import IntEnum


class Priority(IntEnum):
    """
    Named priorities for django-bulk-hooks hooks.

    Higher values run earlier (higher priority).
    Hooks are sorted in descending order.
    """

    LOWEST = 0  # runs last
    LOW = 25  # runs later
    NORMAL = 50  # default ordering
    HIGH = 75  # runs early
    HIGHEST = 100  # runs first
