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
        from tests.test_subquery_hooks import RelatedModel, TestModel, User

        schema_editor.create_model(User)
        schema_editor.create_model(TestModel)
        schema_editor.create_model(RelatedModel)
