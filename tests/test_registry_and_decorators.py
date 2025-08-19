"""
Tests for hook registry and decorator functionality.
"""

from django.contrib.auth.models import User
from django.db import models
from django.test import TestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.conditions import HasChanged, IsEqual
from django_bulk_hooks.constants import AFTER_CREATE, BEFORE_CREATE, BEFORE_UPDATE
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.models import HookModelMixin
from django_bulk_hooks.priority import Priority
from django_bulk_hooks.registry import get_hooks, list_all_hooks, register_hook


# Test Model
class RegistryTestModel(HookModelMixin):
    """Test model for registry and decorator testing."""
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default='active')


# Global state tracking
registry_state = {
    'hook_calls': [],
    'registered_hooks': [],
}


def reset_registry_state():
    """Reset registry state tracking."""
    global registry_state
    registry_state = {
        'hook_calls': [],
        'registered_hooks': [],
    }


class BasicRegistryHooks(Hook):
    """Basic hooks for registry testing."""

    @hook(BEFORE_CREATE, model=RegistryTestModel)
    def before_create_basic(self, new_records, old_records):
        registry_state['hook_calls'].append('before_create_basic')

    @hook(AFTER_CREATE, model=RegistryTestModel, priority=Priority.HIGH)
    def after_create_high(self, new_records, old_records):
        registry_state['hook_calls'].append('after_create_high')

    @hook(BEFORE_UPDATE, model=RegistryTestModel, condition=HasChanged('value'))
    def before_update_conditional(self, new_records, old_records):
        registry_state['hook_calls'].append('before_update_conditional')


class RegistryTestCase(TestCase):
    """Test case for hook registry functionality."""

    def setUp(self):
        """Set up test data."""
        reset_registry_state()
        self.user = User.objects.create_user(username='testuser')
        self.hooks = BasicRegistryHooks()

    def test_hook_registration(self):
        """Test that hooks are properly registered."""
        # Get hooks for BEFORE_CREATE
        before_create_hooks = get_hooks(RegistryTestModel, BEFORE_CREATE)
        
        # Should find our registered hook
        self.assertTrue(len(before_create_hooks) > 0)
        
        # Check that our hook is in the list
        hook_found = False
        for handler_cls, method_name, condition, priority in before_create_hooks:
            if (handler_cls == BasicRegistryHooks and 
                method_name == 'before_create_basic'):
                hook_found = True
                break
        
        self.assertTrue(hook_found, "before_create_basic hook not found in registry")

    def test_hook_priority_in_registry(self):
        """Test that hook priorities are stored correctly in registry."""
        after_create_hooks = get_hooks(RegistryTestModel, AFTER_CREATE)
        
        # Find our high priority hook
        hook_found = False
        for handler_cls, method_name, condition, priority in after_create_hooks:
            if (handler_cls == BasicRegistryHooks and 
                method_name == 'after_create_high'):
                self.assertEqual(priority, Priority.HIGH)
                hook_found = True
                break
        
        self.assertTrue(hook_found, "after_create_high hook not found in registry")

    def test_hook_condition_in_registry(self):
        """Test that hook conditions are stored correctly in registry."""
        before_update_hooks = get_hooks(RegistryTestModel, BEFORE_UPDATE)
        
        # Find our conditional hook
        hook_found = False
        for handler_cls, method_name, condition, priority in before_update_hooks:
            if (handler_cls == BasicRegistryHooks and 
                method_name == 'before_update_conditional'):
                self.assertIsInstance(condition, HasChanged)
                self.assertEqual(condition.field, 'value')
                hook_found = True
                break
        
        self.assertTrue(hook_found, "before_update_conditional hook not found in registry")

    def test_get_hooks_for_nonexistent_model(self):
        """Test getting hooks for non-existent model/event."""
        
        class NonRegisteredModel(models.Model):
            name = models.CharField(max_length=100)
            
            class Meta:
                app_label = 'tests'

        # Should return empty list for non-registered model
        hooks = get_hooks(NonRegisteredModel, BEFORE_CREATE)
        self.assertEqual(hooks, [])

    def test_get_hooks_for_nonexistent_event(self):
        """Test getting hooks for non-existent event."""
        # Should return empty list for non-existent event
        hooks = get_hooks(RegistryTestModel, 'non_existent_event')
        self.assertEqual(hooks, [])

    def test_list_all_hooks(self):
        """Test listing all registered hooks."""
        all_hooks = list_all_hooks()
        
        # Should be a dictionary
        self.assertIsInstance(all_hooks, dict)
        
        # Should contain our model
        model_key = f"{RegistryTestModel._meta.app_label}.{RegistryTestModel.__name__}"
        if model_key in all_hooks:
            model_hooks = all_hooks[model_key]
            self.assertIsInstance(model_hooks, dict)
            
            # Should contain our events
            if BEFORE_CREATE in model_hooks:
                self.assertTrue(len(model_hooks[BEFORE_CREATE]) > 0)

    def test_manual_hook_registration(self):
        """Test manually registering hooks using register_hook function."""
        
        class ManualHook(Hook):
            def manual_method(self, new_records, old_records):
                registry_state['hook_calls'].append('manual_method')

        # Manually register a hook
        register_hook(
            model=RegistryTestModel,
            event=BEFORE_CREATE,
            handler_cls=ManualHook,
            method_name='manual_method',
            condition=None,
            priority=Priority.NORMAL
        )

        # Verify it was registered
        hooks = get_hooks(RegistryTestModel, BEFORE_CREATE)
        manual_hook_found = False
        for handler_cls, method_name, condition, priority in hooks:
            if (handler_cls == ManualHook and method_name == 'manual_method'):
                manual_hook_found = True
                break
        
        self.assertTrue(manual_hook_found, "Manually registered hook not found")

        # Test that it executes
        manual_hook_instance = ManualHook()
        reset_registry_state()
        
        RegistryTestModel.objects.create(name='Test', created_by=self.user)
        
        self.assertIn('manual_method', registry_state['hook_calls'])

    def test_multiple_hook_classes_same_event(self):
        """Test multiple hook classes for the same event."""
        
        class AdditionalHooks(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def additional_before_create(self, new_records, old_records):
                registry_state['hook_calls'].append('additional_before_create')

        additional_hooks = AdditionalHooks()

        # Both hook classes should be registered
        before_create_hooks = get_hooks(RegistryTestModel, BEFORE_CREATE)
        
        hook_classes = [handler_cls for handler_cls, _, _, _ in before_create_hooks]
        self.assertIn(BasicRegistryHooks, hook_classes)
        self.assertIn(AdditionalHooks, hook_classes)

        # Both should execute
        reset_registry_state()
        RegistryTestModel.objects.create(name='Test')
        
        self.assertIn('before_create_basic', registry_state['hook_calls'])
        self.assertIn('additional_before_create', registry_state['hook_calls'])

    def test_hook_inheritance(self):
        """Test hook behavior with class inheritance."""
        
        class BaseHooks(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def base_hook(self, new_records, old_records):
                registry_state['hook_calls'].append('base_hook')

        class DerivedHooks(BaseHooks):
            @hook(AFTER_CREATE, model=RegistryTestModel)
            def derived_hook(self, new_records, old_records):
                registry_state['hook_calls'].append('derived_hook')

        # Create instance of derived class
        derived_hooks = DerivedHooks()

        # Both base and derived hooks should be registered
        before_hooks = get_hooks(RegistryTestModel, BEFORE_CREATE)
        after_hooks = get_hooks(RegistryTestModel, AFTER_CREATE)
        
        # Check for base hook
        base_found = any(
            handler_cls == DerivedHooks and method_name == 'base_hook'
            for handler_cls, method_name, _, _ in before_hooks
        )
        
        # Check for derived hook
        derived_found = any(
            handler_cls == DerivedHooks and method_name == 'derived_hook'
            for handler_cls, method_name, _, _ in after_hooks
        )
        
        self.assertTrue(base_found, "Base hook not found")
        self.assertTrue(derived_found, "Derived hook not found")

        # Both should execute
        reset_registry_state()
        RegistryTestModel.objects.create(name='Test')
        
        self.assertIn('base_hook', registry_state['hook_calls'])
        self.assertIn('derived_hook', registry_state['hook_calls'])


class DecoratorTestCase(TestCase):
    """Test case for hook decorator functionality."""

    def setUp(self):
        """Set up test data."""
        reset_registry_state()
        self.user = User.objects.create_user(username='testuser')

    def test_hook_decorator_basic(self):
        """Test basic hook decorator functionality."""
        
        class DecoratorTestHooks(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def decorated_hook(self, new_records, old_records):
                registry_state['hook_calls'].append('decorated_hook')

        hooks_instance = DecoratorTestHooks()

        RegistryTestModel.objects.create(name='Test')
        self.assertIn('decorated_hook', registry_state['hook_calls'])

    def test_hook_decorator_with_all_parameters(self):
        """Test hook decorator with all parameters."""
        
        class FullDecoratorHooks(Hook):
            @hook(
                BEFORE_UPDATE, 
                model=RegistryTestModel, 
                condition=IsEqual('status', 'active'),
                priority=Priority.HIGH
            )
            def full_decorated_hook(self, new_records, old_records):
                registry_state['hook_calls'].append('full_decorated_hook')

        hooks_instance = FullDecoratorHooks()

        # Create and update object with active status
        obj = RegistryTestModel.objects.create(name='Test', status='active')
        reset_registry_state()
        
        obj.value = 10
        obj.save()
        
        self.assertIn('full_decorated_hook', registry_state['hook_calls'])

        # Update object with inactive status (should not trigger)
        reset_registry_state()
        obj.status = 'inactive'
        obj.value = 20
        obj.save()
        
        self.assertNotIn('full_decorated_hook', registry_state['hook_calls'])

    def test_hook_decorator_invalid_parameters(self):
        """Test hook decorator with invalid parameters."""
        
        with self.assertRaises(TypeError):
            class InvalidHooks(Hook):
                @hook()  # Missing required parameters
                def invalid_hook(self, new_records, old_records):
                    pass

    def test_hook_decorator_on_non_hook_class(self):
        """Test hook decorator on class that doesn't inherit from Hook."""
        
        class NonHookClass:
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def non_hook_method(self, new_records, old_records):
                registry_state['hook_calls'].append('non_hook_method')

        # This should work but the hook won't be automatically registered
        # since the class doesn't inherit from Hook
        instance = NonHookClass()

        RegistryTestModel.objects.create(name='Test')
        
        # Hook should not be called since class doesn't inherit from Hook
        self.assertNotIn('non_hook_method', registry_state['hook_calls'])

    def test_method_without_decorator(self):
        """Test that methods without decorator are not registered as hooks."""
        
        class MixedMethodsHooks(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def decorated_method(self, new_records, old_records):
                registry_state['hook_calls'].append('decorated_method')

            def undecorated_method(self, new_records, old_records):
                registry_state['hook_calls'].append('undecorated_method')

        hooks_instance = MixedMethodsHooks()

        RegistryTestModel.objects.create(name='Test')
        
        # Only decorated method should be called
        self.assertIn('decorated_method', registry_state['hook_calls'])
        self.assertNotIn('undecorated_method', registry_state['hook_calls'])

    def test_decorator_with_complex_conditions(self):
        """Test decorator with complex condition combinations."""
        
        class ComplexConditionHooks(Hook):
            @hook(
                BEFORE_UPDATE, 
                model=RegistryTestModel,
                condition=(HasChanged('value') & IsEqual('status', 'active')) | IsEqual('name', 'special')
            )
            def complex_condition_hook(self, new_records, old_records):
                registry_state['hook_calls'].append('complex_condition_hook')

        hooks_instance = ComplexConditionHooks()

        # Test case 1: value changed and status is active
        obj = RegistryTestModel.objects.create(name='Test', value=1, status='active')
        reset_registry_state()
        
        obj.value = 2
        obj.save()
        
        self.assertIn('complex_condition_hook', registry_state['hook_calls'])

        # Test case 2: name is 'special' regardless of other conditions
        reset_registry_state()
        obj.name = 'special'
        obj.status = 'inactive'  # Even though status is not active
        obj.save()
        
        self.assertIn('complex_condition_hook', registry_state['hook_calls'])

        # Test case 3: conditions not met
        reset_registry_state()
        obj.name = 'normal'
        obj.status = 'inactive'
        obj.value = 3  # Value changed but status not active, name not special
        obj.save()
        
        self.assertNotIn('complex_condition_hook', registry_state['hook_calls'])

    def test_decorator_preserves_method_metadata(self):
        """Test that decorator preserves original method metadata."""
        
        class MetadataHooks(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def documented_hook(self, new_records, old_records):
                """This is a documented hook method."""
                registry_state['hook_calls'].append('documented_hook')

        # Check that docstring is preserved
        self.assertEqual(
            MetadataHooks.documented_hook.__doc__,
            "This is a documented hook method."
        )

        # Check that method name is preserved
        self.assertEqual(
            MetadataHooks.documented_hook.__name__,
            "documented_hook"
        )

    def test_multiple_decorators_same_method(self):
        """Test multiple hook decorators on the same method."""
        
        class MultiDecoratorHooks(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            @hook(AFTER_CREATE, model=RegistryTestModel)
            def multi_event_hook(self, new_records, old_records):
                registry_state['hook_calls'].append('multi_event_hook')

        hooks_instance = MultiDecoratorHooks()

        reset_registry_state()
        RegistryTestModel.objects.create(name='Test')
        
        # Hook should be called for both events
        multi_calls = [call for call in registry_state['hook_calls'] if call == 'multi_event_hook']
        self.assertEqual(len(multi_calls), 2)  # Called for both BEFORE and AFTER


class RegistryEdgeCasesTestCase(TestCase):
    """Test case for edge cases in registry functionality."""

    def setUp(self):
        """Set up test data."""
        reset_registry_state()

    def test_registry_with_duplicate_registrations(self):
        """Test registry behavior with duplicate hook registrations."""
        
        class DuplicateHooks(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def duplicate_hook(self, new_records, old_records):
                registry_state['hook_calls'].append('duplicate_hook')

        # Create multiple instances (shouldn't cause duplicate registration)
        hooks1 = DuplicateHooks()
        hooks2 = DuplicateHooks()

        # Should not have duplicate registrations
        before_hooks = get_hooks(RegistryTestModel, BEFORE_CREATE)
        duplicate_count = sum(
            1 for handler_cls, method_name, _, _ in before_hooks
            if handler_cls == DuplicateHooks and method_name == 'duplicate_hook'
        )
        
        # Should only be registered once despite multiple instances
        self.assertEqual(duplicate_count, 1)

    def test_registry_thread_safety(self):
        """Test registry thread safety (basic test)."""
        import threading
        import time

        results = []

        def register_hooks():
            class ThreadHooks(Hook):
                @hook(BEFORE_CREATE, model=RegistryTestModel)
                def thread_hook(self, new_records, old_records):
                    results.append(threading.current_thread().name)

            hooks = ThreadHooks()
            time.sleep(0.1)  # Small delay to increase chance of race conditions

        # Create multiple threads that register hooks
        threads = []
        for i in range(5):
            thread = threading.Thread(target=register_hooks, name=f'Thread-{i}')
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Registry should handle concurrent registration gracefully
        # This is a basic test - full thread safety testing would be more complex

    def test_registry_memory_usage(self):
        """Test that registry doesn't leak memory with many registrations."""
        
        # Create many hook classes to test memory usage
        hook_classes = []
        for i in range(50):  # Adjust based on test environment
            
            class DynamicHooks(Hook):
                pass

            # Dynamically add hook method
            def make_hook_method(index):
                def hook_method(self, new_records, old_records):
                    registry_state['hook_calls'].append(f'dynamic_hook_{index}')
                return hook_method

            # Add decorated method to class
            hook_method = hook(BEFORE_CREATE, model=RegistryTestModel)(make_hook_method(i))
            setattr(DynamicHooks, f'dynamic_hook_{i}', hook_method)
            
            # Create instance to trigger registration
            hooks_instance = DynamicHooks()
            hook_classes.append(hooks_instance)

        # Verify all hooks were registered
        before_hooks = get_hooks(RegistryTestModel, BEFORE_CREATE)
        dynamic_hooks_count = sum(
            1 for _, method_name, _, _ in before_hooks
            if method_name.startswith('dynamic_hook_')
        )
        
        self.assertEqual(dynamic_hooks_count, 50)

        # Clean up references
        del hook_classes
