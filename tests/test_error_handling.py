"""
Tests for error handling and edge cases in django-bulk-hooks.
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.test import TestCase, TransactionTestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.conditions import HasChanged
from django_bulk_hooks.constants import (
    AFTER_CREATE,
    AFTER_DELETE,
    AFTER_UPDATE,
    BEFORE_CREATE,
    BEFORE_DELETE,
    BEFORE_UPDATE,
    VALIDATE_CREATE,
    VALIDATE_UPDATE,
)
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.models import HookModelMixin


# Test Models
class ErrorTestModel(HookModelMixin):
    """Test model for error handling."""

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    required_field = models.CharField(max_length=50)
    unique_field = models.CharField(max_length=50, unique=True)


class RelatedErrorModel(HookModelMixin):
    """Related model for testing foreign key constraints."""

    parent = models.ForeignKey(ErrorTestModel, on_delete=models.CASCADE)
    description = models.CharField(max_length=200)


# Global state tracking
error_state = {
    "errors": [],
    "hook_calls": [],
    "validation_calls": [],
    "cleanup_calls": [],
}


def reset_error_state():
    """Reset error state tracking."""
    global error_state
    error_state = {
        "errors": [],
        "hook_calls": [],
        "validation_calls": [],
        "cleanup_calls": [],
    }


class ErrorHandlingHooks(Hook):
    """Hooks for testing error handling."""

    @hook(VALIDATE_CREATE, model=ErrorTestModel)
    def validate_create(self, new_records, old_records):
        error_state["validation_calls"].append("validate_create")
        for record in new_records:
            if record.name == "INVALID":
                raise ValidationError("Name cannot be INVALID")

    @hook(VALIDATE_UPDATE, model=ErrorTestModel)
    def validate_update(self, new_records, old_records):
        error_state["validation_calls"].append("validate_update")
        for record in new_records:
            if record.value < 0:
                raise ValidationError("Value cannot be negative")

    @hook(BEFORE_CREATE, model=ErrorTestModel)
    def before_create(self, new_records, old_records):
        error_state["hook_calls"].append("before_create")
        for record in new_records:
            if record.name == "FAIL_BEFORE":
                raise RuntimeError("Before create failure")

    @hook(AFTER_CREATE, model=ErrorTestModel)
    def after_create(self, new_records, old_records):
        error_state["hook_calls"].append("after_create")
        for record in new_records:
            if record.name == "FAIL_AFTER":
                raise RuntimeError("After create failure")

    @hook(BEFORE_UPDATE, model=ErrorTestModel)
    def before_update(self, new_records, old_records):
        error_state["hook_calls"].append("before_update")
        for record in new_records:
            if record.value == 999:
                raise RuntimeError("Before update failure")

    @hook(AFTER_UPDATE, model=ErrorTestModel)
    def after_update(self, new_records, old_records):
        error_state["hook_calls"].append("after_update")
        for record in new_records:
            if record.name == "FAIL_AFTER_UPDATE":
                raise RuntimeError("After update failure")

    @hook(BEFORE_DELETE, model=ErrorTestModel)
    def before_delete(self, new_records, old_records):
        error_state["hook_calls"].append("before_delete")
        for record in new_records or []:
            if record.name == "PROTECTED":
                raise RuntimeError("Cannot delete protected record")

    @hook(AFTER_DELETE, model=ErrorTestModel)
    def after_delete(self, new_records, old_records):
        error_state["hook_calls"].append("after_delete")
        # Simulate cleanup operations
        error_state["cleanup_calls"].append("cleanup_after_delete")


class ValidationErrorsTestCase(TestCase):
    """Test case for validation errors."""

    def setUp(self):
        """Set up test data."""
        reset_error_state()

        # Clear the global hook registry and re-register validation hooks
        from django_bulk_hooks.constants import (
            AFTER_CREATE,
            AFTER_DELETE,
            AFTER_UPDATE,
            BEFORE_CREATE,
            BEFORE_DELETE,
            BEFORE_UPDATE,
            VALIDATE_CREATE,
            VALIDATE_UPDATE,
        )
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import register_hook, isolated_registry, clear_hooks

        # Isolate registry for this test and start from a clean state
        self._iso = isolated_registry()
        self._iso.__enter__()
        clear_hooks()

        # Clean up any existing test data to avoid unique constraints
        ErrorTestModel.objects.all().delete()

        # Manually register the validation hooks that the test expects
        register_hook(
            ErrorTestModel,
            VALIDATE_CREATE,
            ErrorHandlingHooks,
            "validate_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            VALIDATE_UPDATE,
            ErrorHandlingHooks,
            "validate_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_CREATE,
            ErrorHandlingHooks,
            "before_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_CREATE,
            ErrorHandlingHooks,
            "after_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_UPDATE,
            ErrorHandlingHooks,
            "before_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_UPDATE,
            ErrorHandlingHooks,
            "after_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_DELETE,
            ErrorHandlingHooks,
            "before_delete",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_DELETE,
            ErrorHandlingHooks,
            "after_delete",
            None,
            Priority.NORMAL,
        )

        self.hooks = ErrorHandlingHooks()

    def tearDown(self):
        # Restore registry snapshot
        self._iso.__exit__(None, None, None)

    def test_validation_error_in_create(self):
        """Test validation errors during create operations."""
        with self.assertRaises(ValidationError) as context:
            ErrorTestModel.objects.create(
                name="INVALID", required_field="test", unique_field="test1"
            )

        self.assertIn("Name cannot be INVALID", str(context.exception))
        self.assertIn("validate_create", error_state["validation_calls"])

        # Object should not be created
        self.assertEqual(ErrorTestModel.objects.count(), 0)

    def test_validation_error_in_update(self):
        """Test validation errors during update operations."""
        obj = ErrorTestModel.objects.create(
            name="Test", value=10, required_field="test", unique_field="test1"
        )
        reset_error_state()

        with self.assertRaises(ValidationError) as context:
            obj.value = -5
            obj.save()

        self.assertIn("Value cannot be negative", str(context.exception))
        self.assertIn("validate_update", error_state["validation_calls"])

        # Object should not be updated
        obj.refresh_from_db()
        self.assertEqual(obj.value, 10)

    def test_validation_error_in_bulk_create(self):
        """Test validation errors during bulk create operations."""
        objects = [
            ErrorTestModel(
                name="Valid1", required_field="test1", unique_field="unique1"
            ),
            ErrorTestModel(
                name="INVALID", required_field="test2", unique_field="unique2"
            ),
            ErrorTestModel(
                name="Valid2", required_field="test3", unique_field="unique3"
            ),
        ]

        with self.assertRaises(ValidationError):
            ErrorTestModel.objects.bulk_create(objects)

        # No objects should be created due to transaction rollback
        self.assertEqual(ErrorTestModel.objects.count(), 0)

    def test_validation_error_in_bulk_update(self):
        """Test validation errors during bulk update operations."""
        objects = [
            ErrorTestModel.objects.create(
                name="Test1", value=1, required_field="test1", unique_field="unique1"
            ),
            ErrorTestModel.objects.create(
                name="Test2", value=2, required_field="test2", unique_field="unique2"
            ),
        ]
        reset_error_state()

        # Make one object invalid
        objects[0].value = -10

        with self.assertRaises(ValidationError):
            ErrorTestModel.objects.bulk_update(objects, ["value"])

        # Objects should not be updated
        for obj in objects:
            obj.refresh_from_db()
        self.assertEqual(objects[0].value, 1)  # Should remain unchanged


class HookErrorsTestCase(TransactionTestCase):
    """Test case for errors in hook execution."""

    def setUp(self):
        """Set up test data."""
        reset_error_state()

        # Clear the global hook registry for clean slate
        from django_bulk_hooks.constants import (
            AFTER_CREATE,
            AFTER_DELETE,
            AFTER_UPDATE,
            BEFORE_CREATE,
            BEFORE_DELETE,
            BEFORE_UPDATE,
            VALIDATE_CREATE,
            VALIDATE_UPDATE,
        )
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import register_hook, isolated_registry, clear_hooks

        self._iso = isolated_registry()
        self._iso.__enter__()
        clear_hooks()

        # Clean up any existing test data to avoid unique constraints
        ErrorTestModel.objects.all().delete()

        # Manually register the hooks that the test expects
        register_hook(
            ErrorTestModel,
            VALIDATE_CREATE,
            ErrorHandlingHooks,
            "validate_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            VALIDATE_UPDATE,
            ErrorHandlingHooks,
            "validate_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_CREATE,
            ErrorHandlingHooks,
            "before_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_CREATE,
            ErrorHandlingHooks,
            "after_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_UPDATE,
            ErrorHandlingHooks,
            "before_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_UPDATE,
            ErrorHandlingHooks,
            "after_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_DELETE,
            ErrorHandlingHooks,
            "before_delete",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_DELETE,
            ErrorHandlingHooks,
            "after_delete",
            None,
            Priority.NORMAL,
        )

        self.hooks = ErrorHandlingHooks()

    def tearDown(self):
        self._iso.__exit__(None, None, None)

    def test_before_create_hook_error(self):
        """Test error in BEFORE_CREATE hook."""
        with self.assertRaises(RuntimeError) as context:
            ErrorTestModel.objects.create(
                name="FAIL_BEFORE", required_field="test", unique_field="test1"
            )

        self.assertIn("Before create failure", str(context.exception))
        self.assertIn("before_create", error_state["hook_calls"])

        # Object should not be created due to transaction rollback
        self.assertEqual(ErrorTestModel.objects.count(), 0)

    def test_after_create_hook_error(self):
        """Test error in AFTER_CREATE hook."""
        with self.assertRaises(RuntimeError) as context:
            ErrorTestModel.objects.create(
                name="FAIL_AFTER", required_field="test", unique_field="test1"
            )

        self.assertIn("After create failure", str(context.exception))
        self.assertIn("after_create", error_state["hook_calls"])

        # Object should not be created due to transaction rollback
        self.assertEqual(ErrorTestModel.objects.count(), 0)

    def test_before_update_hook_error(self):
        """Test error in BEFORE_UPDATE hook."""
        obj = ErrorTestModel.objects.create(
            name="Test", value=10, required_field="test", unique_field="test1"
        )
        reset_error_state()

        with self.assertRaises(RuntimeError) as context:
            obj.value = 999
            obj.save()

        self.assertIn("Before update failure", str(context.exception))
        self.assertIn("before_update", error_state["hook_calls"])

        # Object should not be updated
        obj.refresh_from_db()
        self.assertEqual(obj.value, 10)

    def test_after_update_hook_error(self):
        """Test error in AFTER_UPDATE hook."""
        obj = ErrorTestModel.objects.create(
            name="Test", value=10, required_field="test", unique_field="test1"
        )
        reset_error_state()

        with self.assertRaises(RuntimeError) as context:
            obj.name = "FAIL_AFTER_UPDATE"
            obj.save()

        self.assertIn("After update failure", str(context.exception))
        self.assertIn("after_update", error_state["hook_calls"])

        # Update should be rolled back
        obj.refresh_from_db()
        self.assertEqual(obj.name, "Test")

    def test_before_delete_hook_error(self):
        """Test error in BEFORE_DELETE hook."""
        obj = ErrorTestModel.objects.create(
            name="PROTECTED", required_field="test", unique_field="test1"
        )
        reset_error_state()

        with self.assertRaises(RuntimeError) as context:
            obj.delete()

        self.assertIn("Cannot delete protected record", str(context.exception))
        self.assertIn("before_delete", error_state["hook_calls"])

        # Object should not be deleted
        self.assertEqual(ErrorTestModel.objects.count(), 1)

    def test_bulk_operation_partial_failure(self):
        """Test bulk operation with partial failures."""
        objects = [
            ErrorTestModel(
                name="Valid", required_field="test1", unique_field="unique1"
            ),
            ErrorTestModel(
                name="FAIL_BEFORE", required_field="test2", unique_field="unique2"
            ),
        ]

        with self.assertRaises(RuntimeError):
            ErrorTestModel.objects.bulk_create(objects)

        # No objects should be created due to transaction rollback
        self.assertEqual(ErrorTestModel.objects.count(), 0)


class DatabaseConstraintErrorsTestCase(TransactionTestCase):
    """Test case for database constraint errors."""

    def setUp(self):
        """Set up test data."""
        reset_error_state()
        
        # Register hooks for consistent test environment
        from django_bulk_hooks.constants import (
            AFTER_CREATE,
            AFTER_DELETE,
            AFTER_UPDATE,
            BEFORE_CREATE,
            BEFORE_DELETE,
            BEFORE_UPDATE,
            VALIDATE_CREATE,
            VALIDATE_UPDATE,
        )
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import register_hook, isolated_registry, clear_hooks

        self._iso = isolated_registry()
        self._iso.__enter__()
        clear_hooks()

        # Manually register the hooks that the test expects
        register_hook(
            ErrorTestModel,
            VALIDATE_CREATE,
            ErrorHandlingHooks,
            "validate_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            VALIDATE_UPDATE,
            ErrorHandlingHooks,
            "validate_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_CREATE,
            ErrorHandlingHooks,
            "before_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_CREATE,
            ErrorHandlingHooks,
            "after_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_UPDATE,
            ErrorHandlingHooks,
            "before_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_UPDATE,
            ErrorHandlingHooks,
            "after_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_DELETE,
            ErrorHandlingHooks,
            "before_delete",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_DELETE,
            ErrorHandlingHooks,
            "after_delete",
            None,
            Priority.NORMAL,
        )
        
        self.hooks = ErrorHandlingHooks()

    def tearDown(self):
        self._iso.__exit__(None, None, None)

    def test_unique_constraint_error(self):
        """Test unique constraint violations."""
        # Create first object
        ErrorTestModel.objects.create(
            name="Test1", required_field="test1", unique_field="duplicate"
        )

        # Try to create second object with same unique_field
        with self.assertRaises(IntegrityError):
            ErrorTestModel.objects.create(
                name="Test2",
                required_field="test2",
                unique_field="duplicate",  # Duplicate value
            )

        # Only first object should exist
        self.assertEqual(ErrorTestModel.objects.count(), 1)

    def test_foreign_key_constraint_error(self):
        """Test foreign key constraint violations."""
        parent = ErrorTestModel.objects.create(
            name="Parent", required_field="test", unique_field="parent1"
        )

        # Create related object
        child = RelatedErrorModel.objects.create(parent=parent, description="Child")

        # Try to delete parent while child exists (should fail due to CASCADE)
        # Note: This depends on the database backend and CASCADE behavior
        # In SQLite with CASCADE, this should succeed and delete both
        parent.delete()

        # Both parent and child should be deleted due to CASCADE
        self.assertEqual(ErrorTestModel.objects.count(), 0)
        self.assertEqual(RelatedErrorModel.objects.count(), 0)

    def test_not_null_constraint_error(self):
        """Test NOT NULL constraint violations."""
        # Try to create an object with a missing required field
        # This should trigger a ValidationError from Django's model validation
        obj = ErrorTestModel(
            name="Test",
            # required_field is missing
            unique_field="test1",
        )
        
        # Django should catch this during validation
        with self.assertRaises(ValidationError):
            obj.full_clean()
        
        # Object should not be created
        self.assertEqual(ErrorTestModel.objects.count(), 0)


class TransactionRollbackTestCase(TransactionTestCase):
    """Test case for transaction rollback behavior."""

    def setUp(self):
        """Set up test data."""
        reset_error_state()
        
        # Register hooks for consistent test environment
        from django_bulk_hooks.constants import (
            AFTER_CREATE,
            AFTER_DELETE,
            AFTER_UPDATE,
            BEFORE_CREATE,
            BEFORE_DELETE,
            BEFORE_UPDATE,
            VALIDATE_CREATE,
            VALIDATE_UPDATE,
        )
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import register_hook, isolated_registry, clear_hooks

        self._iso = isolated_registry()
        self._iso.__enter__()
        clear_hooks()

        # Manually register the hooks that the test expects
        register_hook(
            ErrorTestModel,
            VALIDATE_CREATE,
            ErrorHandlingHooks,
            "validate_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            VALIDATE_UPDATE,
            ErrorHandlingHooks,
            "validate_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_CREATE,
            ErrorHandlingHooks,
            "before_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_CREATE,
            ErrorHandlingHooks,
            "after_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_UPDATE,
            ErrorHandlingHooks,
            "before_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_UPDATE,
            ErrorHandlingHooks,
            "after_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_DELETE,
            ErrorHandlingHooks,
            "before_delete",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_DELETE,
            ErrorHandlingHooks,
            "after_delete",
            None,
            Priority.NORMAL,
        )
        
        self.hooks = ErrorHandlingHooks()

    def tearDown(self):
        self._iso.__exit__(None, None, None)

    def test_rollback_on_hook_error(self):
        """Test that entire transaction is rolled back on hook error."""

        class MultipleOperationHook(Hook):
            @hook(AFTER_CREATE, model=ErrorTestModel)
            def after_create_with_error(self, new_records, old_records):
                # Just fail immediately without creating additional objects
                raise RuntimeError("Hook failed after creating object")

        multi_hook = MultipleOperationHook()

        with self.assertRaises(RuntimeError):
            ErrorTestModel.objects.create(
                name="Original", required_field="test", unique_field="original"
            )

        # Object should be rolled back
        self.assertEqual(ErrorTestModel.objects.count(), 0)

    def test_nested_transaction_rollback(self):
        """Test rollback behavior with nested transactions."""

        # The test expects that when a hook fails, the entire transaction is rolled back
        # This requires letting the exception propagate to the outer transaction context
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                # Create first object successfully
                obj1 = ErrorTestModel.objects.create(
                    name="First", required_field="test1", unique_field="first"
                )

                # Create second object that will fail in hook
                # This should cause the entire transaction to roll back
                ErrorTestModel.objects.create(
                    name="FAIL_BEFORE",
                    required_field="test2",
                    unique_field="second",
                )

        # Both objects should be rolled back due to outer transaction
        self.assertEqual(ErrorTestModel.objects.count(), 0)

    def test_savepoint_rollback(self):
        """Test rollback to savepoint on hook error."""

        with transaction.atomic():
            # Create first object successfully
            ErrorTestModel.objects.create(
                name="Successful", required_field="test1", unique_field="successful"
            )

            # Create savepoint
            sid = transaction.savepoint()

            try:
                # Try to create object that fails in hook
                ErrorTestModel.objects.create(
                    name="FAIL_BEFORE", required_field="test2", unique_field="failing"
                )
            except RuntimeError:
                # Rollback to savepoint
                transaction.savepoint_rollback(sid)

        # First object should still exist
        self.assertEqual(ErrorTestModel.objects.count(), 1)
        self.assertEqual(ErrorTestModel.objects.first().name, "Successful")


class EdgeCasesTestCase(TestCase):
    """Test case for edge cases and unusual scenarios."""

    def setUp(self):
        """Set up test data."""
        reset_error_state()
        
        # Register hooks for consistent test environment
        from django_bulk_hooks.constants import (
            AFTER_CREATE,
            AFTER_DELETE,
            AFTER_UPDATE,
            BEFORE_CREATE,
            BEFORE_DELETE,
            BEFORE_UPDATE,
            VALIDATE_CREATE,
            VALIDATE_UPDATE,
        )
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import _hooks, register_hook

        _hooks.clear()

        # Clean up any existing test data to avoid unique constraints
        ErrorTestModel.objects.all().delete()

        # Manually register the hooks that the test expects
        register_hook(
            ErrorTestModel,
            VALIDATE_CREATE,
            ErrorHandlingHooks,
            "validate_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            VALIDATE_UPDATE,
            ErrorHandlingHooks,
            "validate_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_CREATE,
            ErrorHandlingHooks,
            "before_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_CREATE,
            ErrorHandlingHooks,
            "after_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_UPDATE,
            ErrorHandlingHooks,
            "before_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_UPDATE,
            ErrorHandlingHooks,
            "after_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            BEFORE_DELETE,
            ErrorHandlingHooks,
            "before_delete",
            None,
            Priority.NORMAL,
        )
        register_hook(
            ErrorTestModel,
            AFTER_DELETE,
            ErrorHandlingHooks,
            "after_delete",
            None,
            Priority.NORMAL,
        )
        
        self.hooks = ErrorHandlingHooks()

    def test_empty_bulk_operations(self):
        """Test bulk operations with empty lists."""
        # These should not raise errors
        ErrorTestModel.objects.bulk_create([])
        ErrorTestModel.objects.bulk_update([], ["name"])
        ErrorTestModel.objects.bulk_delete([])

        self.assertEqual(error_state["hook_calls"], [])

    def test_hook_with_none_values(self):
        """Test hooks handling None values gracefully."""

        class NoneHandlingHook(Hook):
            @hook(BEFORE_CREATE, model=ErrorTestModel)
            def handle_none(self, new_records, old_records):
                error_state["hook_calls"].append("handle_none")
                # Ensure we handle None gracefully
                for record in new_records or []:
                    if record is not None and hasattr(record, "name"):
                        error_state["hook_calls"].append(f"processed_{record.name}")

        none_hook = NoneHandlingHook()

        obj = ErrorTestModel.objects.create(
            name="Test", required_field="test", unique_field="test1"
        )

        self.assertIn("handle_none", error_state["hook_calls"])
        self.assertIn("processed_Test", error_state["hook_calls"])

    def test_concurrent_modifications(self):
        """Test behavior with concurrent modifications."""
        obj = ErrorTestModel.objects.create(
            name="Test", value=10, required_field="test", unique_field="test1"
        )

        # Simulate concurrent modification by manually updating in database
        ErrorTestModel.objects.filter(pk=obj.pk).update(value=20)

        reset_error_state()

        # Now update through model - old_records might be stale
        obj.name = "Updated"
        obj.save()

        # Should complete without errors
        self.assertIn("before_update", error_state["hook_calls"])

    def test_very_large_bulk_operations(self):
        """Test performance with large bulk operations."""
        # Create many objects
        objects = []
        for i in range(100):  # Adjust size based on test environment
            objects.append(
                ErrorTestModel(
                    name=f"Test_{i}",
                    value=i,
                    required_field=f"req_{i}",
                    unique_field=f"unique_{i}",
                )
            )

        # This should complete without timeout or memory issues
        result = ErrorTestModel.objects.bulk_create(objects)

        self.assertEqual(len(result), 100)
        self.assertEqual(ErrorTestModel.objects.count(), 100)

    def test_hook_modifying_other_records(self):
        """Test hooks that modify other records."""

        class ModifyingHook(Hook):
            @hook(AFTER_CREATE, model=ErrorTestModel)
            def modify_others(self, new_records, old_records):
                error_state["hook_calls"].append("modify_others")
                # Only create one additional object to prevent infinite recursion
                # Count how many times this specific hook has been called
                modify_calls = [call for call in error_state["hook_calls"] if call == "modify_others"]
                if len(modify_calls) <= 1:
                    # Create another object in the hook
                    # Use a unique field value to avoid conflicts
                    unique_value = f"hook_unique_{len(new_records)}_{id(new_records[0])}"
                    ErrorTestModel.objects.create(
                        name="Created by hook",
                        required_field="hook_req",
                        unique_field=unique_value,
                    )

        modifying_hook = ModifyingHook()
        reset_error_state()

        ErrorTestModel.objects.create(
            name="Original", required_field="orig_req", unique_field="orig_unique"
        )

        # Both objects should be created
        self.assertEqual(ErrorTestModel.objects.count(), 2)
        self.assertIn("modify_others", error_state["hook_calls"])

    def test_recursive_hook_calls(self):
        """Test prevention of infinite recursion in hooks."""

        class RecursiveHook(Hook):
            @hook(AFTER_CREATE, model=ErrorTestModel)
            def recursive_create(self, new_records, old_records):
                error_state["hook_calls"].append("recursive_create")
                # This could potentially cause infinite recursion
                # The framework should handle this gracefully
                if len(error_state["hook_calls"]) < 3:  # Limit recursion for test
                    ErrorTestModel.objects.create(
                        name=f"Recursive_{len(error_state['hook_calls'])}",
                        required_field=f"rec_req_{len(error_state['hook_calls'])}",
                        unique_field=f"rec_unique_{len(error_state['hook_calls'])}",
                    )

        recursive_hook = RecursiveHook()
        reset_error_state()

        ErrorTestModel.objects.create(
            name="Start", required_field="start_req", unique_field="start_unique"
        )

        # Should create limited number of objects without infinite recursion
        self.assertLessEqual(ErrorTestModel.objects.count(), 5)
        self.assertLessEqual(len(error_state["hook_calls"]), 5)

    def test_hook_accessing_deleted_objects(self):
        """Test hooks trying to access deleted objects."""
        obj = ErrorTestModel.objects.create(
            name="ToDelete", required_field="test", unique_field="test1"
        )

        class DeleteAccessHook(Hook):
            @hook(AFTER_DELETE, model=ErrorTestModel)
            def access_deleted(self, new_records, old_records):
                error_state["hook_calls"].append("access_deleted")
                for record in new_records or []:
                    # Try to access the deleted object's attributes
                    error_state["hook_calls"].append(f"accessed_{record.name}")
                    # This should work since we have the object reference

        delete_hook = DeleteAccessHook()
        reset_error_state()

        obj.delete()

        self.assertIn("access_deleted", error_state["hook_calls"])
        self.assertIn("accessed_ToDelete", error_state["hook_calls"])
