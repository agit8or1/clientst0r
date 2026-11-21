"""Settings -> Maintenance -> Off-host Backups (Phase 94.3, SR-17).

Superusers only, like every other install-wide system setting. Every change
is a CSRF-protected POST and is written to the audit log without secrets.
The backup key is shown exactly once, in the response to the POST that
generated it (never stored in the session, never in a redirect URL).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from core.models import OffhostBackupConfig, OffhostBackupRun
from core.offhost_backup import crypto, destinations, service


def _is_superuser(user):
    return user.is_active and user.is_superuser


def _audit(request, description, extra=None):
    service._audit(request.user, 'update', description, extra)


def _int(request, name, lo, hi, label, errors):
    raw = (request.POST.get(name) or '').strip()
    try:
        v = int(raw)
    except ValueError:
        errors.append(f'{label} must be a whole number.')
        return None
    if not lo <= v <= hi:
        errors.append(f'{label} must be between {lo} and {hi}.')
        return None
    return v


def _context(cfg, **extra):
    runs = list(OffhostBackupRun.objects.all()[:20])
    dest_note = ''
    if cfg.destination_type == cfg.DEST_LOCAL and cfg.local_path:
        try:
            if destinations.LocalDirDestination(cfg.local_path).same_filesystem_as_app():
                dest_note = ('This directory is on the same filesystem as the application. It protects against '
                             'mistakes, not against losing this host: mount a network share or another disk.')
        except destinations.DestinationError as e:
            dest_note = str(e)
    ctx = {
        'cfg': cfg,
        'runs': runs,
        'health': service.health(),
        'problems': service.readiness_problems(cfg),
        'public_key': destinations.public_key_of(cfg.sftp_private_key),
        'has_password': bool(cfg.sftp_password),
        'dest_note': dest_note,
        'destination_choices': OffhostBackupConfig.DESTINATION_CHOICES,
    }
    ctx.update(extra)
    return ctx


@never_cache
@login_required
@user_passes_test(_is_superuser)
def offhost_backup_settings(request):
    cfg = OffhostBackupConfig.get()
    if request.method != 'POST':
        return render(request, 'core/offhost_backup.html', _context(cfg))

    action = request.POST.get('action', '')
    handler = ACTIONS.get(action)
    if handler is None:
        messages.error(request, 'Unknown action.')
        return redirect('core:offhost_backup')
    result = handler(request, cfg)
    return result or redirect('core:offhost_backup')


def _save_destination(request, cfg):
    dtype = request.POST.get('destination_type', cfg.destination_type)
    if dtype not in dict(OffhostBackupConfig.DESTINATION_CHOICES):
        messages.error(request, 'Choose a destination type.')
        return None
    errors = []
    port = _int(request, 'sftp_port', 1, 65535, 'Port', errors) if dtype == cfg.DEST_SFTP else cfg.sftp_port
    if errors:
        for e in errors:
            messages.error(request, e)
        return None
    before = {'type': cfg.destination_type, 'destination': cfg.destination_label(),
              'host_key': cfg.host_key_fingerprint}
    host = (request.POST.get('sftp_host') or '').strip()
    host_changed = (host, port) != (cfg.sftp_host, cfg.sftp_port)
    cfg.destination_type = dtype
    if dtype == cfg.DEST_SFTP:
        cfg.sftp_host, cfg.sftp_port = host, port
        cfg.sftp_username = (request.POST.get('sftp_username') or '').strip()
        cfg.sftp_path = (request.POST.get('sftp_path') or '').strip()
        cfg.allow_legacy_ssh_rsa = request.POST.get('allow_legacy_ssh_rsa') == 'on'
        password = request.POST.get('sftp_password') or ''
        changed_secrets = []
        if password:
            cfg.sftp_password = password
            changed_secrets.append('password')
        if request.POST.get('clear_password') == 'on':
            cfg.sftp_password = ''
            changed_secrets.append('password cleared')
        pk = (request.POST.get('sftp_private_key') or '').strip()
        if pk:
            try:
                destinations.load_private_key(pk + '\n')
            except destinations.DestinationError as e:
                messages.error(request, str(e))
                return None
            cfg.sftp_private_key = pk + '\n'
            changed_secrets.append('private key')
        if host_changed and cfg.host_key:
            # The approved key belonged to the previous server.
            cfg.host_key_type = cfg.host_key = cfg.host_key_fingerprint = ''
            cfg.host_key_approved_at, cfg.host_key_approved_by = None, None
        if host_changed:
            cfg.pending_host_key_type = cfg.pending_host_key = cfg.pending_host_key_fingerprint = ''
            cfg.pending_host_key_seen_at = None
    else:
        path = (request.POST.get('local_path') or '').strip()
        if path:
            try:
                destinations.LocalDirDestination(path)
            except destinations.DestinationError as e:
                messages.error(request, str(e))
                return None
        cfg.local_path = path
        changed_secrets = []
    cfg.save()
    _audit(request, f'Off-host backup destination saved: {cfg.destination_label()}',
           {'event': 'offhost_destination', 'before': before,
            'after': {'type': cfg.destination_type, 'destination': cfg.destination_label(),
                      'host_key': cfg.host_key_fingerprint},
            'secrets_changed': changed_secrets})
    msg = 'Destination saved.'
    if dtype == cfg.DEST_SFTP and not cfg.host_key:
        msg += ' Next: fetch the server\'s host key and approve it.'
    messages.success(request, msg)
    return None


def _generate_ssh_key(request, cfg):
    if cfg.sftp_private_key and request.POST.get('confirm_replace') != 'on':
        messages.error(request, 'A private key is already stored. Tick "replace" to generate a new one.')
        return None
    priv, pub = destinations.generate_ssh_keypair()
    cfg.sftp_private_key = priv
    cfg.save(update_fields=['sftp_private_key', 'updated_at'])
    _audit(request, 'Off-host backup SFTP key pair generated', {'event': 'offhost_ssh_key_generated',
                                                                 'public_key': pub})
    messages.success(request, 'SSH key pair generated. Add the public key shown below to the backup account\'s '
                              '~/.ssh/authorized_keys on the server.')
    return None


def _fetch_host_key(request, cfg):
    try:
        key_type, fp, approved = destinations.fetch_host_key(cfg, user=request.user)
    except destinations.DestinationError as e:
        messages.error(request, str(e))
        return None
    if approved:
        messages.success(request, f'The server presented the approved key {fp}.')
    else:
        messages.warning(request, f'The server presented {key_type} {fp}. Compare it with the server '
                                  f'(ssh-keygen -lf /etc/ssh/ssh_host_*_key.pub) before approving.')
    return None


def _approve_host_key(request, cfg):
    from netconfig import hostkeys
    try:
        hostkeys.approve_pending(cfg, request.user, request.POST.get('expected_fingerprint', ''))
    except hostkeys.HostKeyError as e:
        messages.error(request, str(e))
        return None
    messages.success(request, f'Host key {cfg.host_key_fingerprint} approved.')
    return None


def _paste_host_key(request, cfg):
    from netconfig import hostkeys
    try:
        fp = hostkeys.approve_pasted(cfg, request.user, request.POST.get('public_key', ''))
    except hostkeys.HostKeyError as e:
        messages.error(request, str(e))
        return None
    messages.success(request, f'Host key {fp} approved.')
    return None


def _clear_host_key(request, cfg):
    from netconfig import hostkeys
    hostkeys.clear_host_key(cfg, request.user)
    messages.success(request, 'Approved host key removed. Backups will not connect until a key is approved.')
    return None


def _save_schedule(request, cfg):
    errors = []
    vals = {
        'backup_interval_hours': _int(request, 'backup_interval_hours', 1, 24 * 31, 'Backup interval', errors),
        'verify_interval_days': _int(request, 'verify_interval_days', 1, 90, 'Verification interval', errors),
        'keep_daily': _int(request, 'keep_daily', 1, 365, 'Daily archives to keep', errors),
        'keep_weekly': _int(request, 'keep_weekly', 0, 520, 'Weekly archives to keep', errors),
        'alert_after_days': _int(request, 'alert_after_days', 1, 60, 'Warn after', errors),
    }
    if errors:
        for e in errors:
            messages.error(request, e)
        return None
    before = {k: getattr(cfg, k) for k in vals}
    for k, v in vals.items():
        setattr(cfg, k, v)
    cfg.save()
    _audit(request, 'Off-host backup schedule and retention saved',
           {'event': 'offhost_schedule', 'before': before, 'after': vals})
    messages.success(request, 'Schedule and retention saved.')
    return None


def _generate_key(request, cfg):
    if cfg.backup_key and request.POST.get('confirm_rotate') != 'on':
        messages.error(request, 'A backup key already exists. Tick the box to replace it — archives already '
                                'uploaded still need the old key.')
        return None
    rotating = bool(cfg.backup_key)
    old_fp = cfg.backup_key_fingerprint
    key = crypto.generate_key()
    cfg.backup_key = key
    cfg.backup_key_fingerprint = crypto.key_fingerprint(key)
    cfg.backup_key_created_at = timezone.now()
    cfg.backup_key_acknowledged_at, cfg.backup_key_acknowledged_by = None, None
    cfg.save()
    _audit(request, f'Off-host backup key {"rotated" if rotating else "generated"}: '
                    f'{old_fp or "none"} -> {cfg.backup_key_fingerprint}',
           {'event': 'offhost_key_rotated' if rotating else 'offhost_key_generated',
            'old_fingerprint': old_fp, 'new_fingerprint': cfg.backup_key_fingerprint})
    response = render(request, 'core/offhost_backup.html', _context(cfg, new_key=key, rotated_from=old_fp))
    response['Cache-Control'] = 'no-store'
    return response


def _acknowledge_key(request, cfg):
    typed = ''.join((request.POST.get('key_tail') or '').split())
    if not cfg.backup_key:
        messages.error(request, 'There is no backup key yet.')
        return None
    if len(typed) != 6 or not cfg.backup_key.endswith(typed):
        messages.error(request, 'That does not match the last 6 characters of the backup key. If the key was '
                                'not saved, generate a new one.')
        return None
    cfg.backup_key_acknowledged_at, cfg.backup_key_acknowledged_by = timezone.now(), request.user
    cfg.save(update_fields=['backup_key_acknowledged_at', 'backup_key_acknowledged_by', 'updated_at'])
    _audit(request, f'Off-host backup key {cfg.backup_key_fingerprint} confirmed as escrowed',
           {'event': 'offhost_key_acknowledged', 'fingerprint': cfg.backup_key_fingerprint})
    messages.success(request, 'Backup key confirmed.')
    return None


def _set_enabled(request, cfg):
    on = request.POST.get('enabled') == '1'
    if on:
        problems = service.readiness_problems(cfg)
        if problems:
            messages.error(request, 'Cannot switch on yet: ' + '; '.join(problems) + '.')
            return None
    if cfg.enabled == on:
        return None
    cfg.enabled = on
    cfg.save(update_fields=['enabled', 'updated_at'])
    _audit(request, f'Off-host backups switched {"on" if on else "off"}', {'event': 'offhost_enabled', 'enabled': on})
    messages.success(request, 'Off-host backups switched on. The first backup runs within 15 minutes.' if on
                     else 'Off-host backups switched off.')
    return None


def _test_connection(request, cfg):
    try:
        with destinations.open_destination(cfg) as dest:
            n = len(dest.list())
    except destinations.DestinationError as e:
        messages.error(request, str(e))
        return None
    except Exception as e:  # noqa: BLE001
        messages.error(request, service._safe_message(e))
        return None
    messages.success(request, f'Connected to {cfg.destination_label()}: {n} backup archive(s) there.')
    return None


def _run_now(kind):
    def handler(request, cfg):
        problems = service.readiness_problems(cfg)
        if problems:
            messages.error(request, 'Cannot run yet: ' + '; '.join(problems) + '.')
            return None
        service.request_now(kind, request.user)
        messages.success(request, ('Backup' if kind == 'backup' else 'Restore verification') +
                         ' queued; the scheduler starts it within a minute. Reload this page to see the result.')
        return None
    return handler


ACTIONS = {
    'save_destination': _save_destination,
    'generate_ssh_key': _generate_ssh_key,
    'fetch_host_key': _fetch_host_key,
    'approve_host_key': _approve_host_key,
    'paste_host_key': _paste_host_key,
    'clear_host_key': _clear_host_key,
    'save_schedule': _save_schedule,
    'generate_key': _generate_key,
    'acknowledge_key': _acknowledge_key,
    'set_enabled': _set_enabled,
    'test_connection': _test_connection,
    'run_backup_now': _run_now('backup'),
    'run_verify_now': _run_now('verify'),
}
