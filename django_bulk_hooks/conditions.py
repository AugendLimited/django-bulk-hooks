import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def resolve_dotted_attr(instance: Any, dotted_path: str) -> Any:
    """
    Recursively resolve a dotted attribute path, e.g., "type.category".

    Returns None if any intermediate value is None or missing.
    """
    for attr in dotted_path.split("."):
        if instance is None:
            return None
        instance = getattr(instance, attr, None)
    return instance


class HookCondition:
    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        raise NotImplementedError

    def __call__(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        return self.check(instance, original_instance)

    def __and__(self, other: "HookCondition") -> "HookCondition":
        return AndCondition(self, other)

    def __or__(self, other: "HookCondition") -> "HookCondition":
        return OrCondition(self, other)

    def __invert__(self) -> "HookCondition":
        return NotCondition(self)


class IsNotEqual(HookCondition):
    def __init__(self, field: str, value: Any, only_on_change: bool = False):
        self.field = field
        self.value = value
        self.only_on_change = only_on_change

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        current = resolve_dotted_attr(instance, self.field)
        if self.only_on_change:
            if original_instance is None:
                return False
            previous = resolve_dotted_attr(original_instance, self.field)
            return previous == self.value and current != self.value
        else:
            return current != self.value


class IsEqual(HookCondition):
    def __init__(self, field: str, value: Any, only_on_change: bool = False):
        self.field = field
        self.value = value
        self.only_on_change = only_on_change

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        current = resolve_dotted_attr(instance, self.field)
        if self.only_on_change:
            if original_instance is None:
                return False
            previous = resolve_dotted_attr(original_instance, self.field)
            return previous != self.value and current == self.value
        else:
            return current == self.value


class HasChanged(HookCondition):
    def __init__(self, field: str, has_changed: bool = True):
        self.field = field
        self.has_changed = has_changed

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        if not original_instance:
            return False
        
        current = resolve_dotted_attr(instance, self.field)
        previous = resolve_dotted_attr(original_instance, self.field)
        
        result = (current != previous) == self.has_changed
        # Only log when there's an actual change to reduce noise
        if result:
            logger.debug(f"HasChanged {self.field} detected change on instance {getattr(instance, 'pk', 'No PK')}")
        return result


class WasEqual(HookCondition):
    def __init__(self, field: str, value: Any, only_on_change: bool = False):
        """
        Check if a field's original value was `value`.
        If only_on_change is True, only return True when the field has changed away from that value.
        """
        self.field = field
        self.value = value
        self.only_on_change = only_on_change

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        if original_instance is None:
            return False
        previous = resolve_dotted_attr(original_instance, self.field)
        if self.only_on_change:
            current = resolve_dotted_attr(instance, self.field)
            return previous == self.value and current != self.value
        else:
            return previous == self.value


class ChangesTo(HookCondition):
    def __init__(self, field: str, value: Any):
        """
        Check if a field's value has changed to `value`.
        Only returns True when original value != value and current value == value.
        """
        self.field = field
        self.value = value

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        if original_instance is None:
            return False
        previous = resolve_dotted_attr(original_instance, self.field)
        current = resolve_dotted_attr(instance, self.field)
        return previous != self.value and current == self.value


class IsGreaterThan(HookCondition):
    def __init__(self, field: str, value: Any):
        self.field = field
        self.value = value

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        current = resolve_dotted_attr(instance, self.field)
        return current is not None and current > self.value


class IsGreaterThanOrEqual(HookCondition):
    def __init__(self, field: str, value: Any):
        self.field = field
        self.value = value

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        current = resolve_dotted_attr(instance, self.field)
        return current is not None and current >= self.value


class IsLessThan(HookCondition):
    def __init__(self, field: str, value: Any):
        self.field = field
        self.value = value

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        current = resolve_dotted_attr(instance, self.field)
        return current is not None and current < self.value


class IsLessThanOrEqual(HookCondition):
    def __init__(self, field: str, value: Any):
        self.field = field
        self.value = value

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        current = resolve_dotted_attr(instance, self.field)
        return current is not None and current <= self.value


class AndCondition(HookCondition):
    def __init__(self, cond1: HookCondition, cond2: HookCondition):
        self.cond1 = cond1
        self.cond2 = cond2

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        return self.cond1.check(instance, original_instance) and self.cond2.check(
            instance, original_instance
        )


class OrCondition(HookCondition):
    def __init__(self, cond1: HookCondition, cond2: HookCondition):
        self.cond1 = cond1
        self.cond2 = cond2

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        return self.cond1.check(instance, original_instance) or self.cond2.check(
            instance, original_instance
        )


class NotCondition(HookCondition):
    def __init__(self, cond: HookCondition):
        self.cond = cond

    def check(self, instance: Any, original_instance: Optional[Any] = None) -> bool:
        return not self.cond.check(instance, original_instance)
