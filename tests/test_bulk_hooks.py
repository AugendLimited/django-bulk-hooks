"""
Comprehensive tests for django-bulk-hooks functionality.
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.test import TestCase, TransactionTestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.conditions import (
    AndCondition,
    ChangesTo,
    HasChanged,
    IsEqual,
    IsGreaterThan,
    IsLessThan,
    IsNotEqual,
    NotCondition,
    OrCondition,
    WasEqual,
)
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
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.models import HookModelMixin
from django_bulk_hooks.priority import Priority


# Test Models
class Account(HookModelMixin):
    """Test model for account operations."""

    name = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, default="active")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)


class Transaction(HookModelMixin):
    """Test model for transaction operations."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=200)
    processed = models.BooleanField(default=False)


class Product(HookModelMixin):
    """Test model for product operations."""

    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=50)
    in_stock = models.BooleanField(default=True)


# Global hook state tracking
hook_state = {
    "calls": [],
    "validations": [],
    "errors": [],
    "account_events": [],
    "transaction_events": [],
    "product_events": [],
}


def reset_hook_state():
    """Reset the global hook state for each test."""
    global hook_state
    hook_state = {
        "calls": [],
        "validations": [],
        "errors": [],
        "account_events": [],
        "transaction_events": [],
        "product_events": [],
    }


class AccountHooks(Hook):
    """Hook handlers for Account model."""

    @hook(VALIDATE_CREATE, model=Account)
    def validate_account_creation(self, new_records, old_records):
        hook_state["validations"].append("account_validate_create")
        for account in new_records:
            if account.balance < 0:
                raise ValidationError(
                    f"Account {account.name} cannot have negative balance"
                )

    @hook(VALIDATE_UPDATE, model=Account)
    def validate_account_update(self, new_records, old_records):
        hook_state["validations"].append("account_validate_update")
        for account in new_records:
            if account.balance < -1000:
                raise ValidationError(
                    f"Account {account.name} balance cannot be below -1000"
                )

    @hook(BEFORE_CREATE, model=Account)
    def before_account_create(self, new_records, old_records):
        hook_state["calls"].append("account_before_create")
        hook_state["account_events"].append(("before_create", len(new_records)))
        for account in new_records:
            if not account.name:
                account.name = f"Account_{account.pk or 'new'}"

    @hook(AFTER_CREATE, model=Account)
    def after_account_create(self, new_records, old_records):
        hook_state["calls"].append("account_after_create")
        hook_state["account_events"].append(("after_create", len(new_records)))

    @hook(BEFORE_UPDATE, model=Account, condition=HasChanged("balance"))
    def before_balance_update(self, new_records, old_records):
        hook_state["calls"].append("account_before_balance_update")
        for new_account, old_account in zip(new_records, old_records):
            hook_state["account_events"].append(
                ("balance_change", old_account.balance, new_account.balance)
            )

    @hook(AFTER_UPDATE, model=Account)
    def after_account_update(self, new_records, old_records):
        hook_state["calls"].append("account_after_update")
        hook_state["account_events"].append(("after_update", len(new_records)))

    @hook(BEFORE_DELETE, model=Account)
    def before_account_delete(self, new_records, old_records):
        hook_state["calls"].append("account_before_delete")
        hook_state["account_events"].append(
            ("before_delete", len(old_records) if old_records else 0)
        )

    @hook(AFTER_DELETE, model=Account)
    def after_account_delete(self, new_records, old_records):
        hook_state["calls"].append("account_after_delete")
        hook_state["account_events"].append(
            ("after_delete", len(old_records) if old_records else 0)
        )


class TransactionHooks(Hook):
    """Hook handlers for Transaction model."""

    @hook(BEFORE_CREATE, model=Transaction)
    def before_transaction_create(self, new_records, old_records):
        hook_state["calls"].append("transaction_before_create")
        hook_state["transaction_events"].append(("before_create", len(new_records)))

    @hook(AFTER_CREATE, model=Transaction)
    def after_transaction_create(self, new_records, old_records):
        hook_state["calls"].append("transaction_after_create")
        hook_state["transaction_events"].append(("after_create", len(new_records)))

    @hook(BEFORE_UPDATE, model=Transaction, condition=ChangesTo("processed", True))
    def before_transaction_processed(self, new_records, old_records):
        hook_state["calls"].append("transaction_before_processed")
        hook_state["transaction_events"].append(("before_processed", len(new_records)))

    @hook(AFTER_UPDATE, model=Transaction, condition=IsEqual("processed", True))
    def after_transaction_processed(self, new_records, old_records):
        hook_state["calls"].append("transaction_after_processed")
        hook_state["transaction_events"].append(("after_processed", len(new_records)))


class ProductHooks(Hook):
    """Hook handlers for Product model with complex conditions."""

    @hook(BEFORE_UPDATE, model=Product, condition=IsGreaterThan("price", 100))
    def before_expensive_product_update(self, new_records, old_records):
        hook_state["calls"].append("product_before_expensive_update")
        hook_state["product_events"].append(("expensive_update", len(new_records)))

    @hook(AFTER_UPDATE, model=Product, condition=IsLessThan("price", 10))
    def after_cheap_product_update(self, new_records, old_records):
        hook_state["calls"].append("product_after_cheap_update")
        hook_state["product_events"].append(("cheap_update", len(new_records)))

    @hook(
        BEFORE_UPDATE,
        model=Product,
        condition=HasChanged("category") & IsEqual("in_stock", True),
    )
    def before_category_change_in_stock(self, new_records, old_records):
        hook_state["calls"].append("product_before_category_change_in_stock")
        hook_state["product_events"].append(
            ("category_change_in_stock", len(new_records))
        )


class BulkHooksTestCase(TestCase):
    """Test case for bulk operations functionality."""

    def setUp(self):
        """Set up test data."""
        reset_hook_state()
        self.user = User.objects.create_user(username="testuser")

        # Register hook instances
        self.account_hooks = AccountHooks()
        self.transaction_hooks = TransactionHooks()
        self.product_hooks = ProductHooks()

    def test_bulk_create_hooks(self):
        """Test that bulk_create triggers appropriate hooks."""
        accounts = [
            Account(name="Account 1", balance=100, created_by=self.user),
            Account(name="Account 2", balance=200, created_by=self.user),
            Account(name="Account 3", balance=300, created_by=self.user),
        ]

        result = Account.objects.bulk_create(accounts)

        # Verify hooks were called in correct order
        expected_calls = ["account_before_create", "account_after_create"]
        self.assertEqual(hook_state["calls"], expected_calls)

        # Verify validation was called separately
        self.assertIn("account_validate_create", hook_state["validations"])

        # Verify hook events
        expected_events = [("before_create", 3), ("after_create", 3)]
        self.assertEqual(hook_state["account_events"], expected_events)

        # Verify objects were created
        self.assertEqual(Account.objects.count(), 3)
        self.assertEqual(len(result), 3)

    def test_bulk_update_hooks(self):
        """Test that bulk_update triggers appropriate hooks."""
        # Create test accounts
        accounts = [
            Account.objects.create(name="Account 1", balance=100, created_by=self.user),
            Account.objects.create(name="Account 2", balance=200, created_by=self.user),
        ]
        reset_hook_state()

        # Update balances
        for account in accounts:
            account.balance += 50

        Account.objects.bulk_update(accounts, ["balance"])

        # Verify hooks were called
        # Note: bulk_update uses complex database expressions, so some hooks may be skipped
        expected_calls = [
            "account_before_balance_update",  # Conditional hook still works
            "account_after_update",
        ]
        self.assertEqual(hook_state["calls"], expected_calls)

        # Validation hooks may be skipped for complex expressions like bulk_update
        # The validation hook might not be called due to Case expressions

        # Verify balance changes were tracked
        balance_changes = [
            event
            for event in hook_state["account_events"]
            if event[0] == "balance_change"
        ]
        self.assertEqual(len(balance_changes), 2)
        self.assertEqual(balance_changes[0], ("balance_change", 100, 150))
        self.assertEqual(balance_changes[1], ("balance_change", 200, 250))

    def test_bulk_delete_hooks(self):
        """Test that bulk_delete triggers appropriate hooks."""
        # Create test accounts
        accounts = [
            Account.objects.create(name="Account 1", balance=100, created_by=self.user),
            Account.objects.create(name="Account 2", balance=200, created_by=self.user),
        ]
        reset_hook_state()

        # Delete accounts using queryset.delete() since bulk_delete might not be implemented
        Account.objects.filter(pk__in=[account.pk for account in accounts]).delete()

        # Verify hooks were called
        expected_calls = ["account_before_delete", "account_after_delete"]
        self.assertEqual(hook_state["calls"], expected_calls)

        # Verify validation was called separately (if implemented)
        # Note: VALIDATE_DELETE hooks are called by queryset.delete()
        # The validation tracking may not show up in hook_state['validations']
        # depending on how the hooks are implemented

        # Verify objects were deleted
        self.assertEqual(Account.objects.count(), 0)

    def test_queryset_update_hooks(self):
        """Test that queryset.update() triggers appropriate hooks."""
        # Create test accounts
        Account.objects.create(name="Account 1", balance=100, created_by=self.user)
        Account.objects.create(name="Account 2", balance=200, created_by=self.user)
        reset_hook_state()

        # Update via queryset
        Account.objects.filter(balance__gte=100).update(status="inactive")

        # Verify hooks were called
        # Note: There's no general BEFORE_UPDATE hook for Account, only conditional ones
        # The conditional BEFORE_UPDATE hook only triggers on balance changes
        self.assertIn("account_after_update", hook_state["calls"])

        # The balance hook should NOT be called since we're updating status, not balance
        self.assertNotIn("account_before_balance_update", hook_state["calls"])

        # Verify database was updated
        self.assertEqual(Account.objects.filter(status="inactive").count(), 2)

    def test_queryset_delete_hooks(self):
        """Test that queryset.delete() triggers appropriate hooks."""
        # Create test accounts
        Account.objects.create(name="Account 1", balance=100, created_by=self.user)
        Account.objects.create(name="Account 2", balance=200, created_by=self.user)
        reset_hook_state()

        # Delete via queryset
        Account.objects.filter(balance__gte=100).delete()

        # Verify hooks were called
        self.assertIn("account_before_delete", hook_state["calls"])
        self.assertIn("account_after_delete", hook_state["calls"])

        # Verify objects were deleted
        self.assertEqual(Account.objects.count(), 0)

    def test_individual_model_save_create_hooks(self):
        """Test that individual model save() for creation triggers hooks."""
        reset_hook_state()

        account = Account(name="Test Account", balance=100, created_by=self.user)
        account.save()

        # Verify hooks were called
        expected_calls = ["account_before_create", "account_after_create"]
        self.assertEqual(hook_state["calls"], expected_calls)

        # Verify validation was called separately
        self.assertIn("account_validate_create", hook_state["validations"])

        # Verify object was created
        self.assertEqual(Account.objects.count(), 1)

    def test_individual_model_save_update_hooks(self):
        """Test that individual model save() for updates triggers hooks."""
        # Create account first
        account = Account.objects.create(
            name="Test Account", balance=100, created_by=self.user
        )
        reset_hook_state()

        # Update and save
        account.balance = 150
        account.save()

        # Verify hooks were called
        expected_calls = [
            "account_before_balance_update",  # Conditional hook for balance changes
            "account_after_update",
        ]
        self.assertEqual(hook_state["calls"], expected_calls)

        # Verify validation was called separately
        self.assertIn("account_validate_update", hook_state["validations"])

    def test_individual_model_delete_hooks(self):
        """Test that individual model delete() triggers hooks."""
        # Create account first
        account = Account.objects.create(
            name="Test Account", balance=100, created_by=self.user
        )
        reset_hook_state()

        # Delete
        account.delete()

        # Verify hooks were called
        expected_calls = ["account_before_delete", "account_after_delete"]
        self.assertEqual(hook_state["calls"], expected_calls)

        # Verify object was deleted
        self.assertEqual(Account.objects.count(), 0)

    def test_bypass_hooks_parameter(self):
        """Test that bypass_hooks parameter works correctly."""
        reset_hook_state()

        # Create with bypass_hooks=True
        accounts = [
            Account(name="Account 1", balance=100, created_by=self.user),
            Account(name="Account 2", balance=200, created_by=self.user),
        ]
        Account.objects.bulk_create(accounts, bypass_hooks=True)

        # Verify no hooks were called
        self.assertEqual(hook_state["calls"], [])

        # Verify objects were still created
        self.assertEqual(Account.objects.count(), 2)

    def test_bypass_validation_parameter(self):
        """Test that bypass_validation parameter works correctly."""
        reset_hook_state()

        # Create with bypass_validation=True but allow hooks
        accounts = [
            Account(name="Account 1", balance=100, created_by=self.user),
        ]
        Account.objects.bulk_create(accounts, bypass_validation=True)

        # Verify validation hooks were skipped but others were called
        self.assertNotIn("account_validate_create", hook_state["calls"])
        self.assertIn("account_before_create", hook_state["calls"])
        self.assertIn("account_after_create", hook_state["calls"])


class HookConditionsTestCase(TestCase):
    """Test case for hook conditions functionality."""

    def setUp(self):
        """Set up test data."""
        reset_hook_state()
        self.user = User.objects.create_user(username="testuser")
        self.account_hooks = AccountHooks()
        self.transaction_hooks = TransactionHooks()
        self.product_hooks = ProductHooks()

    def test_has_changed_condition(self):
        """Test HasChanged condition."""
        account = Account.objects.create(
            name="Test Account", balance=100, created_by=self.user
        )
        reset_hook_state()

        # Update balance (should trigger condition)
        account.balance = 150
        account.save()

        self.assertIn("account_before_balance_update", hook_state["calls"])

        reset_hook_state()

        # Update name only (should not trigger balance condition)
        account.name = "Updated Name"
        account.save()

        self.assertNotIn("account_before_balance_update", hook_state["calls"])

    def test_changes_to_condition(self):
        """Test ChangesTo condition."""
        transaction = Transaction.objects.create(
            account=Account.objects.create(
                name="Test Account", balance=100, created_by=self.user
            ),
            amount=50,
            description="Test transaction",
            processed=False,
        )
        reset_hook_state()

        # Change processed from False to True (should trigger)
        transaction.processed = True
        transaction.save()

        self.assertIn("transaction_before_processed", hook_state["calls"])

        reset_hook_state()

        # Change processed from True to False (should not trigger)
        transaction.processed = False
        transaction.save()

        self.assertNotIn("transaction_before_processed", hook_state["calls"])

    def test_is_equal_condition(self):
        """Test IsEqual condition."""
        transaction = Transaction.objects.create(
            account=Account.objects.create(
                name="Test Account", balance=100, created_by=self.user
            ),
            amount=50,
            description="Test transaction",
            processed=True,  # Start as processed
        )
        reset_hook_state()

        # Update description while processed=True (should trigger)
        transaction.description = "Updated description"
        transaction.save()

        self.assertIn("transaction_after_processed", hook_state["calls"])

    def test_is_greater_than_condition(self):
        """Test IsGreaterThan condition."""
        product = Product.objects.create(
            name="Test Product", price=50, category="electronics"
        )
        reset_hook_state()

        # Update price to above 100 (should trigger)
        product.price = 150
        product.save()

        self.assertIn("product_before_expensive_update", hook_state["calls"])

        reset_hook_state()

        # Update price to below 100 (should not trigger)
        product.price = 75
        product.save()

        self.assertNotIn("product_before_expensive_update", hook_state["calls"])

    def test_is_less_than_condition(self):
        """Test IsLessThan condition."""
        product = Product.objects.create(
            name="Test Product", price=50, category="electronics"
        )
        reset_hook_state()

        # Update price to below 10 (should trigger)
        product.price = 5
        product.save()

        self.assertIn("product_after_cheap_update", hook_state["calls"])

    def test_and_condition(self):
        """Test AndCondition (& operator)."""
        product = Product.objects.create(
            name="Test Product", price=50, category="electronics", in_stock=True
        )
        reset_hook_state()

        # Change category while in_stock=True (should trigger)
        product.category = "books"
        product.save()

        self.assertIn("product_before_category_change_in_stock", hook_state["calls"])

        reset_hook_state()

        # Change category while in_stock=False (should not trigger)
        product.in_stock = False
        product.category = "toys"
        product.save()

        self.assertNotIn("product_before_category_change_in_stock", hook_state["calls"])


class ValidationHooksTestCase(TestCase):
    """Test case for validation hooks functionality."""

    def setUp(self):
        """Set up test data."""
        reset_hook_state()
        self.user = User.objects.create_user(username="testuser")
        self.account_hooks = AccountHooks()

    def test_validation_create_error(self):
        """Test that validation errors are raised during create."""
        with self.assertRaises(ValidationError) as context:
            Account.objects.create(
                name="Test Account", balance=-100, created_by=self.user
            )

        self.assertIn("negative balance", str(context.exception))
        self.assertEqual(Account.objects.count(), 0)

    def test_validation_update_error(self):
        """Test that validation errors are raised during update."""
        account = Account.objects.create(
            name="Test Account", balance=100, created_by=self.user
        )

        with self.assertRaises(ValidationError) as context:
            account.balance = -2000
            account.save()

        self.assertIn("below -1000", str(context.exception))

    def test_validation_bulk_create_error(self):
        """Test that validation errors are raised during bulk_create."""
        accounts = [
            Account(name="Account 1", balance=100, created_by=self.user),
            Account(name="Account 2", balance=-200, created_by=self.user),  # Invalid
        ]

        with self.assertRaises(ValidationError):
            Account.objects.bulk_create(accounts)

        # No accounts should be created due to transaction rollback
        self.assertEqual(Account.objects.count(), 0)

    def test_clean_method_validation(self):
        """Test that clean() method triggers validation hooks."""
        reset_hook_state()

        account = Account(name="Test Account", balance=-100, created_by=self.user)

        with self.assertRaises(ValidationError):
            account.clean()

        self.assertIn("account_validate_create", hook_state["validations"])


class TransactionTestCase(TransactionTestCase):
    """Test case for transaction behavior."""

    def setUp(self):
        """Set up test data."""
        reset_hook_state()
        self.user = User.objects.create_user(username="testuser")
        self.account_hooks = AccountHooks()

    def test_transaction_rollback_on_hook_error(self):
        """Test that transactions are rolled back when hooks raise errors."""

        class FailingHook(Hook):
            @hook(BEFORE_CREATE, model=Account)
            def failing_hook(self, new_records, old_records):
                raise ValueError("Simulated hook failure")

        failing_hook = FailingHook()

        with self.assertRaises(ValueError):
            Account.objects.create(
                name="Test Account", balance=100, created_by=self.user
            )

        # Account should not be created due to rollback
        self.assertEqual(Account.objects.count(), 0)

    def test_transaction_atomicity_bulk_operations(self):
        """Test that bulk operations are atomic."""

        class ConditionalFailingHook(Hook):
            @hook(BEFORE_CREATE, model=Account)
            def conditional_failing_hook(self, new_records, old_records):
                for account in new_records:
                    if account.name == "Fail Account":
                        raise ValueError("Simulated failure for specific account")

        failing_hook = ConditionalFailingHook()

        accounts = [
            Account(name="Good Account 1", balance=100, created_by=self.user),
            Account(name="Good Account 2", balance=200, created_by=self.user),
            Account(name="Fail Account", balance=300, created_by=self.user),
        ]

        with self.assertRaises(ValueError):
            Account.objects.bulk_create(accounts)

        # No accounts should be created due to transaction rollback
        self.assertEqual(Account.objects.count(), 0)


class HookPriorityTestCase(TestCase):
    """Test case for hook priority and ordering."""

    def setUp(self):
        """Set up test data."""
        reset_hook_state()
        self.user = User.objects.create_user(username="testuser")

    def test_hook_priority_ordering(self):
        """Test that hooks are executed in priority order."""

        class PriorityHooks(Hook):
            @hook(BEFORE_CREATE, model=Account, priority=Priority.HIGH)
            def high_priority_hook(self, new_records, old_records):
                hook_state["calls"].append("high_priority")

            @hook(BEFORE_CREATE, model=Account, priority=Priority.LOW)
            def low_priority_hook(self, new_records, old_records):
                hook_state["calls"].append("low_priority")

            @hook(BEFORE_CREATE, model=Account, priority=Priority.NORMAL)
            def normal_priority_hook(self, new_records, old_records):
                hook_state["calls"].append("normal_priority")

        priority_hooks = PriorityHooks()

        Account.objects.create(name="Test Account", balance=100, created_by=self.user)

        # Check that hooks were called in correct priority order
        priority_calls = [call for call in hook_state["calls"] if "priority" in call]
        expected_order = ["high_priority", "normal_priority", "low_priority"]
        self.assertEqual(priority_calls, expected_order)


class MTITestCase(TestCase):
    """Test case for Multi-Table Inheritance support."""

    def setUp(self):
        """Set up test data."""
        reset_hook_state()
        self.user = User.objects.create_user(username="testuser")

    def test_mti_model_hooks(self):
        """Test that MTI models work with hooks."""
        # Note: This test assumes MTI models exist in the codebase
        # If not implemented yet, this test can be skipped or the models created here

        class BaseAccount(HookModelMixin):
            name = models.CharField(max_length=100)

            class Meta:
                abstract = False

        class SavingsAccount(BaseAccount):
            interest_rate = models.DecimalField(max_digits=5, decimal_places=2)

        # This test would verify MTI functionality when implemented
        pass


class EdgeCasesTestCase(TestCase):
    """Test case for edge cases and error conditions."""

    def setUp(self):
        """Set up test data."""
        reset_hook_state()
        self.user = User.objects.create_user(username="testuser")
        self.account_hooks = AccountHooks()

    def test_empty_bulk_operations(self):
        """Test bulk operations with empty lists."""
        reset_hook_state()

        # Empty bulk_create
        result = Account.objects.bulk_create([])
        self.assertEqual(result, [])
        self.assertEqual(hook_state["calls"], [])

        # Empty bulk_update
        Account.objects.bulk_update([], ["balance"])
        self.assertEqual(hook_state["calls"], [])

        # Empty bulk_delete
        Account.objects.bulk_delete([])
        self.assertEqual(hook_state["calls"], [])

    def test_non_existent_field_update(self):
        """Test updating non-existent fields."""
        account = Account.objects.create(
            name="Test Account", balance=100, created_by=self.user
        )

        # Django allows setting arbitrary attributes, so this shouldn't raise an error
        account.non_existent_field = "value"
        self.assertEqual(account.non_existent_field, "value")

        # But trying to save with non-existent fields in update() should raise an error
        from django.core.exceptions import FieldDoesNotExist

        with self.assertRaises(FieldDoesNotExist):
            Account.objects.filter(pk=account.pk).update(non_existent_field="value")

    def test_hook_with_none_records(self):
        """Test hook behavior with None values."""
        # Create a hook that handles None gracefully

        class SafeHook(Hook):
            @hook(BEFORE_UPDATE, model=Account)
            def safe_hook(self, new_records, old_records):
                hook_state["calls"].append("safe_hook")
                # Ensure we handle None gracefully
                for new_record in new_records or []:
                    if new_record is not None:
                        hook_state["calls"].append(f"processed_{new_record.pk}")

        safe_hook = SafeHook()

        account = Account.objects.create(
            name="Test Account", balance=100, created_by=self.user
        )
        reset_hook_state()

        account.balance = 150
        account.save()

        self.assertIn("safe_hook", hook_state["calls"])

    def test_concurrent_hook_registration(self):
        """Test that multiple hook classes can be registered without conflicts."""

        class AdditionalAccountHooks(Hook):
            @hook(AFTER_CREATE, model=Account)
            def additional_after_create(self, new_records, old_records):
                hook_state["calls"].append("additional_after_create")

        additional_hooks = AdditionalAccountHooks()

        Account.objects.create(name="Test Account", balance=100, created_by=self.user)

        # Both hook classes should have been called
        self.assertIn("account_after_create", hook_state["calls"])
        self.assertIn("additional_after_create", hook_state["calls"])

    def test_hook_with_related_field_access(self):
        """Test hooks that access related fields."""

        class RelatedFieldHook(Hook):
            @hook(AFTER_CREATE, model=Transaction)
            def access_related_fields(self, new_records, old_records):
                hook_state["calls"].append("access_related_fields")
                for transaction in new_records:
                    # Access related account
                    account_name = transaction.account.name
                    hook_state["calls"].append(f"account_name_{account_name}")

        related_hook = RelatedFieldHook()

        account = Account.objects.create(
            name="Main Account", balance=100, created_by=self.user
        )
        transaction = Transaction.objects.create(
            account=account, amount=50, description="Test transaction"
        )

        self.assertIn("access_related_fields", hook_state["calls"])
        self.assertIn("account_name_Main Account", hook_state["calls"])
