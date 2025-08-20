import logging

from django.core.exceptions import ValidationError

from django_bulk_hooks.registry import get_hooks

logger = logging.getLogger(__name__)


def run(model_cls, event, new_records, old_records=None, ctx=None):
    """
    Run hooks for a given model, event, and records.
    
    Args:
        model_cls: The Django model class
        event: The hook event (e.g., 'before_create', 'after_update')
        new_records: List of new/updated records
        old_records: List of original records (for comparison)
        ctx: Optional hook context
    """
    if not new_records:
        return

    # Get hooks for this model and event
    hooks = get_hooks(model_cls, event)

    if not hooks:
        return

    logger.debug(f"Running {len(hooks)} hooks for {model_cls.__name__}.{event} ({len(new_records)} records)")
    
    # Check if we're in a bypass context
    if ctx and hasattr(ctx, 'bypass_hooks') and ctx.bypass_hooks:
        logger.debug("Hook execution bypassed")
        return

    # For BEFORE_* events, run model.clean() first for validation
    if event.startswith("before_"):
        for instance in new_records:
            try:
                instance.clean()
            except ValidationError as e:
                logger.error("Validation failed for %s: %s", instance, e)
                raise

    # Process hooks in priority order (highest priority first)
    # Registry now sorts by priority (highest first)
    for handler_cls, method_name, condition, priority in hooks:
        logger.debug(f"Processing {handler_cls.__name__}.{method_name} (priority: {priority})")
        
        try:
            handler_instance = handler_cls()
            func = getattr(handler_instance, method_name)
        except Exception as e:
            logger.error(f"Failed to instantiate {handler_cls.__name__}: {e}")
            continue

        to_process_new = []
        to_process_old = []

        for new, original in zip(
            new_records,
            old_records or [None] * len(new_records),
            strict=True,
        ):
            if not condition:
                to_process_new.append(new)
                to_process_old.append(original)
            else:
                try:
                    condition_result = condition.check(new, original)
                    if condition_result:
                        to_process_new.append(new)
                        to_process_old.append(original)
                except Exception as e:
                    logger.error(f"Condition check failed for {handler_cls.__name__}.{method_name}: {e}")
                    continue

        if to_process_new:
            logger.debug(f"Executing {handler_cls.__name__}.{method_name} for {len(to_process_new)} records")
            try:
                func(
                    new_records=to_process_new,
                    old_records=to_process_old if any(x is not None for x in to_process_old) else None,
                )
            except Exception as e:
                logger.error(f"Hook execution failed in {handler_cls.__name__}.{method_name}: {e}")
                # Re-raise the exception to ensure proper error handling
                raise
