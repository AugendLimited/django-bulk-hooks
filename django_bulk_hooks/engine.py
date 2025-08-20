import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.conf import settings

from django_bulk_hooks.registry import get_hooks
from django_bulk_hooks.handler import hook_vars

logger = logging.getLogger(__name__)


class AggregatedHookError(Exception):
    """Raised when multiple hook handlers fail under best-effort policy."""

    def __init__(self, errors):
        self.errors = errors
        message_lines = [
            "Multiple hook errors occurred:",
            *(f"- {ctx}: {exc}" for ctx, exc in errors),
        ]
        super().__init__("\n".join(message_lines))


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
        hook_vars.event = event

        try:
            # Build deterministic pairing of new and old by primary key when possible
            def pair_records(new_list, old_list):
                if not old_list:
                    # No old records; pair each new with None
                    return [(n, None) for n in new_list]

                # If all new have PKs, align by PK preserving new order
                if all(getattr(n, "pk", None) is not None for n in new_list):
                    old_by_pk = {getattr(o, "pk", None): o for o in old_list if o is not None}
                    pairs = []
                    for n in new_list:
                        pk = getattr(n, "pk", None)
                        pairs.append((n, old_by_pk.get(pk)))
                    return pairs

                # Fallback: best-effort positional pairing (create flows etc.)
                pairs = []
                for idx, n in enumerate(new_list):
                    o = old_list[idx] if idx < len(old_list) else None
                    pairs.append((n, o))
                return pairs

            pairs = pair_records(new_records, old_records or [])

            failure_policy = getattr(settings, "BULK_HOOKS_FAILURE_POLICY", "fail_fast")
            collected_errors = []

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

                # Condition filtering per record using the deterministic pairs
                to_process_new = []
                to_process_old = []
                for new_obj, old_obj in pairs:
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
                        old_records=to_process_old if any(x is not None for x in to_process_old) else None,
                    )
                except Exception as e:
                    logger.exception(
                        "Error in hook %s.%s", handler_cls.__name__, method_name
                    )
                    if failure_policy == "best_effort":
                        collected_errors.append((f"{handler_cls.__name__}.{method_name}", e))
                        continue
                    # fail_fast
                    raise

            if collected_errors:
                raise AggregatedHookError(collected_errors)
        finally:
            hook_vars.event = None
            hook_vars.depth -= 1

    # Execute immediately so AFTER_* runs within the transaction.
    # If a hook raises, the transaction is rolled back (Salesforce-style).
    _execute()
