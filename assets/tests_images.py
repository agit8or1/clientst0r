"""v3.17.657: asset pictures — an uploaded photo (re-encoded, metadata
stripped, served only to users who can see the asset), catalog artwork, or a
stock drawing by asset type, in that order of precedence."""
import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from assets.models import Asset
from assets.stock_images import STOCK_KEYS, stock_key
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE

MEDIA_TMP = tempfile.mkdtemp(prefix='clientst0r-asset-img-test-')


def tearDownModule():
    shutil.rmtree(MEDIA_TMP, ignore_errors=True)


def _jpeg_with_gps(size=(2400, 1800)):
    from PIL import Image
    img = Image.new('RGB', size, (40, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = 'TestCam'           # Make
    exif[0x8825] = {1: 'N', 2: (51.0, 30.0, 0.0), 3: 'W', 4: (0.0, 7.0, 0.0)}  # GPS IFD
    buf = io.BytesIO()
    img.save(buf, format='JPEG', exif=exif)
    return buf.getvalue()


def _login(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


def _body(resp):
    return b''.join(resp.streaming_content) if resp.streaming else resp.content


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA_TMP)
class AssetImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from hardware.models import HardwareModel, Manufacturer
        cls.a = Organization.objects.create(name='Img A', slug='img-a-657')
        cls.b = Organization.objects.create(name='Img B', slug='img-b-657')
        cls.su = User.objects.create_superuser('img-su', 'su@example.com', 'pw-657-su!')
        cls.alice = User.objects.create_user('img-alice', password='pw-657-alice!')
        Membership.objects.create(user=cls.alice, organization=cls.a, role=Role.READONLY, is_active=True)
        cls.bob = User.objects.create_user('img-bob', password='pw-657-bob!')
        Membership.objects.create(user=cls.bob, organization=cls.b, role=Role.READONLY, is_active=True)
        mfr = Manufacturer.objects.create(name='ImgCo', slug='imgco')
        cls.hm = HardwareModel.objects.create(manufacturer=mfr, model='Edge 100', slug='edge-100',
                                              category='firewall')
        cls.hm2 = HardwareModel.objects.create(manufacturer=mfr, model='Core 48', slug='core-48',
                                               category='switch')
        cls.asset = Asset.objects.create(organization=cls.a, name='fw-01', asset_type='firewall')

    def setUp(self):
        self.c = Client()
        _login(self.c, self.su, self.a)

    def _edit(self, **data):
        post = {'name': self.asset.name, 'asset_type': self.asset.asset_type, 'artwork_face': 'front',
                'lifespan_reminder_months': 6, **data}
        return self.c.post(reverse('assets:asset_edit', args=[self.asset.pk]), post)

    def _upload_photo(self):
        resp = self._edit(image_source='photo',
                          photo=SimpleUploadedFile('IMG_0001.jpg', _jpeg_with_gps(), content_type='image/jpeg'))
        self.assertEqual(resp.status_code, 302, resp.context and resp.context['form'].errors)
        self.asset.refresh_from_db()
        return self.asset

    # --- photo ---------------------------------------------------------------

    def test_photo_is_reencoded_resized_and_stripped(self):
        from PIL import Image
        asset = self._upload_photo()
        self.assertEqual(asset.image_source, 'photo')
        self.assertTrue(asset.photo.name.startswith('assets/photos/'))
        self.assertTrue(asset.photo.name.endswith('.jpg'))
        self.assertNotIn('IMG_0001', asset.photo.name)
        with asset.photo.open('rb') as fh:
            img = Image.open(io.BytesIO(fh.read()))
            self.assertLessEqual(max(img.size), 1600)
            exif = img.getexif()
            self.assertEqual(len(exif), 0)
            self.assertNotIn(0x8825, exif)
        self.assertEqual(asset.image_kind, 'photo')

    def test_non_image_upload_is_refused(self):
        resp = self._edit(image_source='photo',
                          photo=SimpleUploadedFile('evil.png', b'<?php echo 1; ?>', content_type='image/png'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['form'].errors.get('photo'))
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.photo)

    def test_photo_choice_without_a_photo_is_an_error(self):
        resp = self._edit(image_source='photo')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('photo', resp.context['form'].errors)

    def test_photo_served_only_to_users_who_can_see_the_asset(self):
        url = self._upload_photo().photo.url
        alice = Client()
        _login(alice, self.alice, self.a)
        resp = alice.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(_body(resp).startswith(b'\xff\xd8'))
        bob = Client()
        _login(bob, self.bob, self.b)
        self.assertEqual(bob.get(url).status_code, 404)
        self.assertEqual(Client().get(url).status_code, 302)  # anonymous: login first

    def test_remove_photo_clears_it_and_deletes_the_file(self):
        asset = self._upload_photo()
        name, storage = asset.photo.name, asset.photo.storage
        self.assertTrue(storage.exists(name))
        resp = self._edit(image_source='photo', remove_photo='on')
        self.assertEqual(resp.status_code, 302)
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.photo)
        self.assertEqual(self.asset.image_source, 'none')
        self.assertFalse(storage.exists(name))

    # --- artwork -------------------------------------------------------------

    def test_artwork_option_shows_catalog_art_on_detail_and_list(self):
        resp = self._edit(image_source='artwork', artwork_model=self.hm.pk)
        self.assertEqual(resp.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.artwork_model, self.hm)
        art = reverse('hardware:model_art', args=[self.hm.pk, 'front'])
        detail = self.c.get(reverse('assets:asset_detail', args=[self.asset.pk])).content.decode()
        self.assertIn(f'src="{art}"', detail)
        self.assertIn('data-image-kind="artwork"', detail)
        listing = self.c.get(reverse('assets:asset_list')).content.decode()
        self.assertIn(f'{art}?v=thumb', listing)
        thumb = self.c.get(f'{art}?v=thumb')
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb['Content-Type'], 'image/svg+xml')

    def test_artwork_choice_needs_a_model(self):
        resp = self._edit(image_source='artwork')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('artwork_model', resp.context['form'].errors)

    def test_form_has_picture_section_and_multipart(self):
        html = self.c.get(reverse('assets:asset_edit', args=[self.asset.pk])).content.decode()
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('id="picture-section"', html)
        self.assertIn(reverse('hardware:api_models'), html)

    # --- stock fallback and precedence --------------------------------------

    def test_stock_image_by_type_when_nothing_else(self):
        self.assertEqual(self.asset.image_kind, 'stock')
        self.assertTrue(self.asset.image_url.endswith('images/asset-stock/firewall.svg'))
        detail = self.c.get(reverse('assets:asset_detail', args=[self.asset.pk])).content.decode()
        self.assertIn('data-image-kind="stock"', detail)
        self.assertIn('images/asset-stock/firewall.svg', detail)
        listing = self.c.get(reverse('assets:asset_list')).content.decode()
        self.assertIn('images/asset-stock/firewall.svg', listing)
        # Display only: nothing was stored on the asset.
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.image_source, 'none')
        self.assertFalse(self.asset.photo)

    def test_stock_mapping_covers_built_in_and_custom_types(self):
        self.assertEqual(stock_key('server'), 'server')
        self.assertEqual(stock_key('laptop'), 'laptop')
        self.assertEqual(stock_key('wireless_ap'), 'access-point')
        self.assertEqual(stock_key('nas'), 'storage')
        self.assertEqual(stock_key('virtual_machine'), 'vm')
        self.assertEqual(stock_key('vm'), 'vm')
        self.assertEqual(stock_key('custom_kiosk'), 'device')
        self.assertEqual(stock_key(''), 'device')
        for value, _label in Asset.ASSET_TYPES:
            self.assertIn(stock_key(value), STOCK_KEYS, value)

    def test_stock_svgs_exist_are_small_and_theme_aware(self):
        from pathlib import Path
        from django.conf import settings
        root = Path(settings.BASE_DIR) / 'static' / 'images' / 'asset-stock'
        for key in STOCK_KEYS:
            svg = (root / f'{key}.svg').read_text()
            self.assertLess(len(svg.encode()), 3072, key)
            self.assertIn('currentColor', svg)
            self.assertNotIn('<script', svg.lower())

    def test_precedence_photo_then_chosen_artwork_then_device_then_stock(self):
        from hardware.models import HardwareDevice
        asset = Asset.objects.create(organization=self.a, name='sw-01', asset_type='switch')
        self.assertEqual(asset.image_kind, 'stock')
        HardwareDevice.objects.create(organization=self.a, asset=asset, hardware_model=self.hm2)
        asset = Asset.objects.get(pk=asset.pk)
        # A documented hardware device shows its model's artwork automatically.
        self.assertEqual(asset.image_kind, 'artwork')
        self.assertIn(reverse('hardware:model_art', args=[self.hm2.pk, 'front']), asset.image_url)
        # A model the user picked wins over the device's own model.
        asset.image_source, asset.artwork_model = 'artwork', self.hm
        self.assertIn(reverse('hardware:model_art', args=[self.hm.pk, 'front']), asset.image_url)
        # A chosen photo wins over everything.
        asset.image_source = 'photo'
        asset.photo = 'assets/photos/2026/11/x.jpg'
        self.assertEqual(asset.image_kind, 'photo')
        self.assertTrue(asset.image_url.endswith('assets/photos/2026/11/x.jpg'))
        # Photo chosen but missing: fall through to the device artwork.
        asset.photo = None
        self.assertEqual(asset.image_kind, 'artwork')
        self.assertIn(reverse('hardware:model_art', args=[self.hm2.pk, 'front']), asset.image_url)
