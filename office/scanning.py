"""Pluggable content scanning for Office saves and uploads.

**No malware scanner exists in clientst0r today.** This module is only the
hook: every file ``office.storage`` is about to accept is passed to the
function named by ``settings.OFFICE_SCAN_HOOK`` (dotted path). The default,
``office.scanning.no_scan``, accepts everything and reports that nothing
scanned it, and the diagnostics page says so.

To add a scanner (ClamAV over its socket, an ICAP service, ...), write

    def my_scan(path, *, name, target, user) -> ScanResult: ...

and set ``OFFICE_SCAN_HOOK = 'mypackage.scan.my_scan'``. Return
``ScanResult(clean=False, scanner='clamav', detail='Eicar-Test-Signature')`` to
refuse the file; the save is then quarantined with reason ``validation``. A
hook that raises is treated as a refusal (fail closed) and logged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string

from .logging_filters import get_logger

logger = get_logger('office')


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    scanner: str | None = None   # None: nothing actually scanned the file
    detail: str = ''


def no_scan(path, *, name, target, user) -> ScanResult:
    return ScanResult(clean=True, scanner=None, detail='No malware scanner is configured.')


def scanner_configured() -> bool:
    return bool(getattr(settings, 'OFFICE_SCAN_HOOK', ''))


def scan_file(path, *, name, target=None, user=None) -> ScanResult:
    hook_path = getattr(settings, 'OFFICE_SCAN_HOOK', '') or 'office.scanning.no_scan'
    try:
        hook = import_string(hook_path)
        result = hook(path, name=name, target=target, user=user)
    except Exception:
        logger.exception('Office scan hook %s failed; refusing the file', hook_path)
        return ScanResult(clean=False, scanner=hook_path, detail='The content scanner failed.')
    if not isinstance(result, ScanResult):
        return ScanResult(clean=False, scanner=hook_path, detail='The content scanner returned no verdict.')
    return result
