"""
Tests for registry helpers (temporary registration/isolation), concurrency-safe
execution, and expanded bulk/update variants.
"""

import threading
from typing import List

from django.test import TestCase

from django_bulk_hooks import Hook
from django_bulk_hooks.constants import BEFORE_CREATE, BEFORE_UPDATE
from django_bulk_hooks.decorators import hook
from django_bulk_hooks.engine import run as run_hooks
from django_bulk_hooks.registry import (
    get_hooks,
    isolated_registry,
    temporary_hook,
)


# Import existing test models to avoid adding new schema
from tests.test_registry_and_decorators import RegistryTestModel  # noqa: E402
from tests.test_error_handling import ErrorTestModel  # noqa: E402


class RegistryHelpersTestCase(TestCase):
    """Tests for registry helper context managers."""

    def test_temporary_hook_registers_and_unregisters(self):
        calls: List[str] = []

        class TempHandler:
            def temp(self, new_records, old_records):
                calls.append("temp_called")

        # Capture baseline and ensure our hook is not present
        baseline = get_hooks(RegistryTestModel, BEFORE_CREATE)
        self.assertFalse(any(h[0].__name__ == "TempHandler" and h[1] == "temp" for h in baseline))

        with temporary_hook(
            RegistryTestModel, BEFORE_CREATE, TempHandler, "temp", None, 50
        ):
            # Should be registered now
            hooks_inside = get_hooks(RegistryTestModel, BEFORE_CREATE)
            self.assertTrue(
                any(h[0] == TempHandler and h[1] == "temp" for h in hooks_inside)
            )

            # Trigger via engine directly without DB
            instances = [RegistryTestModel(name="n")]  # unsaved is fine
            run_hooks(RegistryTestModel, BEFORE_CREATE, instances)
            self.assertIn("temp_called", calls)

        # After context, hook should be removed (and baseline state preserved)
        hooks_after = get_hooks(RegistryTestModel, BEFORE_CREATE)
        self.assertFalse(any(h[0] == TempHandler and h[1] == "temp" for h in hooks_after))

    def test_isolated_registry_restores_prior_state(self):
        baseline = get_hooks(RegistryTestModel, BEFORE_CREATE)

        with isolated_registry():
            # Define the hook class inside the isolation so metaclass registration
            # occurs only within the isolated context
            class IsoHook(Hook):
                @hook(BEFORE_CREATE, model=RegistryTestModel)
                def iso(self, new_records, old_records):
                    pass

            hooks_inside = get_hooks(RegistryTestModel, BEFORE_CREATE)
            self.assertTrue(
                any(h[0].__name__ == "IsoHook" and h[1] == "iso" for h in hooks_inside)
            )

        # After isolation, registry should be back to baseline (no IsoHook)
        hooks_after = get_hooks(RegistryTestModel, BEFORE_CREATE)
        self.assertFalse(any(h[0].__name__ == "IsoHook" and h[1] == "iso" for h in hooks_after))


class ExpandedOperationsTestCase(TestCase):
    """Expanded tests for bulk and update options."""

    def test_bulk_create_ignore_conflicts(self):
        # Prepare one existing row to cause conflict
        ErrorTestModel.objects.create(
            name="A", required_field="r", unique_field="U1"
        )

        # Two rows: one duplicate unique_field, one new
        objs = [
            ErrorTestModel(name="Dup", required_field="r", unique_field="U1"),
            ErrorTestModel(name="New", required_field="r", unique_field="U2"),
        ]

        created = ErrorTestModel.objects.bulk_create(
            objs, ignore_conflicts=True, batch_size=50
        )

        # Only the new one should be inserted
        self.assertEqual(ErrorTestModel.objects.count(), 2)
        self.assertTrue(any(o.name == "New" for o in ErrorTestModel.objects.all()))
        # Django may return fewer objects when ignore_conflicts=True
        self.assertGreaterEqual(len(created), 1)

    def test_bulk_update_multiple_fields(self):
        a = ErrorTestModel.objects.create(
            name="X", value=1, required_field="r1", unique_field="UA"
        )
        b = ErrorTestModel.objects.create(
            name="Y", value=2, required_field="r2", unique_field="UB"
        )

        a.name, a.value = "X2", 10
        b.name, b.value = "Y2", 20

        ErrorTestModel.objects.bulk_update([a, b], ["name", "value"])

        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.name, a.value), ("X2", 10))
        self.assertEqual((b.name, b.value), ("Y2", 20))

    def test_save_with_update_fields(self):
        obj = ErrorTestModel.objects.create(
            name="N", value=5, required_field="r", unique_field="UC"
        )

        obj.value = 6
        obj.save(update_fields=["value"])  # Should behave like partial update

        obj.refresh_from_db()
        self.assertEqual(obj.value, 6)


class EngineConcurrencyTestCase(TestCase):
    """Concurrency test that avoids DB by invoking engine directly in threads."""

    def test_engine_run_concurrent_threads(self):
        counts: List[int] = []

        class ConcurrencyHook(Hook):
            @hook(BEFORE_CREATE, model=RegistryTestModel)
            def count(self, new_records, old_records):
                counts.append(len(new_records))

        def worker():
            instances = [RegistryTestModel(name="n") for _ in range(50)]
            run_hooks(RegistryTestModel, BEFORE_CREATE, instances)

        with temporary_hook(
            RegistryTestModel, BEFORE_CREATE, ConcurrencyHook, "count", None, 50
        ):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # We should have one call per thread, each processing 50 records
        self.assertEqual(sum(counts), 4 * 50)


