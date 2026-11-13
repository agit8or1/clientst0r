"""What the harness checks, in order, per profile. Plain data (no Django).

profiles:
    local   the default: a live clientst0r install (production) where the
            managed engine is already installed. Nothing on the host is
            touched except the managed office container, and only through
            clientst0r's own code paths (queued operations run by
            ``manage.py office_managed --run-pending``).
    vm      optional: a disposable VM. Adds installation from scratch and
            two operator-assisted steps (engine daemon restart, reboot) that
            hand over to the operator and continue on ``--resume``.

required: a check that must pass for ``mark-tested``. ``may_skip``: a
required check that mark-tested accepts as skipped only when the operator
names it in ``--allow-skipped`` (the skip reason is written into the diff).
"""
from __future__ import annotations

from collections import OrderedDict

LOCAL, VM = 'local', 'vm'
PROFILES = (LOCAL, VM)

CHECKS = OrderedDict((k, dict(title=t, profiles=p, required=r, may_skip=m)) for k, t, p, r, m in [
    ('guard', 'Safety guard', (LOCAL, VM), True, False),
    ('fixtures', 'Test organization, users and documents', (LOCAL, VM), True, False),
    ('install', 'Installation (installed, pinned digest, healthy)', (LOCAL, VM), True, False),
    ('path_mode_cookies', 'Path mode: clientst0r cookies are not forwarded to the editor',
     (LOCAL, VM), True, False),
    ('roundtrip_docx', 'DOCX: create, open, type, save, close, reopen', (LOCAL, VM), True, False),
    ('roundtrip_xlsx', 'XLSX: create, open, type, save, close, reopen', (LOCAL, VM), True, False),
    ('roundtrip_pptx', 'PPTX: create, open, type, save, close, reopen', (LOCAL, VM), True, False),
    ('readonly', 'Read-only user cannot edit (browser and server)', (LOCAL, VM), True, False),
    ('concurrent', 'Two users edit the same document at once', (LOCAL, VM), True, False),
    ('long_session', 'Long session with a delayed save', (LOCAL, VM), True, False),
    ('restart_persistence', 'Restart through clientst0r keeps documents', (LOCAL, VM), True, False),
    ('engine_daemon_restart', 'Container engine restart (operator, VM only)', (VM,), True, True),
    ('reboot', 'Reboot persistence (operator, VM only)', (VM,), True, True),
    ('connectivity', 'Editor unreachable: failure shown, recovery works', (LOCAL, VM), True, False),
    ('maintenance_drain', 'Maintenance drain: restart waits for the save', (LOCAL, VM), True, False),
    ('upgrade_rollback', 'Upgrade to a newer listed release and roll back', (LOCAL, VM), True, True),
    ('uninstall_reinstall', 'Uninstall keeps data; reinstall sees documents', (LOCAL, VM), True, False),
    ('cleanup', 'Remove the test organization, users and documents', (LOCAL, VM), False, False),
])


def plan(profile, *, only=None, skip=None):
    """Ordered check keys for `profile`. `only` / `skip` narrow it; guard,
    fixtures and cleanup always stay (the harness never runs without its
    guard and always cleans up)."""
    if profile not in PROFILES:
        raise ValueError(f'unknown profile {profile!r}')
    keys = [k for k, c in CHECKS.items() if profile in c['profiles']]
    always = {'guard', 'fixtures', 'cleanup'}
    unknown = set(only or ()) | set(skip or ())
    unknown -= set(CHECKS)
    if unknown:
        raise ValueError(f'unknown check(s): {", ".join(sorted(unknown))}')
    if only:
        keys = [k for k in keys if k in only or k in always]
    if skip:
        keys = [k for k in keys if k not in skip or k in always]
    return keys


def title(key):
    return CHECKS.get(key, {}).get('title', key)
