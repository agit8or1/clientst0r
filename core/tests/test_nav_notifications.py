"""The top bar's notification bell (core/notifications.py).

It adds up counts the app already keeps, each with the check of the page it
links to, caches them per user for a minute, and never lists a source the
user cannot open.
"""
import re

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from core import notifications
from core.models import SecureNote
from core.tests.test_navbar_grouping import TEST_MIDDLEWARE, NavbarTestBase

User = get_user_model()


def bell(html):
    if 'id="notifDropdown"' not in html:
        return None
    return html.split('id="notifDropdown"', 1)[1].split('</ul>', 1)[0]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NotificationBellTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        cache.clear()

    def note_for(self, user, sender):
        n = SecureNote(sender=sender, title='Hi')
        n.set_content('secret')
        n.save()
        n.recipients.add(user)
        return n

    def test_unread_secure_note_is_counted_and_linked(self):
        su = self.make_superuser()
        other = User.objects.create_user('bell_from', 'f@x.com', 'pw')
        self.note_for(su, other)
        html = self.page(su)
        b = bell(html)
        self.assertIsNotNone(b)
        self.assertIn('aria-label="Notifications: 1 new"', html)
        self.assertIn(f'href="{reverse("core:secure_note_inbox")}"', b)

    def test_counts_are_cached_for_a_minute(self):
        su = self.make_superuser()
        other = User.objects.create_user('bell_from2', 'f2@x.com', 'pw')
        self.page(su)
        self.note_for(su, other)
        html = self.client.get(reverse('core:dashboard'), follow=True).content.decode()
        self.assertIn('Notifications: nothing new', html)   # still the cached zero
        cache.clear()
        html = self.client.get(reverse('core:dashboard'), follow=True).content.decode()
        self.assertIn('Notifications: 1 new', html)

    def test_customer_gets_no_staff_sources(self):
        cust = self.make_customer()
        html = self.page(cust)
        b = bell(html) or ''
        for name in ('psa:approval_list', 'rmm_permissions:approvals', 'contracts:dashboard'):
            self.assertNotIn(reverse(name), b, name)

    def test_every_listed_source_opens(self):
        for user in (self.make_superuser(), self.make_technician(), self.make_customer()):
            cache.clear()
            html = self.page(user)
            for href in re.findall(r'href="(/[^"#?]*)"', bell(html) or ''):
                with self.subTest(user=user.username, href=href):
                    self.assertNotEqual(self.client.get(href).status_code, 403)

    def test_signed_out_gets_nothing(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(notifications.for_context({'user': AnonymousUser()}),
                         {'items': [], 'total': 0})

    def test_a_failing_source_does_not_break_the_page(self):
        su = self.make_superuser()
        original = notifications.SOURCES
        def boom(user, ctx):
            raise RuntimeError('source down')
        notifications.SOURCES = original + (('boom', 'Boom', 'fa-x', 'core:dashboard', boom),)
        try:
            self.page(su)
        finally:
            notifications.SOURCES = original
