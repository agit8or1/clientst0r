"""
Hand-off from payment collection to the accounting pipeline.

This app never calls QuickBooks Online / Xero. When money moves it writes a
psa.Payment row (positive for a collected payment, negative for a refund or
a lost dispute / chargeback) and marks the record that caused it with
`accounting_post_status = 'pending'`:

  PaymentAttempt.local_payment   collected payment
  Refund.local_payment           refund (negative row)
  Dispute.local_payment          lost dispute / chargeback (negative row)

The accounting pipeline (integrations.services.accounting_sync and the
providers' record_payment) is expected to:

  1. read `pending_posts()`,
  2. post each psa.Payment to the invoice's accounting connection (the
     processing fee is `PaymentAttempt.fee_amount`, separate from the
     payment amount, for a fee / clearing-account entry),
  3. call `mark_posted(record)` or `mark_failed(record, error)`.

Wiring that consumer is owned by the accounting work stream; until it lands
the pending rows simply wait, and nothing is posted twice.
"""
from __future__ import annotations

from django.utils import timezone

from .models import Dispute, PaymentAttempt, Refund


def pending_posts():
    """[(kind, record, psa.Payment)] waiting for the accounting system."""
    out = []
    for a in PaymentAttempt.objects.filter(accounting_post_status='pending', local_payment__isnull=False) \
            .select_related('local_payment', 'invoice'):
        out.append(('payment', a, a.local_payment))
    for r in Refund.objects.filter(accounting_post_status='pending', local_payment__isnull=False) \
            .select_related('local_payment', 'attempt__invoice'):
        out.append(('refund', r, r.local_payment))
    for d in Dispute.objects.filter(accounting_post_status='pending', local_payment__isnull=False) \
            .select_related('local_payment', 'attempt__invoice'):
        out.append(('dispute', d, d.local_payment))
    return out


def mark_posted(record):
    type(record).objects.filter(pk=record.pk).update(accounting_post_status='posted',
                                                     accounting_posted_at=timezone.now())


def mark_failed(record, error=''):
    type(record).objects.filter(pk=record.pk).update(accounting_post_status='failed')
