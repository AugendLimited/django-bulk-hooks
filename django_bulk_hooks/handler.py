import inspect
import logging
import threading
from collections import deque

from django.db import transaction

from django_bulk_hooks.registry import get_hooks, register_hook

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


Hook = HookContextState()


class HookMeta(type):
    _registered = set()

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        for method_name, method in namespace.items():
            if hasattr(method, "hooks_hooks"):
                for model_cls, event, condition, priority in method.hooks_hooks:
                    key = (model_cls, event, cls, method_name)
                    if key not in HookMeta._registered:
                        # Check if the method has been decorated with select_related
                        select_related_fields = getattr(
                            method, "_select_related_fields", None
                        )

                        register_hook(
                            model=model_cls,
                            event=event,
                            handler_cls=cls,
                            method_name=method_name,
                            condition=condition,
                            priority=priority,
                            select_related_fields=select_related_fields,
                        )
                        HookMeta._registered.add(key)
        return cls


class HookHandler(metaclass=HookMeta):
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
        queue = get_hook_queue()
        queue.append((cls, event, model, new_records, old_records, kwargs))

        if len(queue) > 1:
            return  # nested call, will be processed by outermost

        # only outermost handle will process the queue
        while queue:
            cls_, event_, model_, new_, old_, kw_ = queue.popleft()
            cls_._process(event_, model_, new_, old_, **kw_)

    @classmethod
    def _process(
        cls,
        event,
        model,
        new_records,
        old_records,
        **kwargs,
    ):
        hook_vars.depth += 1
        hook_vars.new = new_records
        hook_vars.old = old_records
        hook_vars.event = event
        hook_vars.model = model

        hooks = sorted(get_hooks(model, event), key=lambda x: x[3])

        def _execute():
            new_local = new_records or []
            old_local = old_records or []
            if len(old_local) < len(new_local):
                old_local += [None] * (len(new_local) - len(old_local))

            for handler_cls, method_name, condition, priority, select_related_fields in hooks:
                # Apply select_related if specified to prevent queries in loops
                if select_related_fields:
                    from django_bulk_hooks.engine import _apply_select_related
                    new_local_with_related = _apply_select_related(new_local, select_related_fields)
                else:
                    new_local_with_related = new_local

                if condition is not None:
                    checks = [
                        condition.check(n, o) for n, o in zip(new_local_with_related, old_local)
                    ]
                    if not any(checks):
                        continue

                handler = handler_cls()
                method = getattr(handler, method_name)

                # Inspect the method signature to determine parameter order
                import inspect

                sig = inspect.signature(method)
                params = list(sig.parameters.keys())

                # Remove 'self' from params if it exists
                if params and params[0] == "self":
                    params = params[1:]

                # Always call with keyword arguments to make order irrelevant
                try:
                    method(
                        old_records=old_local,
                        new_records=new_local_with_related,
                        **kwargs,
                    )
                except Exception:
                    logger.exception(
                        "Error in hook %s.%s", handler_cls.__name__, method_name
                    )

        conn = transaction.get_connection()
        try:
            if conn.in_atomic_block and event.startswith("after_"):
                transaction.on_commit(_execute)
            else:
                _execute()
        finally:
            hook_vars.new = None
            hook_vars.old = None
            hook_vars.event = None
            hook_vars.model = None
            hook_vars.depth -= 1
