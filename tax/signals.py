"""An invoice voided in ClientSt0r voids its committed provider transaction
(Avalara void / TaxJar order delete) so the provider stops reporting it.
A failure is kept on the calculation (void_error) and shown on the invoice."""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger('tax')


@receiver(post_save, sender='psa.Invoice', dispatch_uid='tax_void_on_invoice_void')
def void_provider_transaction(sender, instance, **kwargs):
    if instance.status != 'void':
        return
    from .models import TaxCalculation
    if not TaxCalculation.objects.filter(document_type='invoice', document_id=instance.pk, committed=True,
                                         voided_at__isnull=True).exclude(provider_transaction_code='').exists():
        return

    def _void():
        from .services import void_committed_tax
        try:
            void_committed_tax(instance)
        except Exception:
            logger.exception('voiding the tax transaction of invoice %s failed', instance.pk)
    transaction.on_commit(_void)
