import logging
import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Dict, Iterable, Iterator, List, Optional, Tuple, Union

from django_bulk_hooks.priority import Priority

logger = logging.getLogger(__name__)

# Key: (ModelClass, event)
# Value: list of tuples (handler_cls, method_name, condition_callable, priority)
_hooks: Dict[Tuple[type, str], List[Tuple[type, str, Callable, int]]] = {}

# Registry lock for thread-safety during registration and clearing
_lock = threading.RLock()


def register_hook(
    model: type,
    event: str,
    handler_cls: type,
    method_name: str,
    condition: Optional[Callable],
    priority: Union[int, Priority],
) -> None:
    """
    Register a hook for a specific model and event.
    
    Args:
        model: The Django model class
        event: The hook event (e.g., 'before_create', 'after_update')
        handler_cls: The hook handler class
        method_name: The method name in the handler class
        condition: Optional condition for when the hook should run
        priority: Hook execution priority (higher numbers execute first)
    """
    if not model or not event or not handler_cls or not method_name:
        logger.warning("Invalid hook registration parameters")
        return

    # Normalize event to str just in case enums are used upstream
    event = str(event)

    with _lock:
        key = (model, event)
        hooks = _hooks.setdefault(key, [])

        # Check for duplicate registrations
        duplicate = any(h[0] == handler_cls and h[1] == method_name for h in hooks)
        if duplicate:
            logger.warning(
                "Hook %s.%s already registered for %s.%s",
                handler_cls.__name__,
                method_name,
                model.__name__,
                event,
            )
            return

        # Add the hook
        hooks.append((handler_cls, method_name, condition, priority))

        # Sort by priority (highest numbers execute first)
        def sort_key(hook_info: Tuple[type, str, Callable, int]) -> int:
            p = hook_info[3]
            return p.value if hasattr(p, "value") else int(p)

        hooks.sort(key=sort_key, reverse=True)

        logger.debug(
            "Registered %s.%s for %s.%s with priority %s",
            handler_cls.__name__,
            method_name,
            model.__name__,
            event,
            priority,
        )


def get_hooks(model: type, event: str):
    """
    Get all registered hooks for a specific model and event.
    
    Args:
        model: The Django model class
        event: The hook event
        
    Returns:
        List of (handler_cls, method_name, condition, priority) tuples
    """
    if not model or not event:
        return []

    event = str(event)

    with _lock:
        key = (model, event)
        hooks = _hooks.get(key, [])

        # Log hook discovery for debugging
        if hooks:
            logger.debug("Found %d hooks for %s.%s", len(hooks), model.__name__, event)
            for handler_cls, method_name, condition, priority in hooks:
                logger.debug("  - %s.%s (priority: %s)", handler_cls.__name__, method_name, priority)
        else:
            logger.debug("No hooks found for %s.%s", model.__name__, event)

        # Return a shallow copy to prevent external mutation of registry state
        return list(hooks)


def list_all_hooks() -> Dict[Tuple[type, str], List[Tuple[type, str, Callable, int]]]:
    """Debug function to list all registered hooks (shallow copy)."""
    with _lock:
        return {k: list(v) for k, v in _hooks.items()}


def clear_hooks() -> None:
    """Clear all registered hooks (mainly for testing)."""
    with _lock:
        _hooks.clear()
        logger.debug("All hooks cleared")


def unregister_hook(model: type, event: str, handler_cls: type, method_name: str) -> None:
    """Unregister a previously registered hook (safe no-op if not present)."""
    event = str(event)
    with _lock:
        key = (model, event)
        if key not in _hooks:
            return
        _hooks[key] = [
            h for h in _hooks[key] if not (h[0] == handler_cls and h[1] == method_name)
        ]
        if not _hooks[key]:
            del _hooks[key]


@contextmanager
def isolated_registry() -> Iterator[None]:
    """
    Context manager that snapshots the hook registry and restores it on exit.

    Useful for tests to avoid global cross-test interference without relying on
    private state mutation from the outside.
    """
    with _lock:
        snapshot = {k: list(v) for k, v in _hooks.items()}
    try:
        yield
    finally:
        with _lock:
            _hooks.clear()
            _hooks.update({k: list(v) for k, v in snapshot.items()})


@contextmanager
def temporary_hook(
    model: type,
    event: str,
    handler_cls: type,
    method_name: str,
    condition: Optional[Callable] = None,
    priority: Union[int, Priority] = Priority.NORMAL,
) -> Iterator[None]:
    """
    Temporarily register a single hook for the duration of the context.

    Ensures the hook is unregistered even if an exception occurs.
    """
    register_hook(model, event, handler_cls, method_name, condition, priority)
    try:
        yield
    finally:
        unregister_hook(model, event, handler_cls, method_name)


@contextmanager
def temporary_hooks(
    registrations: Iterable[Tuple[type, str, type, str, Optional[Callable], Union[int, Priority]]]
) -> Iterator[None]:
    """
    Temporarily register multiple hooks for the duration of the context.

    Args:
        registrations: Iterable of (model, event, handler_cls, method_name, condition, priority)
    """
    # Register all
    for model, event, handler_cls, method_name, condition, priority in registrations:
        register_hook(model, event, handler_cls, method_name, condition, priority)
    try:
        yield
    finally:
        # Best-effort unregister all in reverse order
        for model, event, handler_cls, method_name, _, _ in reversed(list(registrations)):
            unregister_hook(model, event, handler_cls, method_name)
