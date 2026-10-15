"""/media/ is served by core.media_views.serve_media, behind authorization.

Before v3.17.599 the static() helper served nothing with DEBUG=False (so every
upload 404'd on native installs) and Docker's nginx served every upload to
anyone. These tests pin the replacement: a file is only returned to a user the
owning record's rule allows, unknown files are 404, and only system branding
is public.
"""
import shutil
import tempfile

from django.apps import apps
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import models
from django.test import TestCase, override_settings

from accounts.models import Membership, RoleTemplate
from core.media_views import MEDIA_REGISTRY
from core.models import Organization, SystemSetting


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

MEDIA_TMP = tempfile.mkdtemp(prefix='clientst0r-media-test-')


def tearDownModule():
    shutil.rmtree(MEDIA_TMP, ignore_errors=True)


def _body(response):
    return b''.join(response.streaming_content)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   MEDIA_ROOT=MEDIA_TMP)
class MediaServingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from docs.models import Document
        from psa.models import (
            Queue, Ticket, TicketAttachment, TicketComment, TicketPriority,
            TicketStatus, TicketType,
        )
        call_command('psa_seed_defaults', verbosity=0)

        User = get_user_model()
        cls.org_a = Organization.objects.create(name='Acme', slug='media-a')
        cls.org_b = Organization.objects.create(name='Bravo', slug='media-b')

        cls.staff = User.objects.create_user('media_staff', 's@x.com', 'pw')
        cls.staff.profile.user_type = 'staff'
        cls.staff.profile.save()

        cls.alice = User.objects.create_user('media_alice', 'a@x.com', 'pw')
        Membership.objects.create(user=cls.alice, organization=cls.org_a,
                                  role='readonly', is_active=True)
        cls.bob = User.objects.create_user('media_bob', 'b@x.com', 'pw')
        Membership.objects.create(user=cls.bob, organization=cls.org_b,
                                  role='readonly', is_active=True)
        no_docs = RoleTemplate.objects.create(name='NoDocs', docs_view=False)
        cls.nodocs = User.objects.create_user('media_nodocs', 'n@x.com', 'pw')
        Membership.objects.create(user=cls.nodocs, organization=cls.org_a,
                                  role='readonly', role_template=no_docs,
                                  is_active=True)

        def ticket(org, client_can_view=True):
            return Ticket.objects.create(
                organization=org, subject='Help', description='x',
                queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                ticket_type=TicketType.objects.first(),
                status=TicketStatus.objects.first(), source='portal',
                client_can_view=client_can_view)

        cls.ticket_a = ticket(cls.org_a)
        cls.att = TicketAttachment.objects.create(
            ticket=cls.ticket_a, filename='quote.pdf', size_bytes=9,
            file=SimpleUploadedFile('quote.pdf', b'%PDF-data'))
        cls.internal_att = TicketAttachment.objects.create(
            ticket=cls.ticket_a, filename='notes.txt', size_bytes=6,
            is_internal=True, file=SimpleUploadedFile('notes.txt', b'secret'))
        note = TicketComment.objects.create(
            ticket=cls.ticket_a, author=cls.staff, body='n', is_internal=True)
        cls.note_att = TicketAttachment.objects.create(
            ticket=cls.ticket_a, comment=note, filename='n.txt', size_bytes=1,
            file=SimpleUploadedFile('n.txt', b'n'))
        cls.hidden_ticket_att = TicketAttachment.objects.create(
            ticket=ticket(cls.org_a, client_can_view=False), filename='h.txt',
            size_bytes=1, file=SimpleUploadedFile('h.txt', b'h'))

        cls.doc = Document.objects.create(
            organization=cls.org_a, title='Runbook', body='', is_published=True,
            file=SimpleUploadedFile('runbook.pdf', b'%PDF-doc'))
        cls.global_doc = Document.objects.create(
            organization=None, title='Global KB', body='', is_published=True,
            is_global=True, file=SimpleUploadedFile('global.pdf', b'%PDF-g'))
        cls.draft = Document.objects.create(
            organization=cls.org_a, title='Draft', body='', is_published=False,
            file=SimpleUploadedFile('draft.pdf', b'%PDF-d'))

        settings_obj = SystemSetting.get_settings()
        settings_obj.custom_logo = SimpleUploadedFile('logo.png', b'\x89PNGlogo')
        settings_obj.geoip_map_background_image = SimpleUploadedFile('map.png', b'\x89PNGmap')
        settings_obj.save()
        cls.logo_name = settings_obj.custom_logo.name
        cls.map_name = settings_obj.geoip_map_background_image.name

    def get(self, name, user=None):
        if user is not None:
            self.client.force_login(user)
        return self.client.get('/media/' + name)

    # --- ticket attachments ------------------------------------------------

    def test_url_points_at_media(self):
        self.assertTrue(self.att.file.url.startswith('/media/psa/'))

    def test_anonymous_is_sent_to_login(self):
        r = self.get(self.att.file.name)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_anonymous_gets_same_redirect_for_missing_file(self):
        """No existence oracle for anonymous visitors."""
        r = self.get('psa/999/tickets/1/nothing.pdf')
        self.assertEqual(r.status_code, 302)

    def test_staff_gets_bytes_with_safe_headers(self):
        r = self.get(self.att.file.name, self.staff)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_body(r), b'%PDF-data')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r['Content-Disposition'].startswith('inline'))
        self.assertIn('quote.pdf', r['Content-Disposition'])
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', r['Cache-Control'])

    def test_member_of_ticket_customer_gets_file(self):
        r = self.get(self.att.file.name, self.alice)
        self.assertEqual(r.status_code, 200)

    def test_other_customer_gets_404(self):
        self.assertEqual(self.get(self.att.file.name, self.bob).status_code, 404)

    def test_internal_attachment_is_staff_only(self):
        self.assertEqual(self.get(self.internal_att.file.name, self.alice).status_code, 404)
        r = self.get(self.internal_att.file.name, self.staff)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_body(r), b'secret')

    def test_attachment_on_internal_note_is_staff_only(self):
        self.assertEqual(self.get(self.note_att.file.name, self.alice).status_code, 404)

    def test_ticket_not_client_visible_is_staff_only(self):
        self.assertEqual(self.get(self.hidden_ticket_att.file.name, self.alice).status_code, 404)
        self.assertEqual(self.get(self.hidden_ticket_att.file.name, self.staff).status_code, 200)

    def test_non_inline_type_downloads(self):
        r = self.get(self.internal_att.file.name, self.staff)
        # text/plain is inline-safe; nosniff keeps it text.
        self.assertEqual(r['Content-Type'], 'text/plain')

    # --- documents ---------------------------------------------------------

    def test_document_needs_docs_view(self):
        self.assertEqual(self.get(self.doc.file.name, self.alice).status_code, 200)
        self.assertEqual(self.get(self.doc.file.name, self.nodocs).status_code, 404)
        self.assertEqual(self.get(self.doc.file.name, self.bob).status_code, 404)

    def test_global_document_needs_every_customer_reach(self):
        self.assertEqual(self.get(self.global_doc.file.name, self.alice).status_code, 404)
        self.assertEqual(self.get(self.global_doc.file.name, self.staff).status_code, 200)

    def test_unpublished_document_is_staff_only(self):
        self.assertEqual(self.get(self.draft.file.name, self.alice).status_code, 404)
        self.assertEqual(self.get(self.draft.file.name, self.staff).status_code, 200)

    # --- paths -------------------------------------------------------------

    def test_traversal_is_404(self):
        for path in ('../config/settings.py', 'psa/../../manage.py',
                     'psa/%2e%2e/%2e%2e/manage.py', './' + self.att.file.name):
            r = self.get(path, self.staff)
            self.assertEqual(r.status_code, 404, path)

    def test_unregistered_file_is_404(self):
        import os
        os.makedirs(os.path.join(MEDIA_TMP, 'stray'), exist_ok=True)
        with open(os.path.join(MEDIA_TMP, 'stray', 'loose.png'), 'wb') as fh:
            fh.write(b'\x89PNG')
        self.assertEqual(self.get('stray/loose.png', self.staff).status_code, 404)

    def test_record_without_file_on_disk_is_404(self):
        import os
        from psa.models import TicketAttachment
        gone = TicketAttachment.objects.create(
            ticket=self.ticket_a, filename='gone.txt', size_bytes=1,
            file=SimpleUploadedFile('gone.txt', b'g'))
        os.remove(os.path.join(MEDIA_TMP, gone.file.name))
        self.assertEqual(self.get(gone.file.name, self.staff).status_code, 404)

    # --- branding ----------------------------------------------------------

    def test_custom_logo_is_public(self):
        r = self.get(self.logo_name)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_body(r), b'\x89PNGlogo')
        self.assertIn('public', r['Cache-Control'])

    def test_other_branding_is_not_public(self):
        self.assertEqual(self.get(self.map_name).status_code, 302)
        self.assertEqual(self.get(self.map_name, self.alice).status_code, 404)
        self.assertEqual(self.get(self.map_name, self.staff).status_code, 200)

    # --- files.Attachment via /files/serve/ (shared streaming path) ------

    def test_files_serve_attachment_streams_from_media_root(self):
        from files.models import Attachment
        att = Attachment.objects.create(
            organization=self.org_a, entity_type='asset', entity_id=1,
            original_filename='photo.png', file_size=4, content_type='image/png',
            file=SimpleUploadedFile('photo.png', b'\x89PNG'))
        self.client.force_login(self.alice)
        session = self.client.session
        session['current_organization_id'] = self.org_a.pk
        session.save()
        r = self.client.get(f'/files/serve/{att.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_body(r), b'\x89PNG')
        self.assertNotIn('X-Accel-Redirect', r)
        # Same file through /media/: member yes, other customer no.
        self.assertEqual(self.get(att.file.name).status_code, 200)
        self.assertEqual(self.get(att.file.name, self.bob).status_code, 404)


class MediaRegistryCoverageTests(TestCase):
    """Every FileField / ImageField in the project's own apps has a rule —
    an unregistered field's uploads would silently 404 (fail closed), so a
    new field must be added to MEDIA_REGISTRY deliberately."""

    def test_every_project_file_field_is_registered(self):
        base = str(django_settings.BASE_DIR)
        registered = {(r.model.lower(), r.field) for r in MEDIA_REGISTRY}
        missing = []
        for model in apps.get_models():
            path = model._meta.app_config.path
            if not path.startswith(base) or 'site-packages' in path \
                    or '/local_apps/' in path:
                continue
            for field in model._meta.get_fields():
                if isinstance(field, models.FileField):
                    key = (model._meta.label_lower, field.name)
                    if key not in registered:
                        missing.append(key)
        self.assertEqual(missing, [])

    def test_registry_entries_exist(self):
        for rule in MEDIA_REGISTRY:
            model = apps.get_model(rule.model)
            self.assertIsInstance(model._meta.get_field(rule.field), models.FileField, rule)
