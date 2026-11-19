"""Security review, second wave: SR-06 (ticket attachments), SR-11 (lead form
rate limit per visitor), SR-12 (public token pages throttled; CSAT changes
explicit and bounded)."""
import tempfile
from email.message import EmailMessage

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa import attachment_rules
from psa.models import Queue, Ticket, TicketAttachment, TicketCSATSurvey, TicketPriority, TicketStatus, TicketType
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
HTML = b'<html><script>alert(1)</script></html>'


class _CacheClean:
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()


class AttachmentRuleTests(TestCase):
    def test_type_from_extension_not_declaration(self):
        self.assertEqual(attachment_rules.check('shot.png', PNG), ('image/png', ''))
        self.assertEqual(attachment_rules.check('notes.md', b'# hi')[0], 'text/markdown')

    def test_refusals(self):
        self.assertIn('does not match', attachment_rules.check('photo.png', HTML)[1])
        for name in ('page.html', 'x.exe', 'report.exe.pdf', 'noext', 'run.ps1'):
            self.assertEqual(attachment_rules.check(name, b'%PDF')[0], '', name)

    def test_map_matches_the_previous_allowlist(self):
        previous = {
            'application/pdf', 'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml',
            'text/plain', 'text/csv', 'text/markdown', 'application/json', 'application/zip'}
        self.assertEqual(set(attachment_rules.TYPES_BY_EXT.values()), previous)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=tempfile.mkdtemp())
class TicketAttachUploadTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='AttachCo', slug='attach-co')
        self.admin = User.objects.create_superuser('att_admin', 'a@x.test', 'pw')
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Printer', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first())
        self.c = Client()
        self.c.force_login(self.admin)
        s = self.c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.pk
        s.save()

    def attach(self, name, data, ctype):
        return self.c.post(f'/psa/t/{self.ticket.ticket_number}/attach/',
                           {'file': SimpleUploadedFile(name, data, content_type=ctype)})

    def test_html_declared_as_png_refused(self):
        self.attach('photo.png', HTML, 'image/png')
        self.assertFalse(TicketAttachment.objects.filter(ticket=self.ticket).exists())

    def test_png_stored_with_type_from_name(self):
        self.attach('shot.png', PNG, 'text/html')
        att = TicketAttachment.objects.get(ticket=self.ticket)
        self.assertEqual(att.content_type, 'image/png')

    def test_svg_is_served_as_a_download(self):
        self.attach('logo.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>',
                    'image/svg+xml')
        att = TicketAttachment.objects.get(ticket=self.ticket)
        r = self.c.get(att.file.url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')


class EmailAttachmentTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='MailCo', slug='mail-co')
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Mail', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first())

    @override_settings(PSA_EMAIL_ATTACHMENT_MIME_ALLOWLIST=['image/*', 'application/pdf'],
                       MEDIA_ROOT=tempfile.mkdtemp())
    def test_disguised_and_mismatched_attachments_skipped(self):
        from psa.management.commands.psa_poll_email import _ingest_attachments
        msg = EmailMessage()
        msg.set_content('see attached')
        msg.add_attachment(HTML, maintype='image', subtype='png', filename='photo.png')
        msg.add_attachment(b'%PDF-1.4', maintype='application', subtype='pdf', filename='invoice.exe.pdf')
        msg.add_attachment(PNG, maintype='image', subtype='png', filename='real.png')
        saved, skipped = _ingest_attachments(msg, ticket=self.ticket, comment=None)
        self.assertEqual((saved, skipped), (1, 2))
        self.assertEqual(TicketAttachment.objects.get(ticket=self.ticket).content_type, 'image/png')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LeadFormRateLimitTests(_CacheClean, TestCase):
    def post(self, ip):
        # The test client's peer is 127.0.0.1, a trusted proxy by default.
        return self.client.post('/crm/leads/capture/', {'website_url': 'x'}, HTTP_X_FORWARDED_FOR=ip)

    def test_visitors_behind_the_proxy_have_their_own_limit(self):
        for _ in range(10):
            self.assertEqual(self.post('203.0.113.7').status_code, 200)
        self.assertEqual(self.post('203.0.113.7').status_code, 429)
        self.assertEqual(self.post('198.51.100.9').status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CsatThrottleTests(_CacheClean, TestCase):
    def setUp(self):
        super().setUp()
        _setup_seed()
        self.org = Organization.objects.create(name='CsatThrottle', slug='csat-throttle')
        ticket = Ticket.objects.create(
            organization=self.org, subject='Done', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first())
        self.survey = TicketCSATSurvey(ticket=ticket, organization=self.org, recipient_email='c@x.test')
        self.token = self.survey.issue_token()
        self.survey.save()
        self.url = f'/psa/csat/{self.token}/'

    def test_page_says_an_answer_exists_and_changes_are_bounded(self):
        self.assertEqual(self.client.post(self.url, {'rating': 5}).status_code, 200)
        r = self.client.get(self.url)
        self.assertContains(r, 'data-csat-answered')
        self.assertContains(r, 'Submitting again changes your answer')
        for rating in (4, 3, 2, 1, 2):
            self.assertEqual(self.client.post(self.url, {'rating': rating}).status_code, 200)
        r = self.client.post(self.url, {'rating': 1})
        self.assertEqual(r.status_code, 429)
        self.survey.refresh_from_db()
        self.assertEqual(self.survey.rating, 2)

    def test_per_address_limit(self):
        for _ in range(30):
            self.client.get(self.url)
        self.assertEqual(self.client.get(self.url).status_code, 429)
