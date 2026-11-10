"""Sample data group: psa_extras (v3.17.655). See core/demo_samples/__init__.py.

Change management, problems, releases, procurement, field work, timesheets,
CSAT and the CRM pipeline. Procurement, project templates and CRM belong to
the MSP organization (the first demo customer when there is no MSP); the rest
sits on the demo customers' own tickets and contracts.

New change tickets are assigned to demo technicians only, never the admin:
they can't sign in and have no phone or push devices, so the ticket
assignment notifications have nowhere to go.
"""
from datetime import timedelta
from decimal import Decimal as D

# --- Specs -------------------------------------------------------------------

CANNED_REPLIES = [
    ('Acknowledged - looking into it',
     "Hi,\n\nThanks for getting in touch about {{ticket.subject}}. I've picked up ticket "
     "{{ticket.number}} and I'm looking into it now. I'll update you within the hour.\n\n"
     "{{user.first_name}}"),
    ('Remote session request',
     "Hi,\n\nTo look at this I'll need a quick remote session. Could you reply with a time in the next "
     "few hours that suits you? It takes about 15 minutes and you can watch everything I do.\n\n"
     "{{user.first_name}}"),
    ('Resolved - please confirm',
     "Hi,\n\nI believe {{ticket.number}} is now fixed. Could you check on your side and let me know? "
     "If I don't hear back in three working days I'll close the ticket - reply any time to reopen it.\n\n"
     "Thanks,\n{{user.first_name}} {{user.last_name}}"),
    ('Waiting on vendor',
     "Hi,\n\nQuick update on {{ticket.subject}}: we've escalated this to the vendor and are waiting on "
     "their engineers. I'll chase them daily and let you know as soon as they come back to us.\n\n"
     "{{user.first_name}}"),
]

# risk, final status, ticket status, days from now (negative = past), hours long
CHANGES = [
    {'subject': 'Firewall firmware upgrade to FortiOS 7.4.4', 'risk': 'high', 'status': 'approved',
     'ticket_status': 'Scheduled', 'start': 3, 'hours': 2, 'votes': ['approved', 'approved'],
     'impact': 'Internet and site-to-site VPN unavailable for up to 15 minutes while the unit reboots. '
               'Scheduled after hours; remote staff notified.',
     'plan': '1. Back up running config to the documentation vault.\n2. Confirm HA peer is in sync.\n'
             '3. Upgrade secondary, fail over, upgrade primary.\n4. Verify VPN tunnels, SSL inspection and '
             'policy hit counts.\n5. Post-change health check from the monitoring dashboard.',
     'rollback': 'Boot from the alternate firmware partition (7.2.8) and restore the config backup taken '
                 'in step 1. Tested on the lab unit last week.'},
    {'subject': 'Migrate departmental file shares to SharePoint Online', 'risk': 'medium',
     'status': 'pending_cab', 'ticket_status': 'New', 'start': 10, 'hours': 6, 'votes': ['approved'],
     'impact': 'Shares become read-only during the final sync. Mapped drives replaced by synced libraries.',
     'plan': '1. Pre-stage content with the migration tool (delta sync nightly).\n2. Communicate cut-over '
             'to staff.\n3. Set shares read-only, run final delta.\n4. Push OneDrive sync policy via Intune.\n'
             '5. Remove drive mappings from the logon GPO.',
     'rollback': 'Remove the read-only flag on the shares and restore the drive-mapping GPO. Libraries '
                 'stay in place for a later retry.'},
    {'subject': 'Replace core switch stack in server room', 'risk': 'high', 'status': 'verified',
     'ticket_status': 'Closed', 'start': -12, 'hours': 4, 'votes': ['approved', 'approved'],
     'impact': 'Full LAN outage during the swap. Saturday morning window agreed with the office manager.',
     'plan': '1. Label and photograph all patching.\n2. Pre-load config on the new stack.\n3. Swap units, '
             're-patch per the port map.\n4. Verify VLANs, DHCP relay and uplinks.\n5. Walk the floor and '
             'test a phone and PC at each desk cluster.',
     'rollback': 'Re-rack the old stack (kept powered off in the rack) and restore its patching from the '
                 'photographs.',
     'outcome': 'Completed in 3h10m. Two mis-patched desk ports fixed during the floor walk. No issues '
                'reported on Monday.'},
    {'subject': 'Disable TLS 1.0/1.1 on the Exchange hybrid server', 'risk': 'low', 'status': 'draft',
     'ticket_status': 'New', 'start': 17, 'hours': 1, 'votes': [],
     'impact': 'Old mobile mail clients still using TLS 1.0 will stop syncing.',
     'plan': '1. Check the IIS logs for TLS 1.0/1.1 connections over the last 30 days.\n2. Apply the '
             'SCHANNEL registry settings.\n3. Reboot and test mail flow and hybrid free/busy.',
     'rollback': 'Remove the SCHANNEL keys and reboot.'},
]

PROBLEMS = [
    {'title': 'Recurring Outlook credential prompts after password changes', 'status': 'known_error',
     'priority': 'high', 'match': ['Outlook', 'password'],
     'symptoms': 'Users are prompted for their password every few minutes in Outlook after a password '
                 'change. Webmail is unaffected.',
     'root_cause': 'Stale credentials cached in Windows Credential Manager, combined with an Office build '
                   'that still has the legacy ADAL registry key set by an old deployment script.',
     'workaround': 'Clear the MicrosoftOffice16 entries in Credential Manager and restart Outlook.',
     'whys': ['Outlook prompts for a password', 'The cached token is rejected',
              'The cached credential is the old password', 'Outlook is using legacy auth for the mailbox',
              'An old deployment script set the ADAL override key']},
    {'title': 'VPN tunnels dropping on dead-peer-detection timeouts', 'status': 'investigating',
     'priority': 'medium', 'match': ['VPN'],
     'symptoms': 'Home workers lose the VPN roughly every 20 minutes; the client log shows DPD timeouts.',
     'root_cause': '', 'workaround': '', 'whys': []},
    {'title': 'Print spooler crashes on Windows 11 24H2 workstations', 'status': 'resolved',
     'priority': 'medium', 'match': ['print'],
     'symptoms': 'Spooler service stops several times a day on upgraded machines; users see "printer offline".',
     'root_cause': 'An outdated universal print driver (v6.3) is incompatible with the 24H2 spooler isolation.',
     'workaround': 'Restart the Print Spooler service.',
     'fix': 'Deployed the vendor v7.1 driver through Intune and removed v6.3 from the print server.',
     'whys': ['Spooler crashes', 'Driver host faults', 'v6.3 driver loaded in isolation mode',
              'Driver predates 24H2']},
]

PROBLEM_NOTES = {
    'investigating': [('Pulled VPN client logs from three affected users - all show DPD timeouts at '
                       '20-minute intervals.', False),
                      ('All affected users are on the same ISP. Asked the ISP about CGNAT session timers.', False)],
    'known_error': [('Reproduced on a test laptop: changing the password and leaving Outlook open '
                     'brings the prompts back.', False),
                    ('Found the ADAL override key on every machine built from the 2023 image.', True),
                    ('Workaround documented and linked to the related tickets.', False)],
    'resolved': [('Crash dumps point at the universal print driver host.', True),
                 ('v7.1 driver piloted on five machines for a week with no crashes.', False),
                 ('Rolled out to all workstations; closing once the pilot group confirms.', False)],
}

REQUISITIONS = [
    {'title': 'Laptop refresh - Finance team', 'client': 0, 'status': 'converted', 'days': 9,
     'description': 'Five Finance laptops are out of warranty and failing the BitLocker hardware check.',
     'lines': [('Dell Latitude 7450, Core Ultra 7, 16GB, 512GB', 'LAT7450-U7-16', 5, '1489.00'),
               ('Dell WD22TB4 Thunderbolt dock', 'WD22TB4', 5, '239.00')]},
    {'title': 'Replacement UPS batteries for the server rack', 'client': 1, 'status': 'approved', 'days': 4,
     'description': 'UPS self-test failing; runtime down to 4 minutes.',
     'lines': [('APC RBC43 replacement battery cartridge', 'APCRBC43', 2, '389.00')]},
    {'title': 'Microsoft 365 Business Premium - 10 additional seats', 'client': 2, 'status': 'submitted',
     'days': 1, 'description': 'New starters in January.',
     'lines': [('Microsoft 365 Business Premium (annual, monthly billing)', 'CFQ7TTC0LCHC', 10, '22.00')]},
    {'title': 'Spare docking stations for the bench', 'client': None, 'status': 'draft', 'days': 0,
     'description': 'Bench stock for swaps.',
     'lines': [('Dell WD22TB4 Thunderbolt dock', 'WD22TB4', 3, '239.00')]},
]

PURCHASE_ORDERS = [
    {'title': 'Laptop refresh - Finance team', 'pr': 'Laptop refresh - Finance team', 'client': 0,
     'vendor': 'Dell', 'email': 'orders@dell.example.com', 'status': 'partial', 'days': 8, 'ship': '45.00',
     'lines': [('Dell Latitude 7450, Core Ultra 7, 16GB, 512GB', 'LAT7450-U7-16', 5, '1489.00', 3),
               ('Dell WD22TB4 Thunderbolt dock', 'WD22TB4', 5, '239.00', 5)],
     'receipt': {'carrier': 'UPS', 'tracking': '1Z999AA10123456784', 'days': 3,
                 'serials': ['5CG4281XQ1', '5CG4281XQ7', '5CG4281XR2']},
     'backorder': 'Remaining two laptops on vendor back-order.'},
    {'title': 'Wireless access points - warehouse coverage', 'pr': None, 'client': 1, 'vendor': 'Cisco Meraki',
     'email': 'sales@meraki-reseller.example.com', 'status': 'sent', 'days': 2, 'ship': '0.00',
     'lines': [('Meraki MR46 access point', 'MR46-HW', 4, '879.00', 0),
               ('Meraki MR Enterprise license, 3 years', 'LIC-ENT-3YR', 4, '330.00', 0)]},
    {'title': 'Toner restock', 'pr': None, 'client': 0, 'vendor': 'HP', 'email': 'supplies@hp.example.com',
     'status': 'received', 'days': 20, 'ship': '0.00',
     'lines': [('HP 410X black toner (CF410X)', 'CF410X', 4, '168.00', 4)],
     'receipt': {'carrier': 'FedEx', 'tracking': '7712 3456 7890', 'days': 17, 'serials': []}},
]

RECURRING_PURCHASES = [
    {'name': 'Monthly toner refill - front office', 'client': 0, 'vendor': 'HP', 'recurrence': 'monthly',
     'next': 12, 'lines': [{'description': 'HP 410X black toner (CF410X)', 'sku': 'CF410X',
                            'quantity': 2, 'unit_price': '168.00'}]},
    {'name': 'Quarterly backup media rotation', 'client': 1, 'vendor': 'Iron Mountain', 'recurrence': 'quarterly',
     'next': 40, 'lines': [{'description': 'LTO-9 data cartridge', 'sku': 'LTO9-18TB',
                            'quantity': 6, 'unit_price': '94.00'}]},
]

PROJECT_TEMPLATES = [
    {'name': 'Microsoft 365 tenant migration',
     'description': 'Move a customer from on-premises Exchange and file shares into Microsoft 365.',
     'tasks': [('Discovery and licensing review', 6, 0, False, [('Mailbox and share inventory', 3, 2),
                                                                  ('Licensing recommendation', 2, 4)]),
               ('Tenant preparation', 8, 7, False, [('Domain verification and DNS', 1, 7),
                                                     ('Conditional Access baseline', 4, 9)]),
               ('Mailbox migration batches', 12, 14, False, []),
               ('Cut-over weekend', 8, 21, True, []),
               ('Hypercare and handover', 6, 28, False, [])]},
    {'name': 'New office network build-out',
     'description': 'Firewall, switching and Wi-Fi for a new or moved office.',
     'tasks': [('Site survey', 4, 0, False, []),
               ('Hardware order', 2, 3, False, []),
               ('Rack, cable and patch', 10, 14, False, [('Label patch panel', 2, 14)]),
               ('Firewall and VLAN configuration', 6, 16, False, []),
               ('Go-live', 4, 21, True, [])]},
]

EXPENSES = [
    ('parts', 'USB-C to Ethernet adapters (2)', '38.98', True),
    ('mileage', 'Parking at client site', '14.00', False),
    ('software', 'One-off licence for PDF repair tool', '59.00', True),
]

CHECKLIST = ['Confirm backup completed before work starts', 'Photograph rack before and after',
             'Update the network diagram in documentation', 'Customer sign-off on completion']

KIT = [('USB console cable and adapter', 1), ('Spare SFP+ 10G-SR modules', 2), ('Label printer', 1)]

METERS = [('Microsoft 365 seats', 'seat', '22.00', '18'), ('Endpoint RMM agents', 'device', '4.50', '42'),
          ('Cloud backup storage', 'gb', '0.08', '1250')]

CSAT_RESPONSES = [(5, 'Quick and friendly, sorted first time.'), (4, 'Fixed, though it took a couple of days.'),
                  (5, ''), (3, 'Had to chase for an update.')]

CAMPAIGNS = [
    ('Q4 cybersecurity webinar series', 'event', '2500.00', -45, 30),
    ('Referral partner programme', 'referral', '1000.00', -120, None),
    ('Local business SEO content', 'content', '1800.00', -90, 60),
]

LEADS = [
    ('Harbor Dental Group', 'Rachel', 'Nguyen', 'Practice Manager', 'Healthcare', 24, '18000.00', 'qualified', 0),
    ('Pinecrest Logistics', 'Tom', 'Becker', 'Operations Director', 'Logistics', 85, '42000.00', 'contacted', 0),
    ('Willow & Finch Architects', 'Grace', 'Holloway', 'Partner', 'Professional Services', 12, '9600.00',
     'new', 2),
    ('Summit Ridge Credit Union', 'Daniel', 'Osei', 'IT Manager', 'Finance', 140, '65000.00', 'qualified', 1),
    ('Bluebird Bakery Co.', 'Maya', 'Lopez', 'Owner', 'Food & Beverage', 8, '4800.00', 'disqualified', 2),
    ('Northgate Law LLP', 'Owen', 'Price', 'Office Manager', 'Legal', 30, '21000.00', 'new', None),
]

OPPORTUNITIES = [
    {'name': 'Managed security add-on (EDR + 24/7 SOC)', 'client': 0, 'stage': 'proposal', 'value': '14400.00',
     'prob': 60, 'close': 21},
    {'name': 'Server room refresh and virtualisation', 'client': 1, 'stage': 'negotiation', 'value': '38500.00',
     'prob': 75, 'close': 14},
    {'name': 'Microsoft 365 Business Premium upgrade', 'client': 2, 'stage': 'closed_won', 'value': '26400.00',
     'prob': 100, 'close': -6},
    {'name': 'Co-managed IT for new branch office', 'client': 0, 'stage': 'discovery', 'value': '12000.00',
     'prob': 20, 'close': 60},
    {'name': 'Phone system replacement (hosted VoIP)', 'client': 1, 'stage': 'closed_lost', 'value': '9800.00',
     'prob': 0, 'close': -20, 'lost': 'Went with carrier bundle on price'},
]

COMMISSION_RULES = [
    ('Large deal bonus', 10, '20000.00', '10.00', '500.00'),
    ('Standard new business', 100, '0.00', '8.00', '0.00'),
]


# --- Helpers -----------------------------------------------------------------

def _backdate(obj, **fields):
    """Set auto_now_add timestamps on a row this run just created."""
    type(obj).objects.filter(pk=obj.pk).update(**fields)


def _slot(org):
    """A stable per-customer index, so which samples a customer gets
    doesn't shift when another demo customer is added or removed."""
    from core.demo_samples import CUSTOMER_SLUGS
    return CUSTOMER_SLUGS.index(org.slug) if org.slug in CUSTOMER_SLUGS else 0


def _owner(ctx):
    return ctx.msp or ctx.customer(0)


def _field_techs(ctx):
    return [u for u in ctx.techs if u != ctx.admin] or list(ctx.techs)


def _client(ctx, i):
    return None if i is None else ctx.customer(i)


def _vendor(name):
    from assets.models import Vendor
    return Vendor.objects.filter(name__icontains=name).first()


def _tickets(org):
    from psa.models import Ticket
    return Ticket.objects.filter(organization=org).exclude(ticket_type__slug='change').order_by('pk')


# --- Seeders -----------------------------------------------------------------

def _canned_replies(ctx):
    from psa.models import CannedReply
    n = 0
    for org in ctx.customers:
        for i, (name, body) in enumerate(CANNED_REPLIES):
            _, made = CannedReply.objects.get_or_create(
                organization=org, name=name,
                defaults={'body': body, 'created_by': ctx.admin, 'sort_order': i})
            n += made
    ctx.created('psa.CannedReply', n)


def _changes(ctx):
    """Change tickets with their ChangeRequest, CAB votes and history.
    Returns {org_pk: [ChangeRequest, ...]} for the release windows."""
    from psa.models import (CABVote, ChangeRequest, ChangeRequestTransition, Queue, Ticket, TicketPriority,
                            TicketStatus, TicketType)
    ctype = TicketType.objects.filter(slug='change').first()
    queue = Queue.objects.filter(name='Projects').first() or Queue.objects.order_by('pk').first()
    priority = TicketPriority.objects.filter(code='P3').first() or TicketPriority.objects.order_by('pk').first()
    statuses = {s.name: s for s in TicketStatus.objects.all()}
    if not (ctype and queue and priority and statuses):
        ctx.out.write('  psa_extras: no PSA defaults (change type, queue, priority, status); skipping changes')
        return {}
    techs = _field_techs(ctx)
    approvers = [ctx.admin, techs[0]] if techs[0] != ctx.admin else [ctx.admin]
    by_org, counts = {}, {'psa.Ticket': 0, 'psa.ChangeRequest': 0, 'psa.ChangeRequestTransition': 0,
                          'psa.CABVote': 0}
    for org in ctx.customers:
        oi = _slot(org)
        for ci, spec in enumerate(CHANGES):
            if (oi + ci) % 2 and spec['status'] != 'approved':
                continue  # two to three changes per customer, the approved one everywhere
            existing = Ticket.objects.filter(organization=org, subject=spec['subject'],
                                             ticket_type=ctype).first()
            if existing is not None:
                cr = ChangeRequest.objects.filter(ticket=existing).first()
                if cr:
                    by_org.setdefault(org.pk, []).append(cr)
                continue
            tech = techs[(oi + ci) % len(techs)]
            start = ctx.now + timedelta(days=spec['start'])
            start = start.replace(hour=19 if spec['start'] > 0 else 8, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=spec['hours'])
            created_at = min(ctx.now, start) - timedelta(days=6)
            status = statuses.get(spec['ticket_status']) or next(iter(statuses.values()))
            ticket = Ticket.objects.create(
                organization=org, subject=spec['subject'], description=spec['impact'], queue=queue,
                priority=priority, status=status, ticket_type=ctype, assigned_to=tech,
                created_by=ctx.admin, impact='high' if spec['risk'] == 'high' else 'medium')
            counts['psa.Ticket'] += 1
            stamps = {'created_at': created_at}
            if status.is_terminal:
                stamps['closed_at'] = stamps['resolved_at'] = end
            _backdate(ticket, **stamps)
            cr, made = ChangeRequest.objects.get_or_create(ticket=ticket, defaults={'organization': org})
            counts['psa.ChangeRequest'] += 1
            fields = {
                'risk': spec['risk'], 'implementation_status': spec['status'],
                'implementation_plan': spec['plan'], 'rollback_plan': spec['rollback'],
                'impact_assessment': spec['impact'], 'backout_window_minutes': 30 * spec['hours'],
                'scheduled_start': start, 'scheduled_end': end, 'outcome_summary': spec.get('outcome', ''),
                'created_at': created_at,
            }
            path = {'draft': [], 'pending_cab': ['pending_cab'], 'approved': ['pending_cab', 'approved'],
                    'verified': ['pending_cab', 'approved', 'implementing', 'verified']}[spec['status']]
            submitted = created_at + timedelta(days=1)
            decided = submitted + timedelta(days=2)
            if path:
                fields.update(submitted_at=submitted, submitted_by=tech)
            if 'approved' in path:
                fields.update(decided_at=decided, decided_by=ctx.admin, decision_note='Approved at weekly CAB.')
            if spec['status'] == 'verified':
                fields.update(actual_start=start, actual_end=end - timedelta(minutes=50))
            ChangeRequest.objects.filter(pk=cr.pk).update(**fields)
            cr.required_approvers.set(approvers)
            when = {'pending_cab': submitted, 'approved': decided, 'implementing': start,
                    'verified': end - timedelta(minutes=50)}
            prev = 'draft'
            for step in path:
                t = ChangeRequestTransition.objects.create(
                    change_request=cr, from_status=prev, to_status=step,
                    by_user=tech if step in ('pending_cab', 'implementing', 'verified') else ctx.admin,
                    note={'pending_cab': 'Submitted to CAB', 'approved': 'All CAB approvals in',
                          'implementing': 'Change window started', 'verified': 'Post-change checks passed'}[step])
                _backdate(t, at=when[step])
                counts['psa.ChangeRequestTransition'] += 1
                prev = step
            for vi, decision in enumerate(spec['votes'][:len(approvers)]):
                v = CABVote.objects.create(change_request=cr, user=approvers[vi], decision=decision,
                                           note='Rollback plan reviewed - looks good.' if vi == 0 else '')
                _backdate(v, voted_at=submitted + timedelta(hours=6 + vi * 20))
                counts['psa.CABVote'] += 1
            cr.refresh_from_db()
            by_org.setdefault(org.pk, []).append(cr)
    for label, n in counts.items():
        ctx.created(label, n)
    return by_org


def _releases(ctx, changes_by_org):
    from psa.models import ReleaseWindow
    n = 0
    for org in ctx.customers:
        crs = changes_by_org.get(org.pk, [])
        upcoming = [c for c in crs if c.implementation_status in ('approved', 'pending_cab')]
        done = [c for c in crs if c.implementation_status == 'verified']
        specs = [('Monthly maintenance window', 'planned', upcoming, 3, False)]
        if done:
            specs.append(('Infrastructure refresh window', 'completed', done, -12, True))
        for title, status, members, days, past in specs:
            if ReleaseWindow.objects.filter(organization=org, title=title).exists():
                continue
            start = (ctx.now + timedelta(days=days)).replace(hour=19 if not past else 8, minute=0, second=0,
                                                             microsecond=0)
            rw = ReleaseWindow.objects.create(
                organization=org, title=title, status=status, scheduled_start=start,
                scheduled_end=start + timedelta(hours=5), release_manager=ctx.admin, created_by=ctx.admin,
                actual_start=start if past else None, actual_end=start + timedelta(hours=4) if past else None,
                description='Approved changes bundled into one after-hours window; change freeze applies '
                            'from 17:00 on the day.',
                rollback_plan='Each bundled change carries its own rollback; the release manager decides '
                              'whether to roll back individually or abandon the window.')
            rw.changes.set(members)
            n += 1
    ctx.created('psa.ReleaseWindow', n)


def _problems(ctx, changes_by_org):
    from django.db.models import Q
    from psa.models import Problem, ProblemNote
    techs = _field_techs(ctx)
    n = notes = 0
    for org in ctx.customers:
        oi = _slot(org)
        for pi, spec in enumerate(PROBLEMS):
            if (oi + pi) % 3 == 2:
                continue
            if Problem.objects.filter(organization=org, title=spec['title']).exists():
                continue
            tech = techs[(oi + pi) % len(techs)]
            fix_cr = None
            if spec['status'] == 'resolved':
                fix_cr = next((c for c in changes_by_org.get(org.pk, [])
                               if c.implementation_status == 'verified'), None)
            p = Problem.objects.create(
                organization=org, title=spec['title'], status=spec['status'], priority=spec['priority'],
                description=spec['symptoms'], symptoms=spec['symptoms'], root_cause=spec['root_cause'],
                workaround=spec['workaround'], permanent_fix=spec.get('fix', ''), five_whys=spec['whys'],
                investigated_by=tech, assigned_to=tech, created_by=ctx.admin, fix_change_request=fix_cr,
                resolved_at=ctx.now - timedelta(days=2) if spec['status'] == 'resolved' else None)
            found = ctx.now - timedelta(days=14 + pi * 3)
            _backdate(p, created_at=found, discovered_at=found)
            q = Q()
            for word in spec['match']:
                q |= Q(subject__icontains=word)
            p.related_tickets.set(_tickets(org).filter(q)[:4])
            n += 1
            for ni, (body, key) in enumerate(PROBLEM_NOTES[spec['status']]):
                note = ProblemNote.objects.create(problem=p, user=tech, body=body, is_breakthrough=key)
                _backdate(note, created_at=found + timedelta(days=1 + ni * 3))
                notes += 1
    ctx.created('psa.Problem', n)
    ctx.created('psa.ProblemNote', notes)


def _procurement(ctx):
    from psa.models import (POBackOrder, POReceipt, POReceiptLine, PurchaseOrder, PurchaseOrderLineItem,
                            PurchaseRequisition, PurchaseRequisitionLineItem)
    owner = _owner(ctx)
    techs = _field_techs(ctx)
    counts = dict.fromkeys(['psa.PurchaseRequisition', 'psa.PurchaseRequisitionLineItem', 'psa.PurchaseOrder',
                            'psa.PurchaseOrderLineItem', 'psa.POReceipt', 'psa.POReceiptLine',
                            'psa.POBackOrder'], 0)
    for i, spec in enumerate(REQUISITIONS):
        if PurchaseRequisition.objects.filter(organization=owner, title=spec['title']).exists():
            continue
        decided = spec['status'] in ('approved', 'converted')
        pr = PurchaseRequisition.objects.create(
            organization=owner, client_org=_client(ctx, spec['client']), title=spec['title'],
            description=spec['description'], status=spec['status'], requested_by=techs[i % len(techs)],
            approver=ctx.admin if decided else None,
            decided_at=ctx.now - timedelta(days=max(spec['days'] - 1, 0)) if decided else None,
            decision_note='Approved - within budget.' if decided else '', tax_rate=D('8.25'))
        for si, (desc, sku, qty, price) in enumerate(spec['lines']):
            PurchaseRequisitionLineItem.objects.create(requisition=pr, description=desc, sku=sku,
                                                       quantity=D(qty), unit_price=D(price), sort_order=si)
            counts['psa.PurchaseRequisitionLineItem'] += 1
        pr.recompute_totals()
        pr.save(update_fields=['subtotal', 'tax_amount', 'total', 'updated_at'])
        _backdate(pr, requested_at=ctx.now - timedelta(days=spec['days']),
                  created_at=ctx.now - timedelta(days=spec['days']))
        counts['psa.PurchaseRequisition'] += 1

    for spec in PURCHASE_ORDERS:
        if PurchaseOrder.objects.filter(organization=owner, title=spec['title']).exists():
            continue
        vendor = _vendor(spec['vendor'])
        client = _client(ctx, spec['client'])
        issued = ctx.now - timedelta(days=spec['days'])
        po = PurchaseOrder.objects.create(
            organization=owner, client_org=client,
            requisition=PurchaseRequisition.objects.filter(organization=owner, title=spec['pr']).first()
            if spec['pr'] else None,
            vendor=vendor, vendor_name=vendor.name if vendor else spec['vendor'], vendor_email=spec['email'],
            title=spec['title'], status=spec['status'], issue_date=issued.date(),
            expected_delivery_date=(issued + timedelta(days=7)).date(), is_drop_ship=client is not None,
            ship_to_name=client.name if client else '', tax_rate=D('8.25'), shipping_cost=D(spec['ship']),
            created_by=ctx.admin, sent_at=issued, notes='Deliver to reception; call ahead.')
        lines = []
        for si, (desc, sku, qty, price, got) in enumerate(spec['lines']):
            lines.append((PurchaseOrderLineItem.objects.create(
                po=po, description=desc, sku=sku, quantity=D(qty), unit_price=D(price),
                received_quantity=D(got), sort_order=si), got))
            counts['psa.PurchaseOrderLineItem'] += 1
        po.recompute_totals()
        po.save(update_fields=['subtotal', 'tax_amount', 'total', 'updated_at'])
        _backdate(po, created_at=issued)
        counts['psa.PurchaseOrder'] += 1
        rspec = spec.get('receipt')
        if rspec:
            receipt = POReceipt.objects.create(po=po, received_by=techs[0], carrier=rspec['carrier'],
                                               tracking_number=rspec['tracking'],
                                               is_drop_ship_confirmed=po.is_drop_ship,
                                               notes='Boxes checked against the packing slip.')
            _backdate(receipt, received_at=ctx.now - timedelta(days=rspec['days']))
            counts['psa.POReceipt'] += 1
            serials = list(rspec['serials'])
            for line, got in lines:
                if not got:
                    continue
                take = serials[:got] if line.sku.startswith('LAT') else []
                POReceiptLine.objects.create(receipt=receipt, po_line=line, quantity_received=D(got),
                                             serial_numbers=take)
                counts['psa.POReceiptLine'] += 1
                short = line.quantity - D(got)
                if short > 0 and spec.get('backorder'):
                    POBackOrder.objects.create(po=po, po_line=line, quantity_outstanding=short,
                                               expected_delivery_date=(ctx.now + timedelta(days=10)).date(),
                                               notes=spec['backorder'])
                    counts['psa.POBackOrder'] += 1
    for label, n in counts.items():
        ctx.created(label, n)


def _recurring_purchases(ctx):
    from psa.models import RecurringPurchaseTemplate
    owner = _owner(ctx)
    n = 0
    for spec in RECURRING_PURCHASES:
        _, made = RecurringPurchaseTemplate.objects.get_or_create(
            organization=owner, name=spec['name'],
            defaults={'client_org': _client(ctx, spec['client']), 'vendor_name': spec['vendor'],
                      'recurrence': spec['recurrence'], 'line_items_snapshot': spec['lines'],
                      'next_run_at': (ctx.now + timedelta(days=spec['next'])).date(),
                      'description': 'Spawns a draft requisition for review.', 'created_by': ctx.admin})
        n += made
    ctx.created('psa.RecurringPurchaseTemplate', n)


def _project_templates(ctx):
    from psa.models import ProjectTemplate, ProjectTemplateTask
    owner = _owner(ctx)
    n = tasks = 0
    for spec in PROJECT_TEMPLATES:
        if ProjectTemplate.objects.filter(organization=owner, name=spec['name']).exists():
            continue
        tpl = ProjectTemplate.objects.create(organization=owner, name=spec['name'],
                                             description=spec['description'], created_by=ctx.admin)
        n += 1
        for si, (title, hours, offset, milestone, children) in enumerate(spec['tasks']):
            parent = ProjectTemplateTask.objects.create(template=tpl, title=title, estimated_hours=D(hours),
                                                        due_offset_days=offset, is_milestone=milestone,
                                                        sort_order=si * 10)
            tasks += 1
            for ci, (ctitle, chours, coffset) in enumerate(children):
                ProjectTemplateTask.objects.create(template=tpl, parent=parent, title=ctitle,
                                                   estimated_hours=D(chours), due_offset_days=coffset,
                                                   sort_order=ci)
                tasks += 1
    ctx.created('psa.ProjectTemplate', n)
    ctx.created('psa.ProjectTemplateTask', tasks)


def _timesheets(ctx):
    """Submission headers for the last two weeks. Existing time entries are
    left alone (attaching them would edit rows this seeder didn't make)."""
    from psa.models import TimesheetSubmission
    monday = (ctx.now - timedelta(days=ctx.now.weekday())).date()
    n = 0
    for ti, tech in enumerate(_field_techs(ctx)):
        for weeks, status in ((2, 'approved'), (1, 'pending')):
            start = monday - timedelta(weeks=weeks)
            sub, made = TimesheetSubmission.objects.get_or_create(
                user=tech, period_start=start, period_end=start + timedelta(days=6),
                defaults={'status': status, 'submitter_notes': 'Includes Saturday switch swap.' if ti == 0 else '',
                          'decided_by': ctx.admin if status == 'approved' else None,
                          'decided_at': ctx.now - timedelta(days=5) if status == 'approved' else None,
                          'decision_notes': 'Approved.' if status == 'approved' else ''})
            if made:
                _backdate(sub, submitted_at=ctx.now - timedelta(days=7 * weeks - 5))
                n += 1
    ctx.created('psa.TimesheetSubmission', n)


def _ticket_extras(ctx):
    """Expenses, site visits, mileage, checklists, kit and KB links on the
    customers' existing tickets."""
    from docs.models import Document
    from psa.models import (MileageLog, PSAApproval, SiteVisit, TicketChecklistItem, TicketExpense,
                            TicketKBLink, TicketKitItem)
    techs = _field_techs(ctx)
    counts = dict.fromkeys(['psa.TicketExpense', 'psa.PSAApproval', 'psa.SiteVisit', 'psa.MileageLog',
                            'psa.TicketChecklistItem', 'psa.TicketKitItem', 'psa.TicketKBLink'], 0)
    for org in ctx.customers:
        oi = _slot(org)
        tickets = list(_tickets(org).select_related('status')[:6])
        if not tickets:
            continue
        open_tickets = [t for t in tickets if not t.status.is_terminal] or tickets
        tech = techs[oi % len(techs)]
        for ei, (cat, desc, amount, needs_ok) in enumerate(EXPENSES[:2 + oi % 2]):
            ticket = tickets[ei % len(tickets)]
            if TicketExpense.objects.filter(ticket=ticket, description=desc).exists():
                continue
            approval = None
            if needs_ok:
                approval = PSAApproval.objects.create(
                    organization=org, kind='expense', object_type='psa.TicketExpense', object_id=0,
                    object_repr=f'{desc} - ${amount}', requested_by=tech, related_ticket=ticket,
                    request_comment='Bought locally to get the user working the same day.',
                    status='approved' if ei == 0 else 'pending',
                    decided_by=ctx.admin if ei == 0 else None,
                    decided_at=ctx.now - timedelta(days=1) if ei == 0 else None)
                counts['psa.PSAApproval'] += 1
            exp = TicketExpense.objects.create(
                ticket=ticket, user=tech, category=cat, description=desc, amount=D(amount),
                incurred_on=(ctx.now - timedelta(days=3 + ei)).date(), is_billable=cat != 'mileage',
                approval=approval)
            if approval:
                PSAApproval.objects.filter(pk=approval.pk).update(object_id=exp.pk)
            counts['psa.TicketExpense'] += 1

        visit_ticket = open_tickets[0]
        if not SiteVisit.objects.filter(ticket=visit_ticket, technician=tech).exists():
            arrived = ctx.now - timedelta(days=2, hours=3)
            lat, lng = D('42.3601') + D(oi) / 100, D('-71.0589') - D(oi) / 100
            v = SiteVisit.objects.create(
                organization=org, ticket=visit_ticket, technician=tech, checked_out_at=arrived + timedelta(
                    minutes=95), duration_minutes=95, arrival_lat=lat, arrival_lng=lng, departure_lat=lat,
                departure_lng=lng, notes='Onsite: replaced patch leads, tested with the user, all working.')
            _backdate(v, checked_in_at=arrived)
            counts['psa.SiteVisit'] += 1
        purpose = f'Onsite at {org.name}'
        trip = (ctx.now - timedelta(days=2)).date()
        if not MileageLog.objects.filter(organization=org, technician=tech, trip_date=trip,
                                         purpose=purpose).exists():
            MileageLog.objects.create(organization=org, ticket=visit_ticket, technician=tech, trip_date=trip,
                                      miles=D('18.4') + oi * D('6.5'), purpose=purpose,
                                      notes='Round trip from the office.')
            counts['psa.MileageLog'] += 1

        check_ticket = open_tickets[-1]
        for si, label in enumerate(CHECKLIST):
            done = si < 2
            _, made = TicketChecklistItem.objects.get_or_create(
                ticket=check_ticket, label=label,
                defaults={'sort_order': si, 'is_required': si != 2, 'is_completed': done,
                          'completed_at': ctx.now - timedelta(hours=20 - si) if done else None,
                          'completed_by': tech if done else None})
            counts['psa.TicketChecklistItem'] += made
        for si, (desc, qty) in enumerate(KIT):
            _, made = TicketKitItem.objects.get_or_create(
                organization=org, ticket=visit_ticket, kind=TicketKitItem.KIND_OTHER, description=desc,
                defaults={'quantity': qty, 'sort_order': si, 'packed': si == 0,
                          'packed_at': ctx.now - timedelta(days=2, hours=4) if si == 0 else None,
                          'packed_by': tech if si == 0 else None})
            counts['psa.TicketKitItem'] += made

        docs = list(Document.objects.filter(organization=org, is_archived=False, is_template=False)
                    .order_by('pk')[:3])
        for di, doc in enumerate(docs):
            _, made = TicketKBLink.objects.get_or_create(
                ticket=tickets[di % len(tickets)], article=doc,
                defaults={'linked_by': tech, 'note': 'Followed this procedure for the fix.'})
            counts['psa.TicketKBLink'] += made
    for label, n in counts.items():
        ctx.created(label, n)


def _csat(ctx):
    from psa.models import TicketCSATSurvey
    n = 0
    for org in ctx.customers:
        closed = (_tickets(org).filter(status__is_terminal=True, csat_survey__isnull=True)
                  .exclude(requester_email='')[:len(CSAT_RESPONSES)])
        for i, ticket in enumerate(closed):
            rating, comment = CSAT_RESPONSES[i]
            done = ticket.closed_at or ctx.now - timedelta(days=3)
            s = TicketCSATSurvey.objects.create(ticket=ticket, organization=org,
                                                recipient_email=ticket.requester_email, rating=rating,
                                                comment=comment, responded_at=done + timedelta(hours=5))
            _backdate(s, sent_at=done)
            n += 1
    ctx.created('psa.TicketCSATSurvey', n)


def _meters(ctx):
    from django.db.models import Q
    from psa.models import Contract, ContractMeter
    ids = [o.pk for o in ctx.customers]
    n = 0
    for ci, contract in enumerate(Contract.objects.filter(Q(client_org_id__in=ids) | Q(organization_id__in=ids))
                                  .order_by('pk')[:6]):
        for name, unit, price, qty in METERS[:2 + ci % 2]:
            _, made = ContractMeter.objects.get_or_create(
                contract=contract, name=name,
                defaults={'unit': unit, 'unit_price': D(price), 'current_quantity': D(qty),
                          'last_billed_at': ctx.now - timedelta(days=12)})
            n += made
    ctx.created('psa.ContractMeter', n)


def _crm(ctx):
    from crm.models import Campaign, Commission, CommissionRule, Lead, Opportunity, SalesActivity
    owner = _owner(ctx)
    techs = list(ctx.techs)
    counts = dict.fromkeys(['crm.Campaign', 'crm.Lead', 'crm.Opportunity', 'crm.SalesActivity',
                            'crm.CommissionRule', 'crm.Commission'], 0)
    campaigns = []
    for name, channel, budget, start, length in CAMPAIGNS:
        c, made = Campaign.objects.get_or_create(
            organization=owner, name=name,
            defaults={'channel': channel, 'budget': D(budget), 'created_by': ctx.admin,
                      'start_date': (ctx.now + timedelta(days=start)).date(),
                      'end_date': (ctx.now + timedelta(days=start + length)).date() if length else None,
                      'description': f'{name} aimed at 10-150 seat businesses in the region.'})
        campaigns.append(c)
        counts['crm.Campaign'] += made

    leads = []
    for li, (company, first, last, title, industry, staff, value, status, camp) in enumerate(LEADS):
        lead = Lead.objects.filter(organization=owner, company_name=company).first()
        if lead is None:
            slug = company.lower().replace('&', 'and').replace('.', '').replace(' ', '')
            lead = Lead.objects.create(
                organization=owner, company_name=company, contact_first_name=first, contact_last_name=last,
                contact_title=title, contact_email=f'{first.lower()}.{last.lower()}@{slug}.example.com',
                contact_phone=f'+1 555 01{li:02d}', website=f'https://{slug}.example.com', industry=industry,
                employee_count=staff, estimated_value=D(value), status=status,
                source='Webinar sign-up' if camp == 0 else ('Partner referral' if camp == 1 else 'Website'),
                campaign=campaigns[camp] if camp is not None else None, assigned_to=techs[li % len(techs)],
                created_by=ctx.admin,
                notes='Disqualified: too small for managed services; sent break/fix rates.'
                if status == 'disqualified' else '')
            _backdate(lead, created_at=ctx.now - timedelta(days=4 + li * 5))
            counts['crm.Lead'] += 1
            if status != 'new':
                SalesActivity.objects.create(
                    organization=owner, lead=lead, activity_type='call', duration_minutes=20, user=lead.assigned_to,
                    subject=f'Intro call with {first} {last}', occurred_at=ctx.now - timedelta(days=2 + li),
                    body=f'{staff} staff, current IT is one in-house generalist. Pain points: backups and '
                         'onboarding new starters.',
                    outcome='Booked a discovery meeting' if status == 'qualified' else 'Sending overview pack')
                counts['crm.SalesActivity'] += 1
        leads.append(lead)

    rules = []
    for name, prio, floor, rate, flat in COMMISSION_RULES:
        r, made = CommissionRule.objects.get_or_create(
            organization=owner, name=name,
            defaults={'priority': prio, 'min_value': D(floor), 'rate_pct': D(rate), 'flat_amount': D(flat),
                      'notes': 'Paid the month after the first invoice is collected.'})
        rules.append(r)
        counts['crm.CommissionRule'] += made

    for oi, spec in enumerate(OPPORTUNITIES):
        client = ctx.customer(spec['client'])
        if Opportunity.objects.filter(organization=owner, client_org=client, name=spec['name']).exists():
            continue
        closed = spec['stage'] in ('closed_won', 'closed_lost')
        close = (ctx.now + timedelta(days=spec['close'])).date()
        opp = Opportunity.objects.create(
            organization=owner, client_org=client, name=spec['name'], stage=spec['stage'],
            estimated_value=D(spec['value']), probability_pct=spec['prob'], expected_close_date=close,
            actual_close_date=close if closed else None, lost_reason=spec.get('lost', ''),
            campaign=campaigns[oi % len(campaigns)] if oi % 2 == 0 else None,
            assigned_to=techs[oi % len(techs)], created_by=ctx.admin,
            description=f'{spec["name"]} for {client.name}.')
        _backdate(opp, created_at=ctx.now - timedelta(days=30 + oi * 4))
        counts['crm.Opportunity'] += 1
        for kind, subject, days in (('meeting', 'Discovery meeting onsite', 25),
                                    ('proposal_sent', 'Proposal sent', 10)):
            if kind == 'proposal_sent' and spec['stage'] in ('discovery', 'qualified'):
                continue
            SalesActivity.objects.create(
                organization=owner, opportunity=opp, activity_type=kind, subject=subject, user=opp.assigned_to,
                occurred_at=ctx.now - timedelta(days=days + oi), duration_minutes=60 if kind == 'meeting' else None,
                body='Walked through current setup, risks and a phased plan.' if kind == 'meeting'
                else 'Proposal and SOW sent for review.')
            counts['crm.SalesActivity'] += 1
        if spec['stage'] == 'closed_won' and opp.assigned_to:
            rule = next((r for r in rules if r.matches(opp)), None)
            if rule and not Commission.objects.filter(opportunity=opp, user=opp.assigned_to).exists():
                Commission.objects.create(
                    opportunity=opp, user=opp.assigned_to, rule=rule, amount=rule.compute(opp).quantize(D('0.01')),
                    status='approved', approved_at=ctx.now - timedelta(days=2), approved_by=ctx.admin,
                    notes='First invoice paid.')
                counts['crm.Commission'] += 1
    for label, n in counts.items():
        ctx.created(label, n)


def seed(ctx):
    _canned_replies(ctx)
    changes = _changes(ctx)
    _releases(ctx, changes)
    _problems(ctx, changes)
    _procurement(ctx)
    _recurring_purchases(ctx)
    _project_templates(ctx)
    _timesheets(ctx)
    _ticket_extras(ctx)
    _csat(ctx)
    _meters(ctx)
    _crm(ctx)
