"""Open Office edit sessions: list them, drain an editor instance, resume it.

    manage.py office_sessions --status [--instance N]
    manage.py office_sessions --drain N [--timeout 600] [--poll 10] [--revoke-remaining]
    manage.py office_sessions --resume N

--drain is for editor upgrades and provider switches:
  1. blocks new sessions on instance N (the instance is disabled, so
     office.sessions.open_session refuses it; organizations whose policy
     falls back to another enabled instance use that one);
  2. asks the provider to save every open co-editing group now
     (EditorProvider.force_save; editors without a server-side save request
     report "not supported" and the drain waits for users to close);
  3. waits until no live session is left on N, or the timeout passes;
  4. on timeout lists what is still open and exits 1. --revoke-remaining
     revokes those sessions instead: any save they send later is quarantined
     (recoverable), never written over a newer revision.
--resume re-enables the instance. Run its Health check first after an upgrade.

Output names users, files and states only: never tokens, secrets or document keys.
"""
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from office import audit
from office import sessions as session_api
from office.models import EditorInstance
from office.providers import NotConfigured, NotSupported, get_provider


def _live(instance=None):
    qs = session_api.live_sessions().select_related('user', 'instance').order_by('opened_at')
    if instance is not None:
        qs = qs.filter(instance=instance)
    return qs


class Command(BaseCommand):
    help = 'List, drain or resume Office edit sessions on an editor instance.'

    def add_arguments(self, parser):
        g = parser.add_mutually_exclusive_group(required=True)
        g.add_argument('--status', action='store_true')
        g.add_argument('--drain', type=int, metavar='INSTANCE_ID')
        g.add_argument('--resume', type=int, metavar='INSTANCE_ID')
        parser.add_argument('--instance', type=int, help='With --status: only this instance.')
        parser.add_argument('--timeout', type=int, default=600,
                            help='Seconds to wait for sessions to close (default 600).')
        parser.add_argument('--poll', type=int, default=10, help='Seconds between checks (default 10).')
        parser.add_argument('--revoke-remaining', action='store_true',
                            help='After the timeout, revoke sessions still open (late saves are quarantined).')

    def handle(self, *args, **opts):
        if opts['status']:
            return self._status(opts['instance'])
        if opts['resume']:
            return self._resume(opts['resume'])
        return self._drain(opts['drain'], max(0, opts['timeout']), max(1, opts['poll']),
                           opts['revoke_remaining'])

    def _instance(self, pk):
        inst = EditorInstance.objects.filter(pk=pk).first()
        if inst is None:
            raise CommandError(f'No Office editor instance {pk}.')
        return inst

    def _session_line(self, s):
        now = timezone.now()
        idle = int((now - s.last_activity_at).total_seconds() // 60) if s.last_activity_at else 0
        return (f'  {s.pk}  {s.user.username:<20} {s.mode:<4} {s.state:<7} '
                f'{s.target_label[:50]!s:<50} opened {s.opened_at:%Y-%m-%d %H:%M} idle {idle} min')

    def _status(self, instance_id):
        instances = EditorInstance.objects.all()
        if instance_id:
            instances = [self._instance(instance_id)]
        any_found = False
        for inst in instances:
            any_found = True
            live = list(_live(inst))
            state = 'enabled' if inst.enabled else 'DISABLED (new sessions blocked)'
            self.stdout.write(f'{inst.pk}: {inst.name} [{inst.get_provider_display()}] {state}, '
                              f'health {inst.health_status}, version {inst.detected_version or "unknown"}, '
                              f'{len(live)} open session(s)')
            for s in live:
                self.stdout.write(self._session_line(s))
        if not any_found:
            self.stdout.write('No Office editor instances.')

    def _resume(self, pk):
        inst = self._instance(pk)
        EditorInstance.objects.filter(pk=pk).update(enabled=True)
        audit.log('settings_change', object_type='office.instance', object_id=inst.pk,
                  object_repr=inst.name,
                  description=f'Resumed Office editor instance {inst.name} (office_sessions --resume)',
                  extra={'changed': ['enabled']})
        self.stdout.write(self.style.SUCCESS(
            f'{inst.name} accepts new sessions again. If you upgraded the editor, run its '
            f'Health check so clientst0r records the new version and capabilities.'))

    def _drain(self, pk, timeout, poll, revoke_remaining):
        inst = self._instance(pk)
        was_enabled = inst.enabled
        EditorInstance.objects.filter(pk=pk).update(enabled=False)
        audit.log('settings_change', object_type='office.instance', object_id=inst.pk,
                  object_repr=inst.name,
                  description=f'Draining Office editor instance {inst.name}: new sessions blocked '
                              f'(office_sessions --drain)',
                  extra={'changed': ['enabled'] if was_enabled else []})
        self.stdout.write(f'Draining {inst.name}: new sessions on it are blocked.')

        live = list(_live(inst))
        self.stdout.write(f'{len(live)} open session(s).')
        for s in live:
            self.stdout.write(self._session_line(s))
        try:
            provider = get_provider(inst.provider)
        except NotConfigured as e:
            provider = None
            self.stdout.write(f'Cannot ask the editor to save: {e}')
        asked = set()
        for s in live:
            if provider is None or s.mode != 'edit' or s.document_key in asked:
                continue
            asked.add(s.document_key)
            try:
                ok = provider.force_save(s)
                result = 'save requested' if ok else 'editor refused the save request'
            except NotSupported as e:
                result = f'not supported ({e}); waiting for the user to close the editor'
            except NotConfigured as e:
                result = f'connector not configured ({e})'
            except Exception as e:   # one failing group must not stop the drain
                result = f'error: {type(e).__name__}'
            self.stdout.write(f'  {s.target_label[:60]}: {result}')

        deadline = time.monotonic() + timeout
        while True:
            remaining = list(_live(inst))
            if not remaining:
                self.stdout.write(self.style.SUCCESS(
                    f'{inst.name} is drained: no open sessions. It stays disabled until '
                    f'office_sessions --resume {inst.pk}.'))
                return
            if time.monotonic() >= deadline:
                break
            self.stdout.write(f'Waiting: {len(remaining)} session(s) still open…')
            time.sleep(max(0.1, min(poll, deadline - time.monotonic())))

        self.stdout.write(f'Timed out after {timeout}s with {len(remaining)} session(s) open:')
        for s in remaining:
            self.stdout.write(self._session_line(s))
        if revoke_remaining:
            n = sum(bool(session_api.revoke(s, 'instance drained for maintenance')) for s in remaining)
            self.stdout.write(self.style.WARNING(
                f'Revoked {n} session(s). Saves they send later are quarantined for recovery '
                f'(Settings → Office Documents → Quarantine).'))
            return
        self.stderr.write(self.style.ERROR(
            'Not drained. Ask those users to close their editors, run again with a longer '
            '--timeout, or add --revoke-remaining. The instance stays disabled.'))
        raise SystemExit(1)
