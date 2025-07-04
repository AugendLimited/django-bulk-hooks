import inspect
from functools import wraps

from django.core.exceptions import FieldDoesNotExist
from django_bulk_hooks.enums import DEFAULT_PRIORITY
from django_bulk_hooks.registry import register_hook


def hook(event, *, model, condition=None, priority=DEFAULT_PRIORITY):
    """
    Decorator to annotate a method with multiple hooks hook registrations.
    If no priority is provided, uses Priority.NORMAL (50).
    """

    def decorator(fn):
        if not hasattr(fn, "hooks_hooks"):
            fn.hooks_hooks = []
        fn.hooks_hooks.append((model, event, condition, priority))
        return fn

    return decorator


def select_related(*related_fields):
    """
    Decorator that preloads related fields in-place on `new_records`, before the hook logic runs.

    - Works with instance methods (resolves `self`)
    - Avoids replacing model instances
    - Populates Django's relation cache to avoid extra queries
    """

    def decorator(func):
        sig = inspect.signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()

            if "new_records" not in bound.arguments:
                raise TypeError(
                    "@preload_related requires a 'new_records' argument in the decorated function"
                )

            new_records = bound.arguments["new_records"]

            if not isinstance(new_records, list):
                raise TypeError(
                    f"@preload_related expects a list of model instances, got {type(new_records)}"
                )

            if not new_records:
                return func(*args, **kwargs)

            # Determine which instances actually need preloading
            model_cls = new_records[0].__class__
            ids_to_fetch = []
            for obj in new_records:
                if obj.pk is None:
                    continue
                # if any related field is not already cached on the instance,
                # mark it for fetching
                if any(field not in obj._state.fields_cache for field in related_fields):
                    ids_to_fetch.append(obj.pk)

            fetched = {}
            if ids_to_fetch:
                fetched = model_cls.objects.select_related(*related_fields).in_bulk(ids_to_fetch)

            for obj in new_records:
                preloaded = fetched.get(obj.pk)
                if not preloaded:
                    continue
                for field in related_fields:
                    if field in obj._state.fields_cache:
                        # don't override values that were explicitly set or already loaded
                        continue
                    if "." in field:
                        raise ValueError(
                            f"@preload_related does not support nested fields like '{field}'"
                        )

                    try:
                        f = model_cls._meta.get_field(field)
                        if not (
                            f.is_relation and not f.many_to_many and not f.one_to_many
                        ):
                            continue
                    except FieldDoesNotExist:
                        continue

                    try:
                        rel_obj = getattr(preloaded, field)
                        setattr(obj, field, rel_obj)
                        obj._state.fields_cache[field] = rel_obj
                    except AttributeError:
                        pass

            return func(*bound.args, **bound.kwargs)

        return wrapper

    return decorator


def bulk_hook(model_cls, event, when=None, priority=None):
    """
    Decorator to register a bulk hook for a model.
    
    Args:
        model_cls: The model class to hook into
        event: The event to hook into (e.g., BEFORE_UPDATE, AFTER_UPDATE)
        when: Optional condition for when the hook should run
        priority: Optional priority for hook execution order
    """
    def decorator(func):
        # Create a simple handler class for the function
        class FunctionHandler:
            def __init__(self):
                self.func = func
            
            def handle(self, new_instances, original_instances):
                return self.func(new_instances, original_instances)
        
        # Register the hook using the registry
        register_hook(
            model=model_cls,
            event=event,
            handler_cls=FunctionHandler,
            method_name='handle',
            condition=when,
            priority=priority or DEFAULT_PRIORITY,
        )
        return func
    return decorator
