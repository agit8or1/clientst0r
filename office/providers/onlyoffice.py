"""ONLYOFFICE Docs connector — STUB.

Registered so the rest of Office handling can name the provider, but every
method raises NotConfigured (inherited from EditorProvider): no button that
needs it is enabled. The ONLYOFFICE connector (Docs JS API page, JWT-signed
config, callback handler that saves through office.storage.save_or_quarantine)
replaces this class.
"""
from . import register
from .base import EditorProvider


class OnlyOfficeProvider(EditorProvider):
    key = 'onlyoffice'
    label = 'ONLYOFFICE Docs'


register(OnlyOfficeProvider())
