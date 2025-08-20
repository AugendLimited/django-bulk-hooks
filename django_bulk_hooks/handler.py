import logging
import threading
from collections import deque

from django_bulk_hooks.registry import register_hook

logger = logging.getLogger(__name__)


# Thread-local hook context and hook state
class HookVars(threading.local):
    def __init__(self):
        self.new = None
        self.old = None
        self.event = None
        self.model = None
        self.depth = 0


hook_vars = HookVars()

# Hook queue per thread
_hook_context = threading.local()


def get_hook_queue():
    if not hasattr(_hook_context, "queue"):
        _hook_context.queue = deque()
    return _hook_context.queue


class HookContextState:
    @property
    def is_before(self):
        return hook_vars.event.startswith("before_") if hook_vars.event else False

    @property
    def is_after(self):
        return hook_vars.event.startswith("after_") if hook_vars.event else False

    @property
    def is_create(self):
        return "create" in hook_vars.event if hook_vars.event else False

    @property
    def is_update(self):
        return "update" in hook_vars.event if hook_vars.event else False

    @property
    def new(self):
        return hook_vars.new

    @property
    def old(self):
        return hook_vars.old

    @property
    def model(self):
        return hook_vars.model


class HookMeta(type):
    """Metaclass that automatically registers hooks when Hook classes are defined."""
    
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        
        # Register hooks for this class, including inherited methods
        # We need to check all methods in the MRO to handle inheritance
        for attr_name in dir(cls):
            if attr_name.startswith('_'):
                continue
                
            try:
                attr = getattr(cls, attr_name)
                if callable(attr) and hasattr(attr, "hooks_hooks"):
                    for model_cls, event, condition, priority in attr.hooks_hooks:
                        # Register the hook
                        register_hook(
                            model=model_cls,
                            event=event,
                            handler_cls=cls,
                            method_name=attr_name,
                            condition=condition,
                            priority=priority,
                        )
                        
                        logger.debug(
                            f"Registered hook {cls.__name__}.{attr_name} "
                            f"for {model_cls.__name__}.{event} with priority {priority}"
                        )
            except Exception as e:
                # Skip attributes that can't be accessed
                logger.debug(f"Skipping attribute {attr_name}: {e}")
                continue
        
        return cls


class Hook(metaclass=HookMeta):
    @classmethod
    def handle(
        cls,
        event: str,
        model: type,
        *,
        new_records: list = None,
        old_records: list = None,
        **kwargs,
    ) -> None:
        """
        Legacy entrypoint; delegate to the unified executor in engine.run.
        """
        from django_bulk_hooks.engine import run as run_engine
        run_engine(model, event, new_records or [], old_records or None, ctx=kwargs.get("ctx"))

    @classmethod
    def _process(
        cls,
        event,
        model,
        new_records,
        old_records,
        **kwargs,
    ):
        """
        Legacy internal; delegate to engine.run to avoid divergence.
        """
        from django_bulk_hooks.engine import run as run_engine
        run_engine(model, event, new_records or [], old_records or None, ctx=kwargs.get("ctx"))


# Create a global Hook instance for context access
HookContext = HookContextState()
