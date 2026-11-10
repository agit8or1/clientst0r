"""
Version-specific agreements: MSAs, SOWs and policy acknowledgments.

  Agreement           a customer document that must be signed or
                      acknowledged. One per document.
  AgreementRevision   an exact issued revision of that document: version
                      number, the title/body as issued, the rendered body,
                      a standalone HTML snapshot and a PDF, and SHA-256
                      hashes of each. Issued automatically whenever the live
                      (published, approved, not archived) content changes.
  AgreementSignature  one signature or acknowledgment of one revision:
                      signer identity, time, IP address, user agent, the
                      revision's hashes and a hash of the whole evidence
                      record. Never updated or deleted.

A signature binds to the revision, not the document: editing the document
issues a new revision, which needs a new signature, while every earlier
revision keeps its snapshot, PDF and signatures unchanged.

Rows outlive the document and the customer (SET_NULL with copied names), so
evidence is never lost to a deletion.
"""
from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.db import models
from django.utils import timezone


def canonical_json(data) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data or b'').hexdigest()


class Agreement(models.Model):
    KINDS = [('msa', 'Master services agreement (MSA)'), ('sow', 'Statement of work (SOW)'),
             ('policy', 'Policy acknowledgment'), ('other', 'Other agreement')]
    SIGNATURE, ACKNOWLEDGMENT = 'signature', 'acknowledgment'
    MODES = [(SIGNATURE, 'Signature (drawn signature, name, e-mail)'),
             (ACKNOWLEDGMENT, 'Acknowledgment (“I have read and accept”)')]
    ONE, EACH = 'one', 'each'
    AUDIENCES = [(ONE, 'One person signs for the customer'), (EACH, 'Every portal user of the customer')]

    document = models.OneToOneField('docs.Document', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='agreement')
    organization = models.ForeignKey('core.Organization', on_delete=models.SET_NULL, null=True,
                                     related_name='agreements')
    organization_name = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=255, help_text='Copied from the document; kept if it is deleted.')
    kind = models.CharField(max_length=10, choices=KINDS, default='msa')
    mode = models.CharField(max_length=20, choices=MODES, default=SIGNATURE)
    audience = models.CharField(max_length=10, choices=AUDIENCES, default=ONE)
    is_active = models.BooleanField(default=True, help_text='Open for signing in the customer portal.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'docs_agreements'
        ordering = ['organization_name', 'title']

    def __str__(self):
        return f'{self.get_kind_display()}: {self.title}'

    @property
    def latest_revision(self):
        return self.revisions.order_by('-version_number').first()

    @property
    def verb(self):
        return 'sign' if self.mode == self.SIGNATURE else 'acknowledge'


class AgreementRevision(models.Model):
    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, related_name='revisions')
    version_number = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    content_type = models.CharField(max_length=20)
    content_hash = models.CharField(max_length=64, help_text='SHA-256 of content.json (title, editor type, body).')
    rendered_html = models.TextField(help_text='The sanitised body exactly as the signer saw it.')
    snapshot_html = models.TextField(help_text='Standalone HTML snapshot, as issued.')
    snapshot_hash = models.CharField(max_length=64)
    pdf = models.BinaryField(null=True, blank=True)
    pdf_hash = models.CharField(max_length=64, blank=True)
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='+')

    class Meta:
        db_table = 'docs_agreement_revisions'
        ordering = ['-version_number']
        constraints = [models.UniqueConstraint(fields=['agreement', 'version_number'],
                                               name='docs_agreement_revision_unique')]

    def __str__(self):
        return f'{self.agreement.title} v{self.version_number}'

    @staticmethod
    def content_of(title, content_type, body) -> dict:
        return {'title': title or '', 'content_type': content_type or '', 'body': body or ''}

    def content_json(self) -> bytes:
        return canonical_json(self.content_of(self.title, self.content_type, self.body))

    def verify(self) -> dict:
        """Recompute each hash from the stored bytes."""
        return {'content': sha256(self.content_json()) == self.content_hash,
                'snapshot': sha256(self.snapshot_html.encode('utf-8')) == self.snapshot_hash,
                'pdf': (not self.pdf_hash) or sha256(bytes(self.pdf or b'')) == self.pdf_hash}

    def save(self, *args, **kwargs):
        if self.pk and AgreementRevision.objects.filter(pk=self.pk).exists():
            raise ValueError('An issued agreement revision cannot be changed.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('An issued agreement revision cannot be deleted.')


class AgreementSignature(models.Model):
    revision = models.ForeignKey(AgreementRevision, on_delete=models.PROTECT, related_name='signatures')
    organization = models.ForeignKey('core.Organization', on_delete=models.SET_NULL, null=True,
                                     related_name='+')
    organization_name = models.CharField(max_length=255)
    organization_ref = models.PositiveIntegerField(help_text='Customer id at signing (kept if it is deleted).')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='agreement_signatures')
    user_ref = models.PositiveIntegerField(null=True, blank=True, help_text='Signer account id at signing.')
    username = models.CharField(max_length=150)
    agreement_kind = models.CharField(max_length=10, choices=Agreement.KINDS)
    method = models.CharField(max_length=20, choices=Agreement.MODES)
    signed_by_name = models.CharField(max_length=200)
    signed_by_email = models.EmailField()
    signed_by_title = models.CharField(max_length=200, blank=True)
    signature_data = models.TextField(blank=True, help_text='Drawn signature (data:image/png), signature mode only.')
    signed_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    content_hash = models.CharField(max_length=64)
    snapshot_hash = models.CharField(max_length=64)
    pdf_hash = models.CharField(max_length=64, blank=True)
    evidence_hash = models.CharField(max_length=64, help_text='SHA-256 of evidence.json.')

    class Meta:
        db_table = 'docs_agreement_signatures'
        ordering = ['-signed_at']
        indexes = [models.Index(fields=['organization', 'revision'])]

    def __str__(self):
        return f'{self.signed_by_name} {self.method} v{self.revision.version_number} at {self.signed_at:%Y-%m-%d %H:%M}'

    def evidence(self) -> dict:
        """The evidence record (without its own hash). evidence.json in the
        download is exactly canonical_json(evidence())."""
        r, a = self.revision, self.revision.agreement
        return {
            'schema': 'clientst0r.agreement-evidence.v1',
            'agreement': {'id': a.pk, 'kind': self.agreement_kind},
            'revision': {'id': r.pk, 'version': r.version_number, 'title': r.title,
                         'issued_at': r.issued_at.isoformat(), 'content_hash': self.content_hash,
                         'snapshot_hash': self.snapshot_hash, 'pdf_hash': self.pdf_hash},
            'customer': {'id': self.organization_ref, 'name': self.organization_name},
            'signer': {'user_id': self.user_ref, 'username': self.username, 'name': self.signed_by_name,
                       'email': self.signed_by_email, 'title': self.signed_by_title,
                       'signature_sha256': sha256(self.signature_data.encode('utf-8')) if self.signature_data else ''},
            'method': self.method,
            'signed_at': self.signed_at.isoformat(),
            'ip_address': self.ip_address or '',
            'user_agent': self.user_agent,
        }

    def evidence_json(self) -> bytes:
        return canonical_json(self.evidence())

    def verify(self) -> dict:
        r = self.revision
        checks = r.verify()
        checks['bound'] = (self.content_hash, self.snapshot_hash, self.pdf_hash) == (
            r.content_hash, r.snapshot_hash, r.pdf_hash)
        checks['evidence'] = sha256(self.evidence_json()) == self.evidence_hash
        return checks

    @property
    def verified(self) -> bool:
        return all(self.verify().values())

    def save(self, *args, **kwargs):
        if self.pk and AgreementSignature.objects.filter(pk=self.pk).exists():
            raise ValueError('A signature record cannot be changed.')
        if not self.evidence_hash:
            self.evidence_hash = sha256(self.evidence_json())
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('A signature record cannot be deleted.')
