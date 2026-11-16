"""Code-scanning alert fixes (v3.17.691 onward).

Each test pins one fix for a GitHub code-scanning alert, so the pattern the
alert found cannot come back unnoticed.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)


class KanbanDropUrlTests(SimpleTestCase):
    """CodeQL js/request-forgery: the pipeline board built its POST URL from
    the drag payload, which another page or application can supply."""

    def setUp(self):
        self.src = (ROOT / 'templates/crm/pipeline_kanban.html').read_text()

    def test_url_id_does_not_come_from_drag_payload(self):
        drop = self.src.split("col.addEventListener('drop'", 1)[1]
        self.assertNotIn('getData(', drop)
        self.assertIn('dragged.dataset.oppId', drop)

    def test_only_a_numeric_id_reaches_the_url(self):
        drop = self.src.split("col.addEventListener('drop'", 1)[1]
        check = drop.index("/^[0-9]+$/.test(")
        fetch_at = drop.index('fetch(')
        self.assertLess(check, fetch_at)
        self.assertRegex(drop, re.escape('encodeURIComponent(oppId)'))


# ---------------------------------------------------------------------------
# v3.17.693 — high-severity batch
# ---------------------------------------------------------------------------

import io
import time
import zipfile
from types import SimpleNamespace
from unittest import mock


class HardwareDomXssTests(SimpleTestCase):
    """CodeQL js/xss-through-dom in the hardware device page."""

    def setUp(self):
        self.src = (ROOT / 'hardware/static/hardware/device.js').read_text()

    def test_far_end_name_is_inserted_as_text(self):
        # dataset.text is the *decoded* attribute value: raw device / port names.
        self.assertNotIn("'Far end: <strong>' + b.dataset.text", self.src)
        self.assertIn('strong.textContent = b.dataset.text', self.src)

    def test_colours_reach_style_only_as_hex(self):
        self.assertNotIn('style="background:${v.color}"', self.src)
        self.assertIn("const cssColor = c => /^#[0-9a-f]{3,8}$/i.test(", self.src)


class PortConfigFormEscapingTests(SimpleTestCase):
    def test_port_and_vlan_fields_are_escaped(self):
        src = (ROOT / 'templates/assets/port_config_form.html').read_text()
        for field in ('port.description', 'port.vlan', 'vlan.name', 'vlan.description'):
            self.assertNotIn('value="${%s' % field, src)
            self.assertIn('value="${escAttr(%s' % field, src)


class SavedQueryFormEscapingTests(SimpleTestCase):
    def test_saved_filter_value_and_names_are_escaped(self):
        src = (ROOT / 'templates/reports/saved_query_form.html').read_text()
        self.assertIn('escHtml(filter.value)', src)
        self.assertNotIn("'\">' + col + '</label>'", src)
        self.assertNotIn("'>' + f.name + '</option>'", src)


class NavigateGuardTests(SimpleTestCase):
    def test_backslash_host_is_not_followed(self):
        src = (ROOT / 'static/js/csp-events.js').read_text()
        self.assertIn(r"if (/^\/(?![\/\\])/.test(to)) window.location.assign('/' + to.slice(1));", src)


class SecretLinkScrubTests(SimpleTestCase):
    """CodeQL py/polynomial-redos in psa.ticket_secure."""

    def test_links_are_scrubbed(self):
        from psa.ticket_secure import SCRUBBED, scrub_secret_links
        text = ('Open https://psa.example.com/core/secret/AbC_-123/ or /core/secret/xyz '
                'and <https://a.example/core/secret/q1>.')
        self.assertEqual(
            scrub_secret_links(text),
            f'Open {SCRUBBED} or {SCRUBBED} and <{SCRUBBED}>.')
        self.assertEqual(scrub_secret_links('nothing here'), 'nothing here')
        self.assertEqual(scrub_secret_links(None), '')

    def test_url_is_removed_through_the_last_secret_path(self):
        from psa.ticket_secure import SCRUBBED, scrub_secret_links
        self.assertEqual(scrub_secret_links('x https://h/core/secret/a/core/secret/b! y'),
                         f'x {SCRUBBED}! y')

    def test_repeated_schemes_are_linear(self):
        from psa.ticket_secure import scrub_secret_links
        start = time.monotonic()
        scrub_secret_links('http://' * 100_000 + '/core/secret/abc')
        self.assertLess(time.monotonic() - start, 2.0)


class GraphOutboundAddressTests(SimpleTestCase):
    def test_addresses(self):
        from psa.graph_outbound import _EMAIL_RE
        for good in ('a@b.c', 'first.last@mail.example.co.uk'):
            self.assertTrue(_EMAIL_RE.match(good), good)
        for bad in ('a@b', 'a@b..c', 'a@.b', 'a@b.', 'a b@c.d', 'a@b@c.d'):
            self.assertFalse(_EMAIL_RE.match(bad), bad)

    def test_many_dots_are_linear(self):
        from psa.graph_outbound import _EMAIL_RE
        start = time.monotonic()
        _EMAIL_RE.match('a@' + 'b.' * 100_000 + '@')
        self.assertLess(time.monotonic() - start, 2.0)


class StripTagsTests(SimpleTestCase):
    def test_contract_pdf_strip_tags(self):
        from contracts.pdf import _strip_tags
        self.assertEqual(_strip_tags('<p>A &amp; <b>B</b></p>'), 'A & B')
        start = time.monotonic()
        _strip_tags('<' * 100_000)
        self.assertLess(time.monotonic() - start, 2.0)


class ServiceRequestSubjectTests(SimpleTestCase):
    def test_trailing_separators_and_space_runs(self):
        from psa.service_requests import _SUBJECT_SEP
        self.assertEqual(_SUBJECT_SEP.sub('', 'Laptop — '), 'Laptop')
        # Same result as the previous \\s* form for every collapsed subject.
        old = re.compile(r'\s*([—–:|,-])\s*(?=[—–:|,-]|$)')
        for subject in ('Laptop — | Bob', 'A - B', 'A —', 'A\t—\t|'):
            self.assertEqual(_SUBJECT_SEP.sub('', subject), old.sub('', subject), subject)


class RootHelperOutputTests(SimpleTestCase):
    """CodeQL py/clear-text-logging-sensitive-data: the sudo password must not
    come back in the output that is logged and shown."""

    def test_password_is_redacted_from_output(self):
        from core import root_helper
        done = SimpleNamespace(returncode=1, stdout='prompt: s3cr3t-pw\n', stderr='sudo: s3cr3t-pw wrong')
        with mock.patch.object(root_helper, 'bootstrap_script') as script, \
                mock.patch.object(root_helper.subprocess, 'run', return_value=done):
            script.return_value.is_file.return_value = True
            ok, output = root_helper.bootstrap_with_password('s3cr3t-pw')
        self.assertFalse(ok)
        self.assertNotIn('s3cr3t-pw', output)
        self.assertIn('[redacted]', output)


class DocxImportXmlTests(SimpleTestCase):
    """Semgrep use-defused-xml-parse: uploaded .docx XML refuses DTD entities."""

    def _docx(self, xml):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('word/document.xml', xml)
        buf.seek(0)
        buf.name = 'x.docx'
        return buf

    def test_plain_docx_text(self):
        from docs.services.document_import import extract_document_text
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>')
        result = extract_document_text(self._docx(xml))
        self.assertTrue(result['success'], result)
        self.assertEqual(result['text'], 'Hello')

    def test_entity_declarations_are_refused(self):
        from docs.services.document_import import extract_document_text
        xml = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
               '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>')
        result = extract_document_text(self._docx(xml))
        self.assertFalse(result['success'])
