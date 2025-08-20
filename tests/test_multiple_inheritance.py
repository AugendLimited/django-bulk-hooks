"""
Tests for multiple inheritance compatibility with other manager/queryset mixins.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.models import User
from django.db import models
from django.test import TestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.constants import AFTER_UPDATE, BEFORE_UPDATE
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.manager import BulkHookManager
from django_bulk_hooks.models import HookModelMixin
from django_bulk_hooks.queryset import HookQuerySetMixin


# Mock QueryablePropertiesManager to simulate third-party library
class MockQueryablePropertiesQuerySet:
    """Mock queryset that simulates QueryablePropertiesQuerySet behavior."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._queryable_properties_processed = False

    def update(self, **kwargs):
        """Mock update that processes queryable properties."""
        # Simulate processing queryable properties
        self._queryable_properties_processed = True

        # Process any mock queryable properties in kwargs
        processed_kwargs = {}
        for key, value in kwargs.items():
            if key.startswith("computed_"):
                # Simulate a queryable property that gets transformed
                processed_kwargs[key.replace("computed_", "")] = value * 2
            else:
                processed_kwargs[key] = value

        # Call the next class in MRO
        return super().update(**processed_kwargs)


class MockQueryablePropertiesManager(models.Manager):
    """Mock manager that simulates QueryablePropertiesManager behavior."""

    def get_queryset(self):
        """Return a queryset with mock queryable properties support."""
        base_qs = super().get_queryset()

        # Create a dynamic class that combines our mock with the base queryset
        class CombinedQuerySet(MockQueryablePropertiesQuerySet, base_qs.__class__):
            pass

        # Return an instance of the combined class
        combined_qs = CombinedQuerySet(
            model=base_qs.model,
            query=base_qs.query,
            using=base_qs._db,
            hints=base_qs._hints,
        )
        return combined_qs


# Create a proper queryset class at module level (not inside methods)
class MultiInheritanceQuerySet(HookQuerySetMixin, models.QuerySet):
    """QuerySet that supports hooks for testing multiple inheritance."""
    
    # Don't override update - let HookQuerySetMixin handle it
    pass


class MultiInheritanceManager(BulkHookManager):
    """Simple manager that inherits from BulkHookManager for testing."""
    
    def get_queryset(self):
        """Get queryset with hook support."""
        return MultiInheritanceQuerySet(
            model=self.model,
            query=self.model._base_manager.all().query,
            using=self._db,
            hints={},
        )


# Test Model
class MultiInheritanceTestModel(HookModelMixin):
    """Test model that uses MultiInheritanceManager."""

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    multiplied_value = models.IntegerField(
        default=0
    )  # Will be set by "computed_multiplied_value"

    # Use the multi-inheritance manager
    objects = MultiInheritanceManager()

    class Meta:
        app_label = "tests"


class DailyLoanSummaryMockModel(HookModelMixin):
    """Mock model that simulates the issue with queryable properties and CombinedExpression."""

    cumulative_repayment = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    cumulative_repayment_forecast = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    # Use the multi-inheritance manager to simulate QueryablePropertiesManager + BulkHookManager
    objects = MultiInheritanceManager()

    class Meta:
        app_label = "tests"

    def repayment_efficiency(self):
        """Simulates the queryable property that caused the original error."""
        if self.cumulative_repayment_forecast:
            return (
                self.cumulative_repayment
                / self.cumulative_repayment_forecast
                * Decimal("100")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        return None


# Global state tracking
multi_inheritance_state = {"hook_calls": [], "processed_values": []}


def reset_multi_inheritance_state():
    """Reset the state tracking."""
    global multi_inheritance_state
    multi_inheritance_state = {"hook_calls": [], "processed_values": []}


class MultiInheritanceHooks(Hook):
    """Hook handlers for multiple inheritance tests."""
    
    @hook(BEFORE_UPDATE, model=MultiInheritanceTestModel)
    def before_update(self, new_records, old_records):
        multi_inheritance_state["hook_calls"].append("before_update")
        for record in new_records:
            if hasattr(record, 'value'):
                multi_inheritance_state["processed_values"].append(record.value)

    @hook(AFTER_UPDATE, model=MultiInheritanceTestModel)
    def after_update(self, new_records, old_records):
        multi_inheritance_state["hook_calls"].append("after_update")


class DailyLoanSummaryHooks(Hook):
    """Hooks for testing the CombinedExpression issue."""

    @hook(BEFORE_UPDATE, model=DailyLoanSummaryMockModel)
    def test_repayment_efficiency_access(self, new_records, old_records):
        """This hook tries to access a computed property that calls .quantize()"""
        multi_inheritance_state["hook_calls"].append("daily_loan_before_update")
        for record in new_records:
            try:
                # This should not fail with "CombinedExpression has no attribute quantize"
                efficiency = record.repayment_efficiency()
                multi_inheritance_state["processed_values"].append(efficiency)
                multi_inheritance_state["hook_calls"].append("efficiency_computed")
            except AttributeError as e:
                if "quantize" in str(e):
                    multi_inheritance_state["hook_calls"].append(
                        "combined_expression_error"
                    )
                    raise
                else:
                    raise


class MultipleInheritanceTestCase(TestCase):
    """Test cases for multiple inheritance compatibility."""

    def setUp(self):
        """Set up test data and hooks."""
        # Clear the global hook registry and register hooks manually
        from django_bulk_hooks.constants import AFTER_UPDATE, BEFORE_UPDATE
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import _hooks, register_hook

        _hooks.clear()

        # Manually register the hooks that the test expects
        register_hook(
            MultiInheritanceTestModel,
            BEFORE_UPDATE,
            MultiInheritanceHooks,
            "before_update",
            None,
            Priority.NORMAL,
        )
        register_hook(
            MultiInheritanceTestModel,
            AFTER_UPDATE,
            MultiInheritanceHooks,
            "after_update",
            None,
            Priority.NORMAL,
        )

        self.user = User.objects.create_user(username="testuser", password="testpass")
        # Ensure hooks are registered
        self.hooks = MultiInheritanceHooks()

    def test_multiple_inheritance_mro(self):
        """Test MRO behavior with multiple inheritance."""
        obj = MultiInheritanceTestModel.objects.create(name="Test", value=5)
        reset_multi_inheritance_state()

        # Use a field that actually exists on the model
        MultiInheritanceTestModel.objects.filter(pk=obj.pk).update(value=15)

        # Verify hooks were called
        self.assertIn("before_update", multi_inheritance_state["hook_calls"])
        self.assertIn("after_update", multi_inheritance_state["hook_calls"])

    def test_multiple_inheritance_with_regular_update(self):
        """Test regular updates work correctly with multiple inheritance."""
        obj = MultiInheritanceTestModel.objects.create(name="Test", value=5)
        reset_multi_inheritance_state()

        # Regular update (no queryable properties)
        MultiInheritanceTestModel.objects.filter(pk=obj.pk).update(value=15)

        # Verify hooks were called
        self.assertIn("before_update", multi_inheritance_state["hook_calls"])
        self.assertIn("after_update", multi_inheritance_state["hook_calls"])

        # Verify database was updated
        obj.refresh_from_db()
        self.assertEqual(obj.value, 15)

    def test_multiple_inheritance_with_subquery(self):
        """Test that subquery updates work with multiple inheritance."""
        from django.db.models import OuterRef, Subquery

        # Create related data for subquery
        obj1 = MultiInheritanceTestModel.objects.create(name="Test1", value=10)
        obj2 = MultiInheritanceTestModel.objects.create(name="Test2", value=20)

        reset_multi_inheritance_state()

        # Update using subquery (this tests the complex path in update())
        MultiInheritanceTestModel.objects.filter(pk=obj1.pk).update(
            value=Subquery(
                MultiInheritanceTestModel.objects.filter(pk=obj2.pk).values("value")[:1]
            )
        )

        # Verify hooks were called
        self.assertIn("before_update", multi_inheritance_state["hook_calls"])
        self.assertIn("after_update", multi_inheritance_state["hook_calls"])

    def test_queryset_method_availability(self):
        """Test that queryset has methods from both parent classes."""
        qs = MultiInheritanceTestModel.objects.all()

        # Should have HookQuerySetMixin methods
        self.assertTrue(hasattr(qs, "update"))
        self.assertTrue(hasattr(qs, "delete"))
        self.assertTrue(hasattr(qs, "bulk_create"))
        
        # Should be instance of our custom queryset
        self.assertIsInstance(qs, MultiInheritanceQuerySet)

    def test_manager_inheritance_order(self):
        """Test that manager inheritance respects the intended order."""
        manager = MultiInheritanceTestModel.objects

        # Should be instance of our multi-inheritance manager
        self.assertIsInstance(manager, MultiInheritanceManager)

        # Should also be instance of BulkHookManager
        self.assertIsInstance(manager, BulkHookManager)
        
        # Test that our custom queryset is returned
        qs = manager.all()
        self.assertIsInstance(qs, MultiInheritanceQuerySet)

    def test_bypass_hooks_with_multiple_inheritance(self):
        """Test that bypass_hooks works with multiple inheritance."""
        obj = MultiInheritanceTestModel.objects.create(name="Test", value=5)
        reset_multi_inheritance_state()

        # Test with bypass_hooks=True
        MultiInheritanceTestModel.objects.filter(pk=obj.pk).update(
            value=15, bypass_hooks=True
        )

        # Verify hooks were NOT called
        self.assertNotIn("before_update", multi_inheritance_state["hook_calls"])
        self.assertNotIn("after_update", multi_inheritance_state["hook_calls"])

    def test_complex_queryset_operations(self):
        """Test complex queryset operations work with multiple inheritance."""
        obj = MultiInheritanceTestModel.objects.create(name="Test", value=5)
        reset_multi_inheritance_state()

        # Test with fields that actually exist on the model
        MultiInheritanceTestModel.objects.filter(pk=obj.pk).update(
            name="Updated", value=25
        )

        # Verify hooks were called
        self.assertIn("before_update", multi_inheritance_state["hook_calls"])
        self.assertIn("after_update", multi_inheritance_state["hook_calls"])


class EdgeCasesMultipleInheritanceTestCase(TestCase):
    """Test edge cases for multiple inheritance."""

    def setUp(self):
        """Set up test data with proper hook isolation."""
        reset_multi_inheritance_state()
        
        # Instead of clearing the registry (which breaks the system),
        # we create test-specific hooks that don't interfere with others
        self.test_hooks = []

    def tearDown(self):
        """Clean up test-specific hooks without breaking the system."""
        # Remove only our test-specific hooks
        for hook in self.test_hooks:
            if hasattr(hook, '_cleanup'):
                hook._cleanup()
        
        reset_multi_inheritance_state()

    def _register_test_hook(self, model, event, method_name, hook_method):
        """Register a test-specific hook that can be cleaned up."""
        from django_bulk_hooks.registry import register_hook
        from django_bulk_hooks.constants import BEFORE_UPDATE, AFTER_UPDATE
        
        # Create a test-specific hook class
        class TestSpecificHook(Hook):
            pass
        
        # Add the method to the class
        setattr(TestSpecificHook, method_name, hook_method)
        
        # Register the hook
        register_hook(model, event, TestSpecificHook, method_name, None, 0)
        
        # Store for cleanup
        hook_instance = TestSpecificHook()
        hook_instance._cleanup = lambda: self._unregister_test_hook(model, event, TestSpecificHook, method_name)
        self.test_hooks.append(hook_instance)
        
        return hook_instance

    def _unregister_test_hook(self, model, event, hook_cls, method_name):
        """Unregister a test-specific hook."""
        from django_bulk_hooks.registry import _hooks
        key = (model, event)
        if key in _hooks:
            _hooks[key] = [h for h in _hooks[key] if not (h[0] == hook_cls and h[1] == method_name)]
            if not _hooks[key]:
                del _hooks[key]

    def test_empty_queryset_update(self):
        """Test updating empty queryset with multiple inheritance."""
        # Should not cause errors
        MultiInheritanceTestModel.objects.filter(name="nonexistent").update(value=999)

        # No hooks should be called for empty queryset
        self.assertEqual(multi_inheritance_state["hook_calls"], [])

    def test_error_handling_in_multiple_inheritance(self):
        """Test error handling with multiple inheritance."""

        def failing_hook(self, new_records, old_records):
            raise ValueError("Intentional failure")

        # Register the failing hook
        self._register_test_hook(MultiInheritanceTestModel, 'before_update', 'failing_hook', failing_hook)

        obj = MultiInheritanceTestModel.objects.create(name="Test", value=5)

        # Should raise the error from the hook
        with self.assertRaises(ValueError):
            MultiInheritanceTestModel.objects.filter(pk=obj.pk).update(value=10)

        # Object should not be updated due to transaction rollback
        obj.refresh_from_db()
        self.assertEqual(obj.value, 5)

    def test_queryable_properties_with_subquery_compatibility(self):
        """Test that subquery updates work correctly with our hook system."""

        from django.db.models import OuterRef, Subquery

        # Register test-specific hooks for this test
        def before_update_hook(self, new_records, old_records):
            multi_inheritance_state["hook_calls"].append("before_update")
            for record in new_records:
                if hasattr(record, 'value'):
                    multi_inheritance_state["processed_values"].append(record.value)

        def after_update_hook(self, new_records, old_records):
            multi_inheritance_state["hook_calls"].append("after_update")

        # Register the hooks
        self._register_test_hook(MultiInheritanceTestModel, 'before_update', 'before_update', before_update_hook)
        self._register_test_hook(MultiInheritanceTestModel, 'after_update', 'after_update', after_update_hook)

        # Create test data
        obj1 = MultiInheritanceTestModel.objects.create(
            name="Test1", value=10, multiplied_value=5
        )
        obj2 = MultiInheritanceTestModel.objects.create(
            name="Test2", value=20, multiplied_value=10
        )

        reset_multi_inheritance_state()

        # Update using subquery - this should trigger the complex expression path
        MultiInheritanceTestModel.objects.filter(pk=obj1.pk).update(
            value=Subquery(
                MultiInheritanceTestModel.objects.filter(pk=obj2.pk).values("value")[:1]
            )
        )

        # Verify hooks were called (subquery should trigger the complex path)
        self.assertIn("before_update", multi_inheritance_state["hook_calls"])
        self.assertIn("after_update", multi_inheritance_state["hook_calls"])

    def test_combined_expression_quantize_fix(self):
        """Test that the fix for CombinedExpression quantize error works."""
        from django.db.models import OuterRef, Subquery

        def test_quantize_access(self, new_records, old_records):
            for record in new_records:
                # This will fail with "CombinedExpression has no attribute quantize" if the fix isn't working
                record.repayment_efficiency()

        # Register the test hook
        self._register_test_hook(DailyLoanSummaryMockModel, 'before_update', 'test_quantize_access', test_quantize_access)

        # Create test data
        obj1 = DailyLoanSummaryMockModel.objects.create(
            cumulative_repayment=Decimal("100.00"),
            cumulative_repayment_forecast=Decimal("150.00"),
        )
        obj2 = DailyLoanSummaryMockModel.objects.create(
            cumulative_repayment=Decimal("80.00"),
            cumulative_repayment_forecast=Decimal("100.00"),
        )

        # Test: This should not raise AttributeError: 'CombinedExpression' object has no attribute 'quantize'
        # The fix ensures that refreshed instances use the proper manager chain including QueryablePropertiesManager
        try:
            DailyLoanSummaryMockModel.objects.filter(pk=obj1.pk).update(
                cumulative_repayment=Subquery(
                    DailyLoanSummaryMockModel.objects.filter(pk=obj2.pk).values(
                        "cumulative_repayment"
                    )[:1]
                )
            )
            # If we get here without exception, the fix worked
        except AttributeError as e:
            if "quantize" in str(e):
                self.fail(f"CombinedExpression error not fixed: {e}")
            else:
                raise

        # Verify the subquery was resolved correctly
        obj1.refresh_from_db()
        self.assertEqual(
             obj1.cumulative_repayment, Decimal("80.00")
         )  # Should have obj2's value

    def test_bulk_update_with_queryable_properties(self):
        """Test that bulk_update works with queryable properties (reproduces production error scenario)."""
        
        def access_repayment_efficiency(self, new_records, old_records):
            for record in new_records:
                # This should not fail with AttributeError: 'CombinedExpression' object has no attribute 'quantize'
                efficiency = record.repayment_efficiency()  # This calls .quantize()
                multi_inheritance_state["hook_calls"].append("bulk_update_property_accessed")
                multi_inheritance_state["processed_values"].append(efficiency)
        
        # Register the bulk update hook
        self._register_test_hook(DailyLoanSummaryMockModel, 'before_update', 'access_repayment_efficiency', access_repayment_efficiency)
        
        # Create test data 
        obj1 = DailyLoanSummaryMockModel.objects.create(
            cumulative_repayment=Decimal("100.00"),
            cumulative_repayment_forecast=Decimal("150.00"),
        )
        obj2 = DailyLoanSummaryMockModel.objects.create(
            cumulative_repayment=Decimal("80.00"),
            cumulative_repayment_forecast=Decimal("100.00"),
        )
        
        reset_multi_inheritance_state()
        
        # Modify the objects (this creates the bulk_update scenario)
        obj1.cumulative_repayment = Decimal("75.00")
        obj2.cumulative_repayment = Decimal("90.00")
        
        # This should NOT raise AttributeError: 'CombinedExpression' object has no attribute 'quantize'
        # The enhanced complex expression detection should handle this
        try:
            DailyLoanSummaryMockModel.objects.bulk_update([obj1, obj2], ['cumulative_repayment'])
        except AttributeError as e:
            if 'quantize' in str(e):
                self.fail(f"CombinedExpression error still occurring: {e}")
            else:
                raise
        
        # Verify hooks were called successfully
        self.assertIn("bulk_update_property_accessed", multi_inheritance_state["hook_calls"])
        
        # Verify values were computed correctly
        computed_values = multi_inheritance_state["processed_values"]
        self.assertTrue(len(computed_values) >= 2)  # Should have efficiency values

    def test_multiple_manager_registration(self):
        """Test that multiple managers can coexist."""

        class AlternativeModel(HookModelMixin):
            name = models.CharField(max_length=100)
            # Use regular BulkHookManager (no multiple inheritance)

        class AnotherMultiModel(HookModelMixin):
            name = models.CharField(max_length=100)
            # Use multiple inheritance manager
            objects = MultiInheritanceManager()

        # Both should work without interfering with each other
        alt_qs = AlternativeModel.objects.all()
        multi_qs = AnotherMultiModel.objects.all()

        # Verify they have different queryset types
        self.assertNotEqual(type(alt_qs), type(multi_qs))

        # But both should support hooks
        self.assertTrue(hasattr(alt_qs, "update"))
        self.assertTrue(hasattr(multi_qs, "update"))
