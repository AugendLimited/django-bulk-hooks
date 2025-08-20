
# django-bulk-hooks

⚡ Bulk hooks for Django bulk operations and individual model lifecycle events.

`django-bulk-hooks` brings a declarative, hook-like experience to Django's `bulk_create`, `bulk_update`, and `bulk_delete` — including support for `BEFORE_` and `AFTER_` hooks, conditions, batching, and transactional safety. It also provides comprehensive lifecycle hooks for individual model operations.

## ✨ Features

- Declarative hook system: `@hook(AFTER_UPDATE, condition=...)`
- BEFORE/AFTER hooks for create, update, delete
- Hook-aware manager that wraps Django's `bulk_` operations
- **NEW**: `HookModelMixin` for individual model lifecycle events
- Hook chaining, hook deduplication, and atomicity
- Class-based hook handlers with DI support
- Support for both bulk and individual model operations

## 🚀 Quickstart

```bash
pip install django-bulk-hooks
```

### Define Your Model

```python
from django.db import models
from django_bulk_hooks.models import HookModelMixin

class Account(HookModelMixin):
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    # The HookModelMixin automatically provides BulkHookManager
```

### Create a Hook Handler

```python
from django_bulk_hooks import hook, AFTER_UPDATE, Hook
from django_bulk_hooks.conditions import WhenFieldHasChanged
from .models import Account

class AccountHooks(Hook):
    @hook(AFTER_UPDATE, condition=WhenFieldHasChanged('balance'))
    def _notify_balance_change(self, new_records, old_records, **kwargs):
        for new_record, old_record in zip(new_records, old_records):
            if old_record and new_record.balance != old_record.balance:
                print(f"Balance changed from {old_record.balance} to {new_record.balance}")
```

### Bulk Operations with Hooks

```python
# For complete hook execution, use the update() method
accounts = Account.objects.filter(active=True)
accounts.update(balance=1000)  # Runs all hooks automatically

# For bulk operations with hooks
accounts = Account.objects.filter(active=True)
instances = list(accounts)

# bulk_update now runs complete hook cycle by default
accounts.bulk_update(instances, ['balance'])  # Runs VALIDATE → BEFORE → DB update → AFTER

# To skip hooks (for performance or when called from update())
accounts.bulk_update(instances, ['balance'], bypass_hooks=True)
```

### Understanding Hook Execution

- **`update()` method**: Runs complete hook cycle (VALIDATE → BEFORE → DB update → AFTER)
- **`bulk_update()` method**: Runs complete hook cycle (VALIDATE → BEFORE → DB update → AFTER)
- **`bypass_hooks=True`**: Skips all hooks for performance or to prevent double execution

## 🛠 Supported Hook Events

- `BEFORE_CREATE`, `AFTER_CREATE`
- `BEFORE_UPDATE`, `AFTER_UPDATE`
- `BEFORE_DELETE`, `AFTER_DELETE`

## 🔄 Lifecycle Events

### Individual Model Operations

The `HookModelMixin` automatically triggers hooks for individual model operations:

```python
# These will trigger BEFORE_CREATE and AFTER_CREATE hooks
account = Account.objects.create(balance=100.00)
account.save()  # for new instances

# These will trigger BEFORE_UPDATE and AFTER_UPDATE hooks
account.balance = 200.00
account.save()  # for existing instances

# This will trigger BEFORE_DELETE and AFTER_DELETE hooks
account.delete()
```

### Bulk Operations

Bulk operations also trigger the same hooks:

```python
# Bulk create - triggers BEFORE_CREATE and AFTER_CREATE hooks
accounts = [
    Account(balance=100.00),
    Account(balance=200.00),
]
Account.objects.bulk_create(accounts)

# Bulk update - triggers BEFORE_UPDATE and AFTER_UPDATE hooks
for account in accounts:
    account.balance *= 1.1
Account.objects.bulk_update(accounts, ['balance'])

# Bulk delete - triggers BEFORE_DELETE and AFTER_DELETE hooks
Account.objects.bulk_delete(accounts)
```

### Queryset Operations

Queryset operations are also supported:

```python
# Queryset update - triggers BEFORE_UPDATE and AFTER_UPDATE hooks
Account.objects.update(balance=0.00)

# Queryset delete - triggers BEFORE_DELETE and AFTER_DELETE hooks
Account.objects.delete()
```

### Subquery Support in Updates

When using `Subquery` objects in update operations, the computed values are automatically available in hooks. The system efficiently refreshes all instances in bulk for optimal performance:

```python
from django.db.models import Subquery, OuterRef, Sum

def aggregate_revenue_by_ids(self, ids: Iterable[int]) -> int:
    return self.find_by_ids(ids).update(
        revenue=Subquery(
            FinancialTransaction.objects.filter(daily_financial_aggregate_id=OuterRef("pk"))
            .filter(is_revenue=True)
            .values("daily_financial_aggregate_id")
            .annotate(revenue_sum=Sum("amount"))
            .values("revenue_sum")[:1],
        ),
    )

# In your hooks, you can now access the computed revenue value:
class FinancialAggregateHooks(Hook):
    @hook(AFTER_UPDATE, model=DailyFinancialAggregate)
    def log_revenue_update(self, new_records, old_records):
        for new_record in new_records:
            # This will now contain the computed value, not the Subquery object
            print(f"Updated revenue: {new_record.revenue}")

# Bulk operations are optimized for performance:
def bulk_aggregate_revenue(self, ids: Iterable[int]) -> int:
    # This will efficiently refresh all instances in a single query
    return self.filter(id__in=ids).update(
        revenue=Subquery(
            FinancialTransaction.objects.filter(daily_financial_aggregate_id=OuterRef("pk"))
            .filter(is_revenue=True)
            .values("daily_financial_aggregate_id")
            .annotate(revenue_sum=Sum("amount"))
            .values("revenue_sum")[:1],
        ),
    )
```

## 🧠 Why?

Django's `bulk_` methods bypass signals and `save()`. This package fills that gap with:

- Hooks that behave consistently across creates/updates/deletes
- **NEW**: Individual model lifecycle hooks that work with `save()` and `delete()`
- Scalable performance via chunking (default 200)
- Support for `@hook` decorators and centralized hook classes
- **NEW**: Automatic hook triggering for admin operations and other Django features
- **NEW**: Proper ordering guarantees for old/new record pairing in hooks (Salesforce-like behavior)

## 📦 Usage Examples

### Individual Model Operations

```python
# These automatically trigger hooks
account = Account.objects.create(balance=100.00)
account.balance = 200.00
account.save()
account.delete()
```

### Bulk Operations

```python
# These also trigger hooks
Account.objects.bulk_create(accounts)
Account.objects.bulk_update(accounts, ['balance'])
Account.objects.bulk_delete(accounts)
```

### Advanced Hook Usage

```python
class AdvancedAccountHooks(Hook):
    @hook(BEFORE_UPDATE, model=Account, condition=WhenFieldHasChanged("balance"))
    def validate_balance_change(self, new_records, old_records):
        for new_account, old_account in zip(new_records, old_records):
            if new_account.balance < 0 and old_account.balance >= 0:
                raise ValueError("Cannot set negative balance")
    
    @hook(AFTER_CREATE, model=Account)
    def send_welcome_email(self, new_records, old_records):
        for account in new_records:
            # Send welcome email logic here
            pass
```

### Salesforce-like Ordering Guarantees

The system ensures that `old_records` and `new_records` are always properly paired, regardless of the order in which you pass objects to bulk operations:

```python
class LoanAccountHooks(Hook):
    @hook(BEFORE_UPDATE, model=LoanAccount)
    def validate_account_number(self, new_records, old_records):
        # old_records[i] always corresponds to new_records[i]
        for new_account, old_account in zip(new_records, old_records):
            if old_account.account_number != new_account.account_number:
                raise ValidationError("Account number cannot be changed")

# This works correctly even with reordered objects:
accounts = [account1, account2, account3]  # IDs: 1, 2, 3
reordered = [account3, account1, account2]  # IDs: 3, 1, 2

# The hook will still receive properly paired old/new records
LoanAccount.objects.bulk_update(reordered, ['balance'])
```

## 🧩 Integration with Other Managers

You can extend from `BulkHookManager` to work with other manager classes. The manager uses a cooperative approach that dynamically injects bulk hook functionality into any queryset, ensuring compatibility with other managers.

```python
from django_bulk_hooks.manager import BulkHookManager
from queryable_properties.managers import QueryablePropertiesManager

class MyManager(BulkHookManager, QueryablePropertiesManager):
    pass
```

This approach uses the industry-standard injection pattern, similar to how `QueryablePropertiesManager` works, ensuring both functionalities work seamlessly together without any framework-specific knowledge.

## 📝 License

MIT © 2024 Augend / Konrad Beck
