"""
PSA ticket notes — posting a note to a third-party PSA ticket.

`PSAManager.add_ticket_note` used to decrypt the connection's credentials with
`decrypt_v2(connection.encrypted_credentials)`. The model stores that column as
`json.dumps({field: ciphertext, ...})` — a JSON object of per-value ciphertexts,
not one encrypted blob — so the call raised, `_get_credentials` returned None,
and every provider branch returned False at its first line. No note had ever
reached a PSA through this path, for any provider.

The two lower halves of the same bug are covered here as well: Autotask and
HaloPSA had no note implementation at all behind that dead credential check,
and the one caller ignored the return value entirely.
"""
from __future__ import annotations

import json
from unittest import mock

from django.test import TestCase, override_settings

from core.models import Organization
from .models import PSAConnection, PSATicket
from .psa_manager import PSAManager, PSANoteResult


def make_connection(org, provider_type='connectwise_manage', **creds):
    conn = PSAConnection(
        organization=org,
        provider_type=provider_type,
        name=f'{provider_type} test',
        base_url='https://psa.example.com',
    )
    conn.set_credentials(creds or {'api_key': 'k'})
    conn.save()
    return conn


def make_ticket(org, conn, external_id='4242'):
    return PSATicket.objects.create(
        organization=org,
        connection=conn,
        external_id=external_id,
        ticket_number='T-4242',
        subject='Laptop will not boot',
    )


class CredentialDecryptionTests(TestCase):
    """The regression that made every provider branch dead code."""

    def setUp(self):
        self.org = Organization.objects.create(name='Acme MSP')

    def test_connection_credentials_are_readable_by_the_provider_layer(self):
        conn = make_connection(
            self.org,
            'connectwise_manage',
            company_id='acme',
            public_key='pub',
            private_key='priv',
        )
        # The stored column is a JSON object of ciphertexts, which is exactly
        # what the old decrypt_v2(whole-column) call could not handle.
        stored = json.loads(PSAConnection.objects.get(pk=conn.pk).encrypted_credentials)
        self.assertIn('private_key', stored)
        self.assertNotIn('priv', stored['private_key'])

        creds = PSAConnection.objects.get(pk=conn.pk).get_credentials()
        self.assertEqual(creds['private_key'], 'priv')

    def test_note_is_attempted_rather_than_failing_on_credentials(self):
        conn = make_connection(self.org, 'connectwise_manage',
                               company_id='acme', public_key='pub', private_key='priv')
        ticket = make_ticket(self.org, conn)

        with mock.patch('integrations.providers.connectwise.ConnectWiseManageProvider'
                        '._make_request') as req:
            result = PSAManager().add_ticket_note(ticket, 'workflow done')

        self.assertTrue(result, result.detail)
        self.assertEqual(req.call_count, 1)
        method, endpoint = req.call_args[0]
        self.assertEqual(method, 'POST')
        self.assertIn(f'/tickets/{ticket.external_id}/notes', endpoint)


class ProviderNotePayloadTests(TestCase):
    """Each provider posts to its own documented ticket-note endpoint."""

    def setUp(self):
        self.org = Organization.objects.create(name='Acme MSP')

    def _post(self, provider_type, patch_target, internal=False, external_id='4242'):
        conn = make_connection(self.org, provider_type,
                               api_key='k', client_id='cid', client_secret='sec',
                               username='u', secret='s')
        ticket = make_ticket(self.org, conn, external_id=external_id)
        with mock.patch(patch_target) as req:
            result = PSAManager().add_ticket_note(ticket, 'workflow done', internal=internal)
        return result, req

    def test_connectwise_internal_note_is_internal_analysis(self):
        result, req = self._post(
            'connectwise_manage',
            'integrations.providers.connectwise.ConnectWiseManageProvider._make_request',
            internal=True,
        )
        self.assertTrue(result, result.detail)
        body = req.call_args.kwargs['json']
        self.assertTrue(body['internalAnalysisFlag'])
        self.assertFalse(body['detailDescriptionFlag'])

    def test_autotask_posts_to_the_ticket_notes_collection(self):
        result, req = self._post(
            'autotask',
            'integrations.providers.autotask.AutotaskProvider._make_request',
        )
        self.assertTrue(result, result.detail)
        self.assertEqual(req.call_args[0][1], '/v1.0/Tickets/4242/Notes')
        body = req.call_args.kwargs['json']
        self.assertEqual(body['ticketID'], 4242)
        self.assertEqual(body['description'], 'workflow done')
        self.assertTrue(body['title'])

    def test_autotask_internal_note_never_reaches_the_client_portal(self):
        from .providers.autotask import AutotaskProvider

        result, req = self._post(
            'autotask',
            'integrations.providers.autotask.AutotaskProvider._make_request',
            internal=True,
        )
        self.assertTrue(result, result.detail)
        self.assertEqual(req.call_args.kwargs['json']['publish'],
                         AutotaskProvider.PUBLISH_INTERNAL_ONLY)

    def test_autotask_rejects_a_non_numeric_ticket_id(self):
        result, req = self._post(
            'autotask',
            'integrations.providers.autotask.AutotaskProvider._make_request',
            external_id='not-a-number',
        )
        self.assertFalse(result)
        req.assert_not_called()

    def test_halo_posts_an_action_list(self):
        result, req = self._post(
            'halo_psa',
            'integrations.providers.halo.HaloPSAProvider._make_request',
        )
        self.assertTrue(result, result.detail)
        self.assertEqual(req.call_args[0][1], '/api/Actions')
        body = req.call_args.kwargs['json']
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]['ticket_id'], 4242)
        self.assertFalse(body[0]['hiddenfromuser'])

    def test_halo_internal_note_is_hidden_from_the_end_user(self):
        result, req = self._post(
            'halo_psa',
            'integrations.providers.halo.HaloPSAProvider._make_request',
            internal=True,
        )
        self.assertTrue(result, result.detail)
        self.assertTrue(req.call_args.kwargs['json'][0]['hiddenfromuser'])

    def test_syncro_internal_note_is_hidden_and_not_emailed(self):
        result, req = self._post(
            'syncro',
            'integrations.providers.syncro.SyncroProvider._make_request',
            internal=True,
        )
        self.assertTrue(result, result.detail)
        self.assertEqual(req.call_args[0][1], '/api/v1/tickets/4242/comment')
        body = req.call_args.kwargs['json']
        self.assertTrue(body['hidden'])
        self.assertTrue(body['do_not_email'])

    def test_itflow_posts_form_encoded(self):
        result, req = self._post(
            'itflow',
            'integrations.providers.itflow.ITFlowProvider._make_request',
        )
        self.assertTrue(result, result.detail)
        self.assertEqual(req.call_args[0][1], '/tickets/add_comment.php')
        self.assertIn('data', req.call_args.kwargs)
        self.assertEqual(req.call_args.kwargs['headers']['Content-Type'],
                         'application/x-www-form-urlencoded')


class NoteResultTests(TestCase):
    """A failure has to be distinguishable from a success by the caller."""

    def setUp(self):
        self.org = Organization.objects.create(name='Acme MSP')

    def test_provider_without_note_support_reports_unsupported(self):
        conn = make_connection(self.org, 'zendesk', api_key='k')
        ticket = make_ticket(self.org, conn)
        result = PSAManager().add_ticket_note(ticket, 'workflow done')
        self.assertFalse(result)
        self.assertEqual(result.reason, PSANoteResult.UNSUPPORTED)
        self.assertIn('does not support', result.detail)

    def test_transport_failure_reports_failed(self):
        conn = make_connection(self.org, 'syncro', api_key='k')
        ticket = make_ticket(self.org, conn)
        with mock.patch('integrations.providers.syncro.SyncroProvider._make_request',
                        side_effect=Exception('connection refused')):
            result = PSAManager().add_ticket_note(ticket, 'workflow done')
        self.assertFalse(result)
        self.assertEqual(result.reason, PSANoteResult.FAILED)

    def test_missing_ticket_reports_invalid_ticket(self):
        result = PSAManager().add_ticket_note(None, 'workflow done')
        self.assertFalse(result)
        self.assertEqual(result.reason, PSANoteResult.INVALID_TICKET)

    def test_result_is_truthy_only_on_success(self):
        self.assertTrue(PSANoteResult(PSANoteResult.OK, 'posted'))
        self.assertFalse(PSANoteResult(PSANoteResult.FAILED, 'nope'))

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_a_private_base_url_is_refused_before_anything_is_sent(self):
        """
        The old manager built its own requests against connection.base_url with
        no validation. Going through the provider layer means the SSRF guard
        every other outbound integration call gets applies here too.
        """
        conn = PSAConnection(
            organization=self.org,
            provider_type='syncro',
            name='internal',
            base_url='http://127.0.0.1:8000',
        )
        conn.set_credentials({'api_key': 'k'})
        conn.save()
        ticket = make_ticket(self.org, conn)

        with mock.patch('integrations.providers.syncro.SyncroProvider._make_request') as req:
            result = PSAManager().add_ticket_note(ticket, 'workflow done')

        self.assertFalse(result)
        req.assert_not_called()
