"""
s12 / s13 of the cross-peer run: the remediation chain between the real
ClientSt0r and the real Rem0te, with approval ONLY inside Rem0te.

  s12  Rem0te SERVICE_STOPPED alert (Print Spooler) → ClientSt0r ticket (alert
       policy) → support workflow → the L2 technician proposes the catalog
       action windows.service.start@1 → Rem0te: awaiting_approval → the same
       proposal again is the same job; a changed body is 409 → the proposing
       technician cannot approve (on the signer's roster or not), asking for the
       fix on the ticket is not approval, ClientSt0r has no approve route →
       a distinct approver approves on Rem0te's approval signer with a passkey →
       the next heartbeat delivers the signed envelope → Rem0te's own agent
       decision code (rem0te-action-sim) verifies and runs it against a
       simulated Windows → the result is reported on a heartbeat → ClientSt0r
       polls it and writes a staff-only note → the monitor sees the Spooler
       running → alert.resolved → the workflow run is verified by monitoring.
  s13  The same business in the signer's direct mode: a ClientSt0r proposal is
       refused (DIRECT_MODE_PORTAL_ONLY) and ClientSt0r records the refusal.

The approval signer, its key, its roster, the approvers' passkeys and the
signed update repository are test-only and live in the run's work directory
(rem0te_approval.mjs). They need two binaries built from Rem0te's
tools/windows-installer (Go): RELEASE_BIN (cmd/rem0te-release) and ACTION_SIM
(cmd/rem0te-action-sim) — the same ones Rem0te's e2e-approved-action uses.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path

H = {}

ACTION = 'windows.service.start@1'
SIGNER_ORIGIN = 'https://approve.cross-peer.invalid'  # never resolved: the harness talks to 127.0.0.1


def bind(**helpers):
    H.update(helpers)


def check(*a, **k):
    return H['check'](*a, **k)


class Unavailable(Exception):
    pass


class RemediationChain:
    # -- Rem0te-side test machinery ------------------------------------------
    def approval_node(self, cmd, arg, timeout=300):
        env = dict(os.environ, REM0TE_SRC=str(self.src), DATABASE_URL=self.db)
        r = subprocess.run([self.a.node, str(H['here'] / 'rem0te_approval.mjs'), cmd, json.dumps(arg)], env=env,
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f'rem0te_approval {cmd} failed: {r.stderr[-2000:]}')
        return json.loads(r.stdout or 'null')

    def signer_main(self):
        return self.src / 'apps' / 'api' / 'dist' / 'approval-signer' / 'main.js'

    def signer_env(self):
        env = dict(os.environ, APPROVAL_SIGNER_DIR=str(self.work / 'signer'), APPROVAL_ORIGIN=SIGNER_ORIGIN,
                   APPROVAL_RP_ID='approve.cross-peer.invalid',
                   APPROVAL_PUBLIC_PORT=str(self.a.signer_public_port),
                   APPROVAL_INTERNAL_PORT=str(self.a.signer_internal_port))
        env.pop('DATABASE_URL', None)  # the signer has no database
        return env

    def signer_cli(self, *args):
        return subprocess.run([self.a.node, str(self.signer_main()), *args], env=self.signer_env(),
                              capture_output=True, text=True, timeout=60)

    @property
    def signer_public(self):
        return f'http://127.0.0.1:{self.a.signer_public_port}'

    def ensure_signer(self):
        """Release repo + signer key (offline), signer process, Rem0te restarted
        pointed at both, pairing re-checked so ClientSt0r sees the catalog."""
        if self.signer:
            return self.signer
        rb, sim = os.environ.get('RELEASE_BIN', ''), os.environ.get('ACTION_SIM', '')
        if not (rb and Path(rb).is_file() and sim and Path(sim).is_file()):
            raise Unavailable('RELEASE_BIN (rem0te-release) and ACTION_SIM (rem0te-action-sim) are required: build them '
                              'from Rem0te\'s tools/windows-installer (go build ./cmd/rem0te-release ./cmd/rem0te-action-sim)')
        rel = self.approval_node('release', {'work': str(self.work), 'releaseBin': rb})
        self.procs['signer'] = H['Proc']('signer', [self.a.node, str(self.signer_main()), 'serve'], self.signer_env(),
                                         str(self.src / 'apps' / 'api'), self.logs).start()
        up = H['wait_for'](lambda: H['http_json']('GET', f'http://127.0.0.1:{self.a.signer_internal_port}'
                                                         f'/internal/v1/keys')[0] == 200, 30, 0.5)
        if not up:
            raise RuntimeError('the approval signer did not start:\n' + self.procs['signer'].tail())
        self.r_extra_env = {'UPDATE_REPO_DIR': rel['repo'],
                            'APPROVAL_SIGNER_INTERNAL_URL': f'http://127.0.0.1:{self.a.signer_internal_port}'}
        self.stop_rem0te()
        self.start_rem0te()
        from integrations.rem0te import pairing
        for conn in self.conns.values():
            pairing.check(conn)
            conn.refresh_from_db()
        self.signer = rel
        self.sim = sim
        return rel

    def rem0te_user(self, ext, tech):
        from integrations.rem0te import pairing
        return self.fx['users'][f'{ext}/{pairing.technician_id(tech)}']

    def signed_heartbeat(self, ext, **extra):
        """The heartbeat a signed agent on the published build sends."""
        return self.heartbeat(ext, 60_000, updateChannel='signed', agentActions=[ACTION],
                              agentSha256=self.signer['agentSha256'], **extra)

    def monitor_report(self, ext, status):
        ep = self.fx['endpoints'][ext]
        return H['http_json']('POST', f'{self.r_url}/api/v1/enrollment/monitor-report', {
            'rustdeskId': ep['rid'], 'agentSecret': ep['secret'],
            'services': [{'name': 'Spooler', 'status': status, 'startType': 'Automatic'}]},
            headers={'X-Forwarded-For': '10.1.2.3'})

    def agent_state(self, ext):
        d = self.work / f'agent-{ext}'
        d.mkdir(exist_ok=True)
        return d

    def run_agent(self, ext, job_id, envelope):
        """Rem0te's own agent verifier and executor (internal/action) against a
        simulated Windows, as Rem0te's e2e-approved-action runs it."""
        ep, st = self.fx['endpoints'][ext], self.agent_state(ext)
        env_file = self.work / f'envelope-{job_id}.json'
        env_file.write_text(json.dumps(envelope))
        out = subprocess.run([self.sim, '-state', str(st), '-keys', self.signer['keysFile'], '-job', job_id,
                              '-envelope', str(env_file), '-rustdesk-id', ep['rid'], '-secret', ep['secret'],
                              '-product-type', '1', '-self-sha', self.signer['agentSha256'],
                              '-portal', f'127.0.0.1:{self.a.rem0te_port}'],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise RuntimeError(f'rem0te-action-sim: {out.stderr[-1500:]}')
        return json.loads(out.stdout.strip())

    def agent_results(self, ext):
        d = self.agent_state(ext) / 'actions' / 'results'
        return [json.loads(f.read_text()) for f in sorted(d.glob('*.json'))] if d.is_dir() else []

    def approve(self, job_id, tag, decision='approve'):
        return self.approval_node('approve', {'work': str(self.work), 'jobId': job_id, 'tag': tag,
                                              'origin': SIGNER_ORIGIN, 'publicUrl': self.signer_public,
                                              'decision': decision})

    def _guard(self, key, fn):
        try:
            return fn()
        except Unavailable as e:
            check(os.environ.get('E2E_ALLOW_SKIP') == '1', f'{key} needs the approval machinery', str(e))
            return None

    # -- s12 -------------------------------------------------------------------
    def s12_remediation_chain(self):
        H['section']('s12', 'Remediation chain: Rem0te alert → ticket → proposal → approval inside Rem0te → '
                            'agent → result note → alert.resolved → workflow verified')
        self._guard('s12', self._s12)

    def _s12(self):
        from integrations.rem0te import pairing
        from psa.routing.models import ALERT_MODE_LEGACY, ALERT_MODE_POLICY, AlertPolicySettings

        rel = self.ensure_signer()
        conn, ext = self.conns[self.oa], self.oa
        check(ACTION in {a['key'] for a in pairing.proposable_actions(conn)},
              'with a signer configured, Rem0te advertises windows.service.start@1 and ClientSt0r offers it',
              pairing.last_check(conn).get('features'))

        # Rem0te side (scratch only): the technician may request actions; a
        # distinct approver; both on the signer's roster with passkeys.
        tech_r = self.rem0te_user(ext, self.tech_a)
        self.node('caps', {'userId': tech_r, 'customerId': self.fx['businesses'][ext],
                           'capabilities': ['computers:view', 'integration:ticket_analysis', 'actions:request']})
        appr = self.node('user', {'sfx': self.sfx, 'tag': 'approver', 'platformPermissions': ['technicians:manage']})
        self.fx['users']['approver/olivia'] = appr['id']  # removed by cleanup
        roster = self.approval_node('enrol', {'work': str(self.work), 'api': f'{self.r_url}/api/v1', 'members': [
            {'tag': 'requester', 'userId': tech_r, 'approve': ['*']},
            {'tag': 'approver', 'userId': appr['id'], 'approve': ['*']}]})
        check(all(v.get('added') for v in roster.values()),
              'roster ceremony: the requester and a distinct approver are on the signer\'s roster '
              '(export and fingerprint read from Rem0te\'s own Passkeys list)', roster)
        self.node('serviceRule', {'customerId': self.fx['businesses'][ext], 'service': 'Spooler'})
        st, body = self.signed_heartbeat(ext)
        check(st in (200, 201), 'FRONTDESK-01 checks in as a signed agent on the published build', f'{st} {body}')

        s = AlertPolicySettings.load()
        mode_before = s.mode
        s.mode = ALERT_MODE_POLICY
        s.save()
        try:
            self._s12_chain(conn, ext, rel, tech_r, appr['id'])
        finally:
            s = AlertPolicySettings.load()
            s.mode = mode_before or ALERT_MODE_LEGACY
            s.save()

    def _s12_chain(self, conn, ext, rel, tech_r, approver_id):
        from integrations.rem0te import actions as rem0te_actions, client, protocol
        from integrations.rem0te.jobs import ticket_ext_id
        from psa.models import TicketComment
        from psa.routing.models import AlertTicketLink
        from psa.support_workflows.models import WorkflowRun
        from psa_ai.models import Rem0teAlertTicket, RMMRequest
        from psa_ai.services import rmm_actions
        wait_for = H['wait_for']

        # 1. Rem0te alert → ClientSt0r ticket.
        st, body = self.monitor_report(ext, 'Stopped')
        check(st in (200, 201), 'the agent reports the Print Spooler stopped', f'{st} {body}')
        link = wait_for(lambda: AlertTicketLink.objects.filter(connection=conn, category='service',
                                                               ticket__isnull=False).first(), 60, 1)
        check(link is not None, 'Rem0te pushed a signed SERVICE_STOPPED alert.raised; the alert policy opened a ticket',
              (self.node('alert', {'endpointId': self.fx['endpoints'][ext]['id']}),
               list(AlertTicketLink.objects.filter(connection=conn).values('category', 'disposition', 'reason'))))
        if link is None:
            return
        t = link.ticket
        row = Rem0teAlertTicket.objects.filter(connection=conn, alert_id=link.external_id).first()
        check(row is not None and row.kind == 'SERVICE_STOPPED' and row.ticket_id == t.pk,
              'the Rem0te alert row points at the same ticket', row and (row.kind, row.ticket_id))
        check(t.organization_id == self.org_a.pk and t.visibility == 'staff' and not t.client_can_view
              and t.related_asset_id == self.assets[ext].pk,
              'the ticket is Acme\'s, staff-only, about Acme\'s FRONTDESK-01', (t.visibility, t.related_asset_id))

        # 2. The L2 technician takes the ticket, runs the support workflow and
        #    proposes the catalog action (L2 covers its own tickets only).
        t.assigned_to = self.tech_a
        t.save()
        c = self.client(self.tech_a, self.org_a)
        r = c.post(f'/psa/workflows/t/{t.ticket_number}/', {'workflow': 'service-stopped', 'link': link.pk})
        run = WorkflowRun.objects.filter(ticket=t).order_by('-created_at').first()
        check(run is not None and (run.facts or {}).get('service_name') == 'spooler',
              'support workflow "service-stopped" started from the alert (service: spooler)',
              (r.status_code, run and run.facts))
        if run is None:
            return
        offered = [x for x in run.remediations if x['offered']]
        check([x['action'] for x in offered] == [ACTION], 'it offers exactly windows.service.start@1', run.remediations)
        key = f'wf-{secrets.token_hex(6)}'
        c.post(f'/psa/workflows/runs/{run.pk}/', {'op': 'propose', 'action': ACTION, 'key': key})
        run.refresh_from_db()
        req = run.rmm_request
        check(req is not None and run.status == 'awaiting_approval' and req.remote_status == 'awaiting_approval'
              and req.remote_id, 'the L2 technician\'s proposal: Rem0te answers awaiting_approval',
              (run.status, req and (req.status, req.remote_status, req.error)))
        if req is None or not req.remote_id:
            return
        job_id = req.remote_id
        check(req.approvals_required == 1 and req.approval_url == f'{SIGNER_ORIGIN}/approve/{job_id}',
              'one approval (standard workstation), on the signer\'s own origin — ClientSt0r only links to it',
              (req.approvals_required, req.approval_url))
        sent = req.payload['rem0te_proposal']
        check(sent['action'] == {'id': 'windows.service.start', 'version': 1} and sent['params'] == {'service': 'Spooler'}
              and not ({'command', 'script', 'path', 'url'} & set(sent)),
              'the proposal is the fixed catalog action and parameters, nothing else', sent)
        job = self.node('actionJob', {'id': job_id})
        check(job and job['status'] == 'AWAITING_APPROVAL' and job['via'] == 'clientst0r'
              and job['requestedById'] == tech_r, 'Rem0te records it AWAITING_APPROVAL, via clientst0r, requested '
              'by the mapped technician', job)

        # 3. Idempotency: the same bytes → the same proposal; a changed body → 409.
        def post(b):
            return client.request(conn, 'POST', '/action-proposals', b,
                                  delegation=('actions:propose', b['technician_id'],
                                              protocol.sha256_hex(protocol.canonical_json(b))))
        again = post(sent)
        check(again.status == 200 and (again.data or {}).get('job_id') == job_id
              and again.headers.get('idempotent-replayed') == 'true',
              're-sending the same proposal → 200, the same job (idempotent replay)',
              (again.status, again.headers, again.code))
        rem0te_actions.send(req)
        req.refresh_from_db()
        check(req.remote_id == job_id and req.remote_status == 'awaiting_approval',
              'ClientSt0r\'s own re-send (after a restart) lands on the same proposal', (req.remote_id, req.status))
        changed = post(dict(sent, reason=sent['reason'] + ' (edited)'))
        check(changed.status == 409, 'the same idempotency key with a changed body → 409',
              (changed.status, changed.code))
        try:
            rmm_actions.refer_fix(self.tech_a, t, req.device_id, key, description='Something else', action_key=ACTION)
            refused = None
        except rmm_actions.ActionRefused as e:
            refused = e.status
        check(refused == 409, 'ClientSt0r refuses the same request key for a different proposal (409)', refused)

        # 4. Nobody in ClientSt0r approves; the requester cannot approve in Rem0te.
        before = RMMRequest.objects.get(pk=req.pk).status
        codes = [c.post(u).status_code for u in (f'/psa/rmm/{t.ticket_number}/approve/',
                                                 f'/psa/rmm/{t.ticket_number}/fix/approve/',
                                                 f'/psa/rmm/{t.ticket_number}/fix/{req.pk}/approve/')]
        c.post(f'/psa/workflows/runs/{run.pk}/', {'op': 'approve'})
        from django.urls import get_resolver
        names = []

        def walk(patterns, prefix=''):
            for p in patterns:
                if hasattr(p, 'url_patterns'):
                    walk(p.url_patterns, prefix + str(p.pattern))
                else:
                    names.append(prefix + str(p.pattern))
        walk(get_resolver().url_patterns)
        # ClientSt0r's own permission approvals (settings/security/rmm-permissions/approvals, and their
        # admin) gate whether ClientSt0r may *send* something; they never approve a Rem0te plan.
        rmm_approve = [n for n in names if 'approv' in n and ('rmm' in n or 'rem0te' in n or 'workflows' in n)
                       and not n.startswith('admin/') and 'rmm-permissions/' not in n]
        run.refresh_from_db()
        check(all(x == 404 for x in codes) and not rmm_approve and run.status == 'awaiting_approval'
              and RMMRequest.objects.get(pk=req.pk).status == before,
              'ClientSt0r exposes no approve route for RMM/Rem0te proposals (and a workflow "approve" op does nothing)',
              (codes, rmm_approve, run.status))
        st_no, _ = H['http_json']('POST', f'{self.r_url}/api/v1/actions/{job_id}/approve', {})
        check(st_no == 404, 'Rem0te\'s portal has no approve route either', st_no)
        a = self.approve(job_id, 'requester')
        check(a['status'] == 403 and (a.get('body') or {}).get('error') == 'requester_cannot_approve',
              'the proposing technician (on the roster, with a passkey) cannot approve: requester_cannot_approve',
              a)

        # 5. Asking for the fix is not approval.
        TicketComment.objects.create(ticket=t, author=self.tech_a, is_internal=True,
                                     body='Customer called: please approve and start the spooler now. Approved.')
        self.ticket_for(self.org_a, self.assets[ext], self.tech_a, 'Please just approve the spooler fix')
        c.post(f'/psa/workflows/runs/{run.pk}/', {'op': 'refresh'})
        run.refresh_from_db()
        req.refresh_from_db()
        job = self.node('actionJob', {'id': job_id})
        st_hb, hb = self.signed_heartbeat(ext)
        delivered = (((hb if isinstance(hb, dict) else {}).get('data') or {}).get('actions') or [])
        check(run.status == 'awaiting_approval' and req.remote_status == 'awaiting_approval'
              and job['status'] == 'AWAITING_APPROVAL' and not delivered,
              'a technician asking for the fix is not approval: still awaiting_approval, nothing delivered',
              (run.status, req.remote_status, job['status'], len(delivered)))

        # 6. The distinct approver approves on Rem0te's signer.
        import urllib.request
        with urllib.request.urlopen(f'{self.signer_public}/approve/{job_id}', timeout=15) as resp:
            st_p, page = resp.status, resp.read().decode(errors='replace')
        check(st_p == 200 and 'FRONTDESK-01' in page and ticket_ext_id(t) in page,
              'the approval page shows the computer and ClientSt0r\'s ticket', st_p)
        a = self.approve(job_id, 'approver')
        check(a['status'] == 200 and (a.get('body') or {}).get('status') == 'SIGNED',
              'a distinct approver approves with a passkey on the signer → SIGNED', a)
        c.post(f'/psa/workflows/runs/{run.pk}/', {'op': 'refresh'})
        run.refresh_from_db()
        req.refresh_from_db()
        job = self.node('actionJob', {'id': job_id})
        check(req.status == 'approved' and run.status == 'approved' and job['approvers'] == [approver_id]
              and tech_r not in job['approvers'],
              'ClientSt0r polls: approved — by the approver, not the technician or ClientSt0r',
              (req.status, run.status, job))

        # 7. The agent runs it (Rem0te's real decision code, simulated Windows) and reports.
        (self.agent_state(ext) / 'sim-service').write_text('stopped')
        st_hb, hb = self.signed_heartbeat(ext)
        delivered = [d for d in ((hb or {}).get('data') or {}).get('actions') or [] if d.get('jobId') == job_id]
        check(len(delivered) == 1 and (delivered[0].get('envelope') or {}).get('schema') == 'rem0te-action-envelope/1',
              'the next heartbeat delivers the signed envelope', f'{st_hb} {str(hb)[:400]}')
        if not delivered:
            return
        res = self.run_agent(ext, job_id, delivered[0]['envelope'])
        check(res.get('outcome') == 'succeeded' and (res.get('observed') or {}).get('before') == 'stopped'
              and (self.agent_state(ext) / 'sim-service').read_text().strip() == 'running',
              'the agent verifies the plan (signature, target, approvals) and starts the spooler', res)
        st_hb, hb = self.signed_heartbeat(ext, actionResults=self.agent_results(ext))
        acks = ((hb or {}).get('data') or {}).get('actionAcks') or []
        check(job_id in acks, 'the result is reported on a heartbeat and acknowledged', f'{st_hb} {str(hb)[:300]}')
        c.post(f'/psa/workflows/runs/{run.pk}/', {'op': 'refresh'})
        run.refresh_from_db()
        req.refresh_from_db()
        check(req.status == 'succeeded' and req.remote_outcome == 'succeeded'
              and (req.observed or {}).get('before') == 'stopped',
              'ClientSt0r polls the terminal state: succeeded, with what the agent observed',
              (req.status, req.remote_outcome, req.observed))
        check(run.status == 'verifying', 'the workflow waits for monitoring to confirm (a job success is not the fix)',
              run.status)

        # 8. A staff-only note with the result.
        c.post(f'/psa/rmm/{t.ticket_number}/note/', {'request': str(req.pk)})
        note = TicketComment.objects.filter(ticket=t, source='rmm').order_by('-pk').first()
        check(note is not None and note.is_internal and 'succeeded' in note.body.lower()
              and 'Start the Print Spooler' in note.body,
              'the result is on the ticket as a staff-only note', note and note.body)
        check(not TicketComment.objects.filter(ticket=t, is_internal=False).exists(),
              'nothing on the ticket is customer-visible')
        bad = self.no_secrets(json.dumps([x.body for x in TicketComment.objects.filter(ticket=t)])
                              + json.dumps(req.payload) + req.status_note + req.error)
        check(not bad, 'no secrets in the notes or the stored proposal', bad)

        # 9. Monitoring sees it running: alert.resolved → the workflow outcome.
        st, body = self.monitor_report(ext, 'Running')
        check(st in (200, 201), 'the agent reports the Print Spooler running', f'{st} {body}')

        def resolved():
            link.refresh_from_db()
            run.refresh_from_db()
            if link.state != 'resolved' or run.status == 'verifying':
                self.monitor_report(ext, 'Running')
                return None
            return True
        wait_for(resolved, 60, 2)
        row = Rem0teAlertTicket.objects.filter(connection=conn, alert_id=link.external_id).first()
        check(link.state == 'resolved' and row and row.state == 'resolved',
              'Rem0te pushed alert.resolved; ClientSt0r recorded the recovery', (link.state, row and row.state))
        t.refresh_from_db()
        check(run.status == 'verified' and 'Confirmed by monitoring' in run.outcome_note
              and ((t.custom_fields or {}).get('support_workflows') or {}).get('service-stopped', {}).get('status')
              == 'verified', 'the support-workflow run records the outcome: verified by monitoring',
              (run.status, run.outcome_note))
        check(not t.status.is_terminal, 'the ticket stays open for a person to close', t.status.slug)

    # -- s13 -------------------------------------------------------------------
    def s13_direct_mode(self):
        H['section']('s13', 'Direct mode on the signer: ClientSt0r proposals are refused (DIRECT_MODE_PORTAL_ONLY)')
        self._guard('s13', self._s13)

    def _s13(self):
        from integrations.models import RMMDevice
        from psa_ai.models import RMMRequest
        self.ensure_signer()
        ext, conn = self.ob, self.conns[self.ob]
        self.node('caps', {'userId': self.rem0te_user(ext, self.tech_b), 'customerId': self.fx['businesses'][ext],
                           'capabilities': ['computers:view', 'integration:ticket_analysis', 'actions:request']})
        self.signed_heartbeat(ext)
        p = self.signer_cli('policy', 'set', '--business', self.fx['businesses'][ext], '--approval', 'direct')
        check(p.returncode == 0, 'the signer\'s operator sets Birch to direct mode (signer CLI only)', p.stderr[-300:])
        try:
            c = self.client(self.tech_b, self.org_b)
            t = self.ticket_for(self.org_b, self.assets[ext], self.tech_b, 'Birch spooler (direct mode)')
            dev = RMMDevice.objects.get(connection=conn, external_id=self.fx['endpoints'][ext]['id'])
            c.post(f'/psa/rmm/{t.ticket_number}/fix/', {'device': dev.pk, 'idempotency_key': f'dm-{secrets.token_hex(6)}',
                                                        'action': ACTION, 'description': 'Spooler stopped'})
            req = RMMRequest.objects.filter(ticket=t).order_by('-created_at').first()
            check(req is not None and req.status == 'rejected' and req.remote_status == 'DIRECT_MODE_PORTAL_ONLY'
                  and not req.remote_id, 'Rem0te refuses the ClientSt0r proposal (403 DIRECT_MODE_PORTAL_ONLY); '
                  'ClientSt0r records it rejected, nothing was signed', req and (req.status, req.remote_status, req.error))
            check(req is not None and not self.no_secrets(req.error), 'the reason has no secrets', req and req.error)
        finally:
            self.signer_cli('policy', 'set', '--business', self.fx['businesses'][ext], '--approval', 'signed')
