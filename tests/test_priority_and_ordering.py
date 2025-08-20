"""
Tests for hook priority and execution ordering.
"""

from django.contrib.auth.models import User
from django.db import models
from django.test import TestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.constants import AFTER_CREATE, BEFORE_CREATE, BEFORE_UPDATE
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.models import HookModelMixin
from django_bulk_hooks.priority import Priority


# Test Model
class OrderedTestModel(HookModelMixin):
    """Test model for priority and ordering testing."""

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)


# Global state tracking
execution_order = []


def reset_execution_order():
    """Reset the execution order tracking."""
    global execution_order
    execution_order = []


class HighPriorityHooks(Hook):
    """High priority hook handlers."""

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.HIGH)
    def high_priority_before_create(self, new_records, old_records):
        execution_order.append("high_priority_before_create")

    @hook(BEFORE_UPDATE, model=OrderedTestModel, priority=Priority.HIGH)
    def high_priority_before_update(self, new_records, old_records):
        execution_order.append("high_priority_before_update")

    @hook(AFTER_CREATE, model=OrderedTestModel, priority=Priority.HIGH)
    def high_priority_after_create(self, new_records, old_records):
        execution_order.append("high_priority_after_create")


class NormalPriorityHooks(Hook):
    """Normal priority hook handlers."""

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.NORMAL)
    def normal_priority_before_create(self, new_records, old_records):
        execution_order.append("normal_priority_before_create")

    @hook(BEFORE_UPDATE, model=OrderedTestModel, priority=Priority.NORMAL)
    def normal_priority_before_update(self, new_records, old_records):
        execution_order.append("normal_priority_before_update")

    @hook(AFTER_CREATE, model=OrderedTestModel, priority=Priority.NORMAL)
    def normal_priority_after_create(self, new_records, old_records):
        execution_order.append("normal_priority_after_create")


class LowPriorityHooks(Hook):
    """Low priority hook handlers."""

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.LOW)
    def low_priority_before_create(self, new_records, old_records):
        execution_order.append("low_priority_before_create")

    @hook(BEFORE_UPDATE, model=OrderedTestModel, priority=Priority.LOW)
    def low_priority_before_update(self, new_records, old_records):
        execution_order.append("low_priority_before_update")

    @hook(AFTER_CREATE, model=OrderedTestModel, priority=Priority.LOW)
    def low_priority_after_create(self, new_records, old_records):
        execution_order.append("low_priority_after_create")


class NumericPriorityHooks(Hook):
    """Hook handlers with numeric priorities."""

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=100)  # Very high
    def very_high_numeric_priority(self, new_records, old_records):
        execution_order.append("very_high_numeric_priority")

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=25)  # Between LOW and NORMAL
    def custom_numeric_priority(self, new_records, old_records):
        execution_order.append("custom_numeric_priority")

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=1)  # Very low
    def very_low_numeric_priority(self, new_records, old_records):
        execution_order.append("very_low_numeric_priority")


class MultipleHooksPerClassHooks(Hook):
    """Multiple hooks in the same class to test ordering within a class."""

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.NORMAL)
    def first_hook(self, new_records, old_records):
        execution_order.append("first_hook")

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.NORMAL)
    def second_hook(self, new_records, old_records):
        execution_order.append("second_hook")

    @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.NORMAL)
    def third_hook(self, new_records, old_records):
        execution_order.append("third_hook")


class PriorityOrderingTestCase(TestCase):
    """Test case for hook priority and execution ordering."""

    def setUp(self):
        """Set up test data."""
        reset_execution_order()

        # Clear the global hook registry and force re-registration
        from django_bulk_hooks.constants import (
            AFTER_CREATE,
            BEFORE_CREATE,
            BEFORE_UPDATE,
        )
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import _hooks, register_hook

        # Clear the registry
        _hooks.clear()

        self.user = User.objects.create_user(username="testuser")

        # Create instances of all Hook classes to trigger metaclass registration
        # This ensures all hooks are registered before we manually override some
        self.high_priority_hooks = HighPriorityHooks()
        self.normal_priority_hooks = NormalPriorityHooks()
        self.low_priority_hooks = LowPriorityHooks()
        self.numeric_priority_hooks = NumericPriorityHooks()
        self.multiple_hooks_per_class = MultipleHooksPerClassHooks()

        # Clear the registry again after metaclass registration to avoid conflicts
        _hooks.clear()

        # Now manually register the hooks to ensure proper test control
        # This overrides the metaclass registration for testing purposes
        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            HighPriorityHooks,
            "high_priority_before_create",
            None,
            Priority.HIGH,
        )
        register_hook(
            OrderedTestModel,
            AFTER_CREATE,
            HighPriorityHooks,
            "high_priority_after_create",
            None,
            Priority.HIGH,
        )
        register_hook(
            OrderedTestModel,
            BEFORE_UPDATE,
            HighPriorityHooks,
            "high_priority_before_update",
            None,
            Priority.HIGH,
        )

        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            NormalPriorityHooks,
            "normal_priority_before_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            OrderedTestModel,
            AFTER_CREATE,
            NormalPriorityHooks,
            "normal_priority_after_create",
            None,
            Priority.NORMAL,
        )
        register_hook(
            OrderedTestModel,
            BEFORE_UPDATE,
            NormalPriorityHooks,
            "normal_priority_before_update",
            None,
            Priority.NORMAL,
        )

        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            LowPriorityHooks,
            "low_priority_before_create",
            None,
            Priority.LOW,
        )
        register_hook(
            OrderedTestModel,
            AFTER_CREATE,
            LowPriorityHooks,
            "low_priority_after_create",
            None,
            Priority.LOW,
        )
        register_hook(
            OrderedTestModel,
            BEFORE_UPDATE,
            LowPriorityHooks,
            "low_priority_before_update",
            None,
            Priority.LOW,
        )

        # Register numeric priority hooks
        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            NumericPriorityHooks,
            "very_high_numeric_priority",
            None,
            100,
        )
        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            NumericPriorityHooks,
            "custom_numeric_priority",
            None,
            25,
        )
        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            NumericPriorityHooks,
            "very_low_numeric_priority",
            None,
            1,
        )

        # Register multiple hooks per class
        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            MultipleHooksPerClassHooks,
            "first_hook",
            None,
            Priority.NORMAL,
        )
        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            MultipleHooksPerClassHooks,
            "second_hook",
            None,
            Priority.NORMAL,
        )
        register_hook(
            OrderedTestModel,
            BEFORE_CREATE,
            MultipleHooksPerClassHooks,
            "third_hook",
            None,
            Priority.NORMAL,
        )

    def test_basic_priority_ordering_before_create(self):
        """Test that BEFORE_CREATE hooks execute in priority order."""
        reset_execution_order()

        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        # Extract before_create hooks from execution order
        before_create_hooks = [
            hook for hook in execution_order if "before_create" in hook
        ]

        expected_order = [
            "high_priority_before_create",
            "normal_priority_before_create",
            "low_priority_before_create",
        ]

        self.assertEqual(before_create_hooks, expected_order)

    def test_basic_priority_ordering_after_create(self):
        """Test that AFTER_CREATE hooks execute in priority order."""
        reset_execution_order()

        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        # Extract after_create hooks from execution order
        after_create_hooks = [
            hook for hook in execution_order if "after_create" in hook
        ]

        expected_order = [
            "high_priority_after_create",
            "normal_priority_after_create",
            "low_priority_after_create",
        ]

        self.assertEqual(after_create_hooks, expected_order)

    def test_priority_ordering_before_update(self):
        """Test that BEFORE_UPDATE hooks execute in priority order."""
        # Create object first
        obj = OrderedTestModel.objects.create(
            name="Test", value=1, created_by=self.user
        )
        reset_execution_order()

        # Update to trigger BEFORE_UPDATE hooks
        obj.value = 2
        obj.save()

        # Extract before_update hooks from execution order
        before_update_hooks = [
            hook for hook in execution_order if "before_update" in hook
        ]

        expected_order = [
            "high_priority_before_update",
            "normal_priority_before_update",
            "low_priority_before_update",
        ]

        self.assertEqual(before_update_hooks, expected_order)

    def test_numeric_priority_ordering(self):
        """Test that numeric priorities are ordered correctly."""
        reset_execution_order()

        # Register numeric priority hooks
        numeric_hooks = NumericPriorityHooks()

        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        # Extract numeric priority hooks from execution order
        numeric_priority_hooks = [
            hook for hook in execution_order if "numeric_priority" in hook
        ]

        expected_order = [
            "very_high_numeric_priority",  # priority=100
            "custom_numeric_priority",  # priority=25
            "very_low_numeric_priority",  # priority=1
        ]

        self.assertEqual(numeric_priority_hooks, expected_order)

    def test_mixed_priority_types(self):
        """Test mixing Priority enum and numeric priorities."""
        reset_execution_order()

        # The numeric priority hooks are already registered in setUp
        # No need to create instances here as it would trigger metaclass registration

        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        # All before_create hooks should be ordered by priority value
        # Priority.HIGH = 75, Priority.NORMAL = 50, Priority.LOW = 25
        # Numeric: 100, 25, 1
        
        # Get the method names of all registered BEFORE_CREATE hooks to filter correctly
        from django_bulk_hooks.registry import get_hooks
        before_create_hooks_registered = get_hooks(OrderedTestModel, BEFORE_CREATE)
        registered_method_names = [method_name for _, method_name, _, _ in before_create_hooks_registered]
        
        # Filter execution order to only include BEFORE_CREATE hooks that executed
        before_create_hooks = [
            hook for hook in execution_order if hook in registered_method_names
        ]

        # Expected order based on priority values (highest to lowest)
        expected_contains = [
            "very_high_numeric_priority",  # 100
            "high_priority_before_create",  # 75
            "normal_priority_before_create",  # 50
            # custom_numeric_priority (25) and low_priority_before_create (25) - order may vary
            "very_low_numeric_priority",  # 1
        ]

        # Check that very high and very low are in correct positions
        self.assertEqual(before_create_hooks[0], "very_high_numeric_priority")
        self.assertEqual(before_create_hooks[-1], "very_low_numeric_priority")
        self.assertIn("high_priority_before_create", before_create_hooks[:2])
        self.assertIn("normal_priority_before_create", before_create_hooks)

    def test_bulk_operations_maintain_priority(self):
        """Test that bulk operations maintain hook priority ordering."""
        reset_execution_order()

        # Bulk create
        objects = [
            OrderedTestModel(name="Test 1", value=1, created_by=self.user),
            OrderedTestModel(name="Test 2", value=2, created_by=self.user),
        ]
        OrderedTestModel.objects.bulk_create(objects)

        # Priority should be maintained even in bulk operations
        before_create_hooks = [
            hook for hook in execution_order if "before_create" in hook
        ]

        expected_order = [
            "high_priority_before_create",
            "normal_priority_before_create",
            "low_priority_before_create",
        ]

        self.assertEqual(before_create_hooks, expected_order)

    def test_multiple_hooks_same_priority_same_class(self):
        """Test ordering of multiple hooks with same priority in same class."""
        reset_execution_order()

        # Register hooks with same priority in same class
        multiple_hooks = MultipleHooksPerClassHooks()

        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        # Extract hooks from the multiple hooks class
        multiple_class_hooks = [
            hook
            for hook in execution_order
            if hook in ["first_hook", "second_hook", "third_hook"]
        ]

        # All three should be present
        self.assertEqual(len(multiple_class_hooks), 3)
        self.assertIn("first_hook", multiple_class_hooks)
        self.assertIn("second_hook", multiple_class_hooks)
        self.assertIn("third_hook", multiple_class_hooks)

        # The order within same priority is not guaranteed, but they should all execute

    def test_priority_with_conditions(self):
        """Test that priority is respected even with conditions."""

        class ConditionalPriorityHooks(Hook):
            @hook(BEFORE_UPDATE, model=OrderedTestModel, priority=Priority.HIGH)
            def high_priority_conditional(self, new_records, old_records):
                execution_order.append("high_priority_conditional")

            @hook(BEFORE_UPDATE, model=OrderedTestModel, priority=Priority.LOW)
            def low_priority_conditional(self, new_records, old_records):
                execution_order.append("low_priority_conditional")

        conditional_hooks = ConditionalPriorityHooks()

        # Create and update object
        obj = OrderedTestModel.objects.create(
            name="Test", value=1, created_by=self.user
        )
        reset_execution_order()

        obj.value = 2
        obj.save()

        # Extract conditional hooks
        conditional_hooks_order = [
            hook for hook in execution_order if "conditional" in hook
        ]

        expected_order = ["high_priority_conditional", "low_priority_conditional"]

        self.assertEqual(conditional_hooks_order, expected_order)

    def test_hook_registration_order_independence(self):
        """Test that registration order doesn't affect execution priority."""

        # Create a new test to verify that regardless of when hooks are registered,
        # they execute in priority order

        class LateRegisteredHooks(Hook):
            @hook(
                BEFORE_CREATE, model=OrderedTestModel, priority=Priority.HIGH + 10
            )  # Higher than existing
            def late_high_priority(self, new_records, old_records):
                execution_order.append("late_high_priority")

        reset_execution_order()

        # Register after other hooks are already registered
        late_hooks = LateRegisteredHooks()

        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        # The late-registered high priority hook should still execute first
        before_create_hooks = [
            hook
            for hook in execution_order
            if "before_create" in hook or "late_high_priority" in hook
        ]

        # late_high_priority should be first due to highest priority
        self.assertEqual(before_create_hooks[0], "late_high_priority")

    def test_priority_with_inheritance(self):
        """Test priority behavior with model inheritance."""

        class ChildModel(OrderedTestModel):
            extra_field = models.CharField(max_length=50, default="")

        class InheritanceHooks(Hook):
            @hook(BEFORE_CREATE, model=ChildModel, priority=Priority.HIGH)
            def child_high_priority(self, new_records, old_records):
                execution_order.append("child_high_priority")

            @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.LOW)
            def parent_low_priority(self, new_records, old_records):
                execution_order.append("parent_low_priority")

        inheritance_hooks = InheritanceHooks()
        reset_execution_order()

        # Note: This test depends on how inheritance is handled in the framework
        # It may need adjustment based on the actual implementation

    def test_exception_in_high_priority_hook(self):
        """Test that exception in high priority hook prevents lower priority hooks."""

        class FailingHook(Hook):
            @hook(BEFORE_CREATE, model=OrderedTestModel, priority=200)  # Higher than all other hooks
            def failing_high_priority(self, new_records, old_records):
                execution_order.append("failing_high_priority")
                raise ValueError("High priority hook failed")

        failing_hook = FailingHook()
        reset_execution_order()

        with self.assertRaises(ValueError):
            OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        # Only the failing hook should have executed
        self.assertEqual(execution_order, ["failing_high_priority"])

    def test_performance_with_many_hooks(self):
        """Test performance doesn't degrade significantly with many hooks."""

        class ManyHooksClass(Hook):
            pass

        # Dynamically create many hooks
        for i in range(20):

            def make_hook(index):
                def hook_func(self, new_records, old_records):
                    execution_order.append(f"hook_{index}")

                return hook_func

            # Add hook method to class with varying priorities
            priority = Priority.HIGH - (i * 2)  # Varying priorities
            hook_method = hook(
                BEFORE_CREATE, model=OrderedTestModel, priority=priority
            )(make_hook(i))
            setattr(ManyHooksClass, f"hook_{i}", hook_method)

            # Manually register the hook since metaclass registration happened before dynamic method addition
            from django_bulk_hooks.registry import register_hook
            register_hook(
                OrderedTestModel,
                BEFORE_CREATE,
                ManyHooksClass,
                f"hook_{i}",
                None,
                priority,
            )

        many_hooks = ManyHooksClass()
        reset_execution_order()

        # This should complete without significant performance issues
        start_time = __import__("time").time()
        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)
        end_time = __import__("time").time()

        # Should complete reasonably quickly (adjust threshold as needed)
        self.assertLess(end_time - start_time, 1.0)  # Less than 1 second

        # All hooks should have executed
        hook_calls = [call for call in execution_order if call.startswith("hook_")]
        self.assertEqual(len(hook_calls), 20)


class DefaultPriorityTestCase(TestCase):
    """Test case for default priority behavior."""

    def setUp(self):
        """Set up test data."""
        reset_execution_order()

        # Clear the global hook registry
        from django_bulk_hooks.registry import _hooks

        _hooks.clear()

        self.user = User.objects.create_user(username="testuser")

    def test_default_priority_is_normal(self):
        """Test that hooks without explicit priority default to NORMAL."""

        class DefaultPriorityHooks(Hook):
            @hook(BEFORE_CREATE, model=OrderedTestModel)  # No priority specified
            def default_priority_hook(self, new_records, old_records):
                execution_order.append("default_priority_hook")

            @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.HIGH)
            def explicit_high_priority(self, new_records, old_records):
                execution_order.append("explicit_high_priority")

            @hook(BEFORE_CREATE, model=OrderedTestModel, priority=Priority.LOW)
            def explicit_low_priority(self, new_records, old_records):
                execution_order.append("explicit_low_priority")

        default_hooks = DefaultPriorityHooks()
        reset_execution_order()

        OrderedTestModel.objects.create(name="Test", value=1, created_by=self.user)

        expected_order = [
            "explicit_high_priority",  # HIGH
            "default_priority_hook",  # NORMAL (default)
            "explicit_low_priority",  # LOW
        ]

        before_create_hooks = [
            hook for hook in execution_order if hook in expected_order
        ]

        self.assertEqual(before_create_hooks, expected_order)
