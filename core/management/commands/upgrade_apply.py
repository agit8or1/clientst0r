"""Command-line equivalent of Settings -> Updates -> Apply.

    manage.py upgrade_apply                       show what this instance's channel would install, then ask
    manage.py upgrade_apply --yes                 ... and install it without asking
    manage.py upgrade_apply --ref v3.17.700 --sha <40-hex>        install exactly that release
    manage.py upgrade_apply --kind preview --ref main --sha <40-hex> --allow-preview
    manage.py upgrade_apply --resume              finish an upgrade that was interrupted
    manage.py upgrade_apply --auto                for the nightly timer: install only when
                                                  the channel has something newer

Same pipeline as the web UI (core/upgrade/apply.py): the revision is pinned
by sha and verified, preflight checks run, a verified backup is taken, and
the update script from the target revision is the one that runs.
"""
import sys

from django.core.management.base import BaseCommand, CommandError

from core.upgrade import apply as upgrade_apply
from core.upgrade import channels
from core.upgrade.revision import RevisionError, Target


class Command(BaseCommand):
    help = 'Upgrade to an exact, verified revision (with preflight checks and a verified backup)'

    def add_arguments(self, parser):
        parser.add_argument('--ref', help='release tag (vX.Y.Z) or main')
        parser.add_argument('--sha', help='the full commit sha you reviewed')
        parser.add_argument('--kind', choices=['release', 'preview'], default=None)
        parser.add_argument('--resume', action='store_true')
        parser.add_argument('--auto', action='store_true')
        parser.add_argument('--yes', action='store_true')
        parser.add_argument('--allow-preview', action='store_true',
                            help='allow a preview (unreleased) target while following Stable')
        parser.add_argument('--skip-deps-check', action='store_true',
                            help='skip the pip --dry-run preflight (the install itself still runs)')

    def handle(self, *args, **opts):
        out = self.stdout.write
        target = None
        if opts['resume']:
            pass
        elif opts['sha']:
            kind = opts['kind'] or ('preview' if opts['ref'] in (None, 'main') else 'release')
            try:
                target = Target(kind, opts['ref'] or 'main', opts['sha']).validate()
            except RevisionError as e:
                raise CommandError(str(e))
        else:
            state = channels.resolve(force_refresh=True)
            if state['error']:
                out(self.style.WARNING(f"Update check: {state['error']}"
                                       + (' (showing the last good answer)' if state['stale'] else '')))
            inst = state['installed']
            out(f"Installed: v{inst['version']} @ {(inst['sha'] or '?')[:12]}   channel: {state['channel']}")
            if state['stable']:
                out(f"Stable:    {state['stable']['tag']} @ {state['stable']['sha'][:12]} "
                    f"(published {state['stable'].get('published_at')})")
            if state['preview']:
                p = state['preview']
                ahead = p.get('ahead_of_stable')
                out(f"Preview:   main @ {p['sha'][:12]} v{p.get('version') or '?'}"
                    + (f" -- {ahead} unreleased commit(s) after the stable release (not a release)"
                       if ahead else ''))
            t = state['target']
            if not t:
                out('Nothing newer to install on this channel.')
                return
            target = Target(t['kind'], t['ref'], t['sha'], t.get('version') or '')
            out(f"Apply would install: {target.kind} {target.ref} @ {target.sha}")
            if not (opts['yes'] or opts['auto']):
                if not sys.stdin.isatty() or input('Install it? [y/N] ').strip().lower() != 'y':
                    out('Not applied.')
                    return
        result = upgrade_apply.run(target, emit=out, resume=opts['resume'],
                                   deps_check=not opts['skip_deps_check'],
                                   allow_preview=opts['allow_preview'])
        if result['success']:
            out(self.style.SUCCESS('Upgrade complete.'))
            return
        self.stderr.write(result['error'] or 'Upgrade failed')
        sys.exit(4 if result['refused'] else 3)
