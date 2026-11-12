"""Portal request types with dynamic forms: the "What do you need help
with?" picker, form versions, conditions, lookups, idempotent submission,
approvals and the general-ticket path that stays available."""
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

SCHEMA = [
    {'key': 'who', 'label': 'Their name', 'type': 'text', 'required': True},
    {'key': 'work_mode', 'label': 'Where will they work?', 'type': 'radio', 'required': True,
     'options': [{'value': 'office', 'label': 'In the office'},
                 {'value': 'remote', 'label': 'Remote'}]},
    {'key': 'ship_head', 'label': 'Shipping', 'type': 'heading',
     'show_if': {'field': 'work_mode', 'op': 'equals', 'value': 'remote'}},
    {'key': 'ship_to', 'label': 'Shipping address', 'type': 'textarea', 'required': True},
    {'key': 'more_head', 'label': 'Anything else', 'type': 'heading'},
    {'key': 'notes', 'label': 'Anything else', 'type': 'textarea',
     'required_if': {'field': 'work_mode', 'op': 'equals', 'value': 'office'}},
    {'key': 'impact', 'label': 'How urgent is it?', 'type': 'select', 'maps_to': 'urgency',
     'options': [{'value': 'low', 'label': 'Low'}, {'value': 'critical', 'label': 'Critical'}]},
]


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa import request_forms
        from psa.models import ClientPSASettings, Queue, ServiceCatalogItem, TicketPriority
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_portal_customer_approvals_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='Acme Forms', slug='acme-forms')
        cls.other = Organization.objects.create(name='Other Forms', slug='other-forms')
        for o in (cls.org, cls.other):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True)
        cls.user = User.objects.create_user('rf-user', 'user@acme.example', 'pw', first_name='Uma')
        cls.member = Membership.objects.create(user=cls.user, organization=cls.org,
                                               role=Role.READONLY, is_active=True)
        cls.admin_user = User.objects.create_user('rf-admin', 'admin@acme.example', 'pw')
        cls.admin_member = Membership.objects.create(user=cls.admin_user, organization=cls.org,
                                                     role=Role.READONLY, is_active=True,
                                                     is_org_admin=True)
        cls.other_user = User.objects.create_user('rf-other', 'o@other.example', 'pw')
        Membership.objects.create(user=cls.other_user, organization=cls.other,
                                  role=Role.READONLY, is_active=True)
        cls.staff = User.objects.create_superuser('rf-staff', 'st@msp.example', 'pw')
        cls.p3 = TicketPriority.objects.order_by('sort_order').last()
        cls.item = ServiceCatalogItem.objects.create(
            name='New employee', slug='new-employee', portal_visible=True, category='People',
            default_subject='New user: {{who}} — starts {{start}}',
            default_queue=Queue.objects.filter(is_active=True).first(),
            default_priority=cls.p3, expected_turnaround_hours=48,
        )
        request_forms.publish(cls.item, cls.staff, schema=SCHEMA)

    def setUp(self):
        super().setUp()
        # Portal submissions are rate-limited per user in the cache; start
        # each test with a clean count.
        from django.core.cache import cache
        cache.clear()

    def post_data(self, **kw):
        data = {'f_who': 'Jane Smith', 'f_work_mode': 'remote', 'f_ship_to': '1 Main St',
                'f_notes': '', 'f_impact': 'low', '_form_version': '1',
                '_submission_token': 'tok_' + 'a' * 28}
        data.update(kw)
        return {k: v for k, v in data.items() if v is not None}


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PickerTests(_Base):
    def test_new_ticket_shows_picker_with_general_option(self):
        r = _login(self.user).get('/portal/new/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'What do you need help with?')
        self.assertContains(r, 'New employee')
        self.assertContains(r, 'id="general-support-link"')
        # The plain form is still one click away.
        r = _login(self.user).get('/portal/new/?form=general')
        self.assertContains(r, 'name="subject"')

    def test_audience_and_lifecycle_filter(self):
        from psa.models import ServiceCatalogItem
        from psa.service_requests import portal_catalog_for
        admin_only = ServiceCatalogItem.objects.create(
            name='Change billing contact', slug='billing-contact', portal_visible=True,
            portal_audience=ServiceCatalogItem.AUDIENCE_ORG_ADMINS,
            form_schema=[{'key': 'x', 'label': 'X', 'type': 'text'}])
        draft = ServiceCatalogItem.objects.create(
            name='Draft type', slug='draft-type', portal_visible=True,
            lifecycle=ServiceCatalogItem.LIFECYCLE_DRAFT)
        archived = ServiceCatalogItem.objects.create(
            name='Old type', slug='old-type', portal_visible=True,
            lifecycle=ServiceCatalogItem.LIFECYCLE_ARCHIVED)
        normal = list(portal_catalog_for(self.org, self.member))
        admin = list(portal_catalog_for(self.org, self.admin_member))
        self.assertIn(self.item, normal)
        self.assertNotIn(admin_only, normal)
        self.assertIn(admin_only, admin)
        for hidden in (draft, archived):
            self.assertNotIn(hidden, admin)
        c = _login(self.user)
        self.assertEqual(c.get('/portal/requests/billing-contact/').status_code, 404)
        self.assertEqual(c.get('/portal/requests/draft-type/').status_code, 404)
        self.assertEqual(c.get('/portal/requests/old-type/').status_code, 404)
        self.assertEqual(_login(self.admin_user).get('/portal/requests/billing-contact/').status_code, 200)

    def test_customer_copy_replaces_shared_type_only_for_that_customer(self):
        from psa import request_forms
        from psa.service_requests import portal_catalog_for
        copy = request_forms.duplicate(self.item, self.staff, organization=self.org)
        # A draft copy changes nothing yet.
        self.assertIn(self.item, portal_catalog_for(self.org))
        self.assertNotIn(copy, portal_catalog_for(self.org))
        request_forms.publish(copy, self.staff, schema=SCHEMA[:2])
        acme = list(portal_catalog_for(self.org))
        self.assertIn(copy, acme)
        self.assertNotIn(self.item, acme)
        other = list(portal_catalog_for(self.other))
        self.assertIn(self.item, other)
        self.assertNotIn(copy, other)
        self.assertEqual(_login(self.other_user).get(f'/portal/requests/{copy.slug}/').status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SubmissionTests(_Base):
    def test_submit_creates_one_ticket_with_answers_and_snapshot(self):
        from psa.models import ServiceRequestSubmission, Ticket
        c = _login(self.user)
        r = c.get('/portal/requests/new-employee/')
        self.assertContains(r, 'name="_form_version" value="1"')
        self.assertContains(r, 'not a guaranteed commitment')
        self.assertContains(r, 'id="sr-schema"')
        r = c.post('/portal/requests/new-employee/', self.post_data())
        self.assertEqual(r.status_code, 302, r.content[:500])
        t = Ticket.objects.get(organization=self.org, source='portal')
        self.assertEqual(t.subject, 'New user: Jane Smith')
        self.assertIn('Shipping address: 1 Main St', t.description)
        sub = ServiceRequestSubmission.objects.get(ticket=t)
        self.assertEqual(sub.form_version_number, 1)
        self.assertEqual(sub.catalog_item, self.item)
        self.assertEqual(sub.organization, self.org)
        self.assertEqual(sub.original_answers, sub.answers)
        self.assertEqual([f['key'] for f in sub.schema_snapshot], [f['key'] for f in SCHEMA])
        rec = t.custom_fields['service_request']
        self.assertEqual(rec['form_version'], 1)
        self.assertEqual(rec['submission_id'], sub.pk)
        # The customer sees their own answers on the ticket.
        r = c.get(f'/portal/t/{t.ticket_number}/')
        self.assertContains(r, 'Request details')
        self.assertContains(r, '1 Main St')

    def test_double_post_with_same_token_creates_one_ticket(self):
        from psa.models import Ticket
        c = _login(self.user)
        r1 = c.post('/portal/requests/new-employee/', self.post_data())
        r2 = c.post('/portal/requests/new-employee/', self.post_data())
        self.assertEqual(Ticket.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(r1['Location'], r2['Location'])

    def test_token_from_another_user_is_not_reused(self):
        from psa.models import Ticket
        _login(self.user).post('/portal/requests/new-employee/', self.post_data())
        r = _login(self.admin_user).post('/portal/requests/new-employee/', self.post_data())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Ticket.objects.filter(organization=self.org).count(), 2)

    def test_hidden_section_not_required_and_dropped(self):
        from psa.models import Ticket
        c = _login(self.user)
        # Office: shipping section hidden (its question too); notes now required.
        r = c.post('/portal/requests/new-employee/', self.post_data(f_work_mode='office',
                                                                   f_ship_to='ignored'))
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'Anything else is required', status_code=400)
        self.assertNotContains(r, 'Shipping address is required', status_code=400)
        r = c.post('/portal/requests/new-employee/', self.post_data(
            f_work_mode='office', f_ship_to='ignored', f_notes='Desk 4'))
        self.assertEqual(r.status_code, 302)
        rec = Ticket.objects.get(organization=self.org).custom_fields['service_request']
        keys = [a['key'] for a in rec['answers']]
        self.assertNotIn('ship_to', keys)
        self.assertIn('notes', keys)
        # Remote: the shipping address is required.
        r = c.post('/portal/requests/new-employee/', self.post_data(
            f_ship_to='', _submission_token='tok_' + 'b' * 28))
        self.assertContains(r, 'Shipping address is required', status_code=400)

    def test_unknown_field_and_bad_option_rejected(self):
        c = _login(self.user)
        r = c.post('/portal/requests/new-employee/', self.post_data(f_priority='P1'))
        self.assertContains(r, 'unexpected fields', status_code=400)
        r = c.post('/portal/requests/new-employee/', self.post_data(f_work_mode='moon'))
        self.assertContains(r, 'not one of the choices', status_code=400)

    def test_urgency_recorded_but_priority_unchanged(self):
        from psa.models import Ticket
        r = _login(self.user).post('/portal/requests/new-employee/', self.post_data(f_impact='critical'))
        self.assertEqual(r.status_code, 302)
        t = Ticket.objects.get(organization=self.org)
        self.assertEqual(t.urgency, 'critical')
        self.assertEqual(t.priority, self.p3)

    def test_republished_form_keeps_answers_and_asks_to_check(self):
        from psa import request_forms
        from psa.models import Ticket
        request_forms.publish(self.item, self.staff, schema=SCHEMA + [
            {'key': 'laptop', 'label': 'Laptop needed?', 'type': 'checkbox'}])
        r = _login(self.user).post('/portal/requests/new-employee/', self.post_data())
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, 'This form was updated while you were filling it in', status_code=409)
        self.assertContains(r, 'value="Jane Smith"', status_code=409)
        self.assertContains(r, 'name="_form_version" value="2"', status_code=409)
        self.assertFalse(Ticket.objects.filter(organization=self.org).exists())

    def test_form_edit_and_archive_keep_history(self):
        from psa import request_forms
        from psa.models import ServiceRequestSubmission, Ticket
        _login(self.user).post('/portal/requests/new-employee/', self.post_data())
        t = Ticket.objects.get(organization=self.org)
        request_forms.publish(self.item, self.staff, schema=[
            {'key': 'other', 'label': 'Something else', 'type': 'text'}])
        request_forms.archive(self.item, self.staff)
        sub = ServiceRequestSubmission.objects.get(ticket=t)
        self.assertEqual(sub.form_version.number, 1)
        self.assertEqual(sub.form_version.schema[0]['key'], 'who')
        self.assertIn('ship_to', [f['key'] for f in sub.schema_snapshot])
        t.refresh_from_db()
        self.assertIn('ship_to', [a['key'] for a in t.custom_fields['service_request']['answers']])
        r = _login(self.user).get(f'/portal/t/{t.ticket_number}/')
        self.assertContains(r, '1 Main St')
        self.assertEqual(_login(self.user).get('/portal/requests/new-employee/').status_code, 404)

    def test_other_member_does_not_see_answers(self):
        from accounts.models import Membership, Role
        from psa.models import Ticket
        _login(self.user).post('/portal/requests/new-employee/', self.post_data())
        t = Ticket.objects.get(organization=self.org)
        peer = User.objects.create_user('rf-peer', 'peer@acme.example', 'pw')
        Membership.objects.create(user=peer, organization=self.org, role=Role.READONLY, is_active=True)
        r = _login(peer).get(f'/portal/t/{t.ticket_number}/')
        self.assertEqual(r.status_code, 200)  # org tickets are visible to the customer's users
        self.assertNotContains(r, '1 Main St')
        self.assertContains(r, 'Request details')

    def test_secret_like_questions_cannot_be_published(self):
        from psa import request_forms
        from psa.service_requests import SchemaError
        for label in ('Current password', 'Their PIN', 'MFA code'):
            with self.assertRaises(SchemaError):
                request_forms.publish(self.item, self.staff,
                                      schema=[{'key': 'x', 'label': label, 'type': 'text'}])

    def test_sensitive_answer_kept_out_of_description(self):
        from psa import request_forms
        from psa.models import Ticket
        request_forms.publish(self.item, self.staff, schema=[
            {'key': 'who', 'label': 'Their name', 'type': 'text', 'required': True},
            {'key': 'salary_band', 'label': 'Salary band', 'type': 'text', 'sensitive': True}])
        r = _login(self.user).post('/portal/requests/new-employee/', {
            'f_who': 'Jane', 'f_salary_band': 'Band C', '_form_version': '2',
            '_submission_token': 'tok_' + 'c' * 28})
        self.assertEqual(r.status_code, 302)
        t = Ticket.objects.get(organization=self.org)
        self.assertNotIn('Band C', t.description)
        self.assertIn('Band C', str(t.custom_fields['service_request']['answers']))

    def test_file_upload_saved_as_attachment(self):
        from psa import request_forms
        from psa.models import Ticket, TicketAttachment
        request_forms.publish(self.item, self.staff, schema=[
            {'key': 'shot', 'label': 'Screenshot', 'type': 'file', 'max_files': 2}])
        png = SimpleUploadedFile('screen.png', b'\x89PNG\r\n\x1a\n' + b'\0' * 64, content_type='image/png')
        r = _login(self.user).post('/portal/requests/new-employee/', {
            'f_shot': png, '_form_version': '2', '_submission_token': 'tok_' + 'd' * 28})
        self.assertEqual(r.status_code, 302, r.content[:400])
        t = Ticket.objects.get(organization=self.org)
        self.assertEqual(TicketAttachment.objects.filter(ticket=t).count(), 1)
        svg = SimpleUploadedFile('x.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>',
                                 content_type='image/svg+xml')
        r = _login(self.user).post('/portal/requests/new-employee/', {
            'f_shot': svg, '_form_version': '2', '_submission_token': 'tok_' + 'e' * 28})
        self.assertContains(r, 'SVG', status_code=400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LookupTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from assets.models import Asset, Contact
        from locations.models import Location
        from psa import request_forms
        from psa.models import ServiceCatalogItem
        cls.me = Contact.objects.create(organization=cls.org, first_name='Uma', last_name='User',
                                        email='user@acme.example')
        cls.colleague = Contact.objects.create(organization=cls.org, first_name='Carl', last_name='Colleague')
        cls.foreign = Contact.objects.create(organization=cls.other, first_name='Carla', last_name='Foreign')
        cls.my_laptop = Asset.objects.create(organization=cls.org, name='UMA-LAPTOP', primary_contact=cls.me)
        cls.server = Asset.objects.create(organization=cls.org, name='ACME-SRV1')
        cls.foreign_asset = Asset.objects.create(organization=cls.other, name='OTHER-SRV')
        cls.site = Location.objects.create(organization=cls.org, name='Acme HQ')
        cls.foreign_site = Location.objects.create(organization=cls.other, name='Other HQ')
        cls.lk = ServiceCatalogItem.objects.create(name='Device problem', slug='device-problem',
                                                   portal_visible=True)
        request_forms.publish(cls.lk, cls.staff, schema=[
            {'key': 'person', 'label': 'Who', 'type': 'contact'},
            {'key': 'device', 'label': 'Device', 'type': 'asset'},
            {'key': 'site', 'label': 'Site', 'type': 'location'}])

    def _post(self, user, **kw):
        data = {'_form_version': '1', '_submission_token': 'tok_' + str(len(kw)) + 'f' * 27}
        data.update(kw)
        return _login(user).post('/portal/requests/device-problem/', data)

    def test_forged_cross_org_ids_rejected(self):
        for kw in ({'f_person': str(self.foreign.pk)}, {'f_device': str(self.foreign_asset.pk)},
                   {'f_site': str(self.foreign_site.pk)}):
            r = self._post(self.admin_user, **kw)
            self.assertContains(r, 'pick one of the listed entries', status_code=400)

    def test_non_admin_limited_to_own_records(self):
        r = self._post(self.user, f_person=str(self.colleague.pk))
        self.assertEqual(r.status_code, 400)
        r = self._post(self.user, f_device=str(self.server.pk))
        self.assertEqual(r.status_code, 400)
        r = self._post(self.user, f_person=str(self.me.pk), f_device=str(self.my_laptop.pk),
                       f_site=str(self.site.pk))
        self.assertEqual(r.status_code, 302, r.content[:400])
        from psa.models import Ticket
        rows = {a['key']: a for a in Ticket.objects.get(organization=self.org)
                .custom_fields['service_request']['answers']}
        self.assertEqual(rows['device']['value']['id'], self.my_laptop.pk)
        self.assertEqual(rows['site']['display'], 'Acme HQ')

    def test_free_text_fallback(self):
        r = self._post(self.user, f_device='', f_device__text='The printer by reception')
        self.assertEqual(r.status_code, 302)

    def test_lookup_endpoint_is_scoped(self):
        url = '/portal/requests/device-problem/lookup/person/'
        r = _login(self.admin_user).get(url, {'q': 'Car'})
        labels = [x['label'] for x in r.json()['results']]
        self.assertIn('Carl Colleague', labels)
        self.assertNotIn('Carla Foreign', labels)
        self.assertEqual(_login(self.admin_user).get(url, {'q': 'C'}).json()['results'], [])
        r = _login(self.user).get(url, {'q': 'Car'})
        self.assertEqual([x['label'] for x in r.json()['results']], ['Uma User'])
        r = _login(self.admin_user).get('/portal/requests/device-problem/lookup/device/', {'q': 'SRV'})
        self.assertEqual([x['label'] for x in r.json()['results']], ['ACME-SRV1'])
        self.assertNotIn('email', str(r.json()))
        self.assertEqual(_login(self.admin_user).get(
            '/portal/requests/device-problem/lookup/nope/').status_code, 404)
        self.assertEqual(_login(self.other_user).get(url, {'q': 'Car'}).status_code, 200)
        r = _login(self.other_user).get(url, {'q': 'Carl'})
        self.assertNotIn('Carl Colleague', str(r.json()))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ApprovalTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from processes.models import Process
        from psa.models import ServiceCatalogItem
        cls.item.approval_policy = ServiceCatalogItem.APPROVAL_CUSTOMER
        cls.process = Process.objects.create(title='Onboarding steps', slug='onboarding-steps',
                                             is_global=True, organization=cls.org)
        cls.item.process_template = cls.process
        cls.item.save()

    def _submit(self, user=None):
        from psa.models import Ticket
        r = _login(user or self.user).post('/portal/requests/new-employee/', self.post_data())
        self.assertEqual(r.status_code, 302, r.content[:400])
        return Ticket.objects.filter(organization=self.org).latest('pk')

    def test_pending_approval_defers_workflow_and_email_has_no_answers(self):
        mail.outbox = []
        t = self._submit()
        rec = t.custom_fields['service_request']
        self.assertEqual(rec['approval_status'], 'pending')
        self.assertTrue(rec.get('process_deferred'))
        self.assertNotIn('process_execution_id', rec)
        approver_mail = [m for m in mail.outbox if 'admin@acme.example' in m.to]
        self.assertTrue(approver_mail)
        self.assertNotIn('1 Main St', approver_mail[0].body)
        self.assertNotIn('Jane Smith', approver_mail[0].body)

    def test_requester_cannot_approve_own_request(self):
        from psa.models import PSAApproval
        from accounts.models import Membership
        Membership.objects.filter(pk=self.member.pk).update(is_org_admin=True)
        t = self._submit()
        a = PSAApproval.objects.get(related_ticket=t)
        _login(self.user).post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'pending')

    def test_self_approval_allowed_by_policy(self):
        from psa.models import PSAApproval
        self.item.approval_allow_self = True
        self.item.save()
        t = self._submit(self.admin_user)
        a = PSAApproval.objects.get(related_ticket=t)
        _login(self.admin_user).post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'approved')

    def test_approval_starts_workflow_and_tells_requester(self):
        from psa.models import PSAApproval
        t = self._submit()
        a = PSAApproval.objects.get(related_ticket=t)
        mail.outbox = []
        with mock.patch('psa.service_requests._start_process', return_value=99) as start:
            _login(self.admin_user).post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve'})
        start.assert_called_once()
        t.refresh_from_db()
        rec = t.custom_fields['service_request']
        self.assertEqual(rec['approval_status'], 'approved')
        self.assertEqual(rec['process_execution_id'], 99)
        to_requester = [m for m in mail.outbox if 'user@acme.example' in m.to]
        self.assertTrue(to_requester)
        self.assertIn('approved', to_requester[0].subject)
        self.assertNotIn('1 Main St', to_requester[0].body)

    def test_denied_request_does_not_start_workflow(self):
        from psa.models import PSAApproval
        t = self._submit()
        a = PSAApproval.objects.get(related_ticket=t)
        with mock.patch('psa.service_requests._start_process') as start:
            _login(self.admin_user).post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'deny'})
        start.assert_not_called()
        t.refresh_from_db()
        self.assertEqual(t.custom_fields['service_request']['approval_status'], 'denied')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GeneralTicketTests(_Base):
    def test_general_ticket_still_works_with_attachment(self):
        from psa.models import Ticket, TicketAttachment
        f = SimpleUploadedFile('notes.txt', b'hello there', content_type='text/plain')
        r = _login(self.user).post('/portal/new/', {
            'subject': 'Printer jammed', 'description': 'Paper stuck', 'attachments': f})
        self.assertEqual(r.status_code, 302, r.content[:400])
        t = Ticket.objects.get(subject='Printer jammed')
        self.assertNotIn('service_request', t.custom_fields or {})
        self.assertEqual(TicketAttachment.objects.filter(ticket=t).count(), 1)

    def test_starter_general_support_used_for_general_card(self):
        from psa import request_forms, request_starters
        item = request_starters.install('general_support', self.staff)
        request_forms.publish(item, self.staff)
        r = _login(self.user).get('/portal/new/')
        self.assertContains(r, f'/portal/requests/{item.slug}/')
