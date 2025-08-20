"""
Compatibility layer for priority-related exports.

This module re-exports the canonical Priority enum and a DEFAULT_PRIORITY
constant so existing imports like `from django_bulk_hooks.enums import ...`
continue to work without churn. Prefer importing from `priority` in new code.
"""

from django_bulk_hooks.priority import Priority

# Default priority used when none is specified by the hook decorator
DEFAULT_PRIORITY = Priority.NORMAL

__all__ = ["Priority", "DEFAULT_PRIORITY"]
