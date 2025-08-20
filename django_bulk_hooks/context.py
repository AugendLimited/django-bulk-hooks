import threading
from typing import Deque, Optional
from django_bulk_hooks.handler import hook_vars, get_hook_queue as _handler_get_hook_queue


_hook_context = threading.local()


def get_hook_queue() -> Deque:
    """
    Return the per-thread hook execution queue used by the handler.

    This proxies to the centralized queue in the handler module to avoid
    divergent queues.
    """
    return _handler_get_hook_queue()


def set_bypass_hooks(bypass_hooks: bool) -> None:
    """Set the current bypass_hooks state for the current thread."""
    _hook_context.bypass_hooks = bypass_hooks


def get_bypass_hooks() -> bool:
    """Get the current bypass_hooks state for the current thread."""
    return getattr(_hook_context, 'bypass_hooks', False)


class HookContext:
    """
    Hook execution context helper.

    - Carries the model and bypass_hooks flag.
    - On construction sets thread-local bypass state;
      when used as a context manager, restores previous state on exit.
    """

    def __init__(self, model: type, bypass_hooks: bool = False):
        self.model: type = model
        self.bypass_hooks: bool = bypass_hooks
        self._prev_bypass: Optional[bool] = None
        # Preserve legacy behavior: set bypass state at construction
        set_bypass_hooks(bypass_hooks)

    def __enter__(self) -> "HookContext":
        self._prev_bypass = get_bypass_hooks()
        set_bypass_hooks(self.bypass_hooks)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Restore previous bypass state
        if self._prev_bypass is not None:
            set_bypass_hooks(self._prev_bypass)
        # Do not suppress exceptions
        return False

    @property
    def is_executing(self) -> bool:
        """
        Check if we're currently in a hook execution context.
        Similar to Salesforce's Trigger.isExecuting.
        Use this to prevent infinite recursion in hooks.
        """
        return hasattr(hook_vars, 'event') and hook_vars.event is not None

    @property
    def current_event(self) -> Optional[str]:
        """
        Get the current hook event being executed.
        """
        return getattr(hook_vars, 'event', None)

    @property
    def execution_depth(self) -> int:
        """
        Get the current execution depth to detect deep recursion.
        """
        return getattr(hook_vars, 'depth', 0)

    def __repr__(self) -> str:
        return f"HookContext(model={getattr(self.model, '__name__', self.model)!r}, bypass_hooks={self.bypass_hooks})"
