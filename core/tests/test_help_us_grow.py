"""The "Help Us Grow" call to action — entry button, modal and its links.

Three things are worth protecting here and none of them is cosmetic:

1. **Every destination comes from `config/support_links.py`.** The point of
   the config module is that the modal can be lifted into another of our apps
   by editing one file, so a URL typed into the template is a regression even
   when the URL is correct.
2. **The shared URL is the public one.** Sharing the running install would
   hand out a private dashboard address, often a tenant hostname, sometimes
   one carrying a token.
3. **It never opens by itself.** It is an ask, and an ask that interrupts
   people is a worse ask.
"""
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from config.support_links import DEFAULTS, get_support_links
from core.models import Organization, SystemSetting


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

REPO_ROOT = Path(django_settings.BASE_DIR)
MODAL_TEMPLATE = REPO_ROOT / 'templates' / 'core' / '_help_us_grow_modal.html'
BUTTON_TEMPLATE = REPO_ROOT / 'templates' / 'core' / '_help_us_grow_button.html'
UI_CSS = REPO_ROOT / 'static' / 'css' / 'ui.css'
HUG_JS = REPO_ROOT / 'static' / 'js' / 'help_us_grow.js'


class SupportLinksConfigTests(TestCase):
    """The config module itself — no request needed."""

    def test_the_share_message_carries_the_public_url(self):
        data = get_support_links()
        self.assertIn(data['PROJECT']['public_url'], data['SHARE_MESSAGE'])

    def test_the_share_message_follows_the_agreed_shape(self):
        data = get_support_links()
        self.assertTrue(data['SHARE_MESSAGE'].startswith('Check out '))
        self.assertIn('If it looks useful, give it a try and pass it along!',
                      data['SHARE_MESSAGE'])

    def test_the_share_message_fits_a_single_post(self):
        """X counts a link as 23 characters however long it is."""
        data = get_support_links()
        url = data['PROJECT']['public_url']
        weighted = len(data['SHARE_MESSAGE']) - len(url) + 23
        self.assertLessEqual(weighted, 280, 'share message would be truncated')

    def test_every_configured_url_is_public_https(self):
        data = get_support_links()
        urls = [data['PROJECT']['public_url'], data['PROJECT']['repo_url'],
                data['GITHUB']['org_url'], data['SPONSOR']['url'],
                data['BUSINESS']['url'], data['BUSINESS']['facebook_url']]
        urls += [p['url'] for p in data['NETWORK']]
        for url in urls:
            self.assertTrue(url.startswith('https://'), url)
            # A token in a shared URL is the failure this guards against.
            self.assertNotIn('token', url.lower())
            self.assertNotIn('?', url)

    def test_the_network_covers_both_named_projects(self):
        urls = {p['url'] for p in get_support_links()['NETWORK']}
        self.assertIn('https://mspreboot.com', urls)
        self.assertIn('https://mspzero.com', urls)

    def test_the_network_message_names_both_projects(self):
        message = get_support_links()['NETWORK_MESSAGE']
        self.assertIn('https://mspreboot.com', message)
        self.assertIn('https://mspzero.com', message)
        self.assertIn('pass them along', message)

    def test_the_verified_sponsorship_link_is_preserved(self):
        """This URL shipped before the rebuild and must survive it."""
        self.assertEqual(get_support_links()['SPONSOR']['url'],
                         'https://github.com/sponsors/agit8or1')

    def test_only_this_project_claims_to_be_open_source(self):
        """The others are products and services; we do not speak for them."""
        self.assertTrue(DEFAULTS['PROJECT']['is_open_source'])
        for project in DEFAULTS['NETWORK']:
            blurb = (project['description'] + ' ' + project['name']).lower()
            self.assertNotIn('open source', blurb)
            self.assertNotIn('open-source', blurb)
            self.assertNotIn('free', blurb)

    @override_settings(SUPPORT_LINKS={'SPONSOR': {'url': ''}})
    def test_settings_can_override_one_key_without_losing_the_rest(self):
        data = get_support_links()
        self.assertEqual(data['SPONSOR']['url'], '')
        # A shallow merge, so the sibling key survives.
        self.assertEqual(data['SPONSOR']['label'], 'GitHub Sponsors')
        self.assertEqual(data['PROJECT']['name'], 'ClientSt0r')


class TemplatesCarryNoUrlsTests(TestCase):
    """The config module is the only place a destination may be written."""

    def test_the_modal_template_hard_codes_no_destinations(self):
        markup = MODAL_TEMPLATE.read_text()
        # The network share endpoints are the share mechanism rather than one
        # of our destinations, so they legitimately live in the markup.
        allowed = ('linkedin.com/sharing', 'facebook.com/sharer',
                   'twitter.com/intent')
        for match in re.findall(r'https?://[^\s"\'<>]+', markup):
            self.assertTrue(any(a in match for a in allowed),
                            f'{match} belongs in config/support_links.py')

    def test_the_button_template_hard_codes_nothing(self):
        self.assertNotIn('http', BUTTON_TEMPLATE.read_text())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RenderedPageTests(TestCase):

    def setUp(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.save()
        Organization.objects.create(name='Grow Co', slug='grow-co')
        self.user = get_user_model().objects.create_user(
            'grow_su', 'g@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.support = get_support_links()

    def _html(self):
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    # -- the entry button ----------------------------------------------------

    def test_the_navbar_carries_a_heart_labelled_help_us_grow(self):
        html = self._html()
        self.assertIn('nav-link nav-util nav-help-grow', html)
        self.assertIn('fas fa-heart nav-help-grow__heart', html)
        self.assertIn('>Help Us Grow<', html)

    def test_the_button_is_reachable_and_named_on_every_screen_size(self):
        """The label is hidden at some widths, so the name cannot rely on it."""
        html = self._html()
        self.assertIn('aria-label="Help Us Grow"', html)
        self.assertIn('nav-help-grow__label', html)

    def test_the_button_opens_the_modal(self):
        html = self._html()
        self.assertIn('data-bs-target="#supportProjectModal"', html)
        self.assertIn('id="supportProjectModal"', html)

    def test_the_heart_is_hidden_from_screen_readers(self):
        """The accessible name is on the link; the icon would duplicate it."""
        html = self._html()
        heart = html[html.index('nav-help-grow__heart'):][:120]
        self.assertIn('aria-hidden="true"', heart)

    def test_the_modal_id_that_shipped_before_is_preserved(self):
        """The account menu points at it, and so may anything else."""
        self.assertEqual(self._html().count('data-bs-target="#supportProjectModal"'), 2)

    # -- it is never opened for you ------------------------------------------

    def test_the_modal_is_not_shown_on_load(self):
        html = self._html()
        opening = html[html.index('id="supportProjectModal"') - 200:
                       html.index('id="supportProjectModal"') + 200]
        self.assertNotIn('modal fade show', opening)
        self.assertNotIn('class="modal show', opening)

    def test_nothing_opens_the_modal_from_script(self):
        js = HUG_JS.read_text()
        self.assertNotIn('.show()', js)
        self.assertNotIn('new bootstrap.Modal', js)

    # -- the copy ------------------------------------------------------------

    def test_the_headline_and_intro_are_present(self):
        html = self._html()
        self.assertIn('Help us grow.', html)
        self.assertIn('A quick share, a GitHub star, or a recommendation can '
                      'make a real difference.', html)

    def test_every_section_is_present_in_order_with_sharing_first(self):
        html = self._html()
        body = html[html.index('id="supportProjectModal"'):]
        positions = [body.index(heading) for heading in (
            'Share the project',
            'Discover &amp; share our other projects',
            'Star &amp; explore on GitHub',
            'Sponsor development',
            'Support our business',
        )]
        self.assertEqual(positions, sorted(positions),
                         'sharing must lead and the rest must follow in order')

    def test_the_closing_line_is_present(self):
        self.assertIn('Every share, recommendation, star, and contribution '
                      'helps.', self._html())

    # -- sharing -------------------------------------------------------------

    def test_the_primary_share_action_offers_the_native_sheet(self):
        html = self._html()
        self.assertIn('Share This Project', html)
        self.assertIn('data-hug-share', html)
        self.assertIn('navigator.share', HUG_JS.read_text())

    def test_the_three_copy_actions_are_present(self):
        html = self._html()
        self.assertIn('Copy Link', html)
        self.assertIn('Copy Ready-to-Post Message', html)
        self.assertIn('Copy Network Message', html)

    def test_copy_feedback_only_follows_a_successful_copy(self):
        js = HUG_JS.read_text()
        # The success message is announced from the resolve path, and the
        # reject path falls through to the fallback instead.
        self.assertIn('writeText(text).then(succeed, fail)', js)
        self.assertIn('execCommand', js)
        self.assertIn('press Ctrl+C', js)

    def test_a_cancelled_share_is_not_reported_as_an_error(self):
        self.assertIn("err.name === 'AbortError'", HUG_JS.read_text())

    def test_all_four_sharing_networks_are_offered(self):
        html = self._html()
        for marker in ('linkedin.com/sharing/share-offsite',
                       'facebook.com/sharer/sharer.php',
                       'twitter.com/intent/tweet',
                       'href="mailto:?subject='):
            self.assertIn(marker, html)

    def test_the_share_message_is_shown_for_review_before_sending(self):
        html = self._html()
        self.assertIn('id="hugShareMessage"', html)
        self.assertIn('Each option opens a draft you send yourself', html)

    def test_what_is_shared_is_the_public_url_not_this_install(self):
        html = self._html()
        self.assertIn(self.support['PROJECT']['public_url'], html)
        # `testserver` is the Django test client's host — stand-in for the
        # private dashboard address of a real install.
        modal = html[html.index('id="supportProjectModal"'):]
        self.assertNotIn('testserver', modal)

    # -- the other projects --------------------------------------------------

    def test_each_other_project_gets_visit_and_share_separately(self):
        html = self._html()
        modal = html[html.index('id="supportProjectModal"'):]
        for project in self.support['NETWORK']:
            self.assertIn(project['url'], modal)
            self.assertIn(f'aria-label="Visit {project["name"]}"', modal)
            self.assertIn(f'aria-label="Share {project["name"]}"', modal)
            self.assertIn(f'aria-label="Copy link to {project["name"]}"', modal)

    def test_the_network_message_is_offered_ready_to_copy(self):
        html = self._html()
        self.assertIn('id="hugNetworkMessage"', html)
        self.assertIn('Know an MSP or business owner looking for useful tools',
                      html)

    # -- github, sponsorship, business ---------------------------------------

    def test_github_offers_both_a_star_and_the_profile(self):
        html = self._html()
        self.assertIn('Star This Project', html)
        self.assertIn('Explore Our GitHub', html)
        self.assertIn('https://github.com/agit8or1"', html)

    def test_the_sponsor_button_uses_the_verified_link(self):
        html = self._html()
        self.assertIn('Sponsor Development', html)
        self.assertIn('https://github.com/sponsors/agit8or1', html)

    def test_the_business_section_offers_visit_share_and_facebook(self):
        html = self._html()
        self.assertIn('Visit MSP Reboot', html)
        self.assertIn('Share MSP Reboot', html)
        self.assertIn('Follow MSP Reboot on Facebook', html)
        self.assertIn('https://facebook.com/mspreboot', html)

    def test_every_outbound_link_is_opened_safely(self):
        """`target="_blank"` without `rel` hands the opener to the new tab."""
        html = self._html()
        modal = html[html.index('id="supportProjectModal"'):]
        for chunk in modal.split('target="_blank"')[1:]:
            self.assertIn('noopener', chunk[:120])

    # -- graceful omission ---------------------------------------------------

    @override_settings(SUPPORT_LINKS={'SPONSOR': {'url': ''}})
    def test_sponsorship_is_omitted_when_no_destination_is_configured(self):
        html = self._html()
        self.assertNotIn('Sponsor Development', html)
        self.assertNotIn('Sponsor development', html)
        # The rest of the modal still renders.
        self.assertIn('Share This Project', html)

    @override_settings(SUPPORT_LINKS={'PROJECT': {
        'name': 'ClientSt0r', 'description': 'a test', 'public_url':
        'https://example.com', 'repo_url': ''}})
    def test_the_star_button_is_omitted_when_no_repository_is_known(self):
        html = self._html()
        self.assertNotIn('Star This Project', html)
        self.assertIn('Explore Our GitHub', html)

    @override_settings(SUPPORT_LINKS={'NETWORK': []})
    def test_the_other_projects_section_is_omitted_when_empty(self):
        html = self._html()
        self.assertNotIn('Discover &amp; share our other projects', html)
        self.assertIn('Share This Project', html)


class PresentationTests(TestCase):
    """The animation contract. Asserted against the stylesheet because the
    rule it replaced was a deliberate decision to stop the heart pulsing —
    a future reader needs to find a test saying the pulse is wanted now."""

    def test_the_heartbeat_exists(self):
        css = UI_CSS.read_text()
        self.assertIn('@keyframes hug-heartbeat', css)
        self.assertIn('@keyframes hug-heart-glow', css)

    def test_the_heartbeat_is_gated_on_reduced_motion(self):
        css = UI_CSS.read_text()
        gate = css.index('@media (prefers-reduced-motion: no-preference)',
                         css.index('nav-help-grow__heart'))
        block = css[gate:gate + 600]
        self.assertIn('animation: hug-heartbeat', block)

    def test_reduced_motion_still_gets_the_glow(self):
        """Respecting the preference must not mean a plain grey icon."""
        css = UI_CSS.read_text()
        base = css[css.index('.navbar .nav-help-grow__heart {'):]
        base = base[:base.index('}')]
        self.assertIn('text-shadow', base)
        self.assertNotIn('animation', base)

    def test_the_rule_that_suppressed_the_pulse_is_gone(self):
        self.assertNotIn('[style*="heartbeat"]', UI_CSS.read_text())

    def test_the_modal_stays_inside_the_viewport(self):
        markup = MODAL_TEMPLATE.read_text()
        self.assertIn('modal-dialog-scrollable', markup)
        self.assertIn('modal-dialog-centered', markup)

    def test_the_modal_has_an_obvious_close_control(self):
        markup = MODAL_TEMPLATE.read_text()
        self.assertIn('btn-close', markup)
        self.assertEqual(markup.count('data-bs-dismiss="modal"'), 2,
                         'expected the header X and a footer Close button')

    def test_copy_results_are_announced_to_assistive_tech(self):
        markup = MODAL_TEMPLATE.read_text()
        self.assertIn('aria-live="polite"', markup)
        self.assertIn('role="status"', markup)

    def test_no_multi_line_hash_comment_leaks_into_the_page(self):
        """Django's `{# #}` is single-line only.

        A `{# ... #}` spanning two lines is not a comment — it renders as
        body text. One did, and the words "Star This Project" from an
        explanatory note appeared inside the modal. Both partials are checked
        because the mistake is invisible until you read the rendered page.
        """
        for template in (MODAL_TEMPLATE, BUTTON_TEMPLATE):
            for match in re.findall(r'\{#(.*?)#\}', template.read_text(), re.S):
                self.assertNotIn('\n', match,
                                 f'{template.name}: multi-line {{# #}} renders '
                                 f'as text — use {{% comment %}}')
