from typing import Iterable, Sequence, Any
from django.db import models

from django_bulk_hooks.queryset import HookQuerySet, HookQuerySetMixin


class BulkHookManager(models.Manager):
	"""Manager that ensures all queryset operations are hook-aware.

	Delegates operations to a hook-enabled queryset while preserving any
	customizations from other managers in the MRO by starting with
	``super().get_queryset()``.
	"""

	# Cache for composed queryset classes to preserve custom queryset APIs
	_qs_compose_cache = {}

	def get_queryset(self) -> HookQuerySet:
		# Use super().get_queryset() to let Django and MRO build the queryset
		base_queryset = super().get_queryset()

		# If the base queryset already has hook functionality, return it as-is
		if isinstance(base_queryset, HookQuerySetMixin):
			return base_queryset  # type: ignore[return-value]

		# Otherwise, dynamically compose a queryset class that preserves the
		# base queryset's custom API while adding hook behavior
		base_cls = base_queryset.__class__
		composed_cls = self._qs_compose_cache.get(base_cls)
		if composed_cls is None:
			composed_name = f"ComposedHookQuerySet_{base_cls.__name__}"
			composed_cls = type(composed_name, (HookQuerySetMixin, base_cls), {})
			self._qs_compose_cache[base_cls] = composed_cls

		return composed_cls(
			model=base_queryset.model,
			query=base_queryset.query,
			using=base_queryset._db,
			hints=base_queryset._hints,
		)

	def bulk_create(
		self,
		objs: Iterable[models.Model],
		batch_size: int | None = None,
		ignore_conflicts: bool = False,
		update_conflicts: bool = False,
		update_fields: Sequence[str] | None = None,
		unique_fields: Sequence[str] | None = None,
		bypass_hooks: bool = False,
		bypass_validation: bool = False,
		**kwargs: Any,
	) -> list[models.Model]:
		"""
		Delegate to QuerySet's bulk_create implementation.
		This follows Django's pattern where Manager methods call QuerySet methods.
		"""
		return self.get_queryset().bulk_create(
			objs,
			bypass_hooks=bypass_hooks,
			bypass_validation=bypass_validation,
			batch_size=batch_size,
			ignore_conflicts=ignore_conflicts,
			update_conflicts=update_conflicts,
			update_fields=update_fields,
			unique_fields=unique_fields,
			**kwargs,
		)

	def bulk_update(
		self,
		objs: Iterable[models.Model],
		fields: Sequence[str],
		bypass_hooks: bool = False,
		bypass_validation: bool = False,
		**kwargs: Any,
	) -> int:
		"""
		Delegate to QuerySet's bulk_update implementation.
		This follows Django's pattern where Manager methods call QuerySet methods.
		"""
		return self.get_queryset().bulk_update(
			objs,
			fields,
			bypass_hooks=bypass_hooks,
			bypass_validation=bypass_validation,
			**kwargs,
		)

	def bulk_delete(
		self,
		objs: Iterable[models.Model],
		batch_size: int | None = None,
		bypass_hooks: bool = False,
		bypass_validation: bool = False,
		**kwargs: Any,
	) -> int:
		"""
		Delegate to QuerySet's bulk_delete implementation.
		This follows Django's pattern where Manager methods call QuerySet methods.
		"""
		return self.get_queryset().bulk_delete(
			objs,
			bypass_hooks=bypass_hooks,
			bypass_validation=bypass_validation,
			batch_size=batch_size,
			**kwargs,
		)

	def delete(self) -> int:
		"""
		Delegate to QuerySet's delete implementation.
		This follows Django's pattern where Manager methods call QuerySet methods.
		"""
		return self.get_queryset().delete()

	def update(self, **kwargs: Any) -> int:
		"""
		Delegate to QuerySet's update implementation.
		This follows Django's pattern where Manager methods call QuerySet methods.
		"""
		return self.get_queryset().update(**kwargs)

	def save(self, obj: models.Model) -> models.Model:
		"""
		Save a single object using the appropriate bulk operation.
		"""
		if obj.pk:
			self.bulk_update(
				[obj],
				fields=[field.name for field in obj._meta.fields if field.name != "id"],
			)
		else:
			self.bulk_create([obj])
		return obj
