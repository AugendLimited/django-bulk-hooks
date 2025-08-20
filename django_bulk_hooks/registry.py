import logging
from collections.abc import Callable
from typing import Union

from django_bulk_hooks.priority import Priority

logger = logging.getLogger(__name__)

_hooks: dict[tuple[type, str], list[tuple[type, str, Callable, int]]] = {}


def register_hook(
    model, event, handler_cls, method_name, condition, priority: Union[int, Priority]
):
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
    
    key = (model, event)
    hooks = _hooks.setdefault(key, [])
    
    # Check for duplicate registrations
    existing = [h for h in hooks if h[0] == handler_cls and h[1] == method_name]
    if existing:
        logger.warning(
            f"Hook {handler_cls.__name__}.{method_name} already registered "
            f"for {model.__name__}.{event}"
        )
        return
    
    # Add the hook
    hooks.append((handler_cls, method_name, condition, priority))
    
    # Sort by priority (highest numbers execute first)
    # Convert Priority enum to int for proper sorting
    def sort_key(hook_info):
        priority = hook_info[3]
        if hasattr(priority, 'value'):  # Priority enum
            return priority.value
        return priority
    
    hooks.sort(key=sort_key, reverse=True)
    
    logger.debug(
        f"Registered {handler_cls.__name__}.{method_name} "
        f"for {model.__name__}.{event} with priority {priority}"
    )


def get_hooks(model, event):
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
    
    key = (model, event)
    hooks = _hooks.get(key, [])
    
    # Log hook discovery for debugging
    if hooks:
        logger.debug(f"Found {len(hooks)} hooks for {model.__name__}.{event}")
        for handler_cls, method_name, condition, priority in hooks:
            logger.debug(f"  - {handler_cls.__name__}.{method_name} (priority: {priority})")
    else:
        logger.debug(f"No hooks found for {model.__name__}.{event}")
    
    return hooks


def list_all_hooks():
    """Debug function to list all registered hooks."""
    return _hooks


def clear_hooks():
    """Clear all registered hooks (mainly for testing)."""
    global _hooks
    _hooks.clear()
    logger.debug("All hooks cleared")
