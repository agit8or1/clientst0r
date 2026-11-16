"""The few calls the psa quote / invoice code makes into the tax app.

    default_tax_rate(org)               new document's flat rate field
    on_document_saved(document, request) after a draft's lines are saved
    gate_send(document, request) -> bool before a document is sent / marked sent
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import messages

from . import services
from .models import TaxSettings


def default_tax_rate(org) -> Decimal:
    """Flat mode (and no tax settings at all) keeps the General settings
    default rate. Every other mode computes tax itself, so the per-document
    rate field starts at 0 and is informational."""
    if services.effective_mode(org) != TaxSettings.MODE_FLAT:
        return Decimal('0')
    from core.models import SystemSetting
    rate = getattr(SystemSetting.get_settings(), 'psa_default_tax_rate', None)
    return rate if rate is not None else Decimal('0')


def on_document_saved(document, request=None):
    """Recalculate a draft's tax after an edit (manual rates locally; the
    provider as a preview that is not recorded with it). A provider failure
    does not stop the save: it is shown, and sending stays blocked until tax
    is calculated."""
    mode = services.effective_mode(document.organization_id)
    if not services._document_applies(document):
        return None
    cur = services.current_calculation(document)
    if (cur is not None and cur.provider == 'override'
            and cur.lines_fingerprint == services.lines_fingerprint(document)):
        return None  # an explicit override for these lines stands until the lines change
    user = getattr(request, 'user', None)
    outcome = services.calculate_tax(document, user=user, purpose='preview')
    if request is not None:
        if outcome.blocked:
            messages.warning(request, f'Saved, but tax could not be calculated: {outcome.message} '
                                      'It cannot be sent until this is resolved.')
        elif outcome.status == 'not_configured' and mode != TaxSettings.MODE_FLAT:
            messages.info(request, outcome.message)
    return outcome


def gate_send(document, request=None) -> bool:
    """True when the document may be sent. False (with an error message on
    the request) when tax could not be determined."""
    outcome = services.finalize_document(document, user=getattr(request, 'user', None))
    if outcome.blocked:
        if request is not None:
            messages.error(request, outcome.message)
        return False
    return True
