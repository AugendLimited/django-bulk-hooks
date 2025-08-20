"""
Test to verify that Subquery objects in update operations work correctly with hooks.
"""

from django.db import models
from django.db.models import OuterRef, Subquery, Sum
from django.test import TestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.constants import AFTER_UPDATE, BEFORE_UPDATE
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.models import HookModelMixin


class User(models.Model):
    """Test user model for foreign key testing."""

    username = models.CharField(max_length=100)


class TestModel(HookModelMixin):
    """Test model for Subquery hook testing."""

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    computed_value = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True
    )


class RelatedModel(models.Model):
    """Related model for Subquery testing."""

    test_model = models.ForeignKey(TestModel, on_delete=models.CASCADE)
    amount = models.IntegerField()


# Global variables to track hook calls across instances
hook_state = {
    "after_update_called": False,
    "before_update_called": False,
    "computed_values": [],
    "before_computed_values": [],
    "foreign_key_values": [],
}


class SubqueryHookTest(Hook):
    """Hook to test Subquery functionality."""

    @hook(AFTER_UPDATE, model=TestModel)
    def test_subquery_access(self, new_records, old_records):
        hook_state["after_update_called"] = True
        for record in new_records:
            # This should now contain the computed value, not the Subquery object
            hook_state["computed_values"].append(record.computed_value)
            # This should contain the User instance, not a raw ID
            hook_state["foreign_key_values"].append(record.created_by)

    @hook(BEFORE_UPDATE, model=TestModel)
    def test_before_subquery_access(self, new_records, old_records):
        hook_state["before_update_called"] = True
        for record in new_records:
            # This should also contain the computed value, not the Subquery object
            hook_state["before_computed_values"].append(record.computed_value)


class SubqueryHooksTestCase(TestCase):
    """Test case for Subquery hook functionality."""

    def setUp(self):
        # Clear the global hook registry and register hooks manually
        from django_bulk_hooks.constants import AFTER_UPDATE, BEFORE_UPDATE
        from django_bulk_hooks.priority import Priority
        from django_bulk_hooks.registry import register_hook, isolated_registry, clear_hooks

        self._iso = isolated_registry()
        self._iso.__enter__()
        clear_hooks()

        # Manually register the hooks that the test expects
        register_hook(
            TestModel,
            AFTER_UPDATE,
            SubqueryHookTest,
            "test_subquery_access",
            None,
            Priority.NORMAL,
        )
        register_hook(
            TestModel,
            BEFORE_UPDATE,
            SubqueryHookTest,
            "test_before_subquery_access",
            None,
            Priority.NORMAL,
        )

        # Create test data
        self.user = User.objects.create(username="testuser")
        self.test_model = TestModel.objects.create(
            name="Test", value=10, created_by=self.user
        )
        self.related1 = RelatedModel.objects.create(
            test_model=self.test_model, amount=5
        )
        self.related2 = RelatedModel.objects.create(
            test_model=self.test_model, amount=15
        )

        # Reset global hook state for each test
        global hook_state
        hook_state = {
            "after_update_called": False,
            "before_update_called": False,
            "computed_values": [],
            "before_computed_values": [],
            "foreign_key_values": [],
        }

        # Create hook instance for registration (actual instances will be created by the framework)
        self.hook = SubqueryHookTest()

    def tearDown(self):
        self._iso.__exit__(None, None, None)

    def test_subquery_in_hooks(self):
        """Test that Subquery computed values are accessible in hooks."""

        # Perform update with Subquery
        TestModel.objects.filter(pk=self.test_model.pk).update(
            computed_value=Subquery(
                RelatedModel.objects.filter(test_model=OuterRef("pk"))
                .values("test_model")
                .annotate(total=Sum("amount"))
                .values("total")[:1]
            )
        )

        # Verify that the hook was called and received computed values
        self.assertTrue(hook_state["after_update_called"])
        self.assertEqual(len(hook_state["computed_values"]), 1)
        # The computed value should be 20 (5 + 15)
        self.assertEqual(hook_state["computed_values"][0], 20)

        # Verify the database was actually updated
        self.test_model.refresh_from_db()
        self.assertEqual(self.test_model.computed_value, 20)

    def test_bulk_subquery_performance(self):
        """Test that bulk Subquery operations are efficient."""

        # Create multiple test models for bulk testing
        test_models = []
        for i in range(10):
            model = TestModel.objects.create(name=f"Test{i}", value=i)
            RelatedModel.objects.create(test_model=model, amount=i * 2)
            RelatedModel.objects.create(test_model=model, amount=i * 3)
            test_models.append(model)

        # Perform bulk update with Subquery
        pks = [model.pk for model in test_models]
        TestModel.objects.filter(pk__in=pks).update(
            computed_value=Subquery(
                RelatedModel.objects.filter(test_model=OuterRef("pk"))
                .values("test_model")
                .annotate(total=Sum("amount"))
                .values("total")[:1]
            )
        )

        # Verify all hooks received computed values
        self.assertTrue(hook_state["after_update_called"])
        self.assertEqual(len(hook_state["computed_values"]), 10)

        # Verify all computed values are correct
        for i, value in enumerate(hook_state["computed_values"]):
            expected = i * 2 + i * 3  # sum of the two related amounts
            self.assertEqual(value, expected)

    def test_subquery_object_not_passed_to_hooks(self):
        """Test that Subquery objects are not passed to hooks, only computed values."""

        # Perform update with Subquery
        TestModel.objects.filter(pk=self.test_model.pk).update(
            computed_value=Subquery(
                RelatedModel.objects.filter(test_model=OuterRef("pk"))
                .values("test_model")
                .annotate(total=Sum("amount"))
                .values("total")[:1]
            )
        )

        # Verify that the hook received actual values, not Subquery objects
        self.assertTrue(hook_state["after_update_called"])
        for value in hook_state["computed_values"]:
            # The value should be an integer, not a Subquery object
            self.assertIsInstance(value, int)
            self.assertNotEqual(type(value).__name__, "Subquery")

    def test_foreign_key_fields_preserved(self):
        """Test that foreign key fields are preserved correctly after Subquery updates."""

        # Perform update with Subquery
        TestModel.objects.filter(pk=self.test_model.pk).update(
            computed_value=Subquery(
                RelatedModel.objects.filter(test_model=OuterRef("pk"))
                .values("test_model")
                .annotate(total=Sum("amount"))
                .values("total")[:1]
            )
        )

        # Verify that the hook was called
        self.assertTrue(hook_state["after_update_called"])

        # Verify that foreign key fields are still intact
        # The hook should have access to the created_by field as a User instance
        self.assertEqual(len(hook_state["foreign_key_values"]), 1)
        self.assertIsInstance(hook_state["foreign_key_values"][0], User)
        self.assertEqual(hook_state["foreign_key_values"][0].username, "testuser")

    def test_subquery_in_before_hooks(self):
        """Test that Subquery computed values are accessible in BEFORE hooks."""

        # Perform update with Subquery
        TestModel.objects.filter(pk=self.test_model.pk).update(
            computed_value=Subquery(
                RelatedModel.objects.filter(test_model=OuterRef("pk"))
                .values("test_model")
                .annotate(total=Sum("amount"))
                .values("total")[:1]
            )
        )

        # Verify that the BEFORE hook was called and received computed values
        self.assertTrue(hook_state["before_update_called"])
        self.assertEqual(len(hook_state["before_computed_values"]), 1)
        # The computed value should be 20 (5 + 15), not a Subquery object
        self.assertEqual(hook_state["before_computed_values"][0], 20)

        # Also verify that the hook received actual values, not Subquery objects
        for value in hook_state["before_computed_values"]:
            # The value should be an integer, not a Subquery object
            self.assertIsInstance(value, int)
            self.assertNotEqual(type(value).__name__, "Subquery")
