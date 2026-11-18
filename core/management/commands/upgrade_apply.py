"""Command-line equivalent of Settings -> Updates -> Apply.

    manage.py upgrade_apply                       show what this instance's channel would install, then ask
    manage.py upgrade_apply --yes                 ... and install it without asking
    manage.py upgrade_apply --ref v3.17.700 --sha <40-hex>        install exactly that release
    manage.py upgrade_apply --kind preview --ref main --sha <40-hex> --allow-preview      a testing build (main)
    manage.py upgrade_apply --kind prerelease --ref v3.18.0-rc.1 --sha <40-hex> --allow-preview   a signed pre-release tag (testing)
    manage.py upgrade_apply --resume              finish an upgrade that was interrupted
    manage.py upgrade_apply --auto                for the nightly timer: install only when
                                                  the channel has something newer

Same pipeline as the web UI (core/upgrade/apply.py): the revision is pinned
by sha and verified, preflight checks run, a verified backup is taken, and
the update script from the target revision is the one that runs.
"""
import argparse
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
        parser.add_argument('--kind', choices=['release', 'prerelease', 'preview'], default=None)
        parser.add_argument('--resume', action='store_true',
                            help='finish the unfinished upgrade; with --sha (and --ref/--kind), '
                                 'finish it with that newer revision, which must contain the '
                                 'one it stopped on')
        parser.add_argument('--auto', action='store_true')
        parser.add_argument('--yes', action='store_true')
        parser.add_argument('--allow-preview', action='store_true',
                            help='allow a testing build (main, or a signed pre-release tag) while '
                                 'following Official release (the channel setting is not changed)')
        # Compatibility (v3.17.697-700): same as --allow-preview for a pre-release tag.
        parser.add_argument('--allow-prerelease', action='store_true', help=argparse.SUPPRESS)
        parser.add_argument('--skip-deps-check', action='store_true',
                            help='skip the pip --dry-run preflight (the install itself still runs)')

    def handle(self, *args, **opts):
        out = self.stdout.write
        target = None
        retarget = None
        if opts['resume'] and opts['sha']:
            # Repair: finish the unfinished upgrade with a newer revision
            # that contains the one it stopped on.
            kind = opts['kind'] or ('preview' if opts['ref'] in (None, 'main') else 'release')
            try:
                retarget = Target(kind, opts['ref'] or 'main', opts['sha']).validate()
            except RevisionError as e:
                raise CommandError(str(e))
        elif opts['resume']:
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
            out(f"Installed: v{inst['version']} @ {(inst['sha'] or '?')[:12]}   "
                f"channel: {channels.CHANNEL_LABELS.get(state['channel'], state['channel'])}")
            if state['stable']:
                out(f"Official:  {state['stable']['tag']} @ {state['stable']['sha'][:12]} "
                    f"(published {state['stable'].get('published_at')})")
            if state['preview']:
                p = state['preview']
                ahead = p.get('ahead_of_stable')
                out(f"Testing:   main @ {p['sha'][:12]} v{p.get('version') or '?'}"
                    + (f" -- {ahead} unreleased commit(s) after the official release (not a release)"
                       if ahead else ''))
            if state['error']:
                # Never install from a stored answer: what is installed must
                # be what the channel offers now.
                self.stderr.write('Could not confirm with GitHub what this channel offers; '
                                  'nothing was installed.')
                sys.exit(4)
            t = state['target']
            if not t:
                out('No newer updates on your selected channel.')
                return
            target = Target(t['kind'], t['ref'], t['sha'], t.get('version') or '')
            out(f"Apply would install: {target.kind} {target.ref} @ {target.sha}")
            if not (opts['yes'] or opts['auto']):
                if not sys.stdin.isatty() or input('Install it? [y/N] ').strip().lower() != 'y':
                    out('Not applied.')
                    return
        result = upgrade_apply.run(target, emit=out, resume=opts['resume'], retarget=retarget,
                                   deps_check=not opts['skip_deps_check'],
                                   allow_preview=opts['allow_preview'],
                                   allow_prerelease=opts['allow_prerelease'])
        if result['success']:
            out(self.style.SUCCESS('Upgrade complete.'))
            return
        self.stderr.write(result['error'] or 'Upgrade failed')
        sys.exit(4 if result['refused'] else 3)
