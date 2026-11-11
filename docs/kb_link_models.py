"""
KB dead-link results (written by the `kb_link_check` scheduler task).

  KBExternalLink  one external URL and the result of its last HEAD check,
                  shared by every article that links to it, so a URL is
                  fetched at most once per recheck interval.
  KBDeadLink      one broken link in one article: an internal link to a
                  missing, archived or unpublished document (or, from a
                  customer-visible article, to an internal one), or an
                  external URL that failed its check.
"""
from __future__ import annotations

import hashlib

from django.db import models
from django.utils import timezone


def url_hash(url: str) -> str:
    return hashlib.sha256((url or '').encode('utf-8')).hexdigest()


class KBExternalLink(models.Model):
    url = models.TextField()
    url_hash = models.CharField(max_length=64, unique=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(null=True, help_text='None = not checked (e.g. not a public address).')
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'docs_kb_external_links'

    def __str__(self):
        return self.url[:120]


class KBDeadLink(models.Model):
    INTERNAL, EXTERNAL = 'internal', 'external'
    KINDS = [(INTERNAL, 'Internal'), (EXTERNAL, 'External')]

    document = models.ForeignKey('docs.Document', on_delete=models.CASCADE, related_name='dead_links')
    url = models.TextField()
    url_hash = models.CharField(max_length=64)
    kind = models.CharField(max_length=10, choices=KINDS)
    reason = models.CharField(max_length=255)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    target_document = models.ForeignKey('docs.Document', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+')
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'docs_kb_dead_links'
        ordering = ['kind', '-first_seen_at']
        constraints = [models.UniqueConstraint(fields=['document', 'url_hash'], name='docs_kb_dead_link_unique')]

    def __str__(self):
        return f'{self.document_id}: {self.url[:80]} ({self.reason})'
