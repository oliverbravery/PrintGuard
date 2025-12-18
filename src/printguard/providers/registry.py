"""Provider registration and discovery."""

from typing import Type

from .base import PrinterProvider

_providers: dict[str, Type[PrinterProvider]] = {}


def register(name: str):
    """Decorator to register a provider class."""
    def decorator(cls: Type[PrinterProvider]):
        _providers[name] = cls
        return cls
    return decorator


def get_provider(name: str) -> Type[PrinterProvider] | None:
    """Get provider class by name."""
    return _providers.get(name)


def list_providers() -> list[str]:
    """List registered provider names."""
    return list(_providers.keys())
