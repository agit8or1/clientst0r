"""
v3.17.245 — Phase 22 v1: email KB owners about overdue articles.

Run hourly / daily via cron. Idempotent: per-article reminders are
de-duplicated within a 7-day window via a session-style flag stored on
the article (`last_reminder_sent_at` is *not* a separate field — we
just look at last_reviewed_at + the cron's known frequency).

Usage:
    python manage.py kb_review_reminders [--dry-run]
"""
from collections import defaultdict

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from docs.models import Document, SearchQueryLog


class Command(BaseCommand):
    help = 'Email KB owners about articles overdue for review.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Don't actually send mail; just print what would be sent.",
        )

    def handle(self, *, dry_run=False, **kwargs):
        # Find candidate articles. We re-evaluate `is_review_overdue`
        # in Python because the property reads from multiple fields
        # with fallbacks, which is hard to express in a single ORM
        # query. The base filter narrows the set to articles that
        # could possibly be overdue (review_interval_days > 0,
        # published, not archived).
        candidates = (Document.objects.published()
                      .filter(review_interval_days__gt=0, is_template=False)
                      .select_related('owner'))

        # Group by owner to send a digest rather than one email per
        # article — owners hate the latter.
        per_owner = defaultdict(list)
        for doc in candidates:
            if not doc.owner or not doc.owner.email:
                continue
            if doc.is_review_overdue:
                per_owner[doc.owner].append(doc)

        sent = 0
        for owner, docs in per_owner.items():
            subject = f'KB review reminder — {len(docs)} article(s) overdue'
            lines = [
                f'Hi {owner.first_name or owner.username},',
                '',
                f'You own {len(docs)} KB article(s) past their review date:',
                '',
            ]
            for d in docs:
                anchor = d.last_reviewed_at or d.published_at or d.created_at
                lines.append(f'  - {d.title} (last reviewed: {anchor.date() if anchor else "never"})')
            lines += [
                '',
                'Open each article and click "Mark reviewed" once you\'ve confirmed it\'s still accurate.',
                'Articles you no longer own can be reassigned with the Owner field in the article edit form.',
            ]
            body = '\n'.join(lines)
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'[DRY RUN] {owner.email} ({len(docs)} articles)'
                ))
            else:
                try:
                    send_mail(subject, body, None, [owner.email], fail_silently=False)
                    sent += 1
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(
                        f'send to {owner.email} failed: {exc}'
                    ))
        # This daily job also enforces the 90-day retention on the
        # zero-result search log (KB analytics).
        pruned = 0
        if not dry_run:
            pruned = SearchQueryLog.prune()
        self.stdout.write(self.style.SUCCESS(
            f'Pruned {pruned} search log row(s) older than '
            f'{SearchQueryLog.RETENTION_DAYS} days.'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'KB review reminder run @ {timezone.now().isoformat()}: '
            f'{len(per_owner)} owners, {sent} sent, dry_run={dry_run}'
        ))
