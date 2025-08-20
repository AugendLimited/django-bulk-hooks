import logging
from django.db import models, transaction
from django_bulk_hooks.constants import (
    AFTER_CREATE,
    AFTER_DELETE,
    AFTER_UPDATE,
    BEFORE_CREATE,
    BEFORE_DELETE,
    BEFORE_UPDATE,
    VALIDATE_CREATE,
    VALIDATE_DELETE,
    VALIDATE_UPDATE,
)
from django_bulk_hooks.context import HookContext
from django_bulk_hooks.engine import run
from django_bulk_hooks.manager import BulkHookManager

logger = logging.getLogger(__name__)


class HookModelMixin(models.Model):
    objects = BulkHookManager()

    class Meta:
        abstract = True

    def clean(self, bypass_hooks=False):
        """
        Override clean() to trigger validation hooks.
        This ensures that when Django calls clean() (like in admin forms),
        it triggers the VALIDATE_* hooks for validation only.
        """
        super().clean()

        # If bypass_hooks is True, skip validation hooks
        if bypass_hooks:
            return

        # Determine if this is a create or update operation
        is_create = self.pk is None

        if is_create:
            # For create operations, run VALIDATE_CREATE hooks for validation
            ctx = HookContext(self.__class__, bypass_hooks)
            run(self.__class__, VALIDATE_CREATE, [self], ctx=ctx)
        else:
            # For update operations, run VALIDATE_UPDATE hooks for validation
            try:
                # Use _base_manager to avoid triggering hooks recursively
                old_instance = self.__class__._base_manager.get(pk=self.pk)
                ctx = HookContext(self.__class__, bypass_hooks)
                run(self.__class__, VALIDATE_UPDATE, [self], [old_instance], ctx=ctx)
            except self.__class__.DoesNotExist:
                # If the old instance doesn't exist, treat as create
                ctx = HookContext(self.__class__, bypass_hooks)
                run(self.__class__, VALIDATE_CREATE, [self], ctx=ctx)

    def save(self, *args, bypass_hooks=False, **kwargs):
        # If bypass_hooks is True, call the parent save directly within a bypass context
        if bypass_hooks:
            logger.debug(f"save() called with bypass_hooks=True for {self.__class__.__name__} pk={self.pk}")
            with HookContext(self.__class__, bypass_hooks=True):
                return super().save(*args, **kwargs)

        # Only create a new transaction if we're not already in one
        # This allows for proper nested transaction handling
        from django.db import connection
        if connection.in_atomic_block:
            # We're already in a transaction, don't create a new one
            return self._save_with_hooks(*args, **kwargs)
        else:
            # We're not in a transaction, so create one
            with transaction.atomic():
                return self._save_with_hooks(*args, **kwargs)

    def _save_with_hooks(self, *args, **kwargs):
        """Internal method to handle save with hooks."""
        is_create = self.pk is None
        
        if is_create:
            logger.debug(f"save() creating new {self.__class__.__name__} instance")
            # For create operations, we don't have old records
            ctx = HookContext(self.__class__, bypass_hooks=False)
            
            # Run hooks - if any fail, the transaction will be rolled back
            run(self.__class__, VALIDATE_CREATE, [self], ctx=ctx)
            run(self.__class__, BEFORE_CREATE, [self], ctx=ctx)

            super().save(*args, **kwargs)

            run(self.__class__, AFTER_CREATE, [self], ctx=ctx)
        else:
            logger.debug(f"save() updating existing {self.__class__.__name__} instance pk={self.pk}")
            # For update operations, we need to get the old record
            try:
                # Use _base_manager to avoid triggering hooks recursively
                old_instance = self.__class__._base_manager.get(pk=self.pk)
                ctx = HookContext(self.__class__, bypass_hooks=False)
                
                # Run hooks - if any fail, the transaction will be rolled back
                run(self.__class__, VALIDATE_UPDATE, [self], [old_instance], ctx=ctx)
                run(self.__class__, BEFORE_UPDATE, [self], [old_instance], ctx=ctx)

                super().save(*args, **kwargs)

                run(self.__class__, AFTER_UPDATE, [self], [old_instance], ctx=ctx)
            except self.__class__.DoesNotExist:
                # If the old instance doesn't exist, treat as create
                ctx = HookContext(self.__class__, bypass_hooks=False)
                
                # Run hooks - if any fail, the transaction will be rolled back
                run(self.__class__, VALIDATE_CREATE, [self], ctx=ctx)
                run(self.__class__, BEFORE_CREATE, [self], ctx=ctx)

                super().save(*args, **kwargs)

                run(self.__class__, AFTER_CREATE, [self], ctx=ctx)

        return self

    def delete(self, *args, bypass_hooks=False, **kwargs):
        # If bypass_hooks is True, call the parent delete directly within a bypass context
        if bypass_hooks:
            with HookContext(self.__class__, bypass_hooks=True):
                return super().delete(*args, **kwargs)

        # Only create a new transaction if we're not already in one
        # This allows for proper nested transaction handling
        from django.db import connection
        if connection.in_atomic_block:
            # We're already in a transaction, don't create a new one
            return self._delete_with_hooks(*args, **kwargs)
        else:
            # We're not in a transaction, so create one
            with transaction.atomic():
                return self._delete_with_hooks(*args, **kwargs)

    def _delete_with_hooks(self, *args, **kwargs):
        """Internal method to handle delete with hooks."""
        ctx = HookContext(self.__class__, bypass_hooks=False)

        # Run hooks - if any fail, the transaction will be rolled back
        run(self.__class__, VALIDATE_DELETE, [self], ctx=ctx)

        # Then run business logic hooks
        run(self.__class__, BEFORE_DELETE, [self], ctx=ctx)

        result = super().delete(*args, **kwargs)

        run(self.__class__, AFTER_DELETE, [self], ctx=ctx)
        return result
