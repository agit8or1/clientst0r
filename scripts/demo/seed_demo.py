"""Fill the isolated demo database with the invented MSP dataset the
documentation screenshots are taken from.

Run it through ``setup_demo.py`` (which migrates first and runs the app's own
seed commands around it), or on its own against an already-migrated demo
database:

    export DEMO_DIR=/var/tmp/clientst0r-demo
    export PYTHONPATH=scripts/demo:.
    python scripts/demo/seed_demo.py

One MSP tenant (Beacon Managed IT) and four client tenants. Every organization,
person, hostname, address, IP and credential below is invented; domains use the
reserved ``.example`` TLD and addresses are RFC 1918. Vault entries hold
placeholder strings.

The script refuses to run unless the configured database is the demo SQLite
file under ``$DEMO_DIR``. Most sections are idempotent (get_or_create); run it
on a fresh database for predictable primary keys, which the screenshot manifest
refers to (``/assets/9/``, ``/monitoring/racks/6/``, ``PSA-2026-000001`` …).
"""
import os
import pathlib
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts' / 'demo'))
os.chdir(ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402


def guard_demo_database():
    db = settings.DATABASES['default']
    name = str(db.get('NAME', ''))
    demo_dir = os.environ.get('DEMO_DIR', '')
    if 'sqlite' not in db.get('ENGINE', '') or not demo_dir or not name.startswith(demo_dir):
        raise SystemExit(f'Refusing to seed: {name!r} is not the demo SQLite database under $DEMO_DIR.')


guard_demo_database()

from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402
from django.utils.text import slugify  # noqa: E402

User = get_user_model()
now = timezone.now()
today = now.date()


def org(name):
    from core.models import Organization
    return Organization.objects.get(name=name)


def user(username):
    return User.objects.get(username=username)


# ---------------------------------------------------------------------------
# Clients, technicians, assets, documentation, vault, monitors, contracts,
# tickets
# ---------------------------------------------------------------------------

def seed_showcase():
    from accounts.models import Membership, UserProfile, UserType
    from assets.models import Asset, Contact
    from core.models import Organization
    from docs.models import Document, DocumentCategory
    from monitoring.models import WebsiteMonitor
    from psa.models import (
        Contract, Queue, Ticket, TicketComment, TicketPriority, TicketStatus,
        TicketTimeEntry, TicketType,
    )
    from vault.models import Password, PasswordFolder

    random.seed(20260915)

    TECHS = [
        ('demo.tech', 'Jordan', 'Reyes'),
        ('demo.ipatel', 'Priya', 'Patel'),
        ('demo.mokafor', 'Marcus', 'Okafor'),
        ('demo.lchen', 'Lena', 'Chen'),
    ]
    techs = []
    for username, first, last in TECHS:
        u, _ = User.objects.get_or_create(
            username=username, defaults={'email': f'{username}@example.com', 'is_staff': True})
        u.first_name, u.last_name, u.is_staff = first, last, True
        u.set_unusable_password()
        u.save()
        # MSP technicians are Staff users: they work across every customer.
        profile, _ = UserProfile.objects.get_or_create(user=u)
        profile.user_type = UserType.STAFF
        profile.save()
        techs.append(u)
    lead = techs[0]
    lead.is_superuser = True
    lead.save()

    CLIENTS = [
        dict(name='Northwind Logistics', city='Columbus', state='OH',
             primary_contact_name='Dana Whitfield', primary_contact_title='Operations Director',
             website='https://northwind.example', phone='+1 555 0142'),
        dict(name='Ridgeline Dental Group', city='Boise', state='ID',
             primary_contact_name='Dr. Alan Brekke', primary_contact_title='Practice Owner',
             website='https://ridgeline.example', phone='+1 555 0177'),
        dict(name='Harbor Point Credit Union', city='Portland', state='ME',
             primary_contact_name='Rosa Alvarez', primary_contact_title='VP Technology',
             website='https://harborpoint.example', phone='+1 555 0119'),
        dict(name='Cascade Manufacturing', city='Tacoma', state='WA',
             primary_contact_name='Ben Sorensen', primary_contact_title='Plant IT Manager',
             website='https://cascade-mfg.example', phone='+1 555 0163'),
    ]
    orgs = []
    for spec in CLIENTS:
        o, _ = Organization.objects.get_or_create(
            name=spec['name'],
            defaults={'slug': slugify(spec['name']), 'description': 'Managed client — demo data.',
                      'country': 'United States', 'is_active': True,
                      **{k: v for k, v in spec.items() if k != 'name'}})
        orgs.append(o)

    acme = Organization.objects.filter(name__in=['Acme Corporation', 'Beacon Managed IT']).first()
    all_orgs = ([acme] if acme else []) + orgs
    for u in techs:
        for o in all_orgs:
            Membership.objects.get_or_create(
                user=u, organization=o, defaults={'role': 'admin', 'is_active': True})

    ASSETS = {
        'Northwind Logistics': [
            ('NWL-DC01', 'server', 'Dell', 'PowerEdge R650', 'dc01.northwind.example', '10.42.1.10',
             'Primary domain controller — Server 2022, FSMO roles.'),
            ('NWL-FS01', 'server', 'Dell', 'PowerEdge R450', 'fs01.northwind.example', '10.42.1.12',
             'File server — DFS namespace, Veeam protected nightly.'),
            ('NWL-FW01', 'firewall', 'Fortinet', 'FortiGate 91G', 'fw01.northwind.example', '10.42.0.1',
             'Edge firewall — dual WAN, SD-WAN to the Dayton depot.'),
            ('NWL-SW-CORE', 'switch', 'Aruba', 'CX 6300M', 'sw-core.northwind.example', '10.42.0.2',
             'Core stack — 2x48 port, VSF pair.'),
            ('NWL-WH-AP07', 'wireless_ap', 'Ubiquiti', 'U6 Enterprise', 'ap07.northwind.example', '10.42.4.27',
             'Warehouse ceiling AP — bay 7, PoE from SW-WH02.'),
            ('NWL-NAS01', 'server', 'Synology', 'RS2423+', 'nas01.northwind.example', '10.42.1.40',
             'Backup target — 60 TB usable, immutable snapshots enabled.'),
        ],
        'Ridgeline Dental Group': [
            ('RDG-SRV01', 'server', 'HPE', 'ProLiant DL360 Gen11', 'srv01.ridgeline.example', '10.20.1.5',
             'Practice management + imaging server.'),
            ('RDG-FW01', 'firewall', 'Ubiquiti', 'UDM-SE', 'fw01.ridgeline.example', '10.20.0.1',
             'Gateway — segregated VLAN for imaging hardware.'),
            ('RDG-OP3-PC', 'workstation', 'Lenovo', 'ThinkCentre M70q', 'op3.ridgeline.example', '10.20.2.23',
             'Operatory 3 chairside workstation.'),
        ],
        'Harbor Point Credit Union': [
            ('HPC-HV01', 'server', 'Dell', 'PowerEdge R760', 'hv01.harborpoint.example', '10.60.1.10',
             'Hyper-V host A — 3 guests, cluster witness on NAS01.'),
            ('HPC-HV02', 'server', 'Dell', 'PowerEdge R760', 'hv02.harborpoint.example', '10.60.1.11',
             'Hyper-V host B — failover partner to HV01.'),
            ('HPC-FW01', 'firewall', 'Palo Alto', 'PA-450', 'fw01.harborpoint.example', '10.60.0.1',
             'Perimeter firewall — PCI in-scope segment.'),
        ],
        'Cascade Manufacturing': [
            ('CAS-SCADA01', 'server', 'Dell', 'PowerEdge T560', 'scada01.cascade.example', '10.80.5.10',
             'SCADA historian — isolated OT VLAN, no internet egress.'),
            ('CAS-SW-LINE2', 'switch', 'Cisco', 'IE-3400', 'sw-line2.cascade.example', '10.80.5.2',
             'Line 2 industrial switch — DIN rail, panel B.'),
        ],
    }
    by_name = {o.name: o for o in orgs}
    for org_name, rows in ASSETS.items():
        o = by_name[org_name]
        for name, atype, mfr, model, host, ip, notes in rows:
            Asset.objects.get_or_create(
                name=name, organization=o,
                defaults=dict(asset_type=atype, manufacturer=mfr, model=model, hostname=host,
                              ip_address=ip, notes=notes, created_by=lead,
                              serial_number=f'{name[:3]}-{random.randint(100000, 999999)}',
                              custom_fields={'status': 'active'}))

    CONTACTS = {
        'Northwind Logistics': [('Dana', 'Whitfield', 'Operations Director'),
                                ('Aaron', 'Lindqvist', 'Warehouse Supervisor')],
        'Ridgeline Dental Group': [('Alan', 'Brekke', 'Practice Owner'),
                                   ('Michelle', 'Duarte', 'Office Manager')],
        'Harbor Point Credit Union': [('Rosa', 'Alvarez', 'VP Technology')],
        'Cascade Manufacturing': [('Ben', 'Sorensen', 'Plant IT Manager')],
    }
    contacts = {}
    for org_name, rows in CONTACTS.items():
        o = by_name[org_name]
        for first, last, title in rows:
            c, _ = Contact.objects.get_or_create(
                organization=o, email=f'{first.lower()}.{last.lower()}@example.com',
                defaults=dict(first_name=first, last_name=last, title=title,
                              phone=f'+1 555 0{random.randint(100, 199)}'))
            contacts.setdefault(org_name, []).append(c)

    cat_runbook, _ = DocumentCategory.objects.get_or_create(name='Runbooks')
    cat_net, _ = DocumentCategory.objects.get_or_create(name='Network')
    DOCS = [
        ('Northwind Logistics', cat_net, 'Northwind — Network Overview', """
<h2>Sites</h2>
<p>Columbus HQ (10.42.0.0/16) and the Dayton depot (10.43.0.0/16), joined by an
SD-WAN overlay on the FortiGate pair. Depot traffic egresses through HQ.</p>
<h2>VLANs</h2>
<table><tr><th>VLAN</th><th>Subnet</th><th>Purpose</th></tr>
<tr><td>10</td><td>10.42.1.0/24</td><td>Servers</td></tr>
<tr><td>20</td><td>10.42.2.0/24</td><td>Staff workstations</td></tr>
<tr><td>40</td><td>10.42.4.0/22</td><td>Warehouse Wi-Fi + scanners</td></tr>
<tr><td>90</td><td>10.42.9.0/24</td><td>Management / out-of-band</td></tr></table>
<h2>Internet</h2>
<p>Primary: 1 Gbps fibre. Failover: 500/50 coax, auto-failover verified quarterly.</p>"""),
        ('Northwind Logistics', cat_runbook, 'Runbook — Warehouse Scanner Onboarding', """
<h2>When to use</h2>
<p>A new handheld scanner arrives, or a unit is replaced under warranty.</p>
<h2>Steps</h2>
<ol>
<li>Record the serial in Assets under Northwind Logistics.</li>
<li>Join the device to the <code>NWL-WH</code> SSID (VLAN 40) using the shared
    scanner credential in the vault.</li>
<li>Install the WMS client and point it at <code>wms.northwind.example</code>.</li>
<li>Test a pick and a putaway in bay 7 before handing it to the supervisor.</li>
<li>Label the unit and close the onboarding ticket with the serial in the notes.</li>
</ol>
<h2>Escalation</h2>
<p>If the scanner cannot reach the WMS, check AP07 first — bay 7 has a known
dead spot when the tall racking is fully loaded.</p>"""),
        ('Ridgeline Dental Group', cat_runbook, 'Runbook — Imaging Workstation Rebuild', """
<h2>Prerequisites</h2>
<p>Confirm the imaging vendor licence seat is free before wiping. Rebuilds
outside business hours only — operatories run 07:00–17:00 local.</p>
<h2>Steps</h2>
<ol>
<li>Export the local calibration profile to the file server.</li>
<li>Reimage from the standard operatory image.</li>
<li>Reinstall the sensor driver, then restore the calibration profile.</li>
<li>Capture a test image and confirm it lands in the patient record.</li>
</ol>"""),
        ('Harbor Point Credit Union', cat_net, 'Harbor Point — PCI Segment Notes', """
<h2>Scope</h2>
<p>The card-handling segment sits behind the PA-450 on its own VLAN with an
explicit allow-list. No general staff subnet reaches it.</p>
<h2>Change control</h2>
<p>Firewall changes in this segment require a change request with two approvals
and a named rollback step. Quarterly rule review is tracked as a recurring ticket.</p>"""),
    ]
    for org_name, cat, title, body in DOCS:
        Document.objects.get_or_create(
            organization=by_name[org_name], slug=slugify(title),
            defaults=dict(title=title, body=body, category=cat, is_published=True,
                          created_by=lead, content_type='html'))

    KB = [
        ('Outlook repeatedly prompts for credentials', """
<h2>Symptom</h2>
<p>A user is prompted for their password every time Outlook starts, and the
prompt returns even after a correct password is entered.</p>
<h2>Most common causes</h2>
<ol>
<li>A stale cached credential in Windows Credential Manager.</li>
<li>Modern auth disabled for the mailbox after a migration.</li>
<li>The profile still pointing at a decommissioned endpoint.</li>
</ol>
<h2>Fix</h2>
<ol>
<li>Close Outlook. Remove every <code>MicrosoftOffice*</code> entry from
    Credential Manager.</li>
<li>Confirm modern auth is enabled for the mailbox.</li>
<li>Recreate the mail profile and let autodiscover rebuild it.</li>
<li>Reopen Outlook and sign in once. The prompt should not return.</li>
</ol>"""),
        ('Standard workstation build checklist', """
<h2>Before hand-off</h2>
<ul>
<li>Asset recorded with serial, warranty end date, and assigned user.</li>
<li>Disk encryption on, recovery key escrowed.</li>
<li>Endpoint protection installed and reporting.</li>
<li>Backup agent installed and first backup verified.</li>
<li>Local admin removed from the daily-driver account.</li>
</ul>"""),
        ('Backup restore verification procedure', """
<h2>Cadence</h2>
<p>Monthly per protected server, quarterly for a full bare-metal test.</p>
<h2>Procedure</h2>
<ol>
<li>Pick a restore point at least seven days old.</li>
<li>Restore to an isolated network with no route to production.</li>
<li>Boot, log in, and open one real file the client would recognise.</li>
<li>Record the outcome on the verification ticket and attach the job log.</li>
</ol>"""),
    ]
    for title, body in KB:
        Document.objects.get_or_create(
            slug=slugify(title), organization=None,
            defaults=dict(title=title, body=body, is_global=True, is_published=True,
                          category=cat_runbook, created_by=lead, content_type='html'))

    VAULT = [
        ('Northwind Logistics', 'Network', 'FortiGate FW01 — admin', 'nwl-fwadmin',
         'https://fw01.northwind.example', 'Read-only NOC account. Config changes go through a change request.'),
        ('Northwind Logistics', 'Network', 'Core switch stack — enable', 'admin', '',
         'Console + SSH. Rotated at every quarterly review.'),
        ('Northwind Logistics', 'Servers', 'NWL-DC01 — local administrator', 'Administrator', '',
         'Break-glass only. Reveal is logged and notifies the team lead.'),
        ('Northwind Logistics', 'Backup', 'Veeam service account', 'svc_veeam', '',
         'Backup service identity. Not for interactive logon.'),
        ('Ridgeline Dental Group', 'Servers', 'Practice management — admin console', 'pmadmin',
         'https://srv01.ridgeline.example', 'Vendor-supplied admin console.'),
        ('Harbor Point Credit Union', 'Network', 'PA-450 — management', 'netops',
         'https://fw01.harborpoint.example', 'PCI in-scope. Reveal requires approval.'),
    ]
    for org_name, folder_name, title, username, url, notes in VAULT:
        o = by_name[org_name]
        folder, _ = PasswordFolder.objects.get_or_create(name=folder_name, organization=o)
        if not Password.objects.filter(title=title, organization=o).exists():
            p = Password(title=title, organization=o, folder=folder, username=username,
                         url=url, notes=notes, created_by=lead)
            p.set_password('Demo-Placeholder-' + str(random.randint(1000, 9999)))
            p.save()

    for org_name, label, url, status in [
        ('Northwind Logistics', 'Northwind WMS', 'https://wms.northwind.example', 'active'),
        ('Northwind Logistics', 'Northwind public site', 'https://northwind.example', 'active'),
        ('Ridgeline Dental Group', 'Patient portal', 'https://portal.ridgeline.example', 'active'),
        ('Harbor Point Credit Union', 'Online banking', 'https://online.harborpoint.example', 'active'),
        ('Cascade Manufacturing', 'Plant dashboard', 'https://plant.cascade-mfg.example', 'warning'),
    ]:
        WebsiteMonitor.objects.get_or_create(
            organization=by_name[org_name], url=url,
            defaults=dict(name=label, status=status, ssl_enabled=True,
                          last_status_code=200 if status == 'active' else 503,
                          last_response_time_ms=random.randint(90, 380),
                          ssl_expires_at=now + timedelta(days=random.randint(24, 210)),
                          last_checked_at=now - timedelta(minutes=random.randint(1, 9))))

    msp_org = acme or orgs[0]
    for org_name, cname, ctype, rate, hours in [
        ('Northwind Logistics', 'Northwind — Managed Services', 'managed', Decimal('165.00'), Decimal('0')),
        ('Ridgeline Dental Group', 'Ridgeline — Block Hours 40', 'block_hours', Decimal('150.00'), Decimal('40')),
        ('Harbor Point Credit Union', 'Harbor Point — Managed + Compliance', 'managed', Decimal('185.00'), Decimal('0')),
    ]:
        Contract.objects.get_or_create(
            client_org=by_name[org_name], name=cname,
            defaults=dict(organization=msp_org, contract_type=ctype, status='active',
                          start_date=(now - timedelta(days=210)).date(),
                          end_date=(now + timedelta(days=155)).date(),
                          hourly_rate=rate, total_hours=hours,
                          hours_used_minutes=random.randint(600, 1500)))

    S = {s.name: s for s in TicketStatus.objects.all()}
    P = {p.name: p for p in TicketPriority.objects.all()}
    T = {t.name: t for t in TicketType.objects.all()}
    Q = {q.name: q for q in Queue.objects.all()}

    def pick(mapping, *names):
        for n in names:
            if n in mapping:
                return mapping[n]
        return next(iter(mapping.values()))

    TICKETS = [
        dict(org='Northwind Logistics', subject='Warehouse scanners dropping Wi-Fi in bay 7',
             status='In Progress', priority='High', ttype='Incident', queue='Helpdesk',
             tech=0, age_h=5, asset='NWL-WH-AP07',
             desc=('Pickers in bay 7 report handheld scanners disconnecting for 10–20 seconds '
                   'at a time, roughly every few minutes. Started after the tall racking was '
                   'restocked on Monday. Bays 1–6 are unaffected.'),
             comments=[
                 (0, False, 'Confirmed with the supervisor: three units affected, all in bay 7. '
                            'Pulled the AP07 client log — repeated deauth with reason 4 (inactivity).'),
                 (1, True, 'Heads up — the racking change put a steel wall between AP07 and the '
                           'pick path. Signal at the far end reads -78 dBm on a survey walk.'),
                 (0, False, 'Proposed fix: relocate AP07 one bay south and drop min RSSI to -75. '
                            'Scheduled with Dana for Thursday 06:00 before first shift.'),
             ],
             times=[(0, 45, True, 'Onsite survey — bay 7 signal walk'),
                    (0, 30, True, 'Controller log review and AP config comparison')]),
        dict(org='Harbor Point Credit Union', subject='Quarterly firewall rule review — PCI segment',
             status='Scheduled', priority='Normal', ttype='Change Request', queue='Security',
             tech=1, age_h=52, asset='HPC-FW01',
             desc='Recurring quarterly review of the PA-450 rule base for the in-scope segment.',
             comments=[(1, True, 'Export pulled. 4 rules with no hits in 90 days — candidates for '
                                 'removal, pending owner confirmation.')],
             times=[(1, 90, True, 'Rule base export and hit-count analysis')]),
        dict(org='Ridgeline Dental Group', subject='Operatory 3 workstation will not boot',
             status='Resolved', priority='Critical', ttype='Incident', queue='Helpdesk',
             tech=2, age_h=96, asset='RDG-OP3-PC',
             desc='Chairside PC in operatory 3 powers on but stops at the firmware splash screen.',
             comments=[(2, False, 'Failed NVMe. Swapped from the spare pool, reimaged, calibration '
                                  'profile restored. Test image captured successfully — back in service.')],
             times=[(2, 120, True, 'Onsite — drive replacement, reimage, calibration restore')]),
        dict(org='Cascade Manufacturing', subject='Line 2 switch reporting high error counters',
             status='Assigned', priority='High', ttype='Incident', queue='Monitoring',
             tech=3, age_h=11, asset='CAS-SW-LINE2',
             desc='Monitoring flagged rising CRC errors on the IE-3400 uplink in panel B.',
             comments=[], times=[]),
        dict(org='Northwind Logistics', subject='New hire — warehouse supervisor onboarding',
             status='New', priority='Normal', ttype='Service Request', queue='Helpdesk',
             tech=None, age_h=2, asset=None,
             desc='Account, licence, handheld scanner and badge for a new supervisor starting Monday.',
             comments=[], times=[]),
        dict(org='Ridgeline Dental Group', subject='Backup restore verification — February',
             status='In Progress', priority='Normal', ttype='Service Request', queue='Projects',
             tech=1, age_h=30, asset=None,
             desc='Monthly restore test for the practice management server.',
             comments=[], times=[(1, 60, False, 'Restore test to isolated network')]),
        dict(org='Harbor Point Credit Union', subject='MFA enrolment for three new tellers',
             status='Waiting on Client', priority='Low', ttype='Service Request', queue='Helpdesk',
             tech=0, age_h=64, asset=None,
             desc='Enrol three new staff in MFA and confirm conditional access applies.',
             comments=[(0, False, 'Enrolment links sent to all three tellers. Waiting for them '
                                  'to complete registration on their phones.')],
             times=[]),
        dict(org='Cascade Manufacturing', subject='SCADA historian disk at 88%',
             status='Assigned', priority='Normal', ttype='Incident', queue='Monitoring',
             tech=3, age_h=20, asset='CAS-SCADA01',
             desc='Historian data volume trending toward full. Retention policy review needed.',
             comments=[], times=[]),
        dict(org='Northwind Logistics', subject='Depot link failover test',
             status='Closed', priority='Low', ttype='Change Request', queue='Projects',
             tech=2, age_h=200, asset='NWL-FW01',
             desc='Quarterly WAN failover verification for the Dayton depot.',
             comments=[], times=[(2, 45, True, 'Failover test and documentation update')]),
    ]
    for spec in TICKETS:
        o = by_name[spec['org']]
        if Ticket.objects.filter(organization=o, subject=spec['subject']).exists():
            continue
        created = now - timedelta(hours=spec['age_h'])
        asset = Asset.objects.filter(organization=o, name=spec['asset']).first() if spec['asset'] else None
        contact_list = contacts.get(spec['org']) or []
        status = pick(S, spec['status'])
        t = Ticket.objects.create(
            organization=o, contact=contact_list[0] if contact_list else None,
            subject=spec['subject'], description=spec['desc'], status=status,
            priority=pick(P, spec['priority']), ticket_type=pick(T, spec['ttype']),
            queue=pick(Q, spec['queue']),
            assigned_to=techs[spec['tech']] if spec['tech'] is not None else None,
            related_asset=asset, source='email' if spec['age_h'] % 2 else 'manual',
            client_can_view=True,
            first_response_due_at=created + timedelta(hours=1),
            resolution_due_at=created + timedelta(hours=8),
            first_response_at=created + timedelta(minutes=random.randint(8, 40)))
        Ticket.objects.filter(pk=t.pk).update(created_at=created)
        if status.is_terminal:
            Ticket.objects.filter(pk=t.pk).update(
                resolved_at=created + timedelta(hours=3),
                resolution_summary='Root cause found and fixed; confirmed with the customer.')
        for offset, (tech_idx, internal, body) in enumerate(spec['comments']):
            c = TicketComment.objects.create(ticket=t, author=techs[tech_idx], body=body,
                                             is_internal=internal)
            TicketComment.objects.filter(pk=c.pk).update(
                created_at=created + timedelta(minutes=35 + offset * 70))
        for tech_idx, minutes, billable, note in spec['times']:
            TicketTimeEntry.objects.create(
                ticket=t, user=techs[tech_idx], started_at=created + timedelta(hours=1),
                ended_at=created + timedelta(hours=1, minutes=minutes),
                duration_minutes=minutes, is_billable=billable, notes=note)
    print('  showcase: orgs', Organization.objects.count(), '| assets', Asset.objects.count(),
          '| tickets', Ticket.objects.count())


def seed_presentation():
    """Neutral background, confirmed 2FA devices for the capture users, live
    monitor state, mapped sites and a populated schedule."""
    from accounts.models import UserProfile
    from core.models import Organization, SystemSetting
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from locations.models import Location
    from monitoring.models import WebsiteMonitor
    from psa.models import ClientPSASettings
    from scheduling.models import ScheduledTask

    random.seed(7)
    ss = SystemSetting.get_settings()
    ss.background_policy = 'user'
    ss.psa_enabled = True
    ss.save()
    UserProfile.objects.update(background_mode='none')

    for u in User.objects.filter(username__startswith='demo.'):
        TOTPDevice.objects.get_or_create(user=u, name='default', defaults={'confirmed': True})
        TOTPDevice.objects.filter(user=u).update(confirmed=True)

    for o in Organization.objects.all():
        cs, _ = ClientPSASettings.objects.get_or_create(organization=o)
        for f in ('psa_enabled', 'enabled', 'use_native_psa'):
            if hasattr(cs, f):
                setattr(cs, f, True)
        cs.save()

    for m in WebsiteMonitor.objects.all():
        m.status = m.status if m.status in ('active', 'warning', 'down') else 'active'
        m.last_checked_at = now - timedelta(minutes=random.randint(1, 8))
        m.last_status_code = 200 if m.status == 'active' else 503
        m.last_response_time_ms = random.randint(88, 410)
        m.ssl_enabled = True
        m.ssl_expires_at = m.ssl_expires_at or now + timedelta(days=random.randint(21, 200))
        m.save()

    SITES = {
        'Northwind Logistics': [('Columbus HQ', '2400 Cannon Dr', 'Columbus', 'OH', '43210', 39.9987, -83.0180),
                                ('Dayton Depot', '1150 Webster St', 'Dayton', 'OH', '45404', 39.7719, -84.1839)],
        'Ridgeline Dental Group': [('Boise Practice', '810 W Main St', 'Boise', 'ID', '83702', 43.6165, -116.2023)],
        'Harbor Point Credit Union': [('Portland Branch', '55 Commercial St', 'Portland', 'ME', '04101', 43.6569, -70.2531)],
        'Cascade Manufacturing': [('Tacoma Plant', '3400 E 11th St', 'Tacoma', 'WA', '98421', 47.2540, -122.4100)],
        'Acme Corporation': [('Acme HQ', '500 Market St', 'San Francisco', 'CA', '94105', 37.7912, -122.3985)],
    }
    for org_name, rows in SITES.items():
        o = Organization.objects.filter(name=org_name).first()
        if not o:
            continue
        for i, (name, street, city, state, zipc, lat, lng) in enumerate(rows):
            Location.objects.get_or_create(
                organization=o, name=name,
                defaults=dict(street_address=street, city=city, state=state, postal_code=zipc,
                              latitude=lat, longitude=lng, is_primary=(i == 0),
                              location_type='office' if i == 0 else 'warehouse'))

    lead = user('demo.tech')
    TASKS = [
        ('Northwind Logistics', 'Relocate warehouse AP07 (bay 7)', None, 'high'),
        ('Northwind Logistics', 'Quarterly WAN failover test — Dayton depot', 4, 'normal'),
        ('Harbor Point Credit Union', 'PCI firewall rule review sign-off', 2, 'high'),
        ('Ridgeline Dental Group', 'Monthly restore verification', 3, 'normal'),
        ('Cascade Manufacturing', 'SCADA historian retention review', 5, 'normal'),
        ('Northwind Logistics', 'Patch window — file server cluster', 6, 'normal'),
    ]
    for org_name, title, days, prio in TASKS:
        o = Organization.objects.get(name=org_name)
        due = (now + timedelta(hours=3) if days is None
               else (now + timedelta(days=days)).replace(hour=15, minute=0, second=0, microsecond=0))
        t, created = ScheduledTask.objects.get_or_create(
            organization=o, title=title,
            defaults=dict(due_date=due, priority=prio, status='pending', created_by=lead,
                          description='Demo data — scheduled maintenance item.'))
        if created:
            t.assigned_to.add(lead)

    DESCRIPTIONS = {
        'Northwind Logistics': 'Regional 3PL — Columbus HQ plus a Dayton depot. Managed services since 2023.',
        'Ridgeline Dental Group': 'Three-chair practice. Imaging hardware on a segregated VLAN.',
        'Harbor Point Credit Union': 'Member-owned credit union. PCI in-scope segment under change control.',
        'Cascade Manufacturing': 'Two production lines with an isolated OT network and SCADA historian.',
    }
    for n, d in DESCRIPTIONS.items():
        Organization.objects.filter(name=n).update(description=d)
    print('  presentation: locations', Location.objects.count(),
          '| scheduled tasks', ScheduledTask.objects.count())


def seed_asset_detail():
    from assets.models import Asset, Contact
    from core.models import Tag
    from vault.models import Password, PasswordFolder

    random.seed(11)
    lead = user('demo.tech')
    nwl = org('Northwind Logistics')
    SPECS = {
        'NWL-DC01': dict(asset_tag='NWL-0142', mac_address='B0:83:FE:4C:21:9A',
                         os_name='Windows Server', os_version='2022 Datacenter (21H2)',
                         cpu='Intel Xeon Silver 4314 (16C/32T)', ram_gb=128,
                         storage='2× 960 GB SSD (RAID 1) + 4× 2 TB SAS (RAID 10)',
                         is_rackmount=True, rack_units=1, firmware_version='iDRAC 9 7.10.30.00',
                         purchase_date=today - timedelta(days=560), lifespan_years=5,
                         warranty_expiry=today + timedelta(days=430),
                         warranty_status='ProSupport NBD — active'),
        'NWL-FS01': dict(asset_tag='NWL-0143', mac_address='B0:83:FE:4C:22:0D',
                         os_name='Windows Server', os_version='2022 Standard',
                         cpu='Intel Xeon Silver 4310 (12C/24T)', ram_gb=64,
                         storage='2× 480 GB SSD (RAID 1) + 6× 4 TB SAS (RAID 6)',
                         is_rackmount=True, rack_units=1,
                         purchase_date=today - timedelta(days=430), lifespan_years=5,
                         warranty_expiry=today + timedelta(days=300),
                         warranty_status='ProSupport NBD — active'),
        'NWL-FW01': dict(asset_tag='NWL-0101', mac_address='90:6C:AC:11:5E:33',
                         os_name='FortiOS', os_version='7.4.4', port_count=10,
                         is_rackmount=True, rack_units=1, firmware_version='7.4.4 build 2662',
                         purchase_date=today - timedelta(days=300), lifespan_years=5,
                         warranty_expiry=today + timedelta(days=65),
                         warranty_status='FortiCare 24×7 — renews soon'),
        'NWL-SW-CORE': dict(asset_tag='NWL-0102', mac_address='3C:A8:2A:77:1B:04',
                            os_name='ArubaOS-CX', os_version='10.13.1005', port_count=96,
                            is_rackmount=True, rack_units=2, firmware_version='10.13.1005',
                            purchase_date=today - timedelta(days=690), lifespan_years=7,
                            warranty_expiry=today + timedelta(days=760),
                            warranty_status='Aruba Foundation Care — active'),
        'NWL-NAS01': dict(asset_tag='NWL-0161', os_name='DSM', os_version='7.2.1',
                          storage='12× 8 TB SATA (SHR-2, 60 TB usable)', ram_gb=32,
                          is_rackmount=True, rack_units=2,
                          purchase_date=today - timedelta(days=210), lifespan_years=6,
                          warranty_expiry=today + timedelta(days=880),
                          warranty_status='Manufacturer warranty — active'),
        'NWL-WH-AP07': dict(asset_tag='NWL-0207', mac_address='74:AC:B9:20:8F:71',
                            os_name='UniFi', os_version='6.6.77', port_count=1,
                            purchase_date=today - timedelta(days=120), lifespan_years=5,
                            warranty_expiry=today + timedelta(days=975),
                            warranty_status='Manufacturer warranty — active'),
    }
    tags = {}
    for label, colour in [('Production', '#dc3545'), ('Critical', '#fd7e14'), ('Network', '#0d6efd'),
                          ('Backup', '#198754'), ('Warehouse', '#6f42c1')]:
        t, _ = Tag.objects.get_or_create(name=label, organization=nwl, defaults={'color': colour})
        tags[label] = t
    TAGS = {'NWL-DC01': ['Production', 'Critical'], 'NWL-FS01': ['Production', 'Critical'],
            'NWL-FW01': ['Network', 'Critical'], 'NWL-SW-CORE': ['Network', 'Critical'],
            'NWL-NAS01': ['Backup', 'Production'], 'NWL-WH-AP07': ['Network', 'Warehouse']}
    contact = Contact.objects.filter(email='dana.whitfield@example.com').first()
    for name, spec in SPECS.items():
        a = Asset.objects.filter(name=name).first()
        if not a:
            continue
        for k, v in spec.items():
            setattr(a, k, v)
        a.primary_contact = contact
        a.lifespan_reminder_enabled = True
        a.save()
        a.tags.set([tags[t] for t in TAGS.get(name, [])])

    MORE_VAULT = [
        ('Network', 'Warehouse Wi-Fi — scanner PSK', 'NWL-WH (VLAN 40)', '',
         'Shared PSK for handheld scanners. Rotated when a unit is lost.'),
        ('Servers', 'NWL-FS01 — local administrator', 'Administrator', '',
         'Break-glass only. Reveal is logged.'),
        ('Backup', 'NAS01 — DSM admin', 'nwl-nasadmin', 'https://nas01.northwind.example',
         'Backup appliance console.'),
        ('Applications', 'WMS — vendor support portal', 'northwind-it', 'https://wms.northwind.example',
         'Vendor portal login for raising WMS cases.'),
        ('Applications', 'Microsoft 365 — break-glass admin', 'breakglass@northwind.example', '',
         'Excluded from conditional access. Reveal notifies the team lead.'),
    ]
    for folder_name, title, username, url, notes in MORE_VAULT:
        folder, _ = PasswordFolder.objects.get_or_create(name=folder_name, organization=nwl)
        if not Password.objects.filter(title=title, organization=nwl).exists():
            p = Password(title=title, organization=nwl, folder=folder, username=username,
                         url=url, notes=notes, created_by=lead)
            p.set_password('Demo-Placeholder-' + str(random.randint(1000, 9999)))
            p.save()
    print('  asset detail: enriched', len(SPECS), 'assets')


def seed_commercial():
    from psa.models import Invoice, InvoiceLineItem, Project, ProjectTask, Quote, QuoteLineItem

    msp = org('Acme Corporation')
    nwl, hpc, rdg = org('Northwind Logistics'), org('Harbor Point Credit Union'), org('Ridgeline Dental Group')
    lead, priya, marcus = user('demo.tech'), user('demo.ipatel'), user('demo.mokafor')

    def money(v):
        return Decimal(str(v))

    QUOTES = [
        (nwl, 'Warehouse Wi-Fi remediation — bay 7', 'sent', 18,
         'Relocate AP07, add a second AP at the far end of bay 7, and re-survey after the '
         'racking change. Includes an out-of-hours cutover before first shift.',
         [('Ubiquiti U6 Enterprise access point', 2, 349.00),
          ('PoE injector and mounting hardware', 2, 48.00),
          ('Cat6A drop — warehouse ceiling run', 2, 185.00),
          ('Site survey and post-install validation', 4, 165.00),
          ('Out-of-hours cutover (06:00 window)', 2, 247.50)]),
        (hpc, 'Branch firewall refresh — PA-450 pair', 'accepted', 40,
         'Replace the single perimeter firewall with an HA pair, migrate the in-scope rule '
         'base, and document the change for the quarterly review.',
         [('Palo Alto PA-450 (HA secondary)', 1, 4295.00),
          ('Threat prevention subscription — 12 months', 1, 1180.00),
          ('Rule base migration and HA configuration', 12, 185.00),
          ('Cutover and rollback rehearsal', 6, 185.00)]),
        (rdg, 'Operatory workstation refresh — 3 seats', 'draft', 30,
         'Standard operatory build across three chairs, including imaging sensor drivers '
         'and calibration.',
         [('Lenovo ThinkCentre M70q', 3, 879.00),
          ('24" clinical display', 3, 265.00),
          ('Build, imaging driver install and calibration', 9, 150.00)]),
    ]
    for client, title, status, valid_days, desc, lines in QUOTES:
        if Quote.objects.filter(title=title).exists():
            continue
        q = Quote.objects.create(
            organization=msp, client_org=client, title=title, description=desc,
            status=status, valid_until=today + timedelta(days=valid_days),
            tax_rate=Decimal('0.0725'), created_by=lead,
            sent_at=now - timedelta(days=3) if status in ('sent', 'accepted') else None,
            accepted_at=now - timedelta(days=1) if status == 'accepted' else None)
        for i, (d, qty, price) in enumerate(lines):
            QuoteLineItem.objects.create(quote=q, sort_order=i, description=d,
                                         quantity=money(qty), unit_price=money(price))
        sub = sum(money(qty) * money(price) for _, qty, price in lines)
        tax = (sub * q.tax_rate).quantize(Decimal('0.01'))
        Quote.objects.filter(pk=q.pk).update(subtotal=sub, tax_amount=tax, total=sub + tax)

    INVOICES = [
        (nwl, 'Managed services — September', 'sent', 6, 0,
         [('Managed services retainer — September', 1, 2850.00, 'contract'),
          ('Additional project hours — warehouse Wi-Fi survey', 1.25, 165.00, 'time'),
          ('Handheld scanner replacement (warranty excess)', 1, 89.00, 'expense')]),
        (hpc, 'Quarterly compliance review — Q3', 'paid', 28, 3705.30,
         [('Managed services retainer — September', 1, 3200.00, 'contract'),
          ('PCI segment rule review', 1.5, 185.00, 'time')]),
        (rdg, 'Block hours drawdown — August', 'overdue', 46, 0,
         [('Operatory 3 workstation rebuild', 2, 150.00, 'time'),
          ('NVMe replacement (from spare pool)', 1, 129.00, 'expense'),
          ('Monthly restore verification', 1, 150.00, 'time')]),
    ]
    for client, title, status, age_days, paid, lines in INVOICES:
        if Invoice.objects.filter(title=title, client_org=client).exists():
            continue
        inv = Invoice.objects.create(
            organization=msp, client_org=client, title=title, status=status,
            invoice_date=today - timedelta(days=age_days),
            due_date=today - timedelta(days=age_days) + timedelta(days=30),
            tax_rate=Decimal('0.0725'), amount_paid=money(paid), created_by=lead,
            sent_at=now - timedelta(days=age_days))
        for i, (d, qty, price, src) in enumerate(lines):
            InvoiceLineItem.objects.create(invoice=inv, sort_order=i, description=d,
                                           quantity=money(qty), unit_price=money(price), source=src)
        sub = sum(money(qty) * money(price) for _, qty, price, _ in lines)
        tax = (sub * inv.tax_rate).quantize(Decimal('0.01'))
        Invoice.objects.filter(pk=inv.pk).update(subtotal=sub, tax_amount=tax, total=sub + tax)

    PROJECT = 'Harbor Point — firewall HA rollout'
    if not Project.objects.filter(name=PROJECT).exists():
        pr = Project.objects.create(
            organization=msp, client_org=hpc, name=PROJECT, slug=slugify(PROJECT),
            description='Replace the single perimeter firewall with an HA pair and migrate '
                        'the in-scope rule base under change control.',
            status='active', start_date=today - timedelta(days=12),
            due_date=today + timedelta(days=24), owner=priya, is_billable=True,
            estimated_hours=Decimal('42.00'), budget_hours=Decimal('48.00'),
            budget_amount=Decimal('8880.00'), billing_type='fixed_fee',
            fixed_fee_amount=Decimal('8880.00'))
        TASKS = [
            ('Kick-off and change request raised', 'done', priya, -12, -10, 2, False),
            ('Hardware received and staged', 'done', marcus, -9, -7, 3, True),
            ('Rule base export and clean-up', 'done', priya, -7, -3, 8, False),
            ('HA pair configured in the lab', 'in_progress', priya, -3, 4, 10, False),
            ('Cutover rehearsal with rollback', 'todo', lead, 5, 9, 6, False),
            ('Production cutover (out of hours)', 'todo', priya, 12, 13, 6, True),
            ('Post-change documentation and sign-off', 'todo', marcus, 14, 18, 4, False),
        ]
        prev = None
        for i, (title, status, who, s_off, d_off, hours, milestone) in enumerate(TASKS):
            t = ProjectTask.objects.create(
                project=pr, title=title, status=status, assigned_to=who,
                start_date=today + timedelta(days=s_off), due_date=today + timedelta(days=d_off),
                estimated_hours=Decimal(str(hours)), is_milestone=milestone,
                sort_order=i, created_by=lead,
                completed_at=now - timedelta(days=abs(d_off)) if status == 'done' else None)
            if prev is not None:
                t.depends_on.add(prev)
            prev = t
    print('  commercial: quotes', Quote.objects.count(), '| invoices', Invoice.objects.count())


def rename_msp_tenant():
    from core.models import Organization
    o = Organization.objects.filter(name='Acme Corporation').first()
    if o:
        o.name = 'Beacon Managed IT'
        o.slug = 'beacon-managed-it'
        o.description = 'Our own tenant — the MSP. Client organizations are listed separately.'
        o.city, o.state, o.website = 'Columbus', 'OH', 'https://beaconmanaged.example'
        o.primary_contact_name, o.primary_contact_title = 'Jordan Reyes', 'Service Delivery Lead'
        o.save()


def seed_project_work():
    from psa.models import (
        Project, Queue, Ticket, TicketComment, TicketPriority, TicketStatus,
        TicketTimeEntry, TicketType,
    )
    pr = Project.objects.get(name__startswith='Harbor Point — firewall')
    hpc = org('Harbor Point Credit Union')
    S = {s.name: s for s in TicketStatus.objects.all()}
    P = {p.name: p for p in TicketPriority.objects.all()}
    T = {t.name: t for t in TicketType.objects.all()}
    Q = {q.name: q for q in Queue.objects.all()}
    priya, marcus, lead = user('demo.ipatel'), user('demo.mokafor'), user('demo.tech')
    WORK = [
        ('Stage and rack the HA secondary', 'Resolved', 'Normal', 'Change Request', 'Projects',
         marcus, 9, [(marcus, 180, 'Rack, cable and power the PA-450 secondary'),
                     (marcus, 45, 'Serial console bring-up and licence activation')]),
        ('Export and clean up the in-scope rule base', 'Resolved', 'Normal', 'Change Request', 'Projects',
         priya, 6, [(priya, 240, 'Rule base export, hit-count analysis, dead-rule removal'),
                    (priya, 120, 'Peer review of the proposed rule set')]),
        ('Build the HA pair in the lab', 'In Progress', 'High', 'Change Request', 'Projects',
         priya, 2, [(priya, 300, 'HA config, failover testing against lab traffic'),
                    (lead, 90, 'Second pair of eyes on the failover behaviour')]),
    ]
    for subject, status, prio, ttype, queue, who, age_d, times in WORK:
        if Ticket.objects.filter(subject=subject).exists():
            continue
        created = now - timedelta(days=age_d)
        t = Ticket.objects.create(
            organization=hpc, subject=subject, project=pr,
            description='Project work item — see the project plan for sequencing.',
            status=S[status], priority=P[prio], ticket_type=T[ttype], queue=Q[queue],
            assigned_to=who, client_can_view=True, source='manual',
            first_response_due_at=created + timedelta(hours=1),
            resolution_due_at=created + timedelta(hours=24),
            first_response_at=created + timedelta(minutes=20))
        Ticket.objects.filter(pk=t.pk).update(created_at=created)
        if S[status].is_terminal:
            Ticket.objects.filter(pk=t.pk).update(
                resolved_at=created + timedelta(hours=6),
                resolution_summary='Completed as planned; see the project plan.')
        for u, minutes, note in times:
            TicketTimeEntry.objects.create(
                ticket=t, user=u, started_at=created + timedelta(hours=1),
                ended_at=created + timedelta(hours=1, minutes=minutes),
                duration_minutes=minutes, is_billable=True, notes=note)
    TicketComment.objects.get_or_create(
        ticket=Ticket.objects.get(subject='Build the HA pair in the lab'),
        body='Failover holds at 1.8 s with sessions intact. Ready to schedule the rehearsal '
             'once the change window is confirmed with Rosa.',
        defaults={'author': priya, 'is_internal': False})


def seed_visual():
    from assets.models import Asset
    from monitoring.models import IPAddress, Rack, RackDevice, Subnet, VLAN

    random.seed(42)
    nwl = org('Northwind Logistics')
    rack, _ = Rack.objects.get_or_create(
        organization=nwl, name='HQ Comms Room — Rack A',
        defaults=dict(rack_type='full_rack', datacenter='Columbus HQ', building='HQ',
                      floor='Ground', room='Comms', aisle='A', units=42,
                      width_inches=19, location='Behind the badge reader'))
    DEVICES = [
        ('NWL-FW01 — FortiGate 91G', 40, 1, '#dc3545', 45, 'NWL-FW01'),
        ('NWL-SW-CORE — Aruba CX 6300M', 37, 2, '#0d6efd', 180, 'NWL-SW-CORE'),
        ('Patch panel — 48 port', 35, 2, '#6c757d', 0, None),
        ('NWL-DC01 — PowerEdge R650', 30, 1, '#198754', 320, 'NWL-DC01'),
        ('NWL-FS01 — PowerEdge R450', 28, 1, '#198754', 280, 'NWL-FS01'),
        ('NWL-NAS01 — RS2423+', 24, 2, '#6f42c1', 240, 'NWL-NAS01'),
        ('UPS — 3000VA', 1, 4, '#fd7e14', 0, None),
    ]
    for name, start, units, colour, watts, asset_name in DEVICES:
        asset = Asset.objects.filter(organization=nwl, name=asset_name).first() if asset_name else None
        RackDevice.objects.get_or_create(
            rack=rack, name=name,
            defaults=dict(start_unit=start, units=units, color=colour,
                          power_draw_watts=watts or None, asset=asset))

    VLANS = [(10, 'Servers', 'Server VLAN — HQ comms room', '#0d6efd'),
             (20, 'Staff', 'Office workstations and printers', '#198754'),
             (40, 'Warehouse', 'Handheld scanners and warehouse Wi-Fi', '#fd7e14'),
             (90, 'Management', 'Out-of-band and switch management', '#6f42c1')]
    vlan_objs = {}
    for vid, name, desc, colour in VLANS:
        v, _ = VLAN.objects.get_or_create(organization=nwl, vlan_id=vid,
                                          defaults=dict(name=name, description=desc, color=colour))
        vlan_objs[vid] = v
    SUBNETS = [(10, 'HQ Servers', '10.42.1.0/24', '10.42.1.1', 'Columbus HQ'),
               (20, 'HQ Staff', '10.42.2.0/24', '10.42.2.1', 'Columbus HQ'),
               (40, 'Warehouse Wi-Fi', '10.42.4.0/22', '10.42.4.1', 'Columbus HQ — warehouse'),
               (90, 'Management', '10.42.9.0/24', '10.42.9.1', 'Columbus HQ')]
    for vid, name, network, gw, loc in SUBNETS:
        Subnet.objects.get_or_create(
            organization=nwl, network=network,
            defaults=dict(name=name, vlan=vlan_objs[vid], gateway=gw, location=loc,
                          dns_servers=['10.42.1.10', '10.42.1.12'], description=f'{name} — {loc}'))
    servers = Subnet.objects.get(organization=nwl, network='10.42.1.0/24')
    HOSTS = [('10.42.1.1', 'allocated', 'gw-core', None),
             ('10.42.1.10', 'allocated', 'dc01', 'NWL-DC01'),
             ('10.42.1.12', 'allocated', 'fs01', 'NWL-FS01'),
             ('10.42.1.40', 'allocated', 'nas01', 'NWL-NAS01'),
             ('10.42.1.50', 'reserved', 'hv-spare', None),
             ('10.42.1.51', 'available', '', None),
             ('10.42.1.52', 'available', '', None)]
    for ip, status, host, asset_name in HOSTS:
        asset = Asset.objects.filter(organization=nwl, name=asset_name).first() if asset_name else None
        IPAddress.objects.get_or_create(
            subnet=servers, ip_address=ip,
            defaults=dict(status=status, hostname=host, asset=asset,
                          last_seen_at=(now - timedelta(minutes=random.randint(2, 90))
                                        if status == 'allocated' else None)))
    print('  visual: rack pk', rack.pk, '| subnets', Subnet.objects.filter(organization=nwl).count())


def seed_dispatch():
    """Spread due dates across the coming week so the dispatch board is a schedule."""
    from psa.models import Ticket
    PLAN = [('PSA-2026-000001', 0, 16), ('PSA-2026-000004', 1, 11),
            ('PSA-2026-000008', 1, 15), ('PSA-2026-000012', 2, 13), ('PSA-2026-000006', 3, 10),
            ('PSA-2026-000002', 4, 9), ('PSA-2026-000007', 5, 14)]
    for number, offset, hour in PLAN:
        due = (now + timedelta(days=offset)).replace(hour=hour, minute=0, second=0, microsecond=0)
        Ticket.objects.filter(ticket_number=number).update(resolution_due_at=due)
    # Due within four hours: the dispatch board's "SLA at risk" banner.
    Ticket.objects.filter(ticket_number='PSA-2026-000005').update(
        resolution_due_at=now + timedelta(hours=2, minutes=10))
    # The hero ticket shows a live, healthy SLA; the breach banner is on the dispatch board.
    Ticket.objects.filter(ticket_number='PSA-2026-000001').update(
        first_response_due_at=now - timedelta(hours=4),
        resolution_due_at=now + timedelta(hours=5, minutes=20))


# ---------------------------------------------------------------------------
# 3.17.602–3.17.610: technician workspace, readiness, document lifecycle,
# guided portal requests
# ---------------------------------------------------------------------------

def seed_my_work():
    """Give Jordan (demo.tech) something in every My Work queue: open tickets,
    a running timer, a customer reply, waiting on us / on the customer, a
    pending approval and an internal-note draft."""
    from accounts.models import Membership, UserProfile, UserType
    from assets.models import Contact
    from psa.models import (
        PSAApproval, Queue, Ticket, TicketChecklistItem, TicketComment, TicketDraft,
        TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
    )

    lead, priya = user('demo.tech'), user('demo.ipatel')
    S = {s.name: s for s in TicketStatus.objects.all()}
    P = {p.name: p for p in TicketPriority.objects.all()}
    T = {t.name: t for t in TicketType.objects.all()}
    Q = {q.name: q for q in Queue.objects.all()}
    nwl, rdg, hpc = org('Northwind Logistics'), org('Ridgeline Dental Group'), org('Harbor Point Credit Union')

    # A customer user for Northwind: replies on tickets, and signs in to the portal.
    dana, _ = User.objects.get_or_create(
        username='demo.dwhitfield',
        defaults={'email': 'dana.whitfield@example.com', 'first_name': 'Dana', 'last_name': 'Whitfield'})
    dana.set_unusable_password()
    dana.is_staff = dana.is_superuser = False
    dana.save()
    profile, _ = UserProfile.objects.get_or_create(user=dana)
    profile.user_type = UserType.ORG_USER
    profile.background_mode = 'none'
    profile.save()
    Membership.objects.get_or_create(user=dana, organization=nwl,
                                     defaults={'role': 'admin', 'is_active': True})

    hero = Ticket.objects.get(ticket_number='PSA-2026-000001')
    # Customer replied after Jordan's last public comment.
    reply_at = now - timedelta(minutes=42)
    c = TicketComment.objects.create(
        ticket=hero, author=dana, is_internal=False,
        body='Thursday 06:00 works. Aaron will meet you at the dock door — the racking '
             'contractor is back on Friday, so it would be good to finish before then.')
    TicketComment.objects.filter(pk=c.pk).update(created_at=reply_at)
    Ticket.objects.filter(pk=hero.pk).update(last_client_response_at=reply_at)

    # Running timer on the hero ticket.
    if not TicketTimeEntry.objects.filter(ticket=hero, user=lead, ended_at__isnull=True).exists():
        TicketTimeEntry.objects.create(ticket=hero, user=lead,
                                       started_at=now - timedelta(minutes=38),
                                       notes='Remote — AP07 channel and power changes',
                                       is_billable=True)

    contact = Contact.objects.filter(organization=rdg).first()
    EXTRA = [
        (nwl, 'Label printer at dock 2 prints blank labels', 'New', 'Normal', 'Incident', 3,
         'Since this morning the Zebra at dock 2 feeds labels but nothing prints. Dock 1 is fine.', []),
        (rdg, 'Shared mailbox permissions for the billing team', 'In Progress', 'Normal',
         'Service Request', 26,
         'Michelle and two billing staff need Send As on billing@ridgeline.example.',
         [('staff', 'Send As granted to Michelle. Can you confirm the other two names?', 20),
          ('customer', 'Thanks — the other two are Kim Ortega and Raj Malhotra.', 1)]),
        (hpc, 'VPN disconnects for the remote loan officer', 'Waiting on Client', 'High', 'Incident', 30,
         'Remote loan officer is dropped from the VPN every 20–30 minutes on home Wi-Fi.',
         [('staff', 'Pushed a client profile with a longer keepalive. Please try it today and '
                    'let us know if the drops continue.', 4)]),
    ]
    for o, subject, status, prio, ttype, age_h, desc, thread in EXTRA:
        if Ticket.objects.filter(subject=subject).exists():
            continue
        created = now - timedelta(hours=age_h)
        t = Ticket.objects.create(
            organization=o, subject=subject, description=desc, status=S[status], priority=P[prio],
            ticket_type=T[ttype], queue=Q['Helpdesk'], assigned_to=lead, client_can_view=True,
            source='portal', contact=contact if o == rdg else None,
            first_response_due_at=created + timedelta(hours=1),
            resolution_due_at=now + timedelta(hours=random.randint(3, 30)))
        Ticket.objects.filter(pk=t.pk).update(created_at=created)
        for who, body, hours_ago in thread:
            when = now - timedelta(hours=hours_ago)
            if who == 'staff':
                cm = TicketComment.objects.create(ticket=t, author=lead, body=body, is_internal=False)
                Ticket.objects.filter(pk=t.pk).update(first_response_at=when)
            else:
                cm = TicketComment.objects.create(ticket=t, author=None, body=body, is_internal=False)
                Ticket.objects.filter(pk=t.pk).update(last_client_response_at=when)
            TicketComment.objects.filter(pk=cm.pk).update(created_at=when)

    # A pending approval on Jordan's queue.
    if not PSAApproval.objects.filter(related_ticket=hero).exists():
        PSAApproval.objects.create(
            organization=org('Beacon Managed IT'), kind='expense', object_type='psa.Ticket', object_id=hero.pk,
            object_repr='Second access point for bay 7 — $349.00', requested_by=priya,
            request_comment='Needed to cover the far end of bay 7 after the racking change.',
            related_ticket=hero)

    # Closeout checklist on the shared-mailbox ticket.
    mailbox = Ticket.objects.get(subject='Shared mailbox permissions for the billing team')
    for i, (label, done) in enumerate([('Send As granted to all three named staff', False),
                                       ('Customer confirmed a test send from billing@', False),
                                       ('Mailbox permissions documented', True)]):
        TicketChecklistItem.objects.get_or_create(
            ticket=mailbox, label=label,
            defaults=dict(is_required=True, is_completed=done, sort_order=i,
                          completed_at=now - timedelta(hours=1) if done else None,
                          completed_by=lead if done else None))

    # Internal-note draft on the MFA ticket: the composer opens in internal mode.
    mfa = Ticket.objects.get(subject='MFA enrolment for three new tellers')
    TicketDraft.objects.update_or_create(
        user=lead, ticket=mfa,
        defaults=dict(is_internal=True,
                      body='Two of three tellers registered. Third (T. Nguyen) is on leave until '
                           'Monday — leave the ticket in Waiting on Client and chase on Tuesday.'))
    print('  my work: tickets for demo.tech',
          Ticket.objects.filter(assigned_to=lead).count())


def seed_document_lifecycle():
    """Owners and review dates, a document with version history, drafts, an
    archived page, template drift and KB analytics data."""
    from core.models import Tag
    from docs.models import Document, DocumentCategory, SearchQueryLog

    lead, priya, marcus = user('demo.tech'), user('demo.ipatel'), user('demo.mokafor')
    nwl = org('Northwind Logistics')

    runbook = Document.objects.get(slug='runbook-warehouse-scanner-onboarding')
    if not runbook.versions.exists():
        body = runbook.body
        runbook.last_modified_by = priya
        runbook.body = body.replace(
            '<li>Test a pick and a putaway in bay 7 before handing it to the supervisor.</li>',
            '<li>Test a pick and a putaway in bay 7 before handing it to the supervisor.</li>\n'
            '<li>Confirm the unit roams cleanly between AP06 and AP07 at the bay 7 end cap.</li>')
        runbook.save()
        runbook.last_modified_by = lead
        runbook.body = runbook.body.replace(
            'using the shared\n    scanner credential in the vault.',
            'using the shared\n    scanner credential in the vault. The PSK is rotated whenever a\n'
            '    unit is lost, so always copy it fresh from the vault.').replace(
            'check AP07 first — bay 7 has a known\ndead spot when the tall racking is fully loaded.',
            'check AP07 first. Since the racking change AP07 sits one bay south;\n'
            'if bay 7 still drops, raise a ticket against NWL-WH-AP07.')
        runbook.save()
    runbook.owner = lead
    runbook.review_interval_days = 180
    runbook.last_reviewed_at = now - timedelta(days=21)
    runbook.staff_view_count = 64
    runbook.portal_view_count = 9
    runbook.save(update_fields=['owner', 'review_interval_days', 'last_reviewed_at',
                                'staff_view_count', 'portal_view_count'])

    KB_VIEWS = {'outlook-repeatedly-prompts-for-credentials': (212, 37, 400, 2),
                'standard-workstation-build-checklist': (88, 0, 90, 1),
                'backup-restore-verification-procedure': (0, 0, 120, 0)}
    for slug, (staff, portal, review_days, owner_idx) in KB_VIEWS.items():
        d = Document.objects.filter(slug=slug, organization=None).first()
        if d:
            Document.objects.filter(pk=d.pk).update(
                staff_view_count=staff, portal_view_count=portal,
                owner=[lead, priya, marcus][owner_idx], review_interval_days=90,
                last_reviewed_at=now - timedelta(days=review_days))

    cat_net = DocumentCategory.objects.get(name='Network')
    DRAFTS = [
        (nwl, 'Dayton depot — cabling plan (draft)', marcus,
         '<h2>Scope</h2><p>Replace the depot patch field and re-terminate the dock drops.</p>'),
        (nwl, 'Scanner fleet replacement — options', priya,
         '<h2>Options</h2><p>Compare three handheld models against the WMS client requirements.</p>'),
    ]
    for o, title, author, body in DRAFTS:
        Document.objects.get_or_create(
            organization=o, slug=slugify(title),
            defaults=dict(title=title, body=body, category=cat_net, is_published=False,
                          created_by=author, owner=author, content_type='html'))
    Document.objects.get_or_create(
        organization=nwl, slug='legacy-pbx-dial-plan',
        defaults=dict(title='Legacy PBX dial plan (retired 2025)', category=cat_net,
                      body='<p>Kept for reference after the move to hosted voice.</p>',
                      is_published=True, is_archived=True, created_by=lead, content_type='html'))

    # A customer-facing template and a document created from it, then the template moves on.
    tmpl, created = Document.objects.get_or_create(
        organization=None, slug='site-network-overview-template',
        defaults=dict(title='Site network overview — template', is_template=True, is_global=True,
                      category=cat_net, created_by=lead, content_type='html',
                      body='<h2>Sites</h2><p>…</p><h2>VLANs</h2><p>…</p><h2>Internet</h2><p>…</p>'))
    if created:
        child = Document.objects.get(slug=slugify('Northwind — Network Overview'))
        Document.objects.filter(pk=child.pk).update(source_template=tmpl, source_template_version=1)
        tmpl.last_modified_by = lead
        tmpl.body = tmpl.body + '<h2>Out-of-band access</h2><p>…</p><h2>Escalation contacts</h2><p>…</p>'
        tmpl.save()

    # Readiness: Microsoft 365 documentation tagged "m365".
    m365_tag, _ = Tag.objects.get_or_create(name='m365', organization=nwl, defaults={'color': '#0d6efd'})
    M365 = [
        ('Microsoft 365 tenant — Northwind', 5,
         '<p>Tenant: northwind.example (invented). Primary domain, admin roles and conditional '
         'access baseline.</p>'),
        ('Microsoft 365 licensing and renewal', 200,
         '<p>Business Premium × 48, renews every March through the distributor.</p>'),
    ]
    for title, reviewed_days, body in M365:
        d, _ = Document.objects.get_or_create(
            organization=nwl, slug=slugify(title),
            defaults=dict(title=title, body=body, category=cat_net, is_published=True,
                          created_by=lead, owner=lead, content_type='html', review_interval_days=180))
        Document.objects.filter(pk=d.pk).update(last_reviewed_at=now - timedelta(days=reviewed_days))
        d.tags.add(m365_tag)

    hpc = org('Harbor Point Credit Union')
    hpc_tag, _ = Tag.objects.get_or_create(name='m365', organization=hpc, defaults={'color': '#0d6efd'})
    d, _ = Document.objects.get_or_create(
        organization=hpc, slug='microsoft-365-tenant-harbor-point',
        defaults=dict(title='Microsoft 365 tenant — Harbor Point', category=cat_net,
                      body='<p>Tenant notes, admin roles and retention policies.</p>',
                      is_published=True, created_by=priya, owner=priya, content_type='html'))
    Document.objects.filter(pk=d.pk).update(last_reviewed_at=now - timedelta(days=260))
    d.tags.add(hpc_tag)

    # KB analytics: searches that found nothing (only zero-result searches are kept).
    if not SearchQueryLog.objects.exists():
        for q, src, n in [('zebra printer blank labels', 'global', 6), ('vpn keepalive', 'docs', 4),
                          ('dock door badge reader', 'portal_kb', 3), ('teams room reset', 'global', 2),
                          ('scanner battery swap', 'portal_kb', 2)]:
            for i in range(n):
                row = SearchQueryLog.objects.create(query=q, source=src, user=lead,
                                                    organization=nwl, result_count=0)
                SearchQueryLog.objects.filter(pk=row.pk).update(
                    created_at=now - timedelta(days=random.randint(0, 25), hours=i))
    print('  docs: runbook versions', runbook.versions.count(), '| drafts', Document.objects.drafts().count()
          if hasattr(Document.objects, 'drafts') else '')


def seed_readiness():
    """The sample Microsoft 365 standard (from readiness_seed_samples) plus a
    network baseline, with a mix of met and unmet requirements and one
    audited exception."""
    from readiness.models import DocumentationStandard, StandardException, StandardRequirement as R
    from readiness.params import validate_params
    from vault.models import Password, PasswordFolder

    lead = user('demo.tech')
    std, created = DocumentationStandard.objects.get_or_create(
        name='Network baseline',
        defaults=dict(scope=DocumentationStandard.SCOPE_ALL, created_by=lead,
                      description='What every managed network must have on record before '
                                  'we take on-call responsibility for it.'))
    if created:
        REQS = [
            ('Network overview document', R.KIND_DOCUMENT_EXISTS,
             {'category': 'Network', 'title_contains': 'network|segment'}, 3,
             'Sites, VLANs and internet circuits in one place.'),
            ('Firewalls have serial, firmware and warranty', R.KIND_ASSET_FIELDS,
             {'asset_type': 'firewall', 'fields': ['serial_number', 'firmware_version', 'warranty_expiry']}, 2,
             'Needed to open vendor cases and plan renewals.'),
            ('Firewall admin credential on record', R.KIND_CREDENTIAL_REFERENCE,
             {'title_contains': 'fortigate|pa-450|firewall|udm'}, 3,
             'The vault holds the firewall admin login (the secret itself is never shown here).'),
            ('Named site contact', R.KIND_CONTACT_ROLE,
             {'title_contains': 'operations|it manager|vp technology|office manager', 'min_count': 1}, 1,
             'Someone at the customer who can approve an outage window.'),
        ]
        for i, (title, kind, params, weight, desc) in enumerate(REQS):
            R.objects.create(standard=std, title=title, kind=kind, params=validate_params(kind, params),
                             weight=weight, description=desc, order=i)

    nwl = org('Northwind Logistics')
    folder, _ = PasswordFolder.objects.get_or_create(name='Applications', organization=nwl)
    if not Password.objects.filter(organization=nwl, title='Microsoft 365 global admin').exists():
        p = Password(title='Microsoft 365 global admin', organization=nwl, folder=folder,
                     username='admin@northwind.example', created_by=lead,
                     notes='Tenant global admin. Reveal is logged.')
        p.set_password('Demo-Placeholder-4410')
        p.save()

    m365 = DocumentationStandard.objects.filter(name='Microsoft 365 tenant documentation').first()
    cascade = org('Cascade Manufacturing')
    if m365 and not StandardException.objects.filter(organization=cascade).exists():
        StandardException.objects.create(
            standard=m365, organization=cascade, created_by=lead,
            reason='Plant runs on-premises Exchange; no Microsoft 365 tenant.',
            expires_at=now + timedelta(days=180))
    beacon = org('Beacon Managed IT')
    for s_ in DocumentationStandard.objects.all():
        StandardException.objects.get_or_create(
            standard=s_, organization=beacon, requirement=None,
            defaults=dict(created_by=lead, reason='Our own tenant — not a managed customer.'))
    print('  readiness: standards', DocumentationStandard.objects.count())


def seed_portal_request():
    """Turn the portal on for Northwind and submit one guided request as Dana."""
    from psa.models import ClientPSASettings, ServiceCatalogItem, Ticket
    from psa.service_requests import FIELD_PREFIX, submit_request, validate_submission

    nwl = org('Northwind Logistics')
    ClientPSASettings.objects.filter(organization=nwl).update(portal_enabled=True)
    dana = user('demo.dwhitfield')
    item = ServiceCatalogItem.objects.filter(slug='portal-employee-onboarding').first()
    if not item:
        print('  portal: run psa_seed_portal_requests first')
        return
    if Ticket.objects.filter(organization=nwl, subject__startswith='New starter').exists():
        return
    post = {'full_name': 'Sam Okonkwo', 'job_title': 'Inventory Coordinator',
            'start_date': (today + timedelta(days=6)).isoformat(),
            'manager': 'Aaron Lindqvist', 'licenses': ['Email + Office', 'VPN'],
            'needs_laptop': 'on', 'laptop_type': 'Standard',
            'notes': 'Will split time between HQ and the Dayton depot.'}

    class _Post(dict):
        def getlist(self, key, default=None):
            v = self.get(key, default if default is not None else [])
            return v if isinstance(v, list) else [v]

    answers, errors = validate_submission(
        item.get_form_schema(), _Post({FIELD_PREFIX + k: v for k, v in post.items()}))
    if errors:
        raise SystemExit(f'portal request did not validate: {errors}')
    submit_request(item=item, organization=nwl, user=dana, answers=answers)
    print('  portal: request submitted')


def seed_scheduler_history():
    """Give the built-in scheduler's tasks a believable run history (last run,
    next run, run count) and one task that reports an error."""
    from core.models import ScheduledTask as Job

    random.seed(5)
    Job.get_or_create_defaults()
    for job in Job.objects.all():
        if not job.enabled:
            continue
        interval = max(int(job.interval_minutes or 60), 1)
        last = now - timedelta(minutes=random.randint(0, min(interval, 60 * 24) - 1 if interval > 1 else 0),
                               seconds=random.randint(5, 50))
        job.last_run_at = last
        job.next_run_at = last + timedelta(minutes=interval)
        job.run_count = max(1, int(30 * 24 * 60 / interval)) if interval < 60 * 24 * 30 else 1
        job.last_status = 'success'
        job.last_error = ''
        job.save()
    Job.objects.filter(task_type='psa_generate_recurring_invoices').update(
        last_status='failed',
        last_error=('1 contract(s) skipped, more than one billing period behind — not back-billed: '
                    'Ridgeline — Block Hours 40 (#2, next billing 2026-08-01, 3 periods due, 2 missed). '
                    '2 current-period invoice(s) were generated. For each, set the next billing date '
                    'to the current period to skip the missed periods, or run '
                    '`manage.py psa_generate_recurring_invoices` by hand to bill them.'))
    print('  scheduler: tasks', Job.objects.count())


def main():
    steps = [seed_showcase, seed_presentation, seed_asset_detail, seed_commercial,
             rename_msp_tenant, seed_project_work, seed_visual, seed_dispatch,
             seed_my_work, seed_document_lifecycle, seed_readiness, seed_portal_request,
             seed_scheduler_history]
    only = set(sys.argv[1:])
    for step in steps:
        if only and step.__name__ not in only:
            continue
        print(step.__name__)
        step()


if __name__ == '__main__':
    main()
