"""Collabora Online connector — STUB.

Registered so the rest of Office handling can name the provider, but every
method raises NotConfigured (inherited from EditorProvider): no button that
needs it is enabled. The WOPI host (discovery, CheckFileInfo, GetFile,
PutFile, Lock/Refresh/Unlock) replaces this class.
"""
from . import register
from .base import EditorProvider


class CollaboraProvider(EditorProvider):
    key = 'collabora'
    label = 'Collabora Online'


register(CollaboraProvider())
