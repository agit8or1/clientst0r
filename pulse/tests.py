"""Pulse checks: models, audience selection, sending, scheduled sends, the
token / portal answer pages, staff-only management and customer isolation."""
import io
from datetime import date, datetime, timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.mail import get_connection
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from assets.models import Contact
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from pulse import audience, results, sending
from pulse.models import (PulseCheck, PulseOptOut, PulseQuestion, PulseResponse,
                          PulseSend)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _make_msp_tech(user):
    from accounts.models import UserProfile, UserType
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.save()
    return user


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


def _locmem(*_a, **_kw):
    return get_connection('django.core.mail.backends.locmem.EmailBackend')


def _set(**flags):
    s = SystemSetting.get_settings()
    for k, v in flags.items():
        setattr(s, k, v)
    s.save()


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from psa.models import ClientPSASettings
        _set(pulse_enabled=True, psa_enabled=True)
        cls.acme = Organization.objects.create(name='Acme', slug='acme')
        cls.beta = Organization.objects.create(name='Beta', slug='beta')
        cls.internal = Organization.objects.create(name='Our MSP', slug='msp', organization_type='internal')
        cls.gone = Organization.objects.create(name='Gone Co', slug='gone', is_active=False)
        for o in (cls.acme, cls.beta):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True)

        def member(username, org, role=Role.READONLY, **kw):
            u = User.objects.create_user(username, f'{username}@{org.slug}.example', 'pw')
            m = Membership.objects.create(user=u, organization=org, role=role, is_active=True, **kw)
            return u, m

        cls.owner, cls.owner_m = member('owner', cls.acme, Role.OWNER)
        cls.admin, _ = member('admin', cls.acme, Role.ADMIN)
        cls.editor, _ = member('editor', cls.acme, Role.EDITOR)
        cls.reader, cls.reader_m = member('reader', cls.acme, Role.READONLY)
        cls.finance_role = RoleTemplate.objects.create(name='Finance')
        cls.reader_m.additional_roles.add(cls.finance_role)
        cls.beta_owner, _ = member('bowner', cls.beta, Role.OWNER)
        cls.internal_user, _ = member('inside', cls.internal, Role.OWNER)
        cls.gone_user, _ = member('goneuser', cls.gone, Role.OWNER)
        cls.noemail = User.objects.create_user('noemail', '', 'pw')
        Membership.objects.create(user=cls.noemail, organization=cls.acme, role=Role.OWNER)
        # MSP technician who also holds a membership at a client.
        cls.tech = _make_msp_tech(User.objects.create_user('tech', 'tech@msp.example', 'pw'))
        Membership.objects.create(user=cls.tech, organization=cls.acme, role=Role.ADMIN)
        cls.su = User.objects.create_superuser('root', 'root@msp.example', 'pw')
        cls.contact = Contact.objects.create(organization=cls.acme, first_name='Carl', last_name='Contact',
                                             email='carl@acme.example')
        Contact.objects.create(organization=cls.acme, first_name='No', last_name='Mail', email='')
        # Same address as a portal user: the user wins.
        Contact.objects.create(organization=cls.acme, first_name='Dup', last_name='Owner',
                               email='OWNER@acme.example')

    def setUp(self):
        cache.clear()

    def make_check(self, orgs=None, **kw):
        kw.setdefault('name', 'Quarterly pulse')
        check = PulseCheck.objects.create(**kw)
        check.organizations.set(orgs if orgs is not None else [self.acme])
        PulseQuestion.objects.create(pulse_check=check, order=0, kind='rating', text='Overall?')
        PulseQuestion.objects.create(pulse_check=check, order=1, kind='nps', text='Recommend?')
        PulseQuestion.objects.create(pulse_check=check, order=2, kind='yes_no', text='On time?',
                                     required=False)
        PulseQuestion.objects.create(pulse_check=check, order=3, kind='text', text='Better?',
                                     required=False)
        return check

    def emails(self, check):
        return sorted(r.email.lower() for r in audience.resolve(check)[0])

    def send(self, check, **kw):
        kw.setdefault('connection', _locmem())
        return sending.send_check(check, **kw)


class ModelTests(_Base):
    def test_token_is_stored_hashed_and_looked_up(self):
        send = self.send(self.make_check())
        r = send.responses.first()
        raw = mail.outbox[0].body.split('/feedback/r/')[1].split('/')[0]
        self.assertNotIn(raw, r.token_hash)
        self.assertEqual(len(r.token_hash), 64)
        self.assertEqual(PulseResponse.lookup(raw).pk in set(send.responses.values_list('pk', flat=True)), True)
        self.assertIsNone(PulseResponse.lookup('nope'))
        self.assertIsNone(PulseResponse.lookup(''))

    def test_period_keys_and_due_days(self):
        c = PulseCheck(schedule='monthly', send_day=5, starts_on=date(2026, 1, 1))
        self.assertEqual(c.period_key(date(2026, 11, 13)), '2026-11')
        self.assertTrue(c.is_due(date(2026, 11, 5)))
        self.assertFalse(c.is_due(date(2026, 11, 4)))
        q = PulseCheck(schedule='quarterly', send_day=1, starts_on=date(2026, 1, 1))
        self.assertEqual(q.period_key(date(2026, 11, 13)), '2026-Q4')
        self.assertTrue(q.is_due(date(2026, 10, 2)))
        self.assertFalse(q.is_due(date(2026, 11, 2)))
        self.assertFalse(PulseCheck(schedule='none').is_due(date(2026, 11, 2)))
        self.assertFalse(PulseCheck(schedule='monthly', starts_on=date(2027, 1, 1)).is_due(date(2026, 12, 2)))

    def test_nps_and_answer_parsing(self):
        self.assertEqual(results.nps([10, 9, 8, 6]), 25)
        self.assertIsNone(results.nps([]))
        qs = [{'id': 1, 'kind': 'rating', 'required': True, 'text': 'a'},
              {'id': 2, 'kind': 'nps', 'required': True, 'text': 'b'},
              {'id': 3, 'kind': 'yes_no', 'required': False, 'text': 'c'},
              {'id': 4, 'kind': 'text', 'required': False, 'text': 'd'}]
        answers, errors = results.parse_answers(qs, {'q_1': '4', 'q_2': '10', 'q_3': 'yes', 'q_4': ' hi '})
        self.assertEqual(errors, [])
        self.assertEqual(answers, {'1': 4, '2': 10, '3': True, '4': 'hi'})
        _a, errors = results.parse_answers(qs, {'q_1': '6', 'q_2': ''})
        self.assertEqual(len(errors), 2)

    def test_opt_out_is_case_insensitive(self):
        PulseOptOut.opt_out('Someone@Example.COM', via='test')
        self.assertTrue(PulseOptOut.is_opted_out('someone@example.com'))
        PulseOptOut.opt_in('SOMEONE@example.com')
        self.assertFalse(PulseOptOut.is_opted_out('someone@example.com'))


class AudienceTests(_Base):
    def test_everyone_is_active_portal_users_with_email_without_msp_staff(self):
        check = self.make_check()
        self.assertEqual(self.emails(check), ['admin@acme.example', 'editor@acme.example',
                                              'owner@acme.example', 'reader@acme.example'])

    def test_everyone_with_contacts_dedupes_user_and_contact(self):
        check = self.make_check(include_contacts=True)
        emails = self.emails(check)
        self.assertIn('carl@acme.example', emails)
        self.assertEqual(emails.count('owner@acme.example'), 1)
        owner = [r for r in audience.resolve(check)[0] if r.email.lower() == 'owner@acme.example'][0]
        self.assertEqual(owner.user, self.owner)

    def test_role_groups(self):
        check = self.make_check(audience='roles', audience_roles=['owners'])
        self.assertEqual(self.emails(check), ['owner@acme.example'])
        check.audience_roles = ['admins']
        check.save()
        self.assertEqual(self.emails(check), ['admin@acme.example'])
        check.audience_roles = ['owners', 'admins']
        check.save()
        self.assertEqual(self.emails(check), ['admin@acme.example', 'owner@acme.example'])
        check.audience_roles = ['editors']
        check.save()
        self.assertEqual(self.emails(check), ['editor@acme.example'])

    def test_named_role_matches_additional_role(self):
        check = self.make_check(audience='roles')
        check.audience_role_templates.add(self.finance_role)
        self.assertEqual(self.emails(check), ['reader@acme.example'])

    def test_specific_people_stay_within_the_chosen_organizations(self):
        check = self.make_check(audience='specific')
        check.specific_users.add(self.editor, self.beta_owner)
        check.specific_contacts.add(self.contact)
        self.assertEqual(self.emails(check), ['carl@acme.example', 'editor@acme.example'])
        check.organizations.add(self.beta)
        self.assertEqual(self.emails(check), ['bowner@beta.example', 'carl@acme.example',
                                              'editor@acme.example'])

    def test_all_clients_leaves_out_internal_and_inactive(self):
        check = self.make_check(orgs=[], all_organizations=True, audience='roles', audience_roles=['owners'])
        self.assertEqual(self.emails(check), ['bowner@beta.example', 'owner@acme.example'])

    def test_opted_out_people_are_dropped_and_counted(self):
        PulseOptOut.opt_out('EDITOR@acme.example')
        recipients, skipped = audience.resolve(self.make_check())
        self.assertNotIn('editor@acme.example', [r.email for r in recipients])
        self.assertEqual(skipped, 1)


class SendingTests(_Base):
    def test_send_creates_responses_emails_links_and_audits(self):
        check = self.make_check(audience='roles', audience_roles=['owners', 'admins'])
        send = self.send(check, by=self.su)
        self.assertEqual(send.recipient_count, 2)
        self.assertEqual(send.emailed_count, 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual({m.to[0] for m in mail.outbox}, {'owner@acme.example', 'admin@acme.example'})
        self.assertIn('/portal/feedback/r/', mail.outbox[0].body)
        self.assertIn('/portal/feedback/opt-out/', mail.outbox[0].body)
        self.assertEqual(len(send.questions), 4)
        self.assertTrue(all(r.email_status == 'sent' for r in send.responses.all()))
        logs = AuditLog.objects.filter(object_type='pulse.PulseSend', object_id=send.pk)
        self.assertEqual(logs.count(), 2)   # one overall, one for Acme
        self.assertTrue(logs.filter(organization=self.acme).exists())

    def test_without_outgoing_email_responses_still_exist(self):
        with mock.patch('pulse.sending.get_smtp_connection', return_value=None):
            send = sending.send_check(self.make_check())
        self.assertEqual(send.emailed_count, 0)
        self.assertEqual(send.responses.count(), 4)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(all(r.email_status == 'not_sent' for r in send.responses.all()))

    def test_editing_questions_later_keeps_the_send_snapshot(self):
        check = self.make_check()
        send = self.send(check)
        check.questions.all().delete()
        send.refresh_from_db()
        self.assertEqual([q['text'] for q in send.questions], ['Overall?', 'Recommend?', 'On time?', 'Better?'])

    def test_summary(self):
        check = self.make_check(audience='roles', audience_roles=['owners', 'admins'])
        send = self.send(check)
        q = {x['text']: str(x['id']) for x in send.questions}
        r1, r2 = list(send.responses.all())
        r1.answers = {q['Overall?']: 4, q['Recommend?']: 10, q['On time?']: True, q['Better?']: 'More updates'}
        r1.responded_at = timezone.now()
        r1.save()
        s = results.summarize(send.responses.select_related('send', 'organization'))
        self.assertEqual((s['total'], s['answered'], s['rate']), (2, 1, 50))
        self.assertEqual(s['average_rating'], 4)
        self.assertEqual(s['nps'], 100)
        text = [x for x in s['questions'] if x['kind'] == 'text'][0]
        self.assertEqual(text['comments'][0]['text'], 'More updates')


class SchedulerTests(_Base):
    def test_scheduled_send_is_idempotent_within_a_period(self):
        self.make_check(schedule='monthly', send_day=1, starts_on=date(2026, 1, 1))
        now = timezone.make_aware(datetime(2026, 11, 13, 10, 0))
        with mock.patch('pulse.sending.get_smtp_connection', side_effect=_locmem):
            first = sending.send_due(now=now)
            second = sending.send_due(now=now + timedelta(hours=3))
        self.assertEqual(first['sent'], 1)
        self.assertEqual(second['sent'], 0)
        self.assertEqual(second['skipped'], 1)
        self.assertEqual(PulseSend.objects.count(), 1)
        self.assertEqual(PulseSend.objects.get().period_key, '2026-11')
        self.assertEqual(len(mail.outbox), 4)
        with mock.patch('pulse.sending.get_smtp_connection', side_effect=_locmem):
            sending.send_due(now=timezone.make_aware(datetime(2026, 12, 1, 9, 0)))
        self.assertEqual(PulseSend.objects.count(), 2)

    def test_duplicate_period_insert_is_refused(self):
        check = self.make_check(schedule='monthly')
        self.send(check, trigger='schedule', period_key='2026-11')
        self.assertIsNone(self.send(check, trigger='schedule', period_key='2026-11'))
        self.assertEqual(PulseSend.objects.count(), 1)

    def test_nothing_sent_when_off_inactive_or_not_due(self):
        self.make_check(schedule='quarterly', starts_on=date(2026, 1, 1))
        self.make_check(name='Off', schedule='monthly', is_active=False, starts_on=date(2026, 1, 1))
        nov = timezone.make_aware(datetime(2026, 11, 13, 10, 0))
        self.assertEqual(sending.send_due(now=nov)['sent'], 0)   # quarterly: not a quarter month
        _set(pulse_enabled=False)
        self.assertTrue(sending.send_due(now=timezone.make_aware(datetime(2026, 10, 13)))['disabled'])
        self.assertEqual(PulseSend.objects.count(), 0)

    def test_registered_with_the_scheduler(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['pulse_send_due'], ('pulse_send_due', []))
        self.assertIn('pulse_send_due', dict(ScheduledTask.TASK_TYPES))
        out = io.StringIO()
        call_command('pulse_send_due', stdout=out)
        self.assertIn('Pulse checks', out.getvalue())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TokenViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.check = self.make_check(audience='roles', audience_roles=['owners'])
        self.sent = self.send(self.check)
        self.response = self.sent.responses.get()
        self.raw = mail.outbox[-1].body.split('/feedback/r/')[1].split('/')[0]
        self.url = reverse('portal:pulse_respond', args=[self.raw])
        self.q = {x['text']: str(x['id']) for x in self.sent.questions}

    def answers(self, **kw):
        data = {f'q_{self.q["Overall?"]}': '5', f'q_{self.q["Recommend?"]}': '9'}
        data.update(kw)
        return data

    def test_valid_link_answers_once(self):
        c = Client()
        self.assertContains(c.get(self.url), 'Overall?')
        r = c.post(self.url, self.answers(**{f'q_{self.q["Better?"]}': 'Faster replies'}))
        self.assertContains(r, 'Thank you')
        self.response.refresh_from_db()
        self.assertEqual(self.response.responded_via, 'link')
        self.assertEqual(self.response.answers[self.q['Overall?']], 5)
        self.assertEqual(self.response.answers[self.q['Better?']], 'Faster replies')

    def test_reused_link_does_not_overwrite(self):
        c = Client()
        c.post(self.url, self.answers())
        r = c.post(self.url, self.answers(**{f'q_{self.q["Overall?"]}': '1'}))
        self.assertContains(r, 'Already answered')
        self.response.refresh_from_db()
        self.assertEqual(self.response.answers[self.q['Overall?']], 5)

    def test_expired_link(self):
        PulseSend.objects.filter(pk=self.sent.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        r = Client().post(self.url, self.answers())
        self.assertEqual(r.status_code, 410)
        self.response.refresh_from_db()
        self.assertIsNone(self.response.responded_at)

    def test_invalid_answers_and_bad_token(self):
        r = Client().post(self.url, {f'q_{self.q["Overall?"]}': '9'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Client().get(reverse('portal:pulse_respond', args=['x' * 43])).status_code, 404)

    def test_link_opens_only_its_own_response(self):
        other = self.send(self.make_check(name='Beta pulse', orgs=[self.beta]))
        r = Client().get(self.url)
        self.assertContains(r, 'Acme')
        self.assertNotContains(r, 'Beta pulse')
        Client().post(self.url, self.answers())
        self.assertFalse(other.responses.filter(responded_at__isnull=False).exists())

    def test_off_is_404(self):
        _set(pulse_enabled=False)
        self.assertEqual(Client().get(self.url).status_code, 404)

    def test_opt_out_link(self):
        token = sending.opt_out_token('owner@acme.example')
        url = reverse('portal:pulse_opt_out', args=[token])
        self.assertContains(Client().get(url), 'owner@acme.example')
        Client().post(url)
        self.assertTrue(PulseOptOut.is_opted_out('owner@acme.example'))
        self.assertEqual(Client().get(reverse('portal:pulse_opt_out', args=['bad'])).status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalTests(_Base):
    def setUp(self):
        super().setUp()
        self.acme_send = self.send(self.make_check())
        self.beta_send = self.send(self.make_check(name='Beta check', orgs=[self.beta]))
        self.mine = self.acme_send.responses.get(user=self.owner)

    def test_feedback_page_lists_only_own_responses(self):
        r = _login(self.owner).get(reverse('portal:pulse_feedback'))
        self.assertContains(r, 'Quarterly pulse')
        self.assertNotContains(r, 'Beta check')
        self.assertContains(r, reverse('portal:pulse_answer', args=[self.mine.pk]))
        other = self.acme_send.responses.get(user=self.admin)
        self.assertNotContains(r, reverse('portal:pulse_answer', args=[other.pk]))

    def test_answer_own_response_in_portal(self):
        q = {x['text']: str(x['id']) for x in self.acme_send.questions}
        url = reverse('portal:pulse_answer', args=[self.mine.pk])
        r = _login(self.owner).post(url, {f'q_{q["Overall?"]}': '3', f'q_{q["Recommend?"]}': '6'})
        self.assertContains(r, 'Thank you')
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.responded_via, 'portal')

    def test_other_users_and_other_orgs_responses_are_404(self):
        c = _login(self.owner)
        coworker = self.acme_send.responses.get(user=self.admin)
        beta = self.beta_send.responses.get(user=self.beta_owner)
        self.assertEqual(c.get(reverse('portal:pulse_answer', args=[coworker.pk])).status_code, 404)
        self.assertEqual(c.get(reverse('portal:pulse_answer', args=[beta.pk])).status_code, 404)
        self.assertEqual(c.post(reverse('portal:pulse_answer', args=[beta.pk]), {}).status_code, 404)

    def test_opt_out_switch(self):
        c = _login(self.owner)
        c.post(reverse('portal:pulse_feedback'), {})
        self.assertTrue(PulseOptOut.is_opted_out('owner@acme.example'))
        c.post(reverse('portal:pulse_feedback'), {'receive': 'on'})
        self.assertFalse(PulseOptOut.is_opted_out('owner@acme.example'))

    def test_portal_nav_link_follows_the_switch(self):
        c = _login(self.owner)
        self.assertContains(c.get(reverse('portal:pulse_feedback')), 'fa-comment-dots')
        _set(pulse_enabled=False)
        self.assertEqual(c.get(reverse('portal:pulse_feedback')).status_code, 404)
        self.assertNotContains(c.get(reverse('portal:kb_list')), 'fa-comment-dots')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StaffViewTests(_Base):
    def post_form(self, c, url, **kw):
        data = {'name': 'Owners pulse', 'intro': 'Hi', 'is_active': 'on', 'schedule': 'quarterly',
                'send_day': '1', 'starts_on': '2026-11-01', 'response_days': '14',
                'organizations': [self.acme.pk], 'audience': 'roles', 'audience_roles': ['owners'],
                'q_text_0': 'Overall?', 'q_kind_0': 'rating', 'q_required_0': 'on',
                'q_text_1': 'Recommend?', 'q_kind_1': 'nps'}
        data.update(kw)
        return c.post(url, data)

    def test_customer_users_cannot_reach_staff_pages(self):
        check = self.make_check()
        c = _login(self.owner)
        for url in (reverse('pulse:check_list'), reverse('pulse:check_create'),
                    reverse('pulse:check_detail', args=[check.pk]),
                    reverse('pulse:check_send', args=[check.pk])):
            r = c.get(url)
            self.assertIn(r.status_code, (302, 403, 404), url)
            self.assertNotContains(r, 'Quarterly pulse', status_code=r.status_code)
        r = c.post(reverse('pulse:check_send', args=[check.pk]))
        self.assertFalse(PulseSend.objects.exists())

    def test_non_staff_member_without_portal_gets_403(self):
        u = User.objects.create_user('plain', 'plain@x.example', 'pw')
        self.assertEqual(_login(u).get(reverse('pulse:check_list')).status_code, 403)

    def test_tech_creates_and_sends(self):
        c = _login(self.tech)
        r = self.post_form(c, reverse('pulse:check_create'))
        check = PulseCheck.objects.get(name='Owners pulse')
        self.assertRedirects(r, reverse('pulse:check_detail', args=[check.pk]))
        self.assertEqual(check.audience_roles, ['owners'])
        self.assertEqual(list(check.questions.values_list('kind', flat=True)), ['rating', 'nps'])
        self.assertTrue(AuditLog.objects.filter(object_type='pulse.PulseCheck', object_id=check.pk,
                                                action='create').exists())
        self.assertContains(c.get(reverse('pulse:check_send', args=[check.pk])), 'owner@acme.example')
        with mock.patch('pulse.sending.get_smtp_connection', side_effect=_locmem):
            r = c.post(reverse('pulse:check_send', args=[check.pk]))
        send = PulseSend.objects.get()
        self.assertRedirects(r, reverse('pulse:send_detail', args=[send.pk]))
        self.assertEqual(send.sent_by, self.tech)
        self.assertEqual([m.to[0] for m in mail.outbox], ['owner@acme.example'])
        self.assertContains(c.get(reverse('pulse:check_detail', args=[check.pk])), 'Owners pulse')
        self.assertContains(c.get(reverse('pulse:send_detail', args=[send.pk])), 'owner@acme.example')
        self.assertContains(c.get(reverse('pulse:check_list')), 'Owners pulse')

    def test_form_validation(self):
        c = _login(self.tech)
        r = self.post_form(c, reverse('pulse:check_create'), audience_roles=[], organizations=[])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(PulseCheck.objects.exists())
        r = self.post_form(c, reverse('pulse:check_create'), q_text_0='', q_text_1='')
        self.assertFalse(PulseCheck.objects.exists())

    def test_results_filter_by_organization(self):
        check = self.make_check(orgs=[self.acme, self.beta], audience='roles', audience_roles=['owners'])
        send = self.send(check)
        q = str(send.questions[0]['id'])
        PulseResponse.objects.filter(send=send, organization=self.beta).update(
            answers={q: 1}, responded_at=timezone.now())
        c = _login(self.tech)
        r = c.get(reverse('pulse:check_detail', args=[check.pk]), {'org': self.acme.pk})
        self.assertEqual(r.context['summary']['total'], 1)
        self.assertEqual(r.context['summary']['answered'], 0)
        r = c.get(reverse('pulse:send_detail', args=[send.pk]))
        self.assertEqual(r.context['summary']['average_rating'], 1)
        self.assertContains(r, 'bowner@beta.example')

    def test_off_is_404_for_staff(self):
        _set(pulse_enabled=False)
        self.assertEqual(_login(self.tech).get(reverse('pulse:check_list')).status_code, 404)

    def test_scoped_staff_see_and_manage_only_their_clients(self):
        check = self.make_check(orgs=[self.acme, self.beta], audience='roles', audience_roles=['owners'])
        send = self.send(check)
        c = _login(self.tech)
        with mock.patch('core.tenancy.accessible_org_ids', return_value={self.acme.pk}):
            r = c.get(reverse('pulse:send_detail', args=[send.pk]))
            self.assertContains(r, 'owner@acme.example')
            self.assertNotContains(r, 'bowner@beta.example')
            self.assertEqual(c.get(reverse('pulse:check_edit', args=[check.pk])).status_code, 403)
            self.assertEqual(c.post(reverse('pulse:check_send', args=[check.pk])).status_code, 403)
        with mock.patch('core.tenancy.accessible_org_ids', return_value={self.internal.pk}):
            self.assertEqual(c.get(reverse('pulse:check_detail', args=[check.pk])).status_code, 404)

    def test_org_page_trend_card_is_staff_only(self):
        self.send(self.make_check())
        self.assertContains(_login(self.su).get(reverse('accounts:organization_detail', args=[self.acme.pk])),
                            'client-pulse')
        r = _login(self.editor).get(reverse('accounts:organization_detail', args=[self.acme.pk]))
        self.assertNotContains(r, 'client-pulse', status_code=r.status_code)

    def test_nav_entry_follows_the_switch(self):
        from core import navigation
        self.assertIn('pulse:check_list', [t.url_name for t in navigation.SECTIONS_BY_KEY['mod_pulse'].tabs])
        r = _login(self.su).get(reverse('pulse:check_list'))
        self.assertContains(r, reverse('pulse:opt_out_list'))
        _set(pulse_enabled=False)
        r = _login(self.su).get(reverse('core:dashboard'))
        self.assertNotContains(r, reverse('pulse:check_list'), status_code=r.status_code)

    def test_edit_and_opt_out_pages_render(self):
        check = self.make_check()
        PulseOptOut.opt_out('gone@acme.example', via='link')
        c = _login(self.tech)
        r = c.get(reverse('pulse:check_edit', args=[check.pk]))
        self.assertContains(r, 'value="Overall?"')
        self.assertContains(c.get(reverse('pulse:opt_out_list')), 'gone@acme.example')
        self.assertContains(c.get(reverse('pulse:check_create')), 'How likely are you to recommend us')
        r = self.post_form(c, reverse('pulse:check_edit', args=[check.pk]), name='Renamed')
        check.refresh_from_db()
        self.assertEqual(check.name, 'Renamed')
        self.assertTrue(AuditLog.objects.filter(object_type='pulse.PulseCheck', object_id=check.pk,
                                                action='update').exists())
