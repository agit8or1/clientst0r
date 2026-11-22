"""The interoperability scenario: every step drives the two real
installations over HTTPS. See run.py for how to start it."""
from __future__ import annotations

import html
import json
import os
import re
import time

import infra
from browser import UI, follow, messages
from run import (ALIAS, LABEL, MOVED_SIM, ROGUE_SIM, SCOPES, Abort, brief, check, conn_row, now_iso, q,
                 uuid_text)

DISCOVERY = '/.well-known/agit8or-connect'


def run(h):
    h.build()
    flags_and_sign_in(h)
    network_setup(h)
    installation_rules(h)
    quick_connect(h)
    if _stop(h, 'Q'):
        return
    live_checks(h)
    if _stop(h, 'L'):
        return
    outage_and_recovery(h)
    security_failures(h)
    lifecycle_controls(h)
    code_flow_after_revoke(h)


def _stop(h, prefix):
    return bool(h.args.stop_after) and h.args.stop_after == prefix


# --- 1. feature flags, sign-in, default deny ------------------------------------------------

def flags_and_sign_in(h):
    r, A, B = h.report, h.insts['a'], h.insts['b']
    with r.step('F01', 'Connect off by default: discovery and the admin pages answer 404 on both installations',
                critical=True) as st:
        h.start_all(enabled=False)
        for side, inst in h.insts.items():
            status, _ = h.raw_get(side, DISCOVERY, source=ALIAS['b' if side == 'a' else 'a'])
            st.detail[f'{side}_discovery'] = status
            check(status == 404, f'{side}: discovery must be 404 while AGIT8OR_CONNECT_ENABLED is off', got=status)
    with r.step('F02', 'Sign in four administrators (password + TOTP second factor) over HTTPS',
                critical=True) as st:
        h.start_all(enabled=True)
        h.browsers()
        st.detail['sessions'] = sorted(f'{s}/{u}' for s, u in h.b)
        page = h.b[('a', 'admin1')].get(UI)
        check(page.status_code == 200, 'Connected Applications page', status=page.status_code)
    with r.step('F03', 'Default deny: with Connect on and no rule, discovery refuses the other installation\'s '
                       'address (403 before any authentication)') as st:
        for side in ('a', 'b'):
            other = 'b' if side == 'a' else 'a'
            status, body = h.raw_get(side, DISCOVERY, source=ALIAS[other])
            st.detail[f'{side}_from_{other}'] = {'status': status, 'body': body[:200].decode('utf-8', 'replace')}
            check(status == 403 and b'source_not_authorised' in body, f'{side}: discovery must refuse', status=status)


# --- 2. this installation's network settings ------------------------------------------------

def network_setup(h):
    r = h.report
    with r.step('N01', 'Each side declares its egress address and turns Quick Connect on (fresh re-authentication '
                       'required)', critical=True) as st:
        for side, inst in h.insts.items():
            br = h.b[(side, 'admin1')]
            resp = br.post(UI + 'network/', {'op': 'set_egress', 'egress': inst.sim_ip})
            check(resp.status_code == 302, 'set_egress', status=resp.status_code)
            # Without re-authentication Quick Connect stays off.
            resp = br.post(UI + 'network/', {'op': 'qc_on'})
            off = q(inst, 'SELECT qc_enabled FROM connect_installation')[0]['qc_enabled']
            check(not off, f'{side}: qc_on without re-authentication must be refused')
            resp = br.post(UI + 'network/', {'op': 'qc_on', **br.fresh_fields()})
            ident = q(inst, 'SELECT qc_enabled, egress_addresses FROM connect_installation')[0]
            check(ident['qc_enabled'], f'{side}: Quick Connect on', page=messages(br.get(UI + 'network/').text))
            st.detail[side] = {'qc_enabled': bool(ident['qc_enabled']), 'egress': json.loads(ident['egress_addresses'])}


def approve_connect_change(h, side, change_pk, st, key):
    """Approve a staged Connect change (inline password + TOTP); a widening
    one goes through a protected change confirmed by its requester and
    approved by the second administrator."""
    br, br2 = h.b[(side, 'admin1')], h.b[(side, 'admin2')]
    resp = br.post(UI + f'changes/{change_pk}/', {'op': 'approve', **br.fresh_fields()})
    loc = resp.headers.get('Location', '')
    info = {'approve_status': resp.status_code}
    if '/technician-access/changes/' in loc:
        pc = int(re.search(r'/changes/(\d+)/', loc).group(1))
        info['protected_change'] = pc
        # The requester cannot approve their own widening change.
        br.approve_protected(pc)
        info['self_approval_refused'] = q(h.insts[side], 'SELECT status FROM tech_access_protected_changes WHERE '
                                                         'id = ?', (pc,))[0]['status'] == 'pending'
        br.confirm_protected(pc)
        br2.approve_protected(pc)
        info['protected_status'] = q(h.insts[side], 'SELECT status FROM tech_access_protected_changes WHERE id = ?',
                                     (pc,))[0]['status']
    info['change_status'] = q(h.insts[side], 'SELECT status FROM connect_changes WHERE id = ?',
                              (change_pk,))[0]['status']
    st.detail[key] = info
    return info


def installation_rules(h):
    r = h.report
    with r.step('N02', 'Each side allows the other installation\'s address at the installation layer (staged '
                       'change, private address flagged; widening -> second administrator)', critical=True) as st:
        for side, other in (('a', 'b'), ('b', 'a')):
            inst, br = h.insts[side], h.b[(side, 'admin1')]
            resp = br.post(UI + 'network/', {'op': 'propose_rule', 'network': h.insts[other].sim_ip,
                                             'action': 'allow', 'private': 'on',
                                             'description': f'Interop {other.upper()}'})
            ch = q(inst, 'SELECT id, status, widening FROM connect_changes ORDER BY id DESC LIMIT 1')
            check(ch, f'{side}: change staged', page=messages(br.get(UI + 'network/').text))
            info = approve_connect_change(h, side, ch[0]['id'], st, side)
            rules = q(inst, "SELECT network, private, status, layer FROM connect_source_rules WHERE layer = "
                            "'installation'")
            st.detail[f'{side}_installation_rules'] = rules
            check(any(x['network'].startswith(h.insts[other].sim_ip) and x['status'] == 'active' for x in rules),
                  f'{side}: installation rule active', info=info, page=messages(br.get(UI + 'network/').text))


# --- 3. Quick Connect A -> B -------------------------------------------------------------------

def _scrape(pattern, text, what):
    m = re.search(pattern, text or '', re.S)
    check(m is not None, f'could not find {what} on the page', page=messages(text))
    return html.unescape(m.group(1))


def quick_connect(h):
    r, A, B = h.report, h.insts['a'], h.insts['b']
    a1, a2, b1, b2 = h.b[('a', 'admin1')], h.b[('a', 'admin2')], h.b[('b', 'admin1')], h.b[('b', 'admin2')]
    acme_a, acme_b = h.seed['a']['orgs'][0], h.seed['b']['orgs'][0]
    ca = h.ca_pem
    with r.step('Q01', 'A: Quick Connect wizard — address, DNS + TLS preview with the per-connection test CA, '
                       'single-use signed invitation', critical=True) as st:
        form = {'url': B.base, 'op': 'check', 'allow_private': 'on', 'ca_pem': ca}
        resp = a1.post(UI + 'quick-connect/', form)
        check(resp.status_code == 200 and 'data-qc-screen="network"' in resp.text, 'network check screen',
              status=resp.status_code, page=messages(resp.text))
        check('type="password"' not in resp.text, 'no password field in the wizard')
        form.update({'op': 'authorize', 'own_egress': f'{A.sim_ip}/32', 'egress_confirmed': 'on',
                     'requested_scopes': ' '.join(SCOPES), 'destination_addresses': B.sim_ip,
                     'orgs': [acme_a['pk']]})
        resp = a1.post(UI + 'quick-connect/', form)
        check(resp.status_code == 302, 'attempt created', status=resp.status_code, page=messages(resp.text))
        attempt = resp.headers['Location']
        page = a1.get(attempt)
        link = _scrape(r'href="([^"]+)"[^>]*data-qc-authorize-link', page.text, 'the authorise link')
        check(link.startswith(B.base + '/agit8or-connect/qc-authorize?'), 'link to B\'s own admin page', link=link)
        h.ctx.update(qc_attempt=attempt, qc_link=link)
        st.detail.update(attempt=attempt, authorize_link=link[:120] + '…')
    with r.step('Q02', 'B: the administrator reviews the invitation in B\'s own admin UI; approve needs a fresh '
                       're-authentication; then approves temporary access for A\'s declared egress',
                critical=True) as st:
        link = h.ctx['qc_link']
        review = b1.get(link)
        check(review.status_code == 200 and 'type="password"' not in review.text, 'review page, no password',
              status=review.status_code, page=messages(review.text))
        inv = _scrape(r'name="invitation" value="([^"]+)"', review.text, 'invitation')
        state = _scrape(r'name="state" value="([^"]+)"', review.text, 'state')
        # A session of the same administrator that has not re-authenticated.
        from browser import Browser
        cold = Browser(B, 'admin1', b1.password, h.seed['b']['otp']['admin1'], h.pki['ca'])
        cold.login()
        stale = cold.post('/agit8or-connect/qc-authorize', {'invitation': inv, 'state': state, 'op': 'approve',
                                                            'private_ok': 'on'})
        st.detail['approve_without_reauth'] = stale.status_code
        check(stale.status_code != 303, 'approval without re-authentication must not succeed')
        b1.reauth(force=True)
        resp = b1.post('/agit8or-connect/qc-authorize', {'invitation': inv, 'state': state, 'op': 'approve',
                                                         'private_ok': 'on'})
        check(resp.status_code == 303, 'approved, 303 back to A', status=resp.status_code, page=messages(resp.text))
        h.ctx['qc_return'] = resp.headers['Location']
        check(h.ctx['qc_return'].startswith(A.base + UI + 'quick-connect/callback?'), 'returns to A\'s callback',
              location=h.ctx['qc_return'][:120])
        st.detail['temporary_rules_on_b'] = q(B, "SELECT network, purpose, status, expires_at FROM "
                                                 "connect_source_rules WHERE status = 'temporary'")
        # The same invitation cannot be used twice.
        again = b1.post('/agit8or-connect/qc-authorize', {'invitation': inv, 'state': state, 'op': 'approve',
                                                          'private_ok': 'on'})
        st.detail['invitation_reuse'] = {'status': again.status_code,
                                         'error': re.findall(r'data-qc-error="([^"]*)"', again.text)}
        check(again.status_code == 400, 'single-use invitation: second approval refused', status=again.status_code)
    with r.step('Q03', 'A: callback in the initiator\'s browser session; A approves B\'s declared egress; the '
                       'exchange (PKCE + DPoP) goes A -> B over HTTPS', critical=True) as st:
        resp, url = follow(h.by_host, h.ctx['qc_return'])
        check(resp.status_code == 200, 'attempt page after callback', status=resp.status_code,
              page=messages(resp.text))
        resp = a1.post(h.ctx['qc_attempt'], {'op': 'confirm', 'approve_peer': 'on', 'private_peer': 'on'})
        page = a1.get(h.ctx['qc_attempt'])
        sas_a = _scrape(r'data-connect-sas>([^<]+)<', page.text, 'A\'s comparison code').strip()
        row_a = conn_row(A, remote=h.seed['b']['installation_id'])
        row_b = conn_row(B, remote=h.seed['a']['installation_id'])
        check(row_b is not None, 'B has the connection after the exchange', a=brief(row_a))
        h.ctx.update(conn_a=uuid_text(row_a['id']), conn_b=uuid_text(row_b['id']))
        st.detail.update(a=brief(row_a), b=brief(row_b), sas_a=sas_a)
        h.ctx['sas_a'] = sas_a
    with r.step('Q04', 'SAS: both administrators see the same comparison code', critical=True) as st:
        preq = q(B, 'SELECT id FROM connect_pairing_requests WHERE connection_id = ?',
                 (h.ctx['conn_b'].replace('-', ''),))[0]['id']
        h.ctx['preq_b'] = uuid_text(preq)
        page = b1.get(UI + f'requests/{h.ctx["preq_b"]}/')
        sas_b = _scrape(r'data-connect-sas>([^<]+)<', page.text, 'B\'s comparison code').strip()
        st.detail.update(sas_a=h.ctx['sas_a'], sas_b=sas_b)
        check(sas_b == h.ctx['sas_a'] and len(sas_b) >= 6, 'SAS equal on both sides')
    with r.step('Q05', 'B: looks up A, approves the permissions A may use and which customer maps to A\'s '
                       'customer (scope grants)', critical=True) as st:
        path = UI + f'requests/{h.ctx["preq_b"]}/'
        resp = b1.post(path, {'op': 'lookup', 'allow_private': 'on', 'ca_pem': ca})
        check(resp.status_code == 302, 'lookup', status=resp.status_code, page=messages(resp.text))
        data = {'op': 'approve', 'scopes': SCOPES, 'requested_scopes': SCOPES, 'allow_private': 'on', 'ca_pem': ca,
                'destination_addresses': A.sim_ip, 'grant_rows': '1', 'org_0': str(acme_b['pk']),
                'tenant_0': f'org-{acme_a["pk"]}', 'scope_0': ['customers:read', 'events:publish']}
        resp = b1.post(path, data)
        st.detail['approve'] = {'status': resp.status_code, 'location': resp.headers.get('Location', '')}
        loc = resp.headers.get('Location', '')
        if '/technician-access/changes/' in loc:
            pk = int(re.search(r'/changes/(\d+)/', loc).group(1))
            st.detail['second_admin'] = pk
            check(b1.confirm_protected(pk).status_code == 302, 'requester confirms')
            check(b2.approve_protected(pk).status_code == 302, 'second administrator approves')
        row = conn_row(B, pk=h.ctx['conn_b'])
        st.detail['b'] = brief(row)
        check(row['state'] in ('awaiting_network', 'testing'), 'B approved', b=brief(row),
              page=messages(b1.get(path).text))
    with r.step('Q06', 'A: learns the approval (poll), approves what B may do and the customer mapping',
                critical=True) as st:
        path = UI + f'{h.ctx["conn_a"]}/'
        a1.post(path, {'op': 'poll'})
        row = conn_row(A, pk=h.ctx['conn_a'])
        st.detail['after_poll'] = brief(row)
        check(row['state'].startswith('awaiting_local'), 'A awaits its own approval', a=brief(row),
              page=messages(a1.get(path).text))
        resp = a1.post(path, {'op': 'approve_local', 'scopes': SCOPES, 'grant_rows': '1',
                              'org_0': str(acme_a['pk']), 'tenant_0': f'org-{acme_b["pk"]}',
                              'scope_0': ['customers:read', 'events:publish']})
        loc = resp.headers.get('Location', '')
        if '/technician-access/changes/' in loc:
            pk = int(re.search(r'/changes/(\d+)/', loc).group(1))
            st.detail['second_admin'] = pk
            a1.confirm_protected(pk)
            a2.approve_protected(pk)
        row = conn_row(A, pk=h.ctx['conn_a'])
        st.detail['a'] = brief(row)
        check(row['state'] in ('awaiting_network', 'testing'), 'A approved', a=brief(row),
              page=messages(a1.get(path).text))
    with r.step('Q07', 'Both: approve the other side\'s source address for this connection only (default deny; '
                       'password + TOTP), private address flagged explicitly', critical=True) as st:
        for side, other in (('a', 'b'), ('b', 'a')):
            br, br2 = h.b[(side, 'admin1')], h.b[(side, 'admin2')]
            pk = h.ctx[f'conn_{side}']
            path = UI + f'{pk}/'
            resp = br.post(path, {'op': 'approve_network', 'networks': f'{h.insts[other].sim_ip}/32',
                                  'purpose': 'all', 'private': 'on', **br.fresh_fields()})
            loc = resp.headers.get('Location', '')
            if '/technician-access/changes/' in loc:
                cpk = int(re.search(r'/changes/(\d+)/', loc).group(1))
                st.detail[f'{side}_second_admin'] = cpk
                br.confirm_protected(cpk)
                br2.approve_protected(cpk)
            row = conn_row(h.insts[side], pk=pk)
            st.detail[side] = brief(row)
            st.detail[f'{side}_rules'] = q(h.insts[side], 'SELECT network, private, purpose, status, layer FROM '
                                                          'connect_source_rules WHERE connection_id = ?',
                                           (pk.replace('-', ''),))
            check(row['state'] in ('testing', 'active'), f'{side}: network approved', row=brief(row),
                  page=messages(br.get(path).text))
    with r.step('Q08', 'Test before live: each side\'s commit test (connection test + diagnostics incl. reverse '
                       'connectivity) until both are Connected', critical=True) as st:
        runs = []
        for attempt in range(4):
            for side in ('a', 'b'):
                pk = h.ctx[f'conn_{side}']
                row = conn_row(h.insts[side], pk=pk)
                if row['state'] == 'active':
                    continue
                resp = h.b[(side, 'admin1')].post(UI + f'{pk}/', {'op': 'commit_test'})
                row = conn_row(h.insts[side], pk=pk)
                runs.append({'side': side, 'attempt': attempt, 'state': row['state'], 'last_error': row['last_error'],
                             'messages': messages(h.b[(side, 'admin1')].get(UI + f'{pk}/').text)[:2]})
            if all(conn_row(h.insts[s], pk=h.ctx[f'conn_{s}'])['state'] == 'active' for s in ('a', 'b')):
                break
        st.detail['runs'] = runs
        for side in ('a', 'b'):
            row = conn_row(h.insts[side], pk=h.ctx[f'conn_{side}'])
            st.detail[side] = brief(row)
            lt = json.loads(row['last_test'] or '{}')
            st.detail[f'{side}_last_test'] = {'ok': lt.get('ok'), 'failed': [c.get('id') for c in lt.get('checks', [])
                                                                              if not c.get('ok')]}
            check(row['state'] == 'active' and row['health'] == 'connected', f'{side} Connected', row=brief(row))
        page = a1.get(h.ctx['qc_attempt'])
        check('data-qc-connected' in page.text, 'wizard shows Connected')


API_CALL = r'''
from connect import client
from core.models import Organization
conn = Connection.objects.get(pk=%(pk)r)
out = {}
org = Organization.objects.get(pk=%(org)d)
api = (conn.endpoint('api_base') or conn.base_url.split('/.well-known')[0] + '/connect/v1').rstrip('/')
r = client.call(conn, 'GET', api + '/customers/current', tenant_org=org)
out['customers_current'] = {'status': r.status, 'body': json.loads(r.body or b'null')}
r = client.call(conn, 'GET', api + '/customers')
out['customers'] = {'status': r.status, 'body': json.loads(r.body or b'null')}
print(json.dumps(out))
'''

ENQUEUE = r'''
from connect import events
conn = Connection.objects.get(pk=%(pk)r)
grant = conn.tenant_grants.get(active=True)
ids = []
for i in range(%(n)d):
    ev = events.enqueue(conn, 'alert.raised', {'alert_id': '%(prefix)s-%%d' %% i}, grant=grant)
    ids.append(ev.envelope.get('id') or str(ev.pk))
print(json.dumps({'event_ids': ids}))
'''

# Protocol probes from A's own process (A's code, keys and network identity):
# one signed request sent twice (replay), and tenant headers this connection
# was never granted (cross-tenant).
PROBES = r'''
from agit8or_connect import tokens as sdk_tokens
from connect import client, store, transport
conn = Connection.objects.get(pk=%(pk)r)
api = (conn.endpoint('api_base') or conn.base_url.split('/.well-known')[0] + '/connect/v1').rstrip('/')
tok = client.get_token(conn, use_cache=False)['access_token']
_, priv = store.active_key(conn)
def send(url, tenant=None, proof=None):
    headers = {'Authorization': 'DPoP ' + tok, 'Accept': 'application/json',
               'DPoP': proof or sdk_tokens.build_dpop_proof(priv, 'GET', url, access_token=tok)}
    if tenant:
        headers['Agit8or-Tenant'] = tenant
    r = transport.for_connection(conn).request('GET', url, headers=headers)
    try:
        body = json.loads(r.body or b'null')
    except ValueError:
        body = r.body[:200].decode('utf-8', 'replace')
    return {'status': r.status, 'body': body}, headers['DPoP']
url = api + '/customers/current'
first, proof = send(url, %(granted)r)
replayed, _ = send(url, %(granted)r, proof=proof)
other_customer, _ = send(url, %(ungranted)r)
peer_side_id, _ = send(url, %(peer_id)r)
print(json.dumps({'first': first, 'replayed': replayed, 'ungranted_customer_of_ours': other_customer,
                  'peer_side_tenant_id': peer_side_id}))
'''


def live_checks(h):
    r, A, B = h.report, h.insts['a'], h.insts['b']
    acme = {s: h.seed[s]['orgs'][0] for s in ('a', 'b')}
    globex = {s: h.seed[s]['orgs'][1] for s in ('a', 'b')}
    with r.step('L01', 'Authenticated API calls in both directions (private_key_jwt + DPoP token, '
                       'tenant-scoped resource)') as st:
        for side, other in (('a', 'b'), ('b', 'a')):
            out = h.connect_shell(side, API_CALL % {'pk': h.ctx[f'conn_{side}'], 'org': acme[side]['pk']})
            st.detail[f'{side}_to_{other}'] = out
            check(out['customers_current']['status'] == 200 and
                  out['customers_current']['body']['name'] == acme[other]['name'],
                  f'{side} reads its mapped customer at {other}', out=out)
            check([t['name'] for t in out['customers']['body']['tenants']] == [acme[other]['name']],
                  'only the granted customer is listed', out=out)
    with r.step('L02', 'Signed events delivered A -> B and B -> A through the queue (delivery command), stored '
                       'against the mapped customer') as st:
        for side, other in (('a', 'b'), ('b', 'a')):
            ids = h.connect_shell(side, ENQUEUE % {'pk': h.ctx[f'conn_{side}'], 'n': 2, 'prefix': f'L02-{side}'})
            out = h.insts[side].manage('connect_deliver_events')
            got = q(h.insts[other], 'SELECT e.event_id, e.event_type, e.status, o.name AS customer FROM '
                                    'connect_inbound_events e LEFT JOIN connect_tenant_grants g ON g.id = '
                                    'e.tenant_grant_id LEFT JOIN organizations o ON o.id = g.organization_id '
                                    'WHERE e.connection_id = ? ORDER BY e.received_at',
                    (h.ctx[f'conn_{other}'].replace('-', ''),))
            st.detail[f'{side}_to_{other}'] = {'queued': ids, 'delivery': out.stdout.strip()[-300:], 'received': got}
            alerts = [g for g in got if g['event_type'] == 'alert.raised']
            check(len(alerts) >= 2 and all(g['customer'] == acme[other]['name'] for g in alerts),
                  f'{other} stored the events for its mapped customer', got=got)
    with r.step('L03', 'Health check (monitor command): every dimension passes, health Connected') as st:
        for side in ('a', 'b'):
            out = h.monitor(side)
            st.detail[side] = out
            row = conn_row(h.insts[side], pk=h.ctx[f'conn_{side}'])
            dims = json.loads(row['health_dims'] or '{}')
            st.detail[f'{side}_dims'] = dims
            check(row['state'] == 'active' and row['health'] == 'connected', f'{side} connected', row=brief(row))
    with r.step('L04', 'Replay: the same signed request (same DPoP proof) sent twice — the second is refused') as st:
        out = h.connect_shell('a', PROBES % {'pk': h.ctx['conn_a'], 'granted': f'org-{acme["a"]["pk"]}',
                                             'ungranted': f'org-{globex["a"]["pk"]}',
                                             'peer_id': 'org-999999'})
        h.ctx['probes'] = out
        st.detail.update(first=out['first'], replayed=out['replayed'])
        check(out['first']['status'] == 200, 'first request accepted', out=out['first'])
        check(out['replayed']['status'] in (400, 401, 403), 'replayed proof refused', out=out['replayed'])
    with r.step('L05', 'Cross-tenant: a customer of A\'s that this connection was never granted, and a tenant id '
                       'that exists nowhere, are refused without data') as st:
        out = h.ctx.get('probes') or {}
        st.detail.update(ungranted=out.get('ungranted_customer_of_ours'), peer_side_id=out.get('peer_side_tenant_id'))
        for k in ('ungranted_customer_of_ours', 'peer_side_tenant_id'):
            check(out[k]['status'] in (403, 404) and 'Globex' not in json.dumps(out[k]['body']),
                  f'{k} refused without data', out=out[k])
    with r.step('L06', 'Source policy: an address not in any rule is refused before authentication; the '
                       'connection\'s own address is admitted') as st:
        rogue = h.raw_get('b', DISCOVERY, source=ALIAS['rogue'])
        peer = h.raw_get('b', DISCOVERY, source=ALIAS['a'])
        st.detail.update(rogue={'source': ROGUE_SIM, 'status': rogue[0], 'body': rogue[1][:160].decode()},
                         peer={'source': A.sim_ip, 'status': peer[0]})
        check(rogue[0] == 403 and b'source_not_authorised' in rogue[1], 'rogue source refused')
        check(peer[0] == 200, 'connection source admitted')
        refused = q(B, "SELECT * FROM connect_source_rules WHERE network LIKE ?", (ROGUE_SIM + '%',))
        st.detail['rogue_rule_rows'] = refused


LADDER = (10, 30, 60, 120, 300, 600, 900)


def _ladder_ok(delay, step):
    lo, hi = LADDER[step] * 0.8 - 1, LADDER[step] * 1.2 + 1
    return delay is not None and lo <= delay <= hi


def _a_row(h):
    return conn_row(h.insts['a'], pk=h.ctx['conn_a'])


def _retest(h, side):
    """Administrator retest of a Security Blocked connection (password + TOTP)."""
    br = h.b[(side, 'admin1')]
    pk = h.ctx[f'conn_{side}']
    br.post(UI + f'{pk}/', {'op': 'retest', **br.fresh_fields()})
    row = conn_row(h.insts[side], pk=pk)
    return row, messages(br.get(UI + f'{pk}/').text)[:3]


def outage_and_recovery(h):
    r, A, B = h.report, h.insts['a'], h.insts['b']
    with r.step('O01', 'Availability failure: B stopped -> A Degraded, then Offline with the backoff ladder '
                       '(10 s, 30 s, 60 s … ±20 %); events queued meanwhile wait instead of being used up') as st:
        B.stop()
        passes = []
        for i in range(6):
            out = h.monitor('a')
            row = _a_row(h)
            passes.append({'pass': i, 'before': out['before'], 'after': [x for x in out['after']
                                                                        if x['id'] == h.ctx['conn_a']]})
            if row['health'] == 'offline':
                break
        st.detail['passes'] = passes
        row = _a_row(h)
        st.detail['a'] = brief(row)
        check(row['state'] == 'active' and row['health'] == 'offline' and row['circuit'] == 'open',
              'A shows Offline with the circuit open (state stays active: availability, not security)', row=brief(row))
        delays = [p['after'][0]['scheduled_delay_s'] for p in passes]
        st.detail['scheduled_delays_s'] = delays
        check(all(_ladder_ok(d, min(k, len(LADDER) - 1)) for k, d in enumerate(delays)),
              'each retry waited per the ladder with ±20 % jitter', delays=delays)
        ids = h.connect_shell('a', ENQUEUE % {'pk': h.ctx['conn_a'], 'n': 3, 'prefix': 'O01'})
        h.ctx['offline_events'] = ids['event_ids']
        A.manage('connect_deliver_events')
        evs = q(A, "SELECT status, attempts, last_error FROM connect_outbound_events WHERE connection_id = ? AND "
                   "envelope LIKE '%%O01-%%' ORDER BY created_at", (h.ctx['conn_a'].replace('-', ''),))
        st.detail['queued_while_offline'] = evs
        check(len(evs) == 3 and all(e['status'] == 'queued' for e in evs), 'events wait in the queue', evs=evs)
    with r.step('O02', 'Recovery: B restarted -> A\'s half-open probe and a second pass -> Connected without an '
                       'administrator; the queue drains in order') as st:
        B.start()
        passes = []
        for i in range(4):
            out = h.monitor('a')
            row = _a_row(h)
            passes.append({'pass': i, 'after': [x for x in out['after'] if x['id'] == h.ctx['conn_a']]})
            if row['health'] == 'connected':
                break
        st.detail['passes'] = passes
        row = _a_row(h)
        st.detail['a'] = brief(row)
        check(row['state'] == 'active' and row['health'] == 'connected' and row['circuit'] == 'closed',
              'A Connected again', row=brief(row))
        A.manage('connect_deliver_events')
        got = q(B, "SELECT event_id, data, received_at FROM connect_inbound_events WHERE connection_id = ? AND "
                   "data LIKE '%%O01-%%' ORDER BY received_at, id", (h.ctx['conn_b'].replace('-', ''),))
        order = [json.loads(g['data']).get('alert_id') for g in got]
        st.detail['received_order'] = order
        check(order == ['O01-0', 'O01-1', 'O01-2'], 'drained in order', order=order)


def security_failures(h):
    r, A, B = h.report, h.insts['a'], h.insts['b']
    with r.step('X01', 'Security failure: B now presents a certificate from another CA -> A Security Blocked at '
                       'once with evidence, and NO automatic reconnect') as st:
        B.restart(cert=h.pki['b-other-ca'], ca=h.pki['other_ca'])
        out = h.monitor('a')
        row = _a_row(h)
        st.detail['after_check'] = brief(row)
        st.detail['evidence'] = row.get('security_block_detail')
        check(row['state'] == 'security_blocked', 'Security Blocked', row=brief(row))
        st.detail['block_code'] = row['security_block_code']
        B.restart()            # the right certificate is back ...
        for _ in range(2):
            h.monitor('a', due_now=False)
        row = _a_row(h)
        st.detail['after_cert_restored_and_monitor'] = brief(row)
        check(row['state'] == 'security_blocked' and not row['next_check_at'],
              '... but nothing reconnects by itself', row=brief(row))
    with r.step('X02', 'Administrator retest (password + TOTP) after the certificate is right again -> active') as st:
        row, msgs = _retest(h, 'a')
        st.detail.update(a=brief(row), messages=msgs)
        check(row['state'] == 'active', 'active after the retest', row=brief(row))
    with r.step('X03', 'Address change: B\'s name now resolves to another address -> A Security Blocked '
                       '(destination_changed), nothing sent; restored -> still blocked until the retest') as st:
        hosts = h.net.data['hosts']
        hosts[B.host] = [MOVED_SIM]
        h.net.data['ports'][MOVED_SIM] = B.port
        h.net.save()
        try:
            h.monitor('a')
            row = _a_row(h)
            st.detail['after_move'] = brief(row)
            st.detail['evidence'] = row.get('security_block_detail')
            check(row['state'] == 'security_blocked' and row['security_block_code'] == 'destination_changed',
                  'destination_changed', row=brief(row))
        finally:
            hosts[B.host] = [B.sim_ip]
            h.net.save()
        h.monitor('a', due_now=False)
        row = _a_row(h)
        check(row['state'] == 'security_blocked', 'no automatic reconnect', row=brief(row))
        # A plain retest is refused: an address block needs an address approved after the block.
        row, msgs = _retest(h, 'a')
        st.detail.update(retest_without_approval=brief(row), retest_messages=msgs)
        check(row['state'] == 'security_blocked', 'retest without a new approval stays blocked', row=brief(row))
        # The administrator re-approves the (restored) address as a staged destination change; the
        # change page retests after the approval.
        a1 = h.b[('a', 'admin1')]
        a1.post(UI + f'{h.ctx["conn_a"]}/', {'op': 'propose_destination', 'destination_addresses': B.sim_ip,
                                             'private_destination': 'on'})
        ch = q(A, "SELECT id FROM connect_changes WHERE kind = 'destination' ORDER BY id DESC LIMIT 1")
        check(ch, 'destination change staged', page=messages(a1.get(UI + f'{h.ctx["conn_a"]}/').text))
        approve_connect_change(h, 'a', ch[0]['id'], st, 'destination_change')
        row = _a_row(h)
        if row['state'] != 'active':
            row, msgs = _retest(h, 'a')
            st.detail['explicit_retest_messages'] = msgs
        st.detail['after_approval_and_retest'] = brief(row)
        check(row['state'] == 'active', 'active after re-approval and retest', row=brief(row))


CALL_STATUS = r'''
from agit8or_connect.errors import ConnectError
from connect import client
from core.models import Organization
conn = Connection.objects.get(pk=%(pk)r)
try:
    r = client.call(conn, 'GET', (conn.endpoint('api_base') or conn.base_url.split('/.well-known')[0] + '/connect/v1').rstrip('/') + '/customers/current',
                    tenant_org=Organization.objects.get(pk=%(org)d))
    out = {'status': r.status, 'body': json.loads(r.body or b'null')}
except ConnectError as e:
    out = {'refused_locally': e.code, 'status': e.status}
conn.refresh_from_db()
out['state'] = conn.state
out['security_block_code'] = conn.security_block_code
print(json.dumps(out))
'''


def _call(h, side):
    return h.connect_shell(side, CALL_STATUS % {'pk': h.ctx[f'conn_{side}'], 'org': h.seed[side]['orgs'][0]['pk']})


def lifecycle_controls(h):
    r, A, B = h.report, h.insts['a'], h.insts['b']
    a1, b1 = h.b[('a', 'admin1')], h.b[('b', 'admin1')]
    with r.step('C01', 'Kill switch on B: Connect API calls to B answer 503 kill_switch (an availability failure '
                       'for A, never a security block) and B\'s connection is suspended; released and resumed -> '
                       'active on both sides') as st:
        b1.post(UI + 'kill-switch/', {'op': 'engage'})
        st.detail['b_state'] = brief(conn_row(B, pk=h.ctx['conn_b']))
        check(conn_row(B, pk=h.ctx['conn_b'])['state'] == 'suspended', 'B suspended by the kill switch')
        status, body = h.raw_get('b', DISCOVERY, source=ALIAS['a'])
        st.detail['discovery_at_b'] = {'status': status, 'stopped': b'"stopped"' in body or b'stopped' in body}
        st.detail['a_calls_b'] = _call(h, 'a')
        check(st.detail['a_calls_b'].get('status') == 503 and
              st.detail['a_calls_b'].get('refused_locally') == 'kill_switch', 'A -> B: 503 kill_switch',
              out=st.detail['a_calls_b'])
        h.monitor('a')
        ra = _a_row(h)
        st.detail['a_check_during_kill_switch'] = brief(ra)
        check(ra['state'] == 'active', 'A is not Security Blocked by a kill switch (availability)', row=brief(ra))
        b1.post(UI + 'kill-switch/', {'op': 'release'})
        b1.post(UI + f'{h.ctx["conn_b"]}/', {'op': 'resume'})
        rb = conn_row(B, pk=h.ctx['conn_b'])
        st.detail['b_after_resume'] = brief(rb)
        check(rb['state'] == 'active', 'B active after release + resume (commit test passed)', row=brief(rb))
        h.monitor('a')
        st.detail['a_after'] = brief(_a_row(h))
        check(_a_row(h)['state'] == 'active', 'A active')
        check(_call(h, 'a').get('status') == 200, 'A -> B works again')
    with r.step('C02', 'Suspend on A, then resume: A sends nothing while suspended; after resume both sides '
                       'should be Connected again') as st:
        a1.post(UI + f'{h.ctx["conn_a"]}/', {'op': 'suspend'})
        st.detail['a_after_suspend'] = brief(_a_row(h))
        check(_a_row(h)['state'] == 'suspended', 'A suspended')
        st.detail['a_calls_b'] = _call(h, 'a')
        check(st.detail['a_calls_b'].get('refused_locally') == 'connection_inactive', 'A sends nothing')
        st.detail['b_calls_a'] = _call(h, 'b')
        check(st.detail['b_calls_a'].get('status') == 401, 'B refused by A while suspended', out=st.detail['b_calls_a'])
        # B's scheduled health check meets A's refusal.
        h.monitor('b')
        st.detail['b_after_its_check'] = brief(conn_row(B, pk=h.ctx['conn_b']))
        a1.post(UI + f'{h.ctx["conn_a"]}/', {'op': 'resume'})
        st.detail['a_after_resume'] = brief(_a_row(h))
        # The administrators retest what is blocked, B first then A.
        for side in ('b', 'a'):
            row = conn_row(h.insts[side], pk=h.ctx[f'conn_{side}'])
            if row['state'] == 'security_blocked':
                row, msgs = _retest(h, side)
                st.detail[f'{side}_retest'] = {'row': brief(row), 'messages': msgs}
        ra, rb = _a_row(h), conn_row(B, pk=h.ctx['conn_b'])
        st.detail.update(a_final=brief(ra), b_final=brief(rb))
        if rb['security_block_code'] == 'peer_revoked' and ra['state'] != 'active':
            st.detail['finding'] = (
                'FINDING (protocol): a suspended connection answers the token endpoint with invalid_client, '
                'the code a revoked one uses, so the other side is Security Blocked with peer_revoked. On '
                'resume, A\'s commit test is refused by the blocked B (its token endpoint serves only active or '
                'testing connections) and A is blocked with peer_revoked too; each side\'s retest is refused by '
                'the other\'s blocked state, so the pair cannot recover without pairing again. Fixing it needs '
                'a distinct protocol error for a suspended connection (or a protocol rule for retests), so it '
                'is reported, not changed.')
        check(ra['state'] == 'active' and rb['state'] == 'active', 'both sides Connected after resume',
              a=brief(ra), b=brief(rb))


def code_flow_after_revoke(h):
    r, A, B = h.report, h.insts['a'], h.insts['b']
    a1, a2, b1, b2 = h.b[('a', 'admin1')], h.b[('a', 'admin2')], h.b[('b', 'admin1')], h.b[('b', 'admin2')]
    acme_a, acme_b = h.seed['a']['orgs'][0], h.seed['b']['orgs'][0]
    with r.step('V01', 'Protocol 1 code flow, the other direction: the Quick Connect pair is revoked on both sides; '
                       'A issues a '
                       'single-use pairing code bound to B\'s address; B pairs with it') as st:
        for side in ('a', 'b'):
            h.b[(side, 'admin1')].post(UI + f'{h.ctx[f"conn_{side}"]}/', {'op': 'revoke'})
            st.detail[f'qc_{side}_after_revoke'] = brief(conn_row(h.insts[side], pk=h.ctx[f'conn_{side}']))
        resp = a1.post(UI + 'invite/', {'label': 'interop B', 'peer_sources': B.sim_ip, 'private_sources': 'on'})
        code = _scrape(r'data-connect-code[^>]*>([^<]+)<', resp.text, 'pairing code') if 'data-connect-code' in \
            resp.text else _scrape(r'<code[^>]*>([A-Z0-9-]{8,})</code>', resp.text, 'pairing code')
        h.ctx['v1_code'] = code.strip()
        data = {'url': A.base, 'op': 'pair', 'pairing_secret': h.ctx['v1_code'], 'scopes': SCOPES,
                'orgs': [acme_b['pk']], 'peer_sources': A.sim_ip, 'private_sources': 'on', 'allow_private': 'on',
                'ca_pem': h.ca_pem, 'destination_addresses': A.sim_ip, 'rotation_days': '90'}
        resp = b1.post(UI + 'new/other/', data)
        check(resp.status_code == 302, 'pairing request sent', status=resp.status_code, page=messages(resp.text))
        pk_b = resp.headers['Location'].rstrip('/').split('/')[-1]
        h.ctx['v1_b'] = pk_b
        row_b = conn_row(B, pk=pk_b)
        row_a = conn_row(A, remote=h.seed['b']['installation_id'])
        h.ctx['v1_a'] = uuid_text(row_a['id'])
        st.detail.update(a=brief(row_a), b=brief(row_b))
        check(row_a['sas'] == row_b['sas'] and row_a['sas'], 'SAS equal', a=row_a['sas'], b=row_b['sas'])
        again = b1.post(UI + 'new/other/', data)
        st.detail['code_reuse'] = {'status': again.status_code, 'messages': messages(again.text)}
        check(again.status_code == 200, 'a used code cannot pair again')
    with r.step('V02', 'Code flow: A approves (scopes, customer), B approves its side, both commit tests pass '
                       '-> active; API call both ways') as st:
        preq = q(A, 'SELECT id FROM connect_pairing_requests WHERE connection_id = ?',
                 (h.ctx['v1_a'].replace('-', ''),))[0]['id']
        path = UI + f'requests/{uuid_text(preq)}/'
        a1.post(path, {'op': 'lookup', 'allow_private': 'on', 'ca_pem': h.ca_pem})
        resp = a1.post(path, {'op': 'approve', 'scopes': SCOPES, 'requested_scopes': SCOPES, 'allow_private': 'on',
                              'ca_pem': h.ca_pem, 'destination_addresses': B.sim_ip, 'grant_rows': '1',
                              'org_0': str(acme_a['pk']), 'tenant_0': f'org-{acme_b["pk"]}',
                              'scope_0': ['customers:read', 'events:publish']})
        loc = resp.headers.get('Location', '')
        if '/technician-access/changes/' in loc:
            cpk = int(re.search(r'/changes/(\d+)/', loc).group(1))
            a1.confirm_protected(cpk)
            a2.approve_protected(cpk)
        st.detail['a_after_approve'] = brief(conn_row(A, pk=h.ctx['v1_a']))
        pathb = UI + f'{h.ctx["v1_b"]}/'
        b1.post(pathb, {'op': 'poll'})
        resp = b1.post(pathb, {'op': 'approve_local', 'scopes': SCOPES, 'grant_rows': '1',
                               'org_0': str(acme_b['pk']), 'tenant_0': f'org-{acme_a["pk"]}',
                               'scope_0': ['customers:read', 'events:publish']})
        loc = resp.headers.get('Location', '')
        if '/technician-access/changes/' in loc:
            cpk = int(re.search(r'/changes/(\d+)/', loc).group(1))
            b1.confirm_protected(cpk)
            b2.approve_protected(cpk)
        for _ in range(3):
            for side, key in (('a', 'v1_a'), ('b', 'v1_b')):
                if conn_row(h.insts[side], pk=h.ctx[key])['state'] != 'active':
                    h.b[(side, 'admin1')].post(UI + f'{h.ctx[key]}/', {'op': 'commit_test'})
        for side, key in (('a', 'v1_a'), ('b', 'v1_b')):
            row = conn_row(h.insts[side], pk=h.ctx[key])
            st.detail[side] = brief(row)
            check(row['state'] == 'active', f'{side} active', row=brief(row),
                  page=messages(h.b[(side, 'admin1')].get(UI + f'{h.ctx[key]}/').text))
        for side, key in (('a', 'v1_a'), ('b', 'v1_b')):
            out = h.connect_shell(side, API_CALL % {'pk': h.ctx[key], 'org': h.seed[side]['orgs'][0]['pk']})
            st.detail[f'{side}_api'] = out['customers_current']
            check(out['customers_current']['status'] == 200, f'{side} API call', out=out)


    with r.step('V03', 'Revoke on B: B\'s keys are destroyed; A\'s next check -> Security Blocked and no '
                       'automatic reconnect; A sends nothing') as st:
        b1.post(UI + f'{h.ctx["v1_b"]}/', {'op': 'revoke'})
        check(conn_row(B, pk=h.ctx['v1_b'])['state'] == 'revoked', 'B revoked')
        keys = q(B, 'SELECT state, private_key FROM connect_keys WHERE connection_id = ?',
                 (h.ctx['v1_b'].replace('-', ''),))
        st.detail['b_keys'] = [{'state': k['state'], 'private_key_wiped': not k['private_key']} for k in keys]
        check(keys and all(k['state'] == 'retired' and not k['private_key'] for k in keys), 'keys retired and wiped')
        h.monitor('a')
        ra = conn_row(A, pk=h.ctx['v1_a'])
        st.detail['a_after_check'] = brief(ra)
        check(ra['state'] == 'security_blocked' and ra['security_block_code'] in ('peer_revoked',
                                                                                 'source_not_authorised'),
              'A Security Blocked', row=brief(ra))
        if ra['security_block_code'] == 'source_not_authorised':
            st.detail['observation'] = (
                'Revoking removes the connection\'s source rules on B, so A\'s next request is refused by B\'s '
                'source layer before authentication and A shows source_not_authorised ("your egress may have '
                'changed") rather than peer_revoked. The block and the no-reconnect rule hold; only the reason '
                'shown to A\'s administrator is misleading.')
        h.monitor('a', due_now=False)
        ra = conn_row(A, pk=h.ctx['v1_a'])
        check(ra['state'] == 'security_blocked' and not ra['next_check_at'], 'no automatic reconnect', row=brief(ra))
        out = h.connect_shell('a', CALL_STATUS % {'pk': h.ctx['v1_a'], 'org': acme_a['pk']})
        st.detail['a_calls_b'] = out
        check(out.get('refused_locally') == 'connection_inactive', 'A sends nothing', out=out)


# --- report ---------------------------------------------------------------------------------

def write_report(h, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rep = h.report
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    passed = sum(1 for s in rep.steps if s['result'] == 'pass')
    data = {
        'label': LABEL,
        'not': ['production', 'an independent review', 'two different hosts', 'real DNS'],
        'started': rep.started, 'ended': now_iso(),
        'summary': {'steps': len(rep.steps), 'passed': passed,
                    'failed': sum(1 for s in rep.steps if s['result'] == 'fail'),
                    'skipped': sum(1 for s in rep.steps if s['result'] == 'skipped')},
        'environment': {
            'code': _git_head(), 'installations': {k: {'public_url': i.base, 'simulated_address': i.sim_ip,
                                                        'loopback_source': i.source_alias, 'workers': i.workers}
                                                    for k, i in h.insts.items()},
            'address_simulation': 'netshim: *.interop.test -> simulated 10.231.0.0/16 addresses dialled on '
                                  '127.0.0.1; inbound loopback source aliases translated to the sender\'s '
                                  'simulated address (TLS, HTTP, workers and every Connect check are real)',
            'tls': 'per-run test-only CA, trusted only via each connection\'s private CA and the driver\'s '
                   'verify= path; verification never disabled',
        },
        'steps': rep.steps,
    }
    jpath = os.path.join(out_dir, f'interop-{stamp}.json')
    with open(jpath, 'w') as f:
        json.dump(data, f, indent=1, default=str)
    lines = [f'# Agit8or Connect interoperability run — {LABEL}', '',
             'Not production, not an independent review: two Clientst0r installations from this commit on one '
             'host, 127.0.0.1 only, simulated private addresses, a test-only CA.', '',
             f'- Code: `{data["environment"]["code"]}`', f'- Started {data["started"]}, ended {data["ended"]}',
             f'- Result: **{passed}/{len(rep.steps)} steps passed**', '',
             '| Step | Result | Seconds | What it proves |', '|---|---|---|---|']
    for s in rep.steps:
        lines.append(f'| {s["id"]} | {s["result"].upper()} | {s.get("seconds", "")} | {s["title"]} |')
    fails = [s for s in rep.steps if s['result'] == 'fail']
    if fails:
        lines += ['', '## Failures', '']
        for s in fails:
            lines += [f'### {s["id"]} {s["title"]}', '', '```', s.get('error', ''), '```', '']
    found = [(s['id'], s['detail'][k]) for s in rep.steps for k in ('finding', 'observation')
             if isinstance(s.get('detail'), dict) and s['detail'].get(k)]
    if found:
        lines += ['', '## Findings', '']
        lines += [f'- **{sid}**: {text}' for sid, text in found]
    lines += ['', '## Not proven by this run', '',
              '- Two different hosts, real DNS, NAT or a reverse proxy in front of either side (addresses are '
              'simulated on 127.0.0.1).',
              '- Anything about Rem0te or another implementation: both sides run this Clientst0r code.',
              '- Long timescales: backoff beyond the first steps, key rotation overlap, certificate expiry, the '
              '15-minute diagnostics schedule (the harness moves the next check to now and records the delay the '
              'app scheduled).',
              '- Independent review (roadmap 79.24).']
    lines += ['', 'Full evidence per step (timestamps, states, refusals): the JSON file next to this one.', '']
    mpath = os.path.join(out_dir, f'interop-{stamp}.md')
    with open(mpath, 'w') as f:
        f.write('\n'.join(lines))
    return mpath


def _git_head():
    import subprocess
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=infra.REPO, capture_output=True, text=True,
                              timeout=10).stdout.strip() + (' (+ uncommitted changes)' if subprocess.run(
                                  ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=infra.REPO,
                                  capture_output=True, text=True, timeout=10).stdout.strip() else '')
    except Exception:
        return 'unknown'
