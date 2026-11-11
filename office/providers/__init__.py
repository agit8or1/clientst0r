"""Editor provider registry.

    from office.providers import get_provider, register, all_providers
    provider = get_provider(instance.provider)   # raises NotConfigured if unknown

The stubs in onlyoffice.py and collabora.py register themselves here and raise
NotConfigured from every method until their connector is implemented.
"""
from .base import (  # noqa: F401
    FAIL, NOT_RUN, PASS, WARN, Capabilities, DiagnosticCheck, EditorPage, EditorProvider,
    HealthResult, NotConfigured, NotSupported, RoundTripReport,
)

_REGISTRY = {}


def register(provider, *, replace=False):
    if not provider.key:
        raise ValueError('provider.key is required')
    if provider.key in _REGISTRY and not replace:
        raise ValueError(f'provider {provider.key!r} is already registered')
    _REGISTRY[provider.key] = provider
    return provider


def get_provider(key) -> EditorProvider:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise NotConfigured(f'No connector is installed for editor type {key!r}.')


def all_providers():
    return dict(_REGISTRY)


from . import collabora, onlyoffice  # noqa: E402,F401  (register the stubs)
