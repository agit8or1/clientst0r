"""Staff side of portal request types: the form builder (draft / publish /
archive / copies / starters), schema rules, routing on request answers,
the ticket-list filter, the report, audited answer edits and the upgrade
backfill."""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from psa import request_forms, request_starters
from psa.models import (
    ClientPSASettings, Queue, ServiceCatalogItem, ServiceRequestSubmission, Ticket,
)
from psa.service_requests import SchemaError, normalize_schema, validate_submission

from ._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed

SCHEMA = [
    {'key': 'who', 'label': 'Their name', 'type': 'text', 'required': True},
    {'key': 'work_mode', 'label': 'Where will they work?', 'type': 'radio', 'required': True,
     'options': [{'value': 'office', 'label': 'In the office'}, {'value': 'remote', 'label': 'Remote'}]},
]


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


def _qd(data):
    from django.http import QueryDict
    q = QueryDict(mutable=True)
    for k, v in data.items():
        if isinstance(v, list):
            q.setlist(k, v)
        else:
            q[k] = v
    return q


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.psa_portal_customer_approvals_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='Acme RT', slug='acme-rt')
        cls.other = Organization.objects.create(name='Other RT', slug='other-rt')
        for o in (cls.org, cls.other):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True)
        cls.admin = User.objects.create_superuser('rt-admin', 'admin@msp.example', 'pw')
        cls.customer = User.objects.create_user('rt-cust', 'cust@acme.example', 'pw')
        Membership.objects.create(user=cls.customer, organization=cls.org, role=Role.READONLY,
                                  is_active=True)
        cls.queue = Queue.objects.filter(is_active=True).first()
        cls.escalations = Queue.objects.get(name='Escalations')
        cls.item = ServiceCatalogItem.objects.create(
            name='New employee', slug='new-employee-rt', portal_visible=True,
            default_queue=cls.queue, default_subject='New user: {{who}}')
        request_forms.publish(cls.item, cls.admin, schema=SCHEMA)

    def setUp(self):
        super().setUp()
        # Portal submissions are rate-limited per user in the cache; start
        # each test with a clean count.
        from django.core.cache import cache
        cache.clear()

    def submit(self, **answers):
        data = {'f_who': 'Jane', 'f_work_mode': 'remote', '_form_version': '1'}
        data.update(answers)
        with self.captureOnCommitCallbacks(execute=True):
            r = _login(self.customer).post(f'/portal/requests/{self.item.slug}/', data)
        self.assertEqual(r.status_code, 302, r.content[:400])
        return Ticket.objects.filter(organization=self.org).latest('pk')


class SchemaRuleTests(TestCase):
    def test_new_field_types_and_conditions_normalize(self):
        schema = normalize_schema([
            {'key': 'kind', 'label': 'Kind', 'type': 'radio', 'options': ['a', 'b']},
            {'key': 'when', 'label': 'When', 'type': 'datetime'},
            {'key': 'phone', 'label': 'Phone', 'type': 'tel',
             'show_if': {'any': [{'field': 'kind', 'op': 'equals', 'value': 'a'},
                                 {'field': 'when', 'op': 'is_set'}]}},
            {'key': 'why', 'label': 'Why', 'type': 'textarea',
             'required_if': {'field': 'kind', 'op': 'not_equals', 'value': 'a'}},
            {'key': 'tip', 'label': 'No passwords please', 'type': 'info'},
        ], allow_legacy_types=False)
        self.assertEqual([f['type'] for f in schema], ['radio', 'datetime', 'tel', 'textarea', 'info'])

    def test_condition_on_later_field_or_cycle_rejected(self):
        with self.assertRaises(SchemaError):
            normalize_schema([
                {'key': 'a', 'label': 'A', 'type': 'text', 'show_if': {'field': 'b', 'op': 'is_set'}},
                {'key': 'b', 'label': 'B', 'type': 'text', 'show_if': {'field': 'a', 'op': 'is_set'}},
            ])
        with self.assertRaises(SchemaError):
            normalize_schema([{'key': 'a', 'label': 'A', 'type': 'text',
                               'show_if': {'field': 'a', 'op': 'is_set'}}])

    def test_no_code_in_conditions(self):
        with self.assertRaises(SchemaError):
            normalize_schema([
                {'key': 'a', 'label': 'A', 'type': 'text'},
                {'key': 'b', 'label': 'B', 'type': 'text',
                 'show_if': {'field': 'a', 'op': '__import__("os")', 'value': 'x'}}])
        with self.assertRaises(SchemaError):
            normalize_schema([
                {'key': 'a', 'label': 'A', 'type': 'text'},
                {'key': 'b', 'label': 'B', 'type': 'text', 'show_if': 'a == 1'}])

    def test_secret_fields_rejected(self):
        for f in ({'key': 'pw', 'label': 'Password', 'type': 'text'},
                  {'key': 'x', 'label': 'Login', 'type': 'text', 'placeholder': 'their current password'},
                  {'key': 'recovery_code', 'label': 'Code', 'type': 'text'}):
            with self.assertRaises(SchemaError, msg=f):
                normalize_schema([f])
        # Choice questions about passwords are fine (no secret is typed in).
        normalize_schema([{'key': 'reset', 'label': 'Reset their password?', 'type': 'checkbox'}])

    def test_required_if_server_side(self):
        schema = normalize_schema([
            {'key': 'kind', 'label': 'Kind', 'type': 'select', 'options': ['a', 'b']},
            {'key': 'why', 'label': 'Why', 'type': 'text',
             'required_if': {'field': 'kind', 'op': 'equals', 'value': 'b'}}])
        _, errors = validate_submission(schema, _qd({'f_kind': 'a'}))
        self.assertEqual(errors, [])
        _, errors = validate_submission(schema, _qd({'f_kind': 'b'}))
        self.assertTrue(any('Why is required' in e for e in errors))

    def test_all_starters_are_valid_and_ask_no_secrets(self):
        keys = {s['key'] for s in request_starters.STARTERS}
        self.assertTrue({'new_employee', 'new_phone', 'offboard', 'general_support'} <= keys)
        for s in request_starters.STARTERS:
            normalize_schema(s['schema'], allow_legacy_types=False)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BuilderViewTests(_Base):
    def test_create_draft_save_preview_publish(self):
        c = _login(self.admin)
        r = c.post('/psa/request-types/new/', {'name': 'Laptop request'})
        item = ServiceCatalogItem.objects.get(name='Laptop request')
        self.assertRedirects(r, f'/psa/request-types/{item.pk}/', fetch_redirect_response=False)
        self.assertEqual(item.lifecycle, ServiceCatalogItem.LIFECYCLE_DRAFT)
        r = c.get(f'/psa/request-types/{item.pk}/')
        self.assertContains(r, 'id="rb-schema-json"')
        self.assertContains(r, 'request_form_builder.js')
        schema = [{'key': 'model', 'label': 'Which model?', 'type': 'select', 'options': ['13"', '15"']}]
        r = c.post(f'/psa/request-types/{item.pk}/', {'action': 'save_draft',
                                                      'schema_json': json.dumps(schema)})
        self.assertEqual(r.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.draft_schema[0]['key'], 'model')
        self.assertFalse(item.form_versions.exists())
        # Drafts are never offered to customers.
        self.assertEqual(_login(self.customer).get(f'/portal/requests/{item.slug}/').status_code, 404)
        r = c.get(f'/psa/request-types/{item.pk}/preview/?draft=1&organization={self.org.pk}')
        self.assertContains(r, 'Which model?')
        self.assertContains(r, 'Preview')
        r = c.post(f'/psa/request-types/{item.pk}/', {'action': 'publish',
                                                      'schema_json': json.dumps(schema)})
        item.refresh_from_db()
        self.assertEqual(item.lifecycle, ServiceCatalogItem.LIFECYCLE_PUBLISHED)
        self.assertEqual(item.published_version.number, 1)
        self.assertIsNone(item.draft_schema)
        self.assertEqual(_login(self.customer).get(f'/portal/requests/{item.slug}/').status_code, 200)
        self.assertTrue(AuditLog.objects.filter(object_type='psa.ServiceCatalogItem', object_id=item.pk,
                                                description__startswith='Published form v1').exists())

    def test_invalid_schema_is_refused_with_message(self):
        c = _login(self.admin)
        bad = [{'key': 'a', 'label': 'A', 'type': 'text', 'show_if': {'field': 'zz', 'op': 'is_set'}}]
        r = c.post(f'/psa/request-types/{self.item.pk}/', {'action': 'publish',
                                                           'schema_json': json.dumps(bad)})
        self.assertEqual(r.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.published_version.number, 1)

    def test_customer_users_cannot_reach_builder(self):
        # Customer portal users are sent to the portal from every staff page
        # (PortalUserGuardMiddleware); nothing in the builder is reachable.
        c = _login(self.customer)
        for url in ('/psa/request-types/', f'/psa/request-types/{self.item.pk}/'):
            r = c.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r['Location'].startswith('/portal/'), r['Location'])
        before = ServiceCatalogItem.objects.get(pk=self.item.pk).published_version_id
        r = c.post(f'/psa/request-types/{self.item.pk}/', {'action': 'publish', 'schema_json': '[]'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('/portal/'), r['Location'])
        self.assertEqual(ServiceCatalogItem.objects.get(pk=self.item.pk).published_version_id, before)

    def test_starter_install_archive_restore_duplicate(self):
        c = _login(self.admin)
        r = c.get('/psa/request-types/starters/')
        self.assertContains(r, 'New employee')
        c.post('/psa/request-types/starters/', {'starter': 'new_phone'})
        phone = ServiceCatalogItem.objects.get(starter_key='new_phone')
        self.assertTrue(phone.is_draft)
        self.assertTrue(phone.draft_schema)
        c.post(f'/psa/request-types/{self.item.pk}/action/', {'action': 'archive'})
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_archived)
        self.assertNotContains(c.get('/psa/request-types/'), f'/psa/request-types/{self.item.pk}/"')
        c.post(f'/psa/request-types/{self.item.pk}/action/', {'action': 'restore'})
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_archived)
        c.post(f'/psa/request-types/{self.item.pk}/action/', {'action': 'copy_for_customer',
                                                               'organization_id': self.org.pk})
        copy = ServiceCatalogItem.objects.get(organization=self.org, based_on=self.item)
        self.assertTrue(copy.is_draft)
        self.assertEqual(copy.name, self.item.name)

    def test_routing_preview(self):
        c = _login(self.admin)
        r = c.get(f'/psa/request-types/{self.item.pk}/routing-preview/',
                  {'organization': self.org.pk, 'answers': 'work_mode=remote'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Routing preview')
        self.assertContains(r, 'work_mode=remote')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoutingOnAnswersTests(_Base):
    def setUp(self):
        super().setUp()
        from psa.routing.tests import _set_msp
        _set_msp(mode='auto', business_days=[])

    def _rule(self, name, org, priority, answers, queue):
        from psa.routing.tests import _rule
        return _rule(name, org, priority, {'services': [self.item.slug], 'answers': answers},
                     {'type': 'queue', 'queue_id': queue.pk})

    def test_answer_condition_routes_ticket(self):
        self._rule('Remote starters', None, 10,
                   [{'field': 'work_mode', 'op': 'equals', 'value': 'remote'}], self.escalations)
        t = self.submit()
        t.refresh_from_db()
        self.assertEqual(t.queue, self.escalations)
        t2 = self.submit(f_work_mode='office')
        t2.refresh_from_db()
        self.assertEqual(t2.queue, self.queue)  # request-type default stands

    def test_customer_rule_wins_over_global_rule(self):
        helpdesk = Queue.objects.exclude(pk__in=[self.queue.pk, self.escalations.pk]).first()
        self._rule('Global remote', None, 1,
                   [{'field': 'work_mode', 'op': 'equals', 'value': 'remote'}], self.escalations)
        self._rule('Acme remote', self.org, 90,
                   [{'field': 'work_mode', 'op': 'equals', 'value': 'remote'}], helpdesk)
        t = self.submit()
        t.refresh_from_db()
        self.assertEqual(t.queue, helpdesk)

    def test_rule_form_accepts_answer_conditions(self):
        from psa.routing.views import payload_from_post
        payload = payload_from_post(_qd({
            'name': 'x', 'priority': '10', 'services': [self.item.slug],
            'answer_field_0': 'work_mode', 'answer_op_0': 'equals', 'answer_value_0': 'remote',
            'answer_field_1': 'who', 'answer_op_1': 'bogus', 'answer_value_1': 'x',
            'destination_type': 'queue', 'destination_queue': str(self.queue.pk),
            'fallback_type': 'triage'}))
        answers = payload['conditions']['answers']
        self.assertEqual(answers[0], {'field': 'work_mode', 'op': 'equals', 'value': 'remote'})
        self.assertTrue(all(a['op'] in ('equals', 'not_equals', 'in', 'not_in', 'is_set',
                                        'not_set', 'contains') for a in answers))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketSideTests(_Base):
    def test_ticket_list_filter_by_request_type(self):
        t = self.submit()
        plain = Ticket.objects.create(organization=self.org, subject='Plain one', queue=self.queue,
                                      priority=t.priority, ticket_type=t.ticket_type, status=t.status)
        c = _login(self.admin)
        r = c.get('/psa/', {'request_type': self.item.pk})
        self.assertContains(r, t.ticket_number)
        self.assertNotContains(r, plain.ticket_number)
        r = c.get('/psa/', {'request_type': 'any'})
        self.assertContains(r, t.ticket_number)
        self.assertNotContains(r, plain.ticket_number)

    def test_report_and_csv(self):
        self.submit()
        self.submit(f_who='Bob')
        c = _login(self.admin)
        r = c.get('/psa/request-types/report/')
        self.assertContains(r, 'New employee')
        self.assertEqual(r.context['total'], 2)
        r = c.get('/psa/request-types/report/', {'format': 'csv'})
        self.assertEqual(r['Content-Type'], 'text/csv')
        self.assertIn('New employee,2,2,0', r.content.decode())
        r = c.get('/psa/request-types/report/', {'organization': self.other.pk})
        self.assertEqual(r.context['total'], 0)

    def test_staff_answer_edit_is_validated_and_audited(self):
        t = self.submit()
        c = _login(self.admin)
        url = f'/psa/t/{t.ticket_number}/request-answers/'
        self.assertContains(c.get(url), 'Edit request details')
        r = c.post(url, {'f_who': 'Jane', 'f_work_mode': 'moon'})
        t.refresh_from_db()
        self.assertEqual({a['key']: a['value'] for a in t.custom_fields['service_request']['answers']}
                         ['work_mode'], 'remote')
        r = c.post(url, {'f_who': 'Jane Doe', 'f_work_mode': 'office'})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        vals = {a['key']: a['value'] for a in t.custom_fields['service_request']['answers']}
        self.assertEqual(vals, {'who': 'Jane Doe', 'work_mode': 'office'})
        sub = ServiceRequestSubmission.objects.get(ticket=t)
        self.assertEqual({a['key']: a['value'] for a in sub.original_answers}['who'], 'Jane')
        self.assertEqual(sub.edited_by, self.admin)
        log = AuditLog.objects.filter(object_type='psa.Ticket', object_id=t.pk,
                                      description__startswith='Edited request answers').get()
        self.assertEqual({c['key'] for c in log.extra_data['changes']}, {'who', 'work_mode'})
        self.assertTrue(t.comments.filter(is_internal=True, body__startswith='Request details edited').exists())
        # Customers cannot use the staff edit page.
        self.assertIn(_login(self.customer).post(url, {'f_who': 'X'}).status_code, (302, 403, 404))
        t.refresh_from_db()
        self.assertEqual({a['key']: a['value'] for a in t.custom_fields['service_request']['answers']}
                         ['who'], 'Jane Doe')


class BackfillTests(TestCase):
    def test_existing_items_and_tickets_backfilled(self):
        import importlib
        from django.apps import apps
        _setup_seed()
        admin = User.objects.create_superuser('bf-admin', 'bf@msp.example', 'pw')
        org = Organization.objects.create(name='Backfill', slug='backfill')
        item = ServiceCatalogItem.objects.create(name='Old form', slug='old-form', form_schema=SCHEMA)
        q = Queue.objects.filter(is_active=True).first()
        from psa.models import TicketPriority, TicketStatus, TicketType
        t = Ticket.objects.create(
            organization=org, subject='Old', queue=q, priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.first(),
            custom_fields={'service_request': {
                'catalog_item_id': item.pk, 'catalog_item_name': 'Old form', 'submitted_by_id': admin.pk,
                'answers': [{'key': 'who', 'label': 'Their name', 'type': 'text', 'value': 'Ann',
                             'display': 'Ann'}]}})
        mod = importlib.import_module('psa.migrations.0085_request_form_versions_backfill')
        mod.forwards(apps, None)
        mod.forwards(apps, None)  # idempotent
        item.refresh_from_db()
        self.assertEqual(item.published_version.number, 1)
        sub = ServiceRequestSubmission.objects.get(ticket=t)
        self.assertEqual(sub.catalog_item, item)
        self.assertEqual(sub.answers[0]['value'], 'Ann')
        self.assertEqual(ServiceRequestSubmission.objects.filter(ticket=t).count(), 1)
