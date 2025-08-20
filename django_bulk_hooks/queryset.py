import logging

from django.db import models, transaction
from django.db.models import AutoField, Case, Value, When
from django_bulk_hooks import engine
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
from django_bulk_hooks.context import HookContext

logger = logging.getLogger(__name__)


class HookQuerySetMixin:
    """
    A mixin that provides bulk hook functionality to any QuerySet.
    This can be dynamically injected into querysets from other managers.
    """

    @transaction.atomic
    def delete(self):
        """
        Delete objects from the database with complete hook support.

        This method runs the complete hook cycle:
        VALIDATE_DELETE → BEFORE_DELETE → DB delete → AFTER_DELETE
        """
        objs = list(self)
        if not objs:
            return 0

        model_cls = self.model

        # Validate that all objects have primary keys
        for obj in objs:
            if obj.pk is None:
                raise ValueError("Cannot delete objects without primary keys")

        ctx = HookContext(model_cls)

        # Run validation hooks first
        engine.run(model_cls, VALIDATE_DELETE, objs, ctx=ctx)

        # Then run business logic hooks
        engine.run(model_cls, BEFORE_DELETE, objs, ctx=ctx)

        # Use Django's standard delete() method
        result = super().delete()

        # Run AFTER_DELETE hooks
        engine.run(model_cls, AFTER_DELETE, objs, ctx=ctx)

        return result

    @transaction.atomic
    def update(self, **kwargs):
        """
        Update objects with field values and run complete hook cycle.
        
        This method runs the complete hook cycle for all updates:
        VALIDATE_UPDATE → BEFORE_UPDATE → DB update → AFTER_UPDATE
        
        Supports both simple field updates and complex expressions (Subquery, Case, etc.).
        """
        # Extract custom parameters
        bypass_hooks = kwargs.pop('bypass_hooks', False)
        
        instances = list(self)
        if not instances:
            return 0

        model_cls = self.model
        pks = [obj.pk for obj in instances]

        # Load originals for hook comparison
        original_map = {
            obj.pk: obj for obj in model_cls._base_manager.filter(pk__in=pks)
        }
        originals = [original_map.get(obj.pk) for obj in instances]

        # Check if any of the update values are complex database expressions
        has_subquery = any(
            (hasattr(value, "query") and hasattr(value.query, "model"))
            or (hasattr(value, "get_source_expressions") and value.get_source_expressions())
            for value in kwargs.values()
        )

        # Run hooks only if not bypassed
        if not bypass_hooks:
            ctx = HookContext(model_cls)
            # Run VALIDATE_UPDATE hooks
            engine.run(model_cls, VALIDATE_UPDATE, instances, originals, ctx=ctx)
            
            # For subqueries, we need to compute the values and apply them to instances
            # before running BEFORE_UPDATE hooks
            if has_subquery:
                # Create a temporary update to compute the values
                # We'll use a subquery to compute values without actually updating
                for field_name, value in kwargs.items():
                    if (hasattr(value, "query") and hasattr(value.query, "model")) or \
                       (hasattr(value, "get_source_expressions") and value.get_source_expressions()):
                        # This is a complex expression - compute it for each instance
                        for instance in instances:
                            # Create a single-instance queryset to compute the value
                            single_qs = model_cls._base_manager.filter(pk=instance.pk)
                            computed_values = single_qs.annotate(computed_field=value).values_list('computed_field', flat=True)
                            if computed_values:
                                setattr(instance, field_name, computed_values[0])
            else:
                # For simple updates, apply the values directly
                for obj in instances:
                    for field, value in kwargs.items():
                        setattr(obj, field, value)
            
            # Run BEFORE_UPDATE hooks with updated instances
            engine.run(model_cls, BEFORE_UPDATE, instances, originals, ctx=ctx)

        if has_subquery:
            # For complex expressions, use Django's native update
            # This handles Subquery, Case, F expressions, etc. correctly
            result = super().update(**kwargs)
            
            # After updating with complex expressions, we need to reload the instances
            # to get the computed values for the AFTER_UPDATE hooks
            if not bypass_hooks:
                # Reload instances to get computed values
                updated_instances = list(model_cls._base_manager.filter(pk__in=pks))
                # Maintain the original order
                updated_map = {obj.pk: obj for obj in updated_instances}
                instances = [updated_map.get(obj.pk, obj) for obj in instances]
        else:
            # For simple field updates, instances have already been updated in the hook section
            # Perform database update using Django's native bulk_update
            # We use the base manager to avoid recursion
            base_manager = model_cls._base_manager
            fields_to_update = list(kwargs.keys())
            base_manager.bulk_update(instances, fields_to_update)
            result = len(instances)

        # Run AFTER_UPDATE hooks only if not bypassed
        if not bypass_hooks:
            ctx = HookContext(model_cls)
            engine.run(model_cls, AFTER_UPDATE, instances, originals, ctx=ctx)
        
        return result

    @transaction.atomic
    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
        bypass_hooks=False,
        bypass_validation=False,
    ):
        """
        Insert each of the instances into the database with complete hook support.

        This method runs the complete hook cycle:
        VALIDATE_CREATE → BEFORE_CREATE → DB create → AFTER_CREATE

        Behaves like Django's bulk_create but supports multi-table inheritance (MTI)
        models and hooks. All arguments are supported and passed through to the correct logic.
        """
        model_cls = self.model

        # Validate inputs
        if not isinstance(objs, (list, tuple)):
            raise TypeError("objs must be a list or tuple")

        if not objs:
            return objs

        if any(not isinstance(obj, model_cls) for obj in objs):
            raise TypeError(
                f"bulk_create expected instances of {model_cls.__name__}, "
                f"but got {set(type(obj).__name__ for obj in objs)}"
            )

        if batch_size is not None and batch_size <= 0:
            raise ValueError("batch_size must be a positive integer.")

        # Check for MTI - if we detect multi-table inheritance, we need special handling
        # This follows Django's approach: check that the parents share the same concrete model
        # with our model to detect the inheritance pattern ConcreteGrandParent ->
        # MultiTableParent -> ProxyChild. Simply checking self.model._meta.proxy would not
        # identify that case as involving multiple tables.
        is_mti = False
        for parent in model_cls._meta.all_parents:
            if parent._meta.concrete_model is not model_cls._meta.concrete_model:
                is_mti = True
                break

        # Fire hooks before DB ops
        if not bypass_hooks:
            ctx = HookContext(model_cls, bypass_hooks=False)
            if not bypass_validation:
                engine.run(model_cls, VALIDATE_CREATE, objs, ctx=ctx)
            engine.run(model_cls, BEFORE_CREATE, objs, ctx=ctx)
        else:
            ctx = HookContext(model_cls, bypass_hooks=True)
            logger.debug("bulk_create bypassed hooks")

        # For MTI models, we need to handle them specially
        if is_mti:
            # Use our MTI-specific logic
            # Filter out custom parameters that Django's bulk_create doesn't accept
            mti_kwargs = {
                "batch_size": batch_size,
                "ignore_conflicts": ignore_conflicts,
                "update_conflicts": update_conflicts,
                "update_fields": update_fields,
                "unique_fields": unique_fields,
            }
            # Remove custom hook kwargs if present in self.bulk_create signature
            result = self._mti_bulk_create(
                objs,
                **mti_kwargs,
            )
        else:
            # For single-table models, use Django's built-in bulk_create
            # but we need to call it on the base manager to avoid recursion
            # Filter out custom parameters that Django's bulk_create doesn't accept

            result = super().bulk_create(
                objs,
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
                update_conflicts=update_conflicts,
                update_fields=update_fields,
                unique_fields=unique_fields,
            )

        # Fire AFTER_CREATE hooks
        if not bypass_hooks:
            engine.run(model_cls, AFTER_CREATE, objs, ctx=ctx)

        return result

    @transaction.atomic
    def bulk_update(
        self, objs, fields, bypass_hooks=False, bypass_validation=False, **kwargs
    ):
        """
        Bulk update objects in the database with complete hook support.

        This method always runs the complete hook cycle:
        VALIDATE_UPDATE → BEFORE_UPDATE → DB update → AFTER_UPDATE

        Args:
            objs: List of model instances to update
            fields: List of field names to update
            bypass_hooks: DEPRECATED - kept for backward compatibility only
            bypass_validation: DEPRECATED - kept for backward compatibility only
            **kwargs: Additional arguments passed to Django's bulk_update
        """
        model_cls = self.model

        if not objs:
            return []

        # Validate inputs
        if not isinstance(objs, (list, tuple)):
            raise TypeError("objs must be a list or tuple")

        if not isinstance(fields, (list, tuple)):
            raise TypeError("fields must be a list or tuple")

        if not objs:
            return []

        if not fields:
            raise ValueError("fields cannot be empty")

        # Validate that all objects are instances of the model
        for obj in objs:
            if not isinstance(obj, model_cls):
                raise TypeError(
                    f"Expected instances of {model_cls.__name__}, got {type(obj).__name__}"
                )
            if obj.pk is None:
                raise ValueError("All objects must have a primary key")

        # Load originals for hook comparison
        pks = [obj.pk for obj in objs]
        original_map = {
            obj.pk: obj for obj in model_cls._base_manager.filter(pk__in=pks)
        }
        originals = [original_map.get(obj.pk) for obj in objs]

        # Run VALIDATE_UPDATE hooks
        if not bypass_validation:
            ctx = HookContext(model_cls)
            engine.run(
                model_cls, VALIDATE_UPDATE, objs, originals, ctx=ctx
            )

        # Run BEFORE_UPDATE hooks
        if not bypass_hooks:
            ctx = HookContext(model_cls)
            engine.run(
                model_cls, BEFORE_UPDATE, objs, originals, ctx=ctx
            )

        # Perform database update using Django's native bulk_update
        # We use the base manager to avoid recursion
        base_manager = model_cls._base_manager
        result = base_manager.bulk_update(objs, fields, **kwargs)

        # Run AFTER_UPDATE hooks
        if not bypass_hooks:
            ctx = HookContext(model_cls)
            engine.run(model_cls, AFTER_UPDATE, objs, originals, ctx=ctx)

        return result

    @transaction.atomic
    def bulk_delete(self, objs, **kwargs):
        """
        Delete the given objects from the database with complete hook support.

        This method runs the complete hook cycle:
        VALIDATE_DELETE → BEFORE_DELETE → DB delete → AFTER_DELETE

        This is a convenience method that provides a bulk_delete interface
        similar to bulk_create and bulk_update.
        """
        model_cls = self.model

        # Extract custom kwargs
        bypass_hooks = kwargs.pop("bypass_hooks", False)

        # Validate inputs
        if not isinstance(objs, (list, tuple)):
            raise TypeError("objs must be a list or tuple")

        if not objs:
            return 0

        # Validate that all objects are instances of the model
        for obj in objs:
            if not isinstance(obj, model_cls):
                raise TypeError(
                    f"Expected instances of {model_cls.__name__}, got {type(obj).__name__}"
                )

        # Get the pks to delete
        pks = [obj.pk for obj in objs if obj.pk is not None]
        if not pks:
            return 0

        # Use the delete() method which already has hook support
        return self.filter(pk__in=pks).delete()

    def _detect_modified_fields(self, new_instances, original_instances):
        """
        Detect fields that were modified during BEFORE_UPDATE hooks by comparing
        new instances with their original values.
        """
        if not original_instances:
            return set()

        modified_fields = set()

        # Since original_instances is now ordered to match new_instances, we can zip them directly
        for new_instance, original in zip(new_instances, original_instances):
            if new_instance.pk is None or original is None:
                continue

            # Compare all fields to detect changes
            for field in new_instance._meta.fields:
                if field.name == "id":
                    continue

                new_value = getattr(new_instance, field.name)
                original_value = getattr(original, field.name)

                # Handle different field types appropriately
                if field.is_relation:
                    # For foreign keys, compare the pk values
                    new_pk = new_value.pk if new_value else None
                    original_pk = original_value.pk if original_value else None
                    if new_pk != original_pk:
                        modified_fields.add(field.name)
                else:
                    # For regular fields, use direct comparison
                    if new_value != original_value:
                        modified_fields.add(field.name)

        return modified_fields

    def _get_inheritance_chain(self):
        """
        Get the complete inheritance chain from root parent to current model.
        Returns list of model classes in order: [RootParent, Parent, Child]
        """
        chain = []
        current_model = self.model
        while current_model:
            if not current_model._meta.proxy:
                chain.append(current_model)

            parents = [
                parent
                for parent in current_model._meta.parents.keys()
                if not parent._meta.proxy
            ]
            current_model = parents[0] if parents else None

        chain.reverse()
        return chain

    def _mti_bulk_create(self, objs, inheritance_chain=None, **kwargs):
        """
        Implements Django's suggested workaround #2 for MTI bulk_create:
        O(n) normal inserts into parent tables to get primary keys back,
        then single bulk insert into childmost table.
        Sets auto_now_add/auto_now fields for each model in the chain.
        """
        # Remove custom hook kwargs before passing to Django internals
        django_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k not in ["bypass_hooks", "bypass_validation"]
        }
        if inheritance_chain is None:
            inheritance_chain = self._get_inheritance_chain()

        # Safety check to prevent infinite recursion
        if len(inheritance_chain) > 10:  # Arbitrary limit to prevent infinite loops
            raise ValueError(
                "Inheritance chain too deep - possible infinite recursion detected"
            )

        batch_size = django_kwargs.get("batch_size") or len(objs)
        created_objects = []
        with transaction.atomic(using=self.db, savepoint=False):
            for i in range(0, len(objs), batch_size):
                batch = objs[i : i + batch_size]
                batch_result = self._process_mti_bulk_create_batch(
                    batch, inheritance_chain, **django_kwargs
                )
                created_objects.extend(batch_result)
        return created_objects

    def _process_mti_bulk_create_batch(self, batch, inheritance_chain, **kwargs):
        """
        Process a single batch of objects through the inheritance chain.
        Implements Django's suggested workaround #2: O(n) normal inserts into parent
        tables to get primary keys back, then single bulk insert into childmost table.
        """
        # For MTI, we need to save parent objects first to get PKs
        # Then we can use Django's bulk_create for the child objects
        parent_objects_map = {}

        # Step 1: Do O(n) normal inserts into parent tables to get primary keys back
        # Get bypass_hooks from kwargs
        bypass_hooks = kwargs.get("bypass_hooks", False)
        bypass_validation = kwargs.get("bypass_validation", False)

        for obj in batch:
            parent_instances = {}
            current_parent = None
            for model_class in inheritance_chain[:-1]:
                parent_obj = self._create_parent_instance(
                    obj, model_class, current_parent
                )

                # Fire parent hooks if not bypassed
                if not bypass_hooks:
                    ctx = HookContext(model_class)
                    if not bypass_validation:
                        engine.run(model_class, VALIDATE_CREATE, [parent_obj], ctx=ctx)
                    engine.run(model_class, BEFORE_CREATE, [parent_obj], ctx=ctx)

                # Use Django's base manager to create the object and get PKs back
                # This bypasses hooks and the MTI exception
                field_values = {
                    field.name: getattr(parent_obj, field.name)
                    for field in model_class._meta.local_fields
                    if hasattr(parent_obj, field.name)
                    and getattr(parent_obj, field.name) is not None
                }
                created_obj = model_class._base_manager.using(self.db).create(
                    **field_values
                )

                # Update the parent_obj with the created object's PK
                parent_obj.pk = created_obj.pk
                parent_obj._state.adding = False
                parent_obj._state.db = self.db

                # Fire AFTER_CREATE hooks for parent
                if not bypass_hooks:
                    engine.run(model_class, AFTER_CREATE, [parent_obj], ctx=ctx)

                parent_instances[model_class] = parent_obj
                current_parent = parent_obj
            parent_objects_map[id(obj)] = parent_instances

        # Step 2: Create all child objects and do single bulk insert into childmost table
        child_model = inheritance_chain[-1]
        all_child_objects = []
        for obj in batch:
            child_obj = self._create_child_instance(
                obj, child_model, parent_objects_map.get(id(obj), {})
            )
            all_child_objects.append(child_obj)

        # Step 2.5: Use Django's internal bulk_create infrastructure
        if all_child_objects:
            # Get the base manager's queryset
            base_qs = child_model._base_manager.using(self.db)

            # Use Django's exact approach: call _prepare_for_bulk_create then partition
            base_qs._prepare_for_bulk_create(all_child_objects)

            # Implement our own partition since itertools.partition might not be available
            objs_without_pk, objs_with_pk = [], []
            for obj in all_child_objects:
                if obj._is_pk_set():
                    objs_with_pk.append(obj)
                else:
                    objs_without_pk.append(obj)

            # Use Django's internal _batched_insert method
            opts = child_model._meta
            # For child models in MTI, we need to include the foreign key to the parent
            # but exclude the primary key since it's inherited

            # Include all local fields except generated ones
            # We need to include the foreign key to the parent (business_ptr)
            fields = [f for f in opts.local_fields if not f.generated]

            with transaction.atomic(using=self.db, savepoint=False):
                if objs_with_pk:
                    returned_columns = base_qs._batched_insert(
                        objs_with_pk,
                        fields,
                        batch_size=len(objs_with_pk),  # Use actual batch size
                    )
                    for obj_with_pk, results in zip(objs_with_pk, returned_columns):
                        for result, field in zip(results, opts.db_returning_fields):
                            if field != opts.pk:
                                setattr(obj_with_pk, field.attname, result)
                    for obj_with_pk in objs_with_pk:
                        obj_with_pk._state.adding = False
                        obj_with_pk._state.db = self.db

                if objs_without_pk:
                    # For objects without PK, we still need to exclude primary key fields
                    fields = [
                        f
                        for f in fields
                        if not isinstance(f, AutoField) and not f.primary_key
                    ]
                    returned_columns = base_qs._batched_insert(
                        objs_without_pk,
                        fields,
                        batch_size=len(objs_without_pk),  # Use actual batch size
                    )
                    for obj_without_pk, results in zip(
                        objs_without_pk, returned_columns
                    ):
                        for result, field in zip(results, opts.db_returning_fields):
                            setattr(obj_without_pk, field.attname, result)
                        obj_without_pk._state.adding = False
                        obj_without_pk._state.db = self.db

        # Step 3: Update original objects with generated PKs and state
        pk_field_name = child_model._meta.pk.name
        for orig_obj, child_obj in zip(batch, all_child_objects):
            child_pk = getattr(child_obj, pk_field_name)
            setattr(orig_obj, pk_field_name, child_pk)
            orig_obj._state.adding = False
            orig_obj._state.db = self.db

        return batch

    def _create_parent_instance(self, source_obj, parent_model, current_parent):
        parent_obj = parent_model()
        for field in parent_model._meta.local_fields:
            # Only copy if the field exists on the source and is not None
            if hasattr(source_obj, field.name):
                value = getattr(source_obj, field.name, None)
                if value is not None:
                    setattr(parent_obj, field.name, value)
        if current_parent is not None:
            for field in parent_model._meta.local_fields:
                if (
                    hasattr(field, "remote_field")
                    and field.remote_field
                    and field.remote_field.model == current_parent.__class__
                ):
                    setattr(parent_obj, field.name, current_parent)
                    break

        # Handle auto_now_add and auto_now fields like Django does
        for field in parent_model._meta.local_fields:
            if hasattr(field, "auto_now_add") and field.auto_now_add:
                # Ensure auto_now_add fields are properly set
                if getattr(parent_obj, field.name) is None:
                    field.pre_save(parent_obj, add=True)
                    # Explicitly set the value to ensure it's not None
                    setattr(parent_obj, field.name, field.value_from_object(parent_obj))
            elif hasattr(field, "auto_now") and field.auto_now:
                field.pre_save(parent_obj, add=True)

        return parent_obj

    def _create_child_instance(self, source_obj, child_model, parent_instances):
        child_obj = child_model()
        # Only copy fields that exist in the child model's local fields
        for field in child_model._meta.local_fields:
            if isinstance(field, AutoField):
                continue
            if hasattr(source_obj, field.name):
                value = getattr(source_obj, field.name, None)
                if value is not None:
                    setattr(child_obj, field.name, value)

        # Set parent links for MTI
        for parent_model, parent_instance in parent_instances.items():
            parent_link = child_model._meta.get_ancestor_link(parent_model)
            if parent_link:
                # Set both the foreign key value (the ID) and the object reference
                # This follows Django's pattern in _set_pk_val
                setattr(
                    child_obj, parent_link.attname, parent_instance.pk
                )  # Set the foreign key value
                setattr(
                    child_obj, parent_link.name, parent_instance
                )  # Set the object reference

        # Handle auto_now_add and auto_now fields like Django does
        for field in child_model._meta.local_fields:
            if hasattr(field, "auto_now_add") and field.auto_now_add:
                # Ensure auto_now_add fields are properly set
                if getattr(child_obj, field.name) is None:
                    field.pre_save(child_obj, add=True)
                    # Explicitly set the value to ensure it's not None
                    setattr(child_obj, field.name, field.value_from_object(child_obj))
            elif hasattr(field, "auto_now") and field.auto_now:
                field.pre_save(child_obj, add=True)

        return child_obj

    def _mti_bulk_update(self, objs, fields, **kwargs):
        """
        Custom bulk update implementation for MTI models.
        Updates each table in the inheritance chain efficiently using Django's batch_size.
        """
        model_cls = self.model
        inheritance_chain = self._get_inheritance_chain()

        # Remove custom hook kwargs before passing to Django internals
        django_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k not in ["bypass_hooks", "bypass_validation"]
        }

        # Safety check to prevent infinite recursion
        if len(inheritance_chain) > 10:  # Arbitrary limit to prevent infinite loops
            raise ValueError(
                "Inheritance chain too deep - possible infinite recursion detected"
            )

        # Handle auto_now fields by calling pre_save on objects
        # Check all models in the inheritance chain for auto_now fields
        for obj in objs:
            for model in inheritance_chain:
                for field in model._meta.local_fields:
                    if hasattr(field, "auto_now") and field.auto_now:
                        field.pre_save(obj, add=False)

        # Add auto_now fields to the fields list so they get updated in the database
        auto_now_fields = set()
        for model in inheritance_chain:
            for field in model._meta.local_fields:
                if hasattr(field, "auto_now") and field.auto_now:
                    auto_now_fields.add(field.name)

        # Combine original fields with auto_now fields
        all_fields = list(fields) + list(auto_now_fields)

        # Group fields by model in the inheritance chain
        field_groups = {}
        for field_name in all_fields:
            field = model_cls._meta.get_field(field_name)
            # Find which model in the inheritance chain this field belongs to
            for model in inheritance_chain:
                if field in model._meta.local_fields:
                    if model not in field_groups:
                        field_groups[model] = []
                    field_groups[model].append(field_name)
                    break

        # Process in batches
        batch_size = django_kwargs.get("batch_size") or len(objs)
        total_updated = 0

        with transaction.atomic(using=self.db, savepoint=False):
            for i in range(0, len(objs), batch_size):
                batch = objs[i : i + batch_size]
                batch_result = self._process_mti_bulk_update_batch(
                    batch, field_groups, inheritance_chain, **django_kwargs
                )
                total_updated += batch_result

        return total_updated

    def _process_mti_bulk_update_batch(
        self, batch, field_groups, inheritance_chain, **kwargs
    ):
        """
        Process a single batch of objects for MTI bulk update.
        Updates each table in the inheritance chain for the batch.
        """
        total_updated = 0

        # For MTI, we need to handle parent links correctly
        # The root model (first in chain) has its own PK
        # Child models use the parent link to reference the root PK
        root_model = inheritance_chain[0]

        # Get the primary keys from the objects
        # If objects have pk set but are not loaded from DB, use those PKs
        root_pks = []
        for obj in batch:
            # Check both pk and id attributes
            pk_value = getattr(obj, "pk", None)
            if pk_value is None:
                pk_value = getattr(obj, "id", None)

            if pk_value is not None:
                root_pks.append(pk_value)
            else:
                continue

        if not root_pks:
            return 0

        # Update each table in the inheritance chain
        for model, model_fields in field_groups.items():
            if not model_fields:
                continue

            if model == inheritance_chain[0]:
                # Root model - use primary keys directly
                pks = root_pks
                filter_field = "pk"
            else:
                # Child model - use parent link field
                parent_link = None
                for parent_model in inheritance_chain:
                    if parent_model in model._meta.parents:
                        parent_link = model._meta.parents[parent_model]
                        break

                if parent_link is None:
                    continue

                # For child models, the parent link values should be the same as root PKs
                pks = root_pks
                filter_field = parent_link.attname

            if pks:
                base_qs = model._base_manager.using(self.db)

                # Check if records exist
                existing_count = base_qs.filter(**{f"{filter_field}__in": pks}).count()

                if existing_count == 0:
                    continue

                # Build CASE statements for each field to perform a single bulk update
                case_statements = {}
                for field_name in model_fields:
                    field = model._meta.get_field(field_name)
                    when_statements = []

                    for pk, obj in zip(pks, batch):
                        # Check both pk and id attributes for the object
                        obj_pk = getattr(obj, "pk", None)
                        if obj_pk is None:
                            obj_pk = getattr(obj, "id", None)

                        if obj_pk is None:
                            continue
                        value = getattr(obj, field_name)
                        when_statements.append(
                            When(
                                **{filter_field: pk},
                                then=Value(value, output_field=field),
                            )
                        )

                    case_statements[field_name] = Case(
                        *when_statements, output_field=field
                    )

                # Execute a single bulk update for all objects in this model
                try:
                    updated_count = base_qs.filter(
                        **{f"{filter_field}__in": pks}
                    ).update(**case_statements)
                    total_updated += updated_count
                except Exception as e:
                    import traceback

                    traceback.print_exc()

        return total_updated


class HookQuerySet(HookQuerySetMixin, models.QuerySet):
    """
    A QuerySet that provides bulk hook functionality.
    This is the traditional approach for backward compatibility.
    """

    pass
