"""Provider registry and catalog.

Concrete providers register with ``@register``. Each entry also carries static
catalog metadata (display name, required fields) so the dashboard can show an
"Add provider" form without the backend hardcoding provider knowledge in the UI.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any

from app.core.enums import Capability
from app.providers.base import BaseProvider, ProviderSpec

# (capability, provider_key) -> provider class
_REGISTRY: dict[tuple[Capability, str], type[BaseProvider]] = {}
# catalog metadata keyed the same way
_CATALOG: dict[tuple[Capability, str], "ProviderInfo"] = {}

_DISCOVERED = False


@dataclass
class ProviderInfo:
    capability: Capability
    provider_key: str
    display_name: str
    requires_api_key: bool = True
    default_endpoint: str = ""
    default_model: str = ""
    notes: str = ""
    param_schema: dict[str, Any] = field(default_factory=dict)


def register(
    *,
    display_name: str,
    requires_api_key: bool = True,
    default_endpoint: str = "",
    default_model: str = "",
    notes: str = "",
    param_schema: dict[str, Any] | None = None,
):
    """Class decorator to register a provider implementation."""

    def _wrap(cls: type[BaseProvider]) -> type[BaseProvider]:
        key = (cls.capability, cls.provider_key)
        _REGISTRY[key] = cls
        _CATALOG[key] = ProviderInfo(
            capability=cls.capability,
            provider_key=cls.provider_key,
            display_name=display_name,
            requires_api_key=requires_api_key,
            default_endpoint=default_endpoint,
            default_model=default_model,
            notes=notes,
            param_schema=param_schema or {},
        )
        return cls

    return _wrap


def discover() -> None:
    """Import all provider implementation modules so their ``@register`` runs."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    import app.providers.impl as impl_pkg

    for mod in pkgutil.walk_packages(impl_pkg.__path__, impl_pkg.__name__ + "."):
        importlib.import_module(mod.name)
    _DISCOVERED = True


def get_provider_class(
    capability: Capability, provider_key: str
) -> type[BaseProvider] | None:
    discover()
    return _REGISTRY.get((capability, provider_key))


def build_provider(spec: ProviderSpec) -> BaseProvider:
    """Instantiate a provider for a given spec, raising if unknown."""
    cls = get_provider_class(spec.capability, spec.provider)
    if cls is None:
        raise ValueError(
            f"No provider registered for capability={spec.capability.value} "
            f"provider={spec.provider!r}"
        )
    return cls(spec)


def catalog(capability: Capability | None = None) -> list[ProviderInfo]:
    discover()
    items = list(_CATALOG.values())
    if capability is not None:
        items = [i for i in items if i.capability == capability]
    return sorted(items, key=lambda i: (i.capability.value, i.display_name))
