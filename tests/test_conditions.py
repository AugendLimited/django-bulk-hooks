"""
Tests for hook conditions functionality.
"""

from django.contrib.auth.models import User
from django.db import models
from django.test import TestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.conditions import (
    AndCondition,
    ChangesTo,
    HasChanged,
    IsEqual,
    IsGreaterThan,
    IsGreaterThanOrEqual,
    IsLessThan,
    IsLessThanOrEqual,
    IsNotEqual,
    NotCondition,
    OrCondition,
    WasEqual,
    resolve_dotted_attr,
)
from django_bulk_hooks.constants import BEFORE_UPDATE
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.models import HookModelMixin


# Test Models
class TestAccount(HookModelMixin):
    """Test model for condition testing."""

    name = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, default="active")
    priority = models.IntegerField(default=1)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)


class TestProfile(HookModelMixin):
    """Test model for nested attribute testing."""

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    account = models.ForeignKey(TestAccount, on_delete=models.CASCADE, null=True)
    bio = models.TextField(blank=True)


# Global state tracking
condition_state = {
    "triggered_conditions": [],
    "hook_calls": [],
}


def reset_condition_state():
    """Reset the global condition state for each test."""
    global condition_state
    condition_state = {
        "triggered_conditions": [],
        "hook_calls": [],
    }


class ConditionTestHooks(Hook):
    """Hook handlers for condition testing."""

    @hook(BEFORE_UPDATE, model=TestAccount, condition=HasChanged("balance"))
    def balance_changed(self, new_records, old_records):
        condition_state["triggered_conditions"].append("balance_changed")
        condition_state["hook_calls"].append("balance_changed")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=IsEqual("status", "premium"))
    def status_is_premium(self, new_records, old_records):
        condition_state["triggered_conditions"].append("status_is_premium")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=IsNotEqual("status", "active"))
    def status_not_active(self, new_records, old_records):
        condition_state["triggered_conditions"].append("status_not_active")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=ChangesTo("status", "inactive"))
    def changes_to_inactive(self, new_records, old_records):
        condition_state["triggered_conditions"].append("changes_to_inactive")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=WasEqual("status", "pending"))
    def was_pending(self, new_records, old_records):
        condition_state["triggered_conditions"].append("was_pending")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=IsGreaterThan("balance", 1000))
    def balance_gt_1000(self, new_records, old_records):
        condition_state["triggered_conditions"].append("balance_gt_1000")

    @hook(
        BEFORE_UPDATE,
        model=TestAccount,
        condition=IsGreaterThanOrEqual("balance", 1000),
    )
    def balance_gte_1000(self, new_records, old_records):
        condition_state["triggered_conditions"].append("balance_gte_1000")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=IsLessThan("priority", 5))
    def priority_lt_5(self, new_records, old_records):
        condition_state["triggered_conditions"].append("priority_lt_5")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=IsLessThanOrEqual("priority", 5))
    def priority_lte_5(self, new_records, old_records):
        condition_state["triggered_conditions"].append("priority_lte_5")

    @hook(
        BEFORE_UPDATE,
        model=TestAccount,
        condition=HasChanged("balance") & IsEqual("status", "active"),
    )
    def balance_changed_and_active(self, new_records, old_records):
        condition_state["triggered_conditions"].append("balance_changed_and_active")

    @hook(
        BEFORE_UPDATE,
        model=TestAccount,
        condition=IsEqual("status", "premium") | IsEqual("status", "vip"),
    )
    def status_premium_or_vip(self, new_records, old_records):
        condition_state["triggered_conditions"].append("status_premium_or_vip")

    @hook(BEFORE_UPDATE, model=TestAccount, condition=~IsEqual("status", "inactive"))
    def status_not_inactive(self, new_records, old_records):
        condition_state["triggered_conditions"].append("status_not_inactive")


class ConditionsTestCase(TestCase):
    """Test case for hook conditions."""

    def setUp(self):
        """Set up test data."""
        reset_condition_state()
        self.user = User.objects.create_user(username="testuser")
        self.hooks = ConditionTestHooks()

    def test_has_changed_condition(self):
        """Test HasChanged condition."""
        account = TestAccount.objects.create(
            name="Test", balance=100, created_by=self.user
        )
        reset_condition_state()

        # Change balance - should trigger
        account.balance = 200
        account.save()
        self.assertIn("balance_changed", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change name only - should not trigger balance change
        account.name = "Updated Test"
        account.save()
        self.assertNotIn("balance_changed", condition_state["triggered_conditions"])

        reset_condition_state()

        # Set balance to same value - should not trigger
        account.balance = 200
        account.save()
        self.assertNotIn("balance_changed", condition_state["triggered_conditions"])

    def test_is_equal_condition(self):
        """Test IsEqual condition."""
        account = TestAccount.objects.create(
            name="Test", status="active", created_by=self.user
        )
        reset_condition_state()

        # Change to premium status - should trigger
        account.status = "premium"
        account.save()
        self.assertIn("status_is_premium", condition_state["triggered_conditions"])

        reset_condition_state()

        # Update while still premium - should trigger again
        account.name = "Updated"
        account.save()
        self.assertIn("status_is_premium", condition_state["triggered_conditions"])

    def test_is_not_equal_condition(self):
        """Test IsNotEqual condition."""
        account = TestAccount.objects.create(
            name="Test", status="active", created_by=self.user
        )
        reset_condition_state()

        # Status is active, so IsNotEqual('status', 'active') should not trigger
        account.name = "Updated"
        account.save()
        self.assertNotIn("status_not_active", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change to inactive - should trigger
        account.status = "inactive"
        account.save()
        self.assertIn("status_not_active", condition_state["triggered_conditions"])

    def test_changes_to_condition(self):
        """Test ChangesTo condition."""
        account = TestAccount.objects.create(
            name="Test", status="active", created_by=self.user
        )
        reset_condition_state()

        # Change to inactive - should trigger
        account.status = "inactive"
        account.save()
        self.assertIn("changes_to_inactive", condition_state["triggered_conditions"])

        reset_condition_state()

        # Update while inactive - should not trigger
        account.name = "Updated"
        account.save()
        self.assertNotIn("changes_to_inactive", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change from inactive to premium - should not trigger
        account.status = "premium"
        account.save()
        self.assertNotIn("changes_to_inactive", condition_state["triggered_conditions"])

    def test_was_equal_condition(self):
        """Test WasEqual condition."""
        account = TestAccount.objects.create(
            name="Test", status="pending", created_by=self.user
        )
        reset_condition_state()

        # Change from pending to active - should trigger
        account.status = "active"
        account.save()
        self.assertIn("was_pending", condition_state["triggered_conditions"])

        reset_condition_state()

        # Update while active (was not pending) - should not trigger
        account.name = "Updated"
        account.save()
        self.assertNotIn("was_pending", condition_state["triggered_conditions"])

    def test_greater_than_condition(self):
        """Test IsGreaterThan condition."""
        account = TestAccount.objects.create(
            name="Test", balance=500, created_by=self.user
        )
        reset_condition_state()

        # Set balance to 1500 (> 1000) - should trigger
        account.balance = 1500
        account.save()
        self.assertIn("balance_gt_1000", condition_state["triggered_conditions"])

        reset_condition_state()

        # Set balance to exactly 1000 - should not trigger
        account.balance = 1000
        account.save()
        self.assertNotIn("balance_gt_1000", condition_state["triggered_conditions"])

    def test_greater_than_or_equal_condition(self):
        """Test IsGreaterThanOrEqual condition."""
        account = TestAccount.objects.create(
            name="Test", balance=500, created_by=self.user
        )
        reset_condition_state()

        # Set balance to exactly 1000 - should trigger
        account.balance = 1000
        account.save()
        self.assertIn("balance_gte_1000", condition_state["triggered_conditions"])

        reset_condition_state()

        # Set balance to 999 - should not trigger
        account.balance = 999
        account.save()
        self.assertNotIn("balance_gte_1000", condition_state["triggered_conditions"])

    def test_less_than_condition(self):
        """Test IsLessThan condition."""
        account = TestAccount.objects.create(
            name="Test", priority=3, created_by=self.user
        )
        reset_condition_state()

        # Priority 3 < 5 - should trigger
        account.name = "Updated"
        account.save()
        self.assertIn("priority_lt_5", condition_state["triggered_conditions"])

        reset_condition_state()

        # Set priority to 5 - should not trigger
        account.priority = 5
        account.save()
        self.assertNotIn("priority_lt_5", condition_state["triggered_conditions"])

    def test_less_than_or_equal_condition(self):
        """Test IsLessThanOrEqual condition."""
        account = TestAccount.objects.create(
            name="Test", priority=5, created_by=self.user
        )
        reset_condition_state()

        # Priority 5 <= 5 - should trigger
        account.name = "Updated"
        account.save()
        self.assertIn("priority_lte_5", condition_state["triggered_conditions"])

        reset_condition_state()

        # Set priority to 6 - should not trigger
        account.priority = 6
        account.save()
        self.assertNotIn("priority_lte_5", condition_state["triggered_conditions"])

    def test_and_condition(self):
        """Test AndCondition (& operator)."""
        account = TestAccount.objects.create(
            name="Test", balance=100, status="active", created_by=self.user
        )
        reset_condition_state()

        # Change balance while active - should trigger both conditions
        account.balance = 200
        account.save()
        self.assertIn(
            "balance_changed_and_active", condition_state["triggered_conditions"]
        )

        reset_condition_state()

        # Change balance while inactive - should not trigger
        account.status = "inactive"
        account.balance = 300
        account.save()
        self.assertNotIn(
            "balance_changed_and_active", condition_state["triggered_conditions"]
        )

    def test_or_condition(self):
        """Test OrCondition (| operator)."""
        account = TestAccount.objects.create(
            name="Test", status="active", created_by=self.user
        )
        reset_condition_state()

        # Change to premium - should trigger
        account.status = "premium"
        account.save()
        self.assertIn("status_premium_or_vip", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change to vip - should trigger
        account.status = "vip"
        account.save()
        self.assertIn("status_premium_or_vip", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change to inactive - should not trigger
        account.status = "inactive"
        account.save()
        self.assertNotIn(
            "status_premium_or_vip", condition_state["triggered_conditions"]
        )

    def test_not_condition(self):
        """Test NotCondition (~ operator)."""
        account = TestAccount.objects.create(
            name="Test", status="active", created_by=self.user
        )
        reset_condition_state()

        # Status is active (not inactive) - should trigger
        account.name = "Updated"
        account.save()
        self.assertIn("status_not_inactive", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change to inactive - should not trigger
        account.status = "inactive"
        account.save()
        self.assertNotIn("status_not_inactive", condition_state["triggered_conditions"])

    def test_resolve_dotted_attr(self):
        """Test resolve_dotted_attr function."""
        # Clean up any existing users to avoid unique constraint
        User.objects.filter(username="testuser").delete()
        user = User.objects.create_user(
            username="testuser", first_name="John", last_name="Doe"
        )
        account = TestAccount.objects.create(name="Test", created_by=user)
        profile = TestProfile.objects.create(user=user, account=account, bio="Test bio")

        # Test simple attribute
        self.assertEqual(resolve_dotted_attr(account, "name"), "Test")

        # Test dotted attribute
        self.assertEqual(
            resolve_dotted_attr(account, "created_by.username"), "testuser"
        )
        self.assertEqual(resolve_dotted_attr(account, "created_by.first_name"), "John")

        # Test nested dotted attribute
        self.assertEqual(resolve_dotted_attr(profile, "account.name"), "Test")
        self.assertEqual(resolve_dotted_attr(profile, "user.username"), "testuser")

        # Test non-existent attribute
        self.assertIsNone(resolve_dotted_attr(account, "non_existent"))
        self.assertIsNone(resolve_dotted_attr(account, "created_by.non_existent"))

        # Test with None instance
        self.assertIsNone(resolve_dotted_attr(None, "any.path"))

    def test_complex_condition_combinations(self):
        """Test complex combinations of conditions."""

        class ComplexConditionHooks(Hook):
            @hook(
                BEFORE_UPDATE,
                model=TestAccount,
                condition=(HasChanged("balance") & IsGreaterThan("balance", 100))
                | (HasChanged("status") & IsEqual("status", "premium")),
            )
            def complex_condition(self, new_records, old_records):
                condition_state["triggered_conditions"].append("complex_condition")

        complex_hooks = ComplexConditionHooks()

        account = TestAccount.objects.create(
            name="Test", balance=50, status="active", created_by=self.user
        )
        reset_condition_state()

        # Change balance to > 100 - should trigger
        account.balance = 150
        account.save()
        self.assertIn("complex_condition", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change balance to <= 100 - should not trigger
        account.balance = 80
        account.save()
        self.assertNotIn("complex_condition", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change status to premium - should trigger
        account.status = "premium"
        account.save()
        self.assertIn("complex_condition", condition_state["triggered_conditions"])

        reset_condition_state()

        # Change status to something other than premium - should not trigger
        account.status = "inactive"
        account.save()
        self.assertNotIn("complex_condition", condition_state["triggered_conditions"])

    def test_condition_with_none_values(self):
        """Test conditions with None values."""
        account = TestAccount.objects.create(name="Test", created_by=None)  # No user
        reset_condition_state()

        # Update account with None created_by
        account.name = "Updated"
        account.save()

        # Should not cause errors even with None values
        # Specific condition behaviors with None depend on the condition implementation

    def test_condition_performance(self):
        """Test that conditions don't significantly impact performance."""
        # Create multiple accounts
        accounts = []
        for i in range(10):
            account = TestAccount.objects.create(
                name=f"Account {i}", balance=i * 100, created_by=self.user
            )
            accounts.append(account)

        reset_condition_state()

        # Bulk update - conditions should be evaluated efficiently
        for account in accounts:
            account.balance += 50

        TestAccount.objects.bulk_update(accounts, ["balance"])

        # All accounts should have triggered the balance_changed condition
        self.assertIn("balance_changed", condition_state["triggered_conditions"])

    def test_condition_edge_cases(self):
        """Test edge cases for conditions."""
        account = TestAccount.objects.create(
            name="Test", balance=0, created_by=self.user
        )

        # Test with zero values
        reset_condition_state()
        account.balance = 0  # No change
        account.save()
        self.assertNotIn("balance_changed", condition_state["triggered_conditions"])

        # Test with negative values
        reset_condition_state()
        account.balance = -100
        account.save()
        self.assertIn("balance_changed", condition_state["triggered_conditions"])

        # Test with very large values
        reset_condition_state()
        account.balance = 999999999.99
        account.save()
        self.assertIn("balance_changed", condition_state["triggered_conditions"])
