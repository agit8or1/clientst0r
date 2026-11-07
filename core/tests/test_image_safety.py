"""Image decoding is limited to the accepted formats (v3.17.629).

Pillow picks a decoder from the file's bytes, not its name. These tests make
real files in other formats, give them image extensions, and check that they
are refused everywhere uploads are decoded — Pillow itself, Django's
ImageField (avatars, logos, rack/location photos), the attachment upload
view — while the accepted formats still upload, optimize and thumbnail.
"""
import io

from django import forms
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image, UnidentifiedImageError

from core.image_safety import ALLOWED_FORMATS, open_image

TEST_MIDDLEWARE_EXCLUDE = ('Enforce2FAMiddleware', 'AxesMiddleware')


def _img_bytes(fmt, size=(64, 48), mode='RGB'):
    buf = io.BytesIO()
    im = Image.new(mode, size, (200, 30, 30) if mode == 'RGB' else 1)
    if fmt == 'GIF':
        im = im.convert('P')
    im.save(buf, format=fmt)
    return buf.getvalue()


def _foreign_files():
    """Files in formats we do not accept. Encoders still exist, decoders must not."""
    files = {}
    for fmt in ('TIFF', 'PCX', 'XBM', 'EPS', 'TGA', 'PPM', 'SGI', 'IM', 'DDS'):
        try:
            mode = '1' if fmt == 'XBM' else 'RGB'
            files[fmt] = _img_bytes(fmt, mode=mode)
        except (KeyError, OSError, ValueError):
            continue  # encoder not built in this Pillow
    return files


class DecoderRegistryTests(SimpleTestCase):
    def test_only_allowed_decoders_are_registered(self):
        Image.init()
        self.assertTrue(set(Image.OPEN) <= ALLOWED_FORMATS, sorted(set(Image.OPEN) - ALLOWED_FORMATS))
        self.assertTrue({'PNG', 'JPEG', 'GIF', 'WEBP'} <= set(Image.OPEN))

    def test_allowed_formats_open_and_thumbnail(self):
        for fmt in ('PNG', 'JPEG', 'GIF', 'WEBP', 'BMP', 'ICO'):
            with self.subTest(fmt=fmt):
                im = Image.open(io.BytesIO(_img_bytes(fmt)))
                self.assertEqual(im.format, fmt)
                im.thumbnail((16, 16), Image.Resampling.LANCZOS)
                self.assertLessEqual(max(im.size), 16)

    def test_foreign_formats_are_refused_whatever_the_name(self):
        foreign = _foreign_files()
        self.assertGreaterEqual(len(foreign), 4, 'expected several foreign encoders to build fixtures')
        for fmt, data in foreign.items():
            with self.subTest(fmt=fmt):
                with self.assertRaises(UnidentifiedImageError):
                    Image.open(io.BytesIO(data))
                with self.assertRaises(UnidentifiedImageError):
                    open_image(io.BytesIO(data))

    def test_django_imagefield_rejects_disguised_files(self):
        field = forms.ImageField()
        field.clean(SimpleUploadedFile('ok.png', _img_bytes('PNG'), content_type='image/png'))
        for fmt, data in _foreign_files().items():
            with self.subTest(fmt=fmt):
                with self.assertRaises(forms.ValidationError):
                    field.clean(SimpleUploadedFile('avatar.png', data, content_type='image/png'))


def _middleware():
    from django.conf import settings
    return [m for m in settings.MIDDLEWARE if not m.endswith(TEST_MIDDLEWARE_EXCLUDE)]


@override_settings(SECURE_SSL_REDIRECT=False)
class UploadPathTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        cls.org = Organization.objects.create(name='ImgCo', slug='imgco')
        cls.user = get_user_model().objects.create_user('img_editor', password='x')
        Membership.objects.create(user=cls.user, organization=cls.org, role=Role.EDITOR, is_active=True)
        from assets.models import Asset
        cls.asset = Asset.objects.create(organization=cls.org, name='Box')

    def setUp(self):
        self._mw = override_settings(MIDDLEWARE=_middleware())
        self._mw.enable()
        self.client.force_login(self.user)
        s = self.client.session
        s['current_organization_id'] = self.org.pk
        s.save()

    def tearDown(self):
        self._mw.disable()

    def _upload(self, name, data):
        return self.client.post('/files/upload/', {
            'file': SimpleUploadedFile(name, data), 'entity_type': 'asset', 'entity_id': str(self.asset.pk)})

    def test_valid_images_upload_and_are_optimized(self):
        from files.models import Attachment
        for name, fmt in (('a.png', 'PNG'), ('b.jpg', 'JPEG'), ('c.gif', 'GIF'), ('d.webp', 'WEBP')):
            with self.subTest(name=name):
                resp = self._upload(name, _img_bytes(fmt, size=(2600, 1300)))
                self.assertIn(resp.status_code, (200, 201, 302), resp.content[:200])
                att = Attachment.objects.filter(organization=self.org, original_filename=name).first()
                self.assertIsNotNone(att)
                with att.file.open('rb') as fh:
                    data = fh.read()
                self.assertGreater(len(data), 100, 'stored file is empty')
                im = Image.open(io.BytesIO(data))
                self.assertEqual(im.format, fmt, 'stored content must stay in its own format')
                self.assertEqual(att.file_size, len(data), 'recorded size must match the stored file')
                self.assertLessEqual(max(im.size), 2048)

    def test_disguised_and_mismatched_images_are_rejected(self):
        from files.models import Attachment
        before = Attachment.objects.count()
        cases = [(f'evil-{fmt.lower()}.png', data) for fmt, data in _foreign_files().items()]
        cases.append(('jpeg-named.webp', _img_bytes('JPEG')))   # decodes, but not as its extension
        cases.append(('garbage.gif', b'GIF89a' + b'\x00' * 100))
        for name, data in cases:
            with self.subTest(name=name):
                resp = self._upload(name, data)
                self.assertEqual(resp.status_code, 400, name)
        self.assertEqual(Attachment.objects.count(), before)

    def test_rack_device_photo_resize_still_works(self):
        from monitoring.models import Rack, RackDevice
        rack = Rack.objects.create(organization=self.org, name='R1', units=10)
        rd = RackDevice(rack=rack, name='Sw', start_unit=1, units=1,
                        photo=SimpleUploadedFile('p.png', _img_bytes('PNG', size=(900, 300))))
        rd.save()
        with rd.photo.open('rb') as fh:
            im = Image.open(fh)
            self.assertEqual(im.format, 'JPEG')
            self.assertLessEqual(im.size[1], 40)
