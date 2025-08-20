import logging

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import transaction

from django_bulk_hooks.registry import get_hooks
from django_bulk_hooks.handler import hook_vars

logger = logging.getLogger(__name__)


def run(model_cls, event, new_records, old_records=None, ctx=None):
    """
    Run hooks for a given model, event, and records.

    Production-grade executor:
    - Honors bypass_hooks via ctx
    - Runs model.clean() before BEFORE_* events for validation
    - Executes hooks in registry priority order with condition filtering
    - Exposes thread-local context via hook_vars during execution
    - AFTER_* timing is configurable via settings.BULK_HOOKS_AFTER_ON_COMMIT (default: False)

    Args:
        model_cls: The Django model class
        event: The hook event (e.g., 'before_create', 'after_update')
        new_records: List of new/updated records
        old_records: List of original records (for comparison)
        ctx: Optional hook context
    """
    if not new_records:
        return

    hooks = get_hooks(model_cls, event)
    if not hooks:
        return

    logger.debug(
        f"Running {len(hooks)} hooks for {model_cls.__name__}.{event} ({len(new_records)} records)"
    )

    # Check if we're in a bypass context
    if ctx and hasattr(ctx, "bypass_hooks") and ctx.bypass_hooks:
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

    def _execute():
        hook_vars.depth += 1
        hook_vars.new = new_records
        hook_vars.old = old_records
        hook_vars.event = event
        hook_vars.model = model_cls

        try:
            # Align old_records length with new_records for safe zipping
            local_old = old_records or []
            if len(local_old) < len(new_records):
                local_old = local_old + [None] * (len(new_records) - len(local_old))

            for handler_cls, method_name, condition, priority in hooks:
                try:
                    handler_instance = handler_cls()
                    func = getattr(handler_instance, method_name)
                except Exception as e:
                    logger.error(
                        "Failed to instantiate %s.%s: %s",
                        handler_cls.__name__,
                        method_name,
                        e,
                    )
                    continue

                # Condition filtering per record
                to_process_new = []
                to_process_old = []
                for new_obj, old_obj in zip(new_records, local_old, strict=True):
                    if not condition:
                        to_process_new.append(new_obj)
                        to_process_old.append(old_obj)
                    else:
                        try:
                            if condition.check(new_obj, old_obj):
                                to_process_new.append(new_obj)
                                to_process_old.append(old_obj)
                        except Exception as e:
                            logger.error(
                                "Condition failed for %s.%s: %s",
                                handler_cls.__name__,
                                method_name,
                                e,
                            )
                            continue

                if not to_process_new:
                    continue

                try:
                    func(
                        new_records=to_process_new,
                        old_records=to_process_old
                        if any(x is not None for x in to_process_old)
                        else None,
                    )
                except Exception:
                    logger.exception(
                        "Error in hook %s.%s", handler_cls.__name__, method_name
                    )
                    # Re-raise to ensure proper transactional behavior
                    raise
        finally:
            hook_vars.new = None
            hook_vars.old = None
            hook_vars.event = None
            hook_vars.model = None
            hook_vars.depth -= 1

    # AFTER_* timing policy: default immediate; optional on-commit
    use_on_commit = bool(getattr(django_settings, "BULK_HOOKS_AFTER_ON_COMMIT", False))
    if event.startswith("after_") and use_on_commit and transaction.get_connection().in_atomic_block:
        transaction.on_commit(_execute)
    else:
        _execute()
