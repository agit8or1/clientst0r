"""Issue a new agreement revision as soon as an agreement document's live
content changes (an edit saved while published, or an approval that puts a
reviewed edit live). Signers of earlier revisions keep their evidence; the
new revision needs a new signature."""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger('docs.agreements')


@receiver(post_save, sender='docs.Document', dispatch_uid='docs_agreement_revision_on_save')
def _issue_agreement_revision(sender, instance, raw=False, **kwargs):
    if raw:
        return
    from .agreement_models import Agreement
    agreement = Agreement.objects.filter(document=instance, is_active=True).first()
    if agreement is None:
        return
    try:
        from .agreements import ensure_revision
        agreement.document = instance
        ensure_revision(agreement, instance.last_modified_by)
    except Exception:  # a save must not fail because issuing did; the reminder task issues it
        logger.exception('could not issue agreement revision for document %s', instance.pk)
