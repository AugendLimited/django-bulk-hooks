import os

import django
from django.conf import settings
from django.core.management import call_command
from django.db import connection


def pytest_configure():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_settings")
    settings.configure(
        DEBUG=True,
        SECRET_KEY="test-secret-key",
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "tests",
        ],
        USE_TZ=True,
        MIGRATION_MODULES={"tests": None},  # Disable migrations for test app
    )
    django.setup()
    # Create test database tables
    call_command("migrate", verbosity=0, interactive=False)

    # Create test app tables manually
    with connection.schema_editor() as schema_editor:
        from tests.test_bulk_hooks import Account, Product, Transaction
        from tests.test_conditions import TestAccount, TestProfile
        from tests.test_error_handling import ErrorTestModel, RelatedErrorModel
        from tests.test_multiple_inheritance import MultiInheritanceTestModel, DailyLoanSummaryMockModel
        from tests.test_priority_and_ordering import OrderedTestModel
        from tests.test_subquery_hooks import RelatedModel, TestModel, User

        # Create User model first (it's referenced by others)
        schema_editor.create_model(User)

        # Create test models from subquery tests
        schema_editor.create_model(TestModel)
        schema_editor.create_model(RelatedModel)

        # Create test models from bulk hooks tests
        schema_editor.create_model(Account)
        schema_editor.create_model(Transaction)
        schema_editor.create_model(Product)

        # Create test models from conditions tests
        schema_editor.create_model(TestAccount)
        schema_editor.create_model(TestProfile)

        # Create test models from priority tests
        schema_editor.create_model(OrderedTestModel)

        # Create test models from error handling tests
        schema_editor.create_model(ErrorTestModel)
        schema_editor.create_model(RelatedErrorModel)

        # Create test models from multiple inheritance tests
        schema_editor.create_model(MultiInheritanceTestModel)
        schema_editor.create_model(DailyLoanSummaryMockModel)
