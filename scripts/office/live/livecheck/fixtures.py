"""The harness's own, isolated test data (Django; runs as the app user).

* one organization, ``TEST_ORG_NAME``, created by the harness and by
  nothing else;
* three users, all MSP staff (user type Staff): two editors (Editor role)
  and one read-only member (Read-Only role), each a member of the test
  organization only. Their passwords are random (``secrets``), set hashed,
  never printed or stored, and registered with the run's Redactor. They
  sign in through an injected Django session that is OTP-verified with a
  static device created for the user, so the run works whether 2FA is
  required or not and nobody types a password;
* the documents the checks create (blank DOCX/XLSX/PPTX through
  office.creation, the same code as "New document").

Nothing here reads or changes another organization's data. ``cleanup``
deletes exactly the rows created here (looked up by the fixed names), the
revision files they own, and the sessions; audit log entries stay
(AuditLog.user / organization are SET_NULL and keep the names).
"""
from __future__ import annotations

import secrets

TEST_ORG_NAME = 'Office Live Check (automated)'
TEST_ORG_SLUG = 'office-live-check-automated'
USERNAMES = {'editor': 'livecheck-editor', 'editor2': 'livecheck-editor2',
             'reader': 'livecheck-reader'}
DEVICE_NAME = 'office-livecheck'
_CREATED_SESSIONS = set()     # in memory only, never written


def test_org():
    from core.models import Organization
    return Organization.objects.filter(slug=TEST_ORG_SLUG).first() or \
        Organization.objects.filter(name=TEST_ORG_NAME).first()


def leftovers():
    """What a previous run left behind (names only)."""
    from django.contrib.auth import get_user_model
    out = []
    if test_org() is not None:
        out.append(f'organization "{TEST_ORG_NAME}"')
    users = list(get_user_model().objects.filter(username__in=USERNAMES.values())
                 .values_list('username', flat=True))
    out += [f'user {u}' for u in users]
    return out


def test_user_ids():
    from django.contrib.auth import get_user_model
    return list(get_user_model().objects.filter(username__in=USERNAMES.values())
                .values_list('pk', flat=True))


class Fixtures:
    def __init__(self, redactor):
        self.redactor = redactor
        self.org = None
        self.users = {}

    def create(self):
        from django.contrib.auth import get_user_model
        from django.db import transaction
        from django_otp.plugins.otp_static.models import StaticDevice
        from accounts.models import Membership, Role, UserProfile, UserType
        from core.models import Organization
        if leftovers():
            raise RuntimeError('test data from a previous run exists: ' + ', '.join(leftovers()))
        User = get_user_model()
        roles = {'editor': Role.EDITOR, 'editor2': Role.EDITOR, 'reader': Role.READONLY}
        with transaction.atomic():
            self.org = Organization.objects.create(
                name=TEST_ORG_NAME, slug=TEST_ORG_SLUG,
                description='Created by scripts/office/live/run_live_checks.py for the Office live '
                            'verification. Deleted at the end of the run; safe to remove with '
                            '--cleanup-only.')
            for role_key, username in USERNAMES.items():
                password = secrets.token_urlsafe(32)
                self.redactor.add(password)
                user = User.objects.create_user(username, f'{username}@livecheck.invalid', password)
                user.first_name, user.last_name = 'Live check', role_key
                user.save(update_fields=['first_name', 'last_name'])
                del password
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.user_type = UserType.STAFF
                profile.save()
                Membership.objects.create(user=user, organization=self.org, role=roles[role_key],
                                          is_active=True)
                StaticDevice.objects.create(user=user, name=DEVICE_NAME, confirmed=True)
                # Fresh from the database: the cached profile on `user` is the
                # one the post-save signal created, before user_type was set.
                self.users[role_key] = User.objects.get(pk=user.pk)
        return self.ids()

    def ids(self):
        return {'org': self.org.pk if self.org else None,
                'users': {k: u.pk for k, u in self.users.items()}}

    @classmethod
    def load(cls, redactor, ids):
        from django.contrib.auth import get_user_model
        from core.models import Organization
        fx = cls(redactor)
        fx.org = Organization.objects.filter(pk=ids.get('org'), slug=TEST_ORG_SLUG).first()
        if fx.org is None:
            raise RuntimeError('the test organization of this run is gone')
        User = get_user_model()
        for key, pk in (ids.get('users') or {}).items():
            fx.users[key] = User.objects.get(pk=pk, username=USERNAMES[key])
        return fx

    # -- browser sign-in ---------------------------------------------------
    def session_key(self, role_key):
        """A new signed-in, OTP-verified Django session for a test user."""
        from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
        from django.contrib.sessions.backends.db import SessionStore
        from django_otp.plugins.otp_static.models import StaticDevice
        user = self.users[role_key]
        device = StaticDevice.objects.get(user=user, name=DEVICE_NAME)
        store = SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
        store[HASH_SESSION_KEY] = user.get_session_auth_hash()
        store['otp_device_id'] = device.persistent_id
        store['current_organization_id'] = self.org.pk
        store['2fa_prompted'] = True
        store.create()
        self.redactor.add(store.session_key)
        _CREATED_SESSIONS.add(store.session_key)
        return store.session_key

    def cookies(self, role_key, base_url):
        from urllib.parse import urlsplit
        from django.conf import settings
        host = urlsplit(base_url).hostname
        return [{'name': settings.SESSION_COOKIE_NAME, 'value': self.session_key(role_key),
                 'domain': host, 'path': '/', 'httpOnly': True,
                 'secure': urlsplit(base_url).scheme == 'https', 'sameSite': 'Lax'}]

    # -- documents ---------------------------------------------------------
    def new_document(self, fmt, title):
        from office import creation
        target = creation.new_document(self.org, fmt, title, self.users['editor'])
        return target

    def target(self, pk):
        from office import targets
        from docs.models import Document
        doc = Document._base_manager.get(pk=pk, organization=self.org)
        return targets.target_for(doc)


def cleanup():
    """Delete everything the harness created. Returns a summary dict."""
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from docs.models import Document
    from office import storage
    from office.models import EditSession, FileRevision, QuarantinedSave
    User = get_user_model()
    org = test_org()
    users = list(User.objects.filter(username__in=USERNAMES.values()))
    summary = {'organization': bool(org), 'users': [u.username for u in users],
               'documents': 0, 'revisions': 0, 'quarantined': 0, 'sessions': 0}
    files = set()
    with transaction.atomic():
        if org is not None:
            sess = EditSession.objects.filter(organization=org)
            q = QuarantinedSave.objects.filter(organization=org)
            revs = FileRevision.objects.filter(organization=org)
            docs = Document._base_manager.filter(organization=org)
            files |= set(revs.values_list('file', flat=True))
            files |= set(q.values_list('file', flat=True))
            files |= {f for f in docs.values_list('file', flat=True) if f}
            summary.update(documents=docs.count(), revisions=revs.count(), quarantined=q.count(),
                           sessions=sess.count())
            q.delete()
            revs.delete()
            docs.delete()
            sess.delete()
        if users:
            EditSession.objects.filter(user__in=users).delete()
            QuarantinedSave.objects.filter(user__in=users, organization__isnull=True).delete()
            from django_otp.plugins.otp_static.models import StaticDevice
            StaticDevice.objects.filter(user__in=users, name=DEVICE_NAME).delete()
            # Django sessions of the deleted users stop working (the auth
            # hash no longer matches a user) and expire on their own; the
            # keys this process created are deleted explicitly below.
            from django.contrib.sessions.models import Session
            Session.objects.filter(session_key__in=list(_CREATED_SESSIONS)).delete()
            _CREATED_SESSIONS.clear()
            for u in users:
                u.delete()
        if org is not None:
            org.delete()
    for name in files:
        storage.purge_unreferenced_file(name)
        if name and name.startswith('office/quarantine/'):
            try:
                storage._abs(name).unlink()
            except (FileNotFoundError, ValueError):
                pass
    return summary
