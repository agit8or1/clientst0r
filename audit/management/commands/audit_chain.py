"""manage.py audit_chain seal|verify|tick|export|prune — the audit log's
tamper-evident chain (audit.chain, SR-07)."""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from audit import chain


class Command(BaseCommand):
    help = 'Seal, verify, export or clean up the tamper-evident audit log chain.'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='op', required=True)
        sub.add_parser('seal', help='Seal entries written since the last run')
        sub.add_parser('verify', help='Check every sealed entry; exit 1 when the chain does not verify')
        sub.add_parser('tick', help='Scheduler entry: seal, and verify once a day')
        ex = sub.add_parser('export', help='Write entries as gzip JSON lines')
        ex.add_argument('--out', required=True)
        ex.add_argument('--days', type=int, default=0, help='Only the last N days (0 = everything)')
        pr = sub.add_parser('prune', help='Archive, then delete sealed entries older than N days')
        pr.add_argument('--days', type=int, required=True)

    def handle(self, *args, **opts):
        op = opts['op']
        if op == 'seal':
            self.stdout.write(f'sealed {chain.seal()} entries')
        elif op == 'tick':
            sealed, verified = chain.tick()
            self.stdout.write(f'sealed {sealed} entries' + ('' if verified is None else
                                                             f'; verified: {"ok" if verified else "FAILED"}'))
            if verified is False:
                raise CommandError('audit chain verification failed; see Settings -> System warnings')
        elif op == 'verify':
            chain.seal()
            ok, problems = chain.verify()
            if ok:
                self.stdout.write(self.style.SUCCESS('audit chain verifies'))
            else:
                for p in problems:
                    self.stdout.write(self.style.ERROR(p))
                raise CommandError('audit chain does not verify')
        elif op == 'export':
            from audit.models import AuditLog
            chain.seal()
            qs = AuditLog.objects.all()
            if opts['days']:
                qs = qs.filter(timestamp__gte=timezone.now() - timedelta(days=opts['days']))
            n = chain.export(qs, opts['out'])
            self.stdout.write(f'exported {n} entries to {opts["out"]}')
        elif op == 'prune':
            if opts['days'] < 30:
                raise CommandError('Entries younger than 30 days are kept.')
            try:
                n, path = chain.prune_before(timezone.now() - timedelta(days=opts['days']))
            except chain.PruneRefused as e:
                raise CommandError(str(e))
            self.stdout.write(f'deleted {n} entries' + (f'; archive {path}' if path else ''))
