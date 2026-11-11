"""
Background re-check of LDAP group -> customer membership mappings.

Sign-in already applies the mappings (accounts.ldap_mapping). This module
does the same for LDAP users who have not signed in again, so somebody
removed from a mapped group loses the mapped membership within one sync
cycle. Run by the scheduler (task `ldap_group_sync`, management command
`ldap_group_sync`).

Rules:
- Uses the configured service bind; no user password is involved.
- Bounded: at most `batch_size` users per run, oldest-checked first, and a
  user is not re-checked within `min_interval_minutes` (throttle).
- Fail closed for grants, fail safe for removals. Nothing changes for a user
  unless the directory gave a definite answer:
    * directory unreachable / bind fails / search errors -> the run stops,
      nobody is changed, the run reports the failure;
    * user not found (or found more than once) -> that user is skipped and
      reported, never deactivated;
    * a mapped group cannot be read (missing, unexpected error) -> that
      customer is skipped for the user: no grant, no role change, no removal.
- Only memberships a mapping created are ever changed (same as sign-in).
  Every change is audited with trigger=background_sync.
- When a mapped membership is deactivated, open sessions that had that
  customer selected drop it; a user left with no customer access at all
  (and who is not MSP staff) is signed out everywhere. Membership is also
  re-checked on every request, so access ends at the next request either way.
"""
import logging
from dataclasses import dataclass, field

from django.utils import timezone

logger = logging.getLogger('accounts.ldap')

DEFAULT_BATCH_SIZE = 100
DEFAULT_MIN_INTERVAL_MINUTES = 60

# Session keys that select a customer: staff app and customer portal.
_ORG_SESSION_KEYS = ('current_organization_id', 'portal_org_id')


class DirectoryUnavailable(Exception):
    """The directory could not give an answer; nothing may change."""


class _Unknown(Exception):
    """One group lookup could not be answered."""


@dataclass
class SyncReport:
    status: str = 'ok'           # ok | skipped | failed
    message: str = ''
    checked: int = 0
    changed_users: int = 0
    changes: list = field(default_factory=list)       # (username, action, org_id)
    not_found: list = field(default_factory=list)     # usernames
    uncertain: list = field(default_factory=list)     # (username, org_id)
    sessions_ended: int = 0
    sessions_trimmed: int = 0

    def summary(self):
        parts = [f'{self.status}: {self.message}' if self.message else self.status,
                 f'checked {self.checked}', f'changes {len(self.changes)}']
        if self.not_found:
            parts.append(f'not found in directory (skipped): {", ".join(self.not_found[:20])}')
        if self.uncertain:
            parts.append(f'{len(self.uncertain)} customer check(s) skipped (group unreadable)')
        if self.sessions_ended or self.sessions_trimmed:
            parts.append(f'sessions ended {self.sessions_ended}, trimmed {self.sessions_trimmed}')
        return '; '.join(parts)


def _strict_is_member(conn, cfg, group_dn, user_dn, uid):
    """Like ldap_backend.is_group_member, but a missing / unreadable group is
    'unknown' rather than 'no', and connection errors propagate."""
    import ldap
    import ldap.filter
    from accounts.ldap_backend import _AD_IN_CHAIN
    try:
        if cfg.group_type == 'active_directory':
            flt = '(member:%s:=%s)' % (_AD_IN_CHAIN, ldap.filter.escape_filter_chars(user_dn))
            results = conn.search_s(group_dn, ldap.SCOPE_BASE, flt, ['1.1'])
            if results:
                return any(dn for dn, _attrs in results)
            # No match: make sure the group itself exists before saying "no".
            if not [dn for dn, _a in (conn.search_s(group_dn, ldap.SCOPE_BASE,
                                                    '(objectClass=*)', ['1.1']) or []) if dn]:
                raise _Unknown(group_dn)
            return False
        if cfg.group_type == 'posix':
            if not uid:
                raise _Unknown(group_dn)
            return bool(conn.compare_s(group_dn, 'memberUid', uid.encode()))
        attr = 'uniqueMember' if cfg.group_type == 'group_of_unique_names' else 'member'
        return bool(conn.compare_s(group_dn, attr, user_dn.encode()))
    except ldap.NO_SUCH_ATTRIBUTE:
        return False  # the group exists and has no members of that kind
    except (ldap.NO_SUCH_OBJECT, ldap.UNDEFINED_TYPE, ldap.INAPPROPRIATE_MATCHING,
            ldap.INVALID_DN_SYNTAX, ldap.INSUFFICIENT_ACCESS):
        raise _Unknown(group_dn)
    except (ldap.SERVER_DOWN, ldap.TIMEOUT, ldap.CONNECT_ERROR, ldap.INVALID_CREDENTIALS,
            ldap.UNAVAILABLE, ldap.BUSY):
        raise DirectoryUnavailable('directory connection lost')
    except ldap.LDAPError:
        raise _Unknown(group_dn)


def _connect(cfg):
    import ldap
    from accounts.ldap_backend import _describe_ldap_error
    try:
        conn = ldap.initialize(' '.join(cfg.server_uris), bytes_mode=False)
        for opt, value in cfg.connection_options().items():
            conn.set_option(opt, value)
        if cfg.effective_start_tls:
            conn.start_tls_s()
        conn.simple_bind_s(cfg.bind_dn, cfg.bind_password)
        return conn
    except ldap.LDAPError as exc:
        raise DirectoryUnavailable(_describe_ldap_error(exc, cfg.bind_password))


def _find_user(conn, cfg, username):
    """(dn, uid) for `username`, or None when not exactly one entry matches."""
    import ldap
    import ldap.filter
    from accounts.ldap_backend import _first
    flt = cfg.user_search_filter % {'user': ldap.filter.escape_filter_chars(username)}
    try:
        found = [r for r in (conn.search_s(cfg.user_search_base, ldap.SCOPE_SUBTREE, flt,
                                           cfg.attrlist) or []) if r[0]]
    except ldap.NO_SUCH_OBJECT:
        raise DirectoryUnavailable('user search base not found')
    except ldap.LDAPError as exc:
        from accounts.ldap_backend import _describe_ldap_error
        raise DirectoryUnavailable(_describe_ldap_error(exc, cfg.bind_password))
    if len(found) != 1:
        return None
    dn, raw = found[0]
    attrs = ldap.cidict.cidict(raw or {})
    return dn, (_first(attrs, cfg.attr_username) or username)


def _candidates(batch_size, min_interval_minutes, now):
    from datetime import timedelta
    from django.db.models import F, Q
    from accounts.models import UserProfile
    cutoff = now - timedelta(minutes=min_interval_minutes)
    return list(UserProfile.objects.filter(
        auth_source='ldap', user__is_active=True,
    ).filter(
        Q(ldap_groups_checked_at__isnull=True) | Q(ldap_groups_checked_at__lt=cutoff)
    ).select_related('user').order_by(
        F('ldap_groups_checked_at').asc(nulls_first=True), 'pk',
    )[:batch_size])


def _end_sessions(removed, report):
    """removed: {user_id: set(org_ids)}. Trim or end matching sessions."""
    from django.conf import settings
    from django.contrib.sessions.models import Session
    from accounts.models import Membership
    engine = getattr(settings, 'SESSION_ENGINE', 'django.contrib.sessions.backends.db')
    if engine not in ('django.contrib.sessions.backends.db',
                      'django.contrib.sessions.backends.cached_db'):
        return  # not enumerable; per-request membership checks still apply
    from importlib import import_module
    store_cls = import_module(engine).SessionStore
    from django.contrib.auth import get_user_model
    users = {u.pk: u for u in get_user_model().objects.filter(pk__in=removed).select_related('profile')}
    lost_everything = set()
    for uid, user in users.items():
        profile = getattr(user, 'profile', None)
        is_staff = bool(profile and profile.is_staff_user()) or user.is_superuser
        if not is_staff and not Membership.objects.filter(
                user_id=uid, is_active=True, organization__is_active=True).exists():
            lost_everything.add(uid)
    wanted = {str(uid) for uid in removed}
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        try:
            data = session.get_decoded()
        except Exception:
            continue
        uid = data.get('_auth_user_id')
        if uid not in wanted:
            continue
        uid = int(uid)
        store = store_cls(session_key=session.session_key)
        if uid in lost_everything:
            store.delete()
            report.sessions_ended += 1
            continue
        dirty = False
        for key in _ORG_SESSION_KEYS:
            try:
                value = int(data.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value and value in removed[uid]:
                store[key] = None
                dirty = True
        if dirty:
            store.save()
            report.sessions_trimmed += 1


def _audit_run(report):
    if not report.changes and not report.sessions_ended:
        return
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=None, action='update', object_type='ldap_group_sync',
            object_repr='LDAP group mapping background sync',
            description=report.summary()[:1000],
            extra_data={'source': 'ldap_group_mapping', 'trigger': 'background_sync',
                        'checked': report.checked, 'changes': len(report.changes),
                        'not_found': report.not_found[:50],
                        'sessions_ended': report.sessions_ended,
                        'sessions_trimmed': report.sessions_trimmed},
        )
    except Exception:
        logger.exception('Could not write LDAP group sync audit entry')


def run_sync(batch_size=DEFAULT_BATCH_SIZE, min_interval_minutes=DEFAULT_MIN_INTERVAL_MINUTES):
    """Re-check a batch of LDAP users. Returns a SyncReport; status 'failed'
    means the directory could not be used and nothing was changed."""
    from accounts import ldap_backend
    from accounts.ldap_mapping import active_mappings, sync_memberships
    from accounts.models import Membership

    report = SyncReport()
    try:
        cfg = ldap_backend.config_from_settings()
    except Exception as exc:
        report.status, report.message = 'failed', f'could not load LDAP settings ({type(exc).__name__})'
        return report
    if not cfg.enabled:
        report.status, report.message = 'skipped', 'LDAP sign-in is off'
        return report
    if not ldap_backend.LDAP_AVAILABLE:
        report.status, report.message = 'skipped', 'python-ldap / django-auth-ldap not installed'
        return report
    errors, _warnings = cfg.validate()
    if errors:
        report.status, report.message = 'failed', 'LDAP settings are incomplete'
        return report

    mappings = active_mappings()
    if not mappings and not Membership.objects.filter(ldap_group_mapping__isnull=False,
                                                      is_active=True).exists():
        report.status, report.message = 'skipped', 'no group mappings'
        return report

    now = timezone.now()
    profiles = _candidates(batch_size, min_interval_minutes, now)
    if not profiles:
        report.message = 'nobody due'
        return report

    try:
        conn = _connect(cfg)
    except DirectoryUnavailable as exc:
        report.status, report.message = 'failed', f'directory unavailable, nothing changed: {exc}'
        return report

    removed = {}
    try:
        for profile in profiles:
            user = profile.user
            found = _find_user(conn, cfg, user.get_username())
            if found is None:
                report.not_found.append(user.get_username())
                profile.ldap_groups_checked_at = now
                profile.save(update_fields=['ldap_groups_checked_at'])
                continue
            user_dn, uid = found
            member_ids, skip_orgs, cache = set(), set(), {}
            for m in mappings:
                key = m.group_dn_normalized
                if key not in cache:
                    try:
                        cache[key] = bool(_strict_is_member(conn, cfg, m.group_dn, user_dn, uid))
                    except _Unknown:
                        cache[key] = None
                if cache[key] is None:
                    skip_orgs.add(m.organization_id)
                elif cache[key]:
                    member_ids.add(m.pk)
            for org_id in sorted(skip_orgs):
                report.uncertain.append((user.get_username(), org_id))
            changes = sync_memberships(user, mappings, member_ids, skip_org_ids=skip_orgs,
                                       trigger='background_sync')
            report.checked += 1
            if changes:
                report.changed_users += 1
            for action, org_id in changes:
                report.changes.append((user.get_username(), action, org_id))
                if action == 'deactivate':
                    removed.setdefault(user.pk, set()).add(org_id)
            profile.ldap_groups_checked_at = now
            profile.save(update_fields=['ldap_groups_checked_at'])
    except DirectoryUnavailable as exc:
        # Users already processed keep their (definite) result; the rest wait.
        report.status = 'failed'
        report.message = f'directory became unavailable after {report.checked} user(s); rest skipped: {exc}'
    finally:
        try:
            conn.unbind_s()
        except Exception:
            pass

    if removed:
        try:
            _end_sessions(removed, report)
        except Exception:
            logger.exception('LDAP group sync could not end sessions')
    _audit_run(report)
    return report
