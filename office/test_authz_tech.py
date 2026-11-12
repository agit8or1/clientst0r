"""Roles & permissions program (authz-tech): a queued managed ONLYOFFICE
operation rechecks its requester when the scheduler starts it."""
from django.contrib.auth.models import User

from office.managed import jobs
from office.test_managed import ManagedBase


class QueuedOperationRecheckTests(ManagedBase):
    def test_operation_fails_when_requester_lost_superuser(self):
        admin = User.objects.create_superuser('authz-office-admin', 'a@x.test', 'pw')
        op = jobs.enqueue('start', user=admin)
        admin.is_superuser = False
        admin.save()
        jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'failed')
        self.assertIn('no longer has platform administrator rights', op.error)
        self.assertFalse(any(c.get('action') == 'start' for c in getattr(self.helper, 'calls', [])
                             if isinstance(c, dict)))

    def test_deactivated_requester_fails_too(self):
        admin = User.objects.create_superuser('authz-office-admin2', 'b@x.test', 'pw')
        op = jobs.enqueue('restart', user=admin)
        admin.is_active = False
        admin.save()
        jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'failed')
