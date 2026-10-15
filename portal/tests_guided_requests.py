"""Guided service requests in the customer portal ("Request a service")."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

SCHEMA = [
    {'key': 'full_name', 'label': 'Full name', 'type': 'text', 'required': True},
    {'key': 'needs_laptop', 'label': 'Needs a laptop', 'type': 'checkbox'},
    {'key': 'laptop_type', 'label': 'Laptop type', 'type': 'select', 'required': True,
     'options': ['Standard', 'Mac'],
     'show_if': {'field': 'needs_laptop', 'equals': True}},
    {'key': 'apps', 'label': 'Apps', 'type': 'multiselect', 'options': ['Email', 'CRM']},
    {'key': 'start', 'label': 'Start date', 'type': 'date'},
    {'key': 'manager', 'label': 'Manager', 'type': 'user'},
    {'key': 'contact', 'label': 'Contact', 'type': 'email'},
]


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa.models import ClientPSASettings, Queue, ServiceCatalogItem, TicketPriority, TicketType
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_portal_customer_approvals_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='Acme Guided', slug='acme-guided')
        cls.other = Organization.objects.create(name='Other Guided', slug='other-guided')
        cls.third = Organization.objects.create(name='Third Guided', slug='third-guided')
        for o in (cls.org, cls.other):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True)
        cls.user = User.objects.create_user('gr-user', 'gr@x.com', 'pw', first_name='Gina')
        cls.member = Membership.objects.create(user=cls.user, organization=cls.org,
                                               role=Role.READONLY, is_active=True)
        cls.approver = User.objects.create_user('gr-approver', 'ap@x.com', 'pw')
        Membership.objects.create(user=cls.approver, organization=cls.org,
                                  role=Role.READONLY, is_active=True, is_org_admin=True)
        cls.staff = User.objects.create_user('gr-staff', 'st@x.com', 'pw',
                                             is_staff=True, is_superuser=True)
        cls.queue = Queue.objects.get(name='Procurement')
        cls.ttype = TicketType.objects.get(name='Onboarding')
        cls.prio = TicketPriority.objects.get(code='P2')
        cls.item = ServiceCatalogItem.objects.create(
            name='Onboard someone', slug='onboard-someone', portal_visible=True,
            category='People', form_schema=SCHEMA,
            default_subject='New starter — {{full_name}}',
            default_queue=cls.queue, default_type=cls.ttype, default_priority=cls.prio,
            expected_turnaround_hours=48,
        )

    def login(self, user=None):
        c = Client()
        c.force_login(user or self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AvailabilityTests(_Base):
    def test_default_available_to_all_customers(self):
        from psa.service_requests import portal_catalog_for
        self.assertIn(self.item, portal_catalog_for(self.org))
        self.assertIn(self.item, portal_catalog_for(self.other))

    def test_include_list_limits_customers(self):
        from psa.service_requests import portal_catalog_for
        self.item.include_organizations.set([self.other])
        self.assertNotIn(self.item, portal_catalog_for(self.org))
        self.assertIn(self.item, portal_catalog_for(self.other))
        self.assertFalse(self.item.is_available_to(self.org))
        self.assertTrue(self.item.is_available_to(self.other))

    def test_exclude_wins_over_include(self):
        from psa.service_requests import portal_catalog_for
        self.item.include_organizations.set([self.org, self.other])
        self.item.exclude_organizations.set([self.org])
        self.assertNotIn(self.item, portal_catalog_for(self.org))
        self.assertIn(self.item, portal_catalog_for(self.other))
        self.assertEqual(list(portal_catalog_for(self.other)).count(self.item), 1)

    def test_hidden_or_inactive_not_offered(self):
        from psa.service_requests import portal_catalog_for
        self.item.portal_visible = False
        self.item.save()
        self.assertNotIn(self.item, portal_catalog_for(self.org))

    def test_excluded_customer_gets_404_on_form(self):
        self.item.exclude_organizations.set([self.org])
        c = self.login()
        self.assertEqual(c.get('/portal/requests/onboard-someone/').status_code, 404)
        r = c.get('/portal/requests/')
        self.assertNotContains(r, 'Onboard someone')

    def test_catalog_grouped_by_category(self):
        c = self.login()
        r = c.get('/portal/requests/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'People')
        self.assertContains(r, 'Onboard someone')


class SchemaValidationTests(TestCase):
    def _post(self, data):
        from django.http import QueryDict
        q = QueryDict(mutable=True)
        for k, v in data.items():
            if isinstance(v, list):
                q.setlist(k, v)
            else:
                q[k] = v
        return q

    def test_conditional_required_only_when_visible(self):
        from psa.service_requests import validate_submission
        answers, errors = validate_submission(SCHEMA, self._post({'f_full_name': 'Ann'}))
        self.assertEqual(errors, [])
        self.assertNotIn('laptop_type', answers)
        answers, errors = validate_submission(SCHEMA, self._post(
            {'f_full_name': 'Ann', 'f_needs_laptop': 'on'}))
        self.assertTrue(any('Laptop type is required' in e for e in errors))

    def test_hidden_field_value_is_dropped(self):
        from psa.service_requests import validate_submission
        answers, errors = validate_submission(SCHEMA, self._post(
            {'f_full_name': 'Ann', 'f_laptop_type': 'Mac'}))
        self.assertEqual(errors, [])
        self.assertNotIn('laptop_type', answers)

    def test_unknown_field_rejected(self):
        from psa.service_requests import validate_submission
        answers, errors = validate_submission(SCHEMA, self._post(
            {'f_full_name': 'Ann', 'f_is_admin': '1'}))
        self.assertTrue(errors)
        self.assertEqual(answers, {})
        _, errors = validate_submission(SCHEMA, self._post(
            {'f_full_name': 'Ann', 'client_can_view': '0'}))
        self.assertTrue(errors)

    def test_values_validated_and_sanitized(self):
        from psa.service_requests import validate_submission
        _, errors = validate_submission(SCHEMA, self._post(
            {'f_full_name': 'Ann', 'f_apps': ['Email', 'Payroll']}))
        self.assertTrue(any('not one of the choices' in e for e in errors))
        _, errors = validate_submission(SCHEMA, self._post(
            {'f_full_name': 'Ann', 'f_contact': 'nope', 'f_start': '31/12/2026'}))
        self.assertEqual(len(errors), 2)
        answers, errors = validate_submission(SCHEMA, self._post(
            {'f_full_name': ' Ann\x00\x07 ' + 'x' * 900, 'f_apps': ['CRM', 'Email', 'CRM']}))
        self.assertEqual(errors, [])
        self.assertTrue(answers['full_name'].startswith('Ann'))
        self.assertNotIn('\x00', answers['full_name'])
        self.assertLessEqual(len(answers['full_name']), 500)
        self.assertEqual(answers['apps'], ['CRM', 'Email'])

    def test_in_condition_and_chained_hiding(self):
        from psa.service_requests import visible_keys
        schema = [
            {'key': 'a', 'label': 'A', 'type': 'select', 'options': ['x', 'y', 'z']},
            {'key': 'b', 'label': 'B', 'type': 'checkbox', 'show_if': {'field': 'a', 'in': ['x', 'y']}},
            {'key': 'c', 'label': 'C', 'type': 'text', 'show_if': {'field': 'b', 'equals': True}},
        ]
        self.assertEqual(visible_keys(schema, {'a': 'x', 'b': True}), {'a', 'b', 'c'})
        # b is hidden (a=z), so c is hidden even though b's stale value is True.
        self.assertEqual(visible_keys(schema, {'a': 'z', 'b': True}), {'a'})

    def test_normalize_schema_rejects_bad_definitions(self):
        from psa.service_requests import SchemaError, normalize_schema
        bad = [
            [{'key': 'Bad Key', 'label': 'x'}],
            [{'key': 'a', 'label': 'A', 'type': 'shell'}],
            [{'key': 'a', 'label': 'A', 'type': 'select'}],
            [{'key': 'a', 'label': 'A'}, {'key': 'a', 'label': 'Again'}],
            [{'key': 'a', 'label': 'A', 'show_if': {'field': 'later', 'equals': 'x'}},
             {'key': 'later', 'label': 'L'}],
        ]
        for schema in bad:
            with self.assertRaises(SchemaError):
                normalize_schema(schema)

    def test_legacy_fields_json_read_when_no_schema(self):
        from psa.models import ServiceCatalogItem
        item = ServiceCatalogItem(name='Legacy', fields_json=[
            {'key': 'username', 'label': 'Username', 'type': 'text', 'required': True},
            {'key': 'bogus', 'label': 'B', 'type': 'select'},  # no options → text
        ])
        schema = item.get_form_schema()
        self.assertEqual([f['key'] for f in schema], ['username', 'bogus'])
        self.assertEqual(schema[1]['type'], 'text')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SubmissionTests(_Base):
    def test_submission_creates_client_visible_routed_ticket_with_answers(self):
        from psa.models import Ticket
        c = self.login()
        r = c.post('/portal/requests/onboard-someone/', {
            'f_full_name': 'Ann Example', 'f_needs_laptop': 'on', 'f_laptop_type': 'Mac',
            'f_apps': ['Email', 'CRM'], 'f_start': '2026-11-02',
        })
        self.assertEqual(r.status_code, 302)
        t = Ticket.objects.get(organization=self.org, source='portal')
        self.assertTrue(t.client_can_view)
        self.assertEqual(t.visibility, 'client')
        self.assertEqual(t.queue, self.queue)
        self.assertEqual(t.ticket_type, self.ttype)
        self.assertEqual(t.priority, self.prio)
        self.assertEqual(t.subject, 'New starter — Ann Example')
        sr = t.custom_fields['service_request']
        self.assertEqual(sr['catalog_item_id'], self.item.pk)
        answers = {a['key']: a['value'] for a in sr['answers']}
        self.assertEqual(answers['laptop_type'], 'Mac')
        self.assertEqual(answers['apps'], ['Email', 'CRM'])
        self.assertIs(answers['needs_laptop'], True)
        self.assertIn('Laptop type: Mac', t.description)
        # Portal + staff views render the answers readably.
        r = c.get(f'/portal/t/{t.ticket_number}/')
        self.assertContains(r, 'Laptop type')
        self.assertContains(r, 'Email, CRM')
        self.assertContains(r, 'Expected turnaround')
        staff = self.login(self.staff)
        s = staff.session
        s['current_organization_id'] = self.org.pk
        s.save()
        r = staff.get(f'/psa/t/{t.ticket_number}/')
        self.assertContains(r, 'Service request: Onboard someone')
        self.assertContains(r, 'Email, CRM')

    def test_missing_conditional_required_rerenders_400(self):
        from psa.models import Ticket
        c = self.login()
        r = c.post('/portal/requests/onboard-someone/', {
            'f_full_name': 'Ann', 'f_needs_laptop': 'on'})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'Laptop type is required', status_code=400)
        self.assertFalse(Ticket.objects.filter(organization=self.org).exists())

    def test_unknown_field_rejected_by_view(self):
        from psa.models import Ticket
        c = self.login()
        r = c.post('/portal/requests/onboard-someone/', {
            'f_full_name': 'Ann', 'organization': str(self.other.pk)})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Ticket.objects.exists())

    def test_process_started_when_configured(self):
        from processes.models import Process, ProcessExecution
        from psa.models import Ticket
        proc = Process.objects.create(organization=self.third, title='Onboard runbook',
                                      is_global=True, created_by=self.staff)
        self.item.process_template = proc
        self.item.save()
        c = self.login()
        c.post('/portal/requests/onboard-someone/', {'f_full_name': 'Ann'})
        t = Ticket.objects.get(organization=self.org)
        ex = ProcessExecution.objects.get(native_psa_ticket=t)
        self.assertEqual(ex.process, proc)
        self.assertEqual(ex.organization, self.org)
        self.assertEqual(ex.assigned_to, self.staff)
        self.assertEqual(t.custom_fields['service_request']['process_execution_id'], ex.pk)
        # The launch note is internal and never shown in the portal.
        self.assertTrue(t.comments.filter(is_internal=True, body__icontains='Launched workflow').exists())
        r = c.get(f'/portal/t/{t.ticket_number}/')
        self.assertNotContains(r, 'Launched workflow')

    def test_approval_created_and_customer_approver_rules(self):
        from psa.models import PSAApproval, Ticket
        self.item.approval_policy = 'customer'
        self.item.save()
        c = self.login()
        c.post('/portal/requests/onboard-someone/', {'f_full_name': 'Ann'})
        t = Ticket.objects.get(organization=self.org)
        a = PSAApproval.objects.get(related_ticket=t)
        self.assertTrue(a.is_client_approval)
        self.assertEqual(a.status, 'pending')
        self.assertEqual(a.requested_by, self.user)
        r = c.get(f'/portal/t/{t.ticket_number}/')
        self.assertContains(r, 'Waiting for approval')
        # The requester can't approve their own request.
        c.post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'pending')
        # A customer org admin can.
        ap = self.login(self.approver)
        ap.post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve', 'comment': 'ok'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'approved')
        self.assertTrue(t.comments.filter(is_internal=False, body__icontains='approved').exists())
        r = c.get(f'/portal/t/{t.ticket_number}/')
        self.assertNotContains(r, 'Waiting for approval')

    def test_internal_comments_never_shown(self):
        from psa.models import Ticket, TicketComment
        c = self.login()
        c.post('/portal/requests/onboard-someone/', {'f_full_name': 'Ann'})
        t = Ticket.objects.get(organization=self.org)
        TicketComment.objects.create(ticket=t, author=self.staff, body='SECRET-INTERNAL-NOTE',
                                     is_internal=True)
        TicketComment.objects.create(ticket=t, author=self.staff, body='Which office?',
                                     is_internal=False)
        r = c.get(f'/portal/t/{t.ticket_number}/')
        self.assertNotContains(r, 'SECRET-INTERNAL-NOTE')
        self.assertContains(r, 'Which office?')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class KBSuggestionTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from docs.models import Document
        common = dict(is_published=True, is_client_visible=True, body='laptop steps')
        Document.objects.create(organization=cls.org, title='Onboard laptop guide',
                                slug='ok-own', **common)
        Document.objects.create(organization=None, is_global=True, title='Onboard global FAQ',
                                slug='ok-global', **common)
        Document.objects.create(organization=cls.other, title='Onboard OTHER-CUSTOMER',
                                slug='bad-other', **common)
        Document.objects.create(organization=cls.org, title='Onboard INTERNAL-ONLY',
                                slug='bad-internal', is_published=True,
                                is_client_visible=False, body='x')
        Document.objects.create(organization=cls.org, title='Onboard DRAFT-DOC',
                                slug='bad-draft', is_draft=True, **common)
        Document.objects.create(organization=cls.org, title='Onboard UNPUBLISHED',
                                slug='bad-unpub', is_published=False,
                                is_client_visible=True, body='x')
        Document.objects.create(organization=cls.org, title='Onboard ARCHIVED',
                                slug='bad-arch', is_archived=True, **common)

    def _titles(self, r):
        return [d.title for d in r.context['kb_suggestions']]

    def test_suggestions_only_visible_docs_for_customer(self):
        c = self.login()
        r = c.get('/portal/requests/onboard-someone/')
        titles = self._titles(r)
        self.assertIn('Onboard laptop guide', titles)
        self.assertIn('Onboard global FAQ', titles)
        for bad in ('OTHER-CUSTOMER', 'INTERNAL-ONLY', 'DRAFT-DOC', 'UNPUBLISHED', 'ARCHIVED'):
            self.assertNotContains(r, bad)

    def test_live_suggest_endpoint_same_rules(self):
        c = self.login()
        r = c.get('/portal/requests/onboard-someone/kb/?q=onboard laptop')
        self.assertEqual(r.status_code, 200)
        titles = [a['title'] for a in r.json()['articles']]
        self.assertIn('Onboard laptop guide', titles)
        self.assertFalse([t for t in titles if any(
            b in t for b in ('OTHER', 'INTERNAL', 'DRAFT', 'UNPUBLISHED', 'ARCHIVED'))])

    def test_portal_kb_list_excludes_drafts(self):
        c = self.login()
        r = c.get('/portal/kb/')
        self.assertNotContains(r, 'DRAFT-DOC')
        self.assertEqual(c.get('/portal/kb/bad-draft/').status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProgressPhraseTests(_Base):
    def _ticket(self, status_slug, **kw):
        from psa.models import Ticket, TicketStatus
        return Ticket.objects.create(
            organization=self.org, subject='t', queue=self.queue, priority=self.prio,
            ticket_type=self.ttype, status=TicketStatus.objects.get(slug=status_slug),
            client_can_view=True, visibility='client', **kw)

    def test_default_mapping(self):
        from portal.progress import customer_progress
        self.assertEqual(customer_progress(self._ticket('new'))['label'], 'Received')
        self.assertEqual(customer_progress(self._ticket('assigned'))['label'], 'In progress')
        self.assertEqual(customer_progress(self._ticket('waiting-on-client'))['label'], 'Waiting for you')
        self.assertEqual(customer_progress(self._ticket('waiting-on-vendor'))['label'], 'In progress')
        self.assertEqual(customer_progress(self._ticket('resolved'))['label'], 'Resolved')
        self.assertEqual(customer_progress(self._ticket('cancelled'))['label'], 'Resolved')

    def test_pending_approval_overrides_until_resolved(self):
        from portal.progress import customer_progress
        from psa.models import PSAApproval
        t = self._ticket('in-progress')
        PSAApproval.objects.create(organization=self.org, kind='other', object_type='x',
                                   object_id=1, related_ticket=t, is_client_approval=True)
        self.assertEqual(customer_progress(t)['label'], 'Waiting for approval')
        r = self._ticket('closed')
        PSAApproval.objects.create(organization=self.org, kind='other', object_type='x',
                                   object_id=2, related_ticket=r, is_client_approval=True)
        self.assertEqual(customer_progress(r)['label'], 'Resolved')

    def test_configured_override(self):
        from portal.models import PortalStatusPhrase
        from portal.progress import customer_progress
        from psa.models import TicketStatus
        PortalStatusPhrase.objects.create(status=TicketStatus.objects.get(slug='scheduled'),
                                          phrase='waiting_on_customer')
        self.assertEqual(customer_progress(self._ticket('scheduled'))['label'], 'Waiting for you')

    def test_portal_pages_show_phrase_and_waiting_question(self):
        from psa.models import TicketComment
        t = self._ticket('waiting-on-client')
        TicketComment.objects.create(ticket=t, author=self.staff, body='Which office are they in?',
                                     is_internal=False)
        c = self.login()
        r = c.get('/portal/')
        self.assertContains(r, 'Waiting for you')
        self.assertNotContains(r, 'Waiting on Client')
        r = c.get(f'/portal/t/{t.ticket_number}/')
        self.assertContains(r, 'We asked:')
        self.assertContains(r, 'Which office are they in?')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OptOutAndSwitcherTests(_Base):
    def test_psa_opt_out_404s_ticket_and_request_features(self):
        from psa.models import ClientPSASettings, Ticket, TicketStatus
        t = Ticket.objects.create(
            organization=self.org, subject='t', queue=self.queue, priority=self.prio,
            ticket_type=self.ttype, status=TicketStatus.objects.get(slug='new'),
            client_can_view=True, visibility='client')
        ClientPSASettings.objects.filter(organization=self.org).update(enabled=False)
        c = self.login()
        for url in ('/portal/new/', '/portal/requests/', '/portal/requests/onboard-someone/',
                    f'/portal/t/{t.ticket_number}/', '/portal/approvals/'):
            self.assertEqual(c.get(url).status_code, 404, url)
        self.assertEqual(c.post('/portal/requests/onboard-someone/',
                                {'f_full_name': 'x'}).status_code, 404)
        self.assertEqual(c.post(f'/portal/t/{t.ticket_number}/reply/',
                                {'body': 'x'}).status_code, 404)
        r = c.get('/portal/')
        self.assertRedirects(r, '/portal/kb/', fetch_redirect_response=False)
        self.assertEqual(c.get('/portal/kb/').status_code, 200)

    def test_switcher_changes_active_customer(self):
        from accounts.models import Membership, Role
        Membership.objects.create(user=self.user, organization=self.other,
                                  role=Role.READONLY, is_active=True)
        c = self.login()
        r = c.get('/portal/kb/')
        self.assertContains(r, 'portal-customer-switcher')
        self.assertEqual(r.context['organization'], self.org)  # alphabetical first
        r = c.post('/portal/switch/', {'organization_id': self.other.pk})
        self.assertEqual(r.status_code, 302)
        r = c.get('/portal/kb/')
        self.assertEqual(r.context['organization'], self.other)

    def test_switcher_rejects_customer_user_does_not_belong_to(self):
        from accounts.models import Membership, Role
        from core.models import Organization
        from psa.models import ClientPSASettings
        Membership.objects.create(user=self.user, organization=self.other,
                                  role=Role.READONLY, is_active=True)
        stranger = Organization.objects.create(name='Stranger Co', slug='stranger-co')
        ClientPSASettings.objects.create(organization=stranger, portal_enabled=True)
        c = self.login()
        r = c.post('/portal/switch/', {'organization_id': stranger.pk})
        self.assertEqual(r.status_code, 404)
        # Forcing the session key doesn't help either.
        s = c.session
        s['portal_org_id'] = stranger.pk
        s.save()
        r = c.get('/portal/kb/')
        self.assertEqual(r.context['organization'], self.org)
        # An inactive membership doesn't count.
        Membership.objects.filter(user=self.user, organization=self.other).update(is_active=False)
        self.assertEqual(c.post('/portal/switch/', {'organization_id': self.other.pk}).status_code, 404)


class SeedCommandTests(TestCase):
    def test_seed_creates_items_with_conditional_fields(self):
        from psa.models import ServiceCatalogItem
        call_command('psa_seed_defaults', verbosity=0)
        call_command('psa_seed_portal_requests', stdout=open('/dev/null', 'w'))
        names = set(ServiceCatalogItem.objects.filter(portal_visible=True)
                    .values_list('name', flat=True))
        for n in ('Employee onboarding', 'Employee offboarding', 'Access request',
                  'New equipment', 'Application change'):
            self.assertIn(n, names)
            item = ServiceCatalogItem.objects.get(name=n)
            self.assertTrue(any(f.get('show_if') for f in item.form_schema), n)
            self.assertIsNotNone(item.default_queue)
            self.assertTrue(item.turnaround_display)
        # Idempotent.
        call_command('psa_seed_portal_requests', stdout=open('/dev/null', 'w'))
        self.assertEqual(ServiceCatalogItem.objects.filter(slug__startswith='portal-').count(), 5)
