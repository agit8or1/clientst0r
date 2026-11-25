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
    HOSTS = [('10.42.1.1', 'assigned', 'gw-core', None),
             ('10.42.1.10', 'assigned', 'dc01', 'NWL-DC01'),
             ('10.42.1.12', 'assigned', 'fs01', 'NWL-FS01'),
             ('10.42.1.40', 'assigned', 'nas01', 'NWL-NAS01'),
             ('10.42.1.50', 'reserved', 'hv-spare', None),
             ('10.42.1.51', 'available', '', None),
             ('10.42.1.52', 'available', '', None)]
    for ip, status, host, asset_name in HOSTS:
        asset = Asset.objects.filter(organization=nwl, name=asset_name).first() if asset_name else None
        IPAddress.objects.get_or_create(
            subnet=servers, ip_address=ip,
            defaults=dict(status=status, hostname=host, asset=asset,
                          last_seen_at=(now - timedelta(minutes=random.randint(2, 90))
                                        if status == 'assigned' else None)))
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

    lead = user('demo.tech')
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
    # A status-change system event after the internal note, so the hero
    # conversation shows every entry kind (customer, technician, note, event).
    status_body = 'Status changed: Assigned → In Progress'
    if not TicketComment.objects.filter(ticket=hero, is_system=True, body=status_body).exists():
        ev = TicketComment.objects.create(ticket=hero, author=hero.assigned_to or lead,
                                          body=status_body, is_internal=True, is_system=True)
        TicketComment.objects.filter(pk=ev.pk).update(
            created_at=hero.created_at + timedelta(hours=2, minutes=5))

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
            object_repr='Second access point for bay 7 — $349.00', requested_by=user('demo.ipatel'),
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


def seed_rack_artwork():
    """Rack A as the README shows it: one mixed rack covering every way a
    placement finds its artwork.

    - NWL-SW-CORE is documented in the hardware inventory (ports and all), so
      the rack draws that device and links to its port view;
    - the firewall, DC01 and the NAS are plain assets whose manufacturer and
      model match a catalog model, as on their asset pages;
    - NWL-FS01 becomes a 2U PowerEdge R750xs, drawn across both units;
    - the patch panel is a legacy placement linked only to an equipment model;
    - the UPS is a legacy placement with neither, so it gets the plain face.
    """
    from assets.models import Asset, EquipmentModel, Vendor
    from hardware import services as HS
    from hardware.models import HardwareDevice, HardwareModel
    from monitoring.models import Rack, RackDevice

    nwl = org('Northwind Logistics')
    rack = Rack.objects.get(organization=nwl, name='HQ Comms Room — Rack A')

    def placement(old, new):
        return (RackDevice.objects.filter(rack=rack, name=new).first()
                or RackDevice.objects.filter(rack=rack, name=old).first())

    # Core switch → a documented inventory device built from the catalog model.
    sw_model = HardwareModel.objects.get(manufacturer__name='HPE', model='Aruba 6300M-48G-4SFP56')
    sw = Asset.objects.get(organization=nwl, name='NWL-SW-CORE')
    sw.manufacturer, sw.model, sw.rack_units, sw.is_rackmount = 'HPE', 'Aruba 6300M-48G-4SFP56 (JL663A)', 1, True
    sw.save()
    if not HardwareDevice.objects.filter(asset=sw).exists():
        hw = HardwareDevice.objects.create(organization=nwl, asset=sw, hardware_model=sw_model,
                                           template_revision=sw_model.revision, platform='AOS-CX')
        by_tpl = HS._ports_from_templates(hw, list(sw_model.components.all()))
        HS._mappings_from_templates(hw, sw_model, by_tpl)
    rd = placement('NWL-SW-CORE — Aruba CX 6300M', 'NWL-SW-CORE — Aruba 6300M')
    rd.name, rd.start_unit, rd.units, rd.is_full_depth = 'NWL-SW-CORE — Aruba 6300M', 37, 1, sw_model.is_full_depth
    rd.save()

    # File server → a 2U chassis.
    fs = Asset.objects.get(organization=nwl, name='NWL-FS01')
    fs.model, fs.rack_units, fs.is_rackmount = 'PowerEdge R750xs', 2, True
    fs.save()
    rd = placement('NWL-FS01 — PowerEdge R450', 'NWL-FS01 — PowerEdge R750xs')
    rd.name, rd.start_unit, rd.units = 'NWL-FS01 — PowerEdge R750xs', 27, 2
    rd.save()

    # Patch panel → linked only to a procurement equipment model, as older
    # placements were; that model maps to the catalog's panel.
    pp_model = HardwareModel.objects.get(manufacturer__name='Panduit', part_number='DP48688TGY')
    vendor, _ = Vendor.objects.get_or_create(name='Panduit', defaults={'slug': 'panduit'})
    em, _ = EquipmentModel.objects.get_or_create(
        vendor=vendor, model_name='Cat 6 Punchdown Patch Panel, 48 port, 2U',
        defaults=dict(model_number='DP48688TGY', slug='panduit-dp48688tgy', equipment_type='patch_panel',
                      is_rackmount=True, rack_units=2))
    if pp_model.equipment_model_id is None:
        pp_model.equipment_model = em
        pp_model.save(update_fields=['equipment_model'])
    rd = placement('Patch panel — 48 port', 'Patch panel — 48 port')
    rd.equipment_model, rd.start_unit, rd.units, rd.is_full_depth = em, 35, 2, pp_model.is_full_depth
    rd.save()

    # The UPS and a KVM console stay legacy placements with no asset and no
    # model: plain faces with their saved names.
    RackDevice.objects.get_or_create(rack=rack, name='KVM console — 1U',
                                     defaults=dict(start_unit=33, units=1, color='#6c757d'))
    print('  rack artwork: rack pk', rack.pk, '|', rack.rack_devices.count(), 'placements')


# ---------------------------------------------------------------------------
# v3.17.646–656 screens: named approvers, readiness custom fields, a secure
# message link, ticket AI (OPTIONAL AI), an RMM fixture and the update badge.
# ---------------------------------------------------------------------------

# Where the sample conversations (psa_seed_sample_conversations) and module
# samples (seed_module_samples) land in this instance. setup_demo.py passes
# these to the two commands, whose defaults target the built-in demo slugs.
CONVERSATION_ORG_MAP = [
    'demo-globex=northwind-logistics',
    'demo-initech=ridgeline-dental-group',
    'demo-acme=harbor-point-credit-union',
    'demo=cascade-manufacturing',
]
MODULE_SAMPLE_OPTIONS = dict(
    customers='northwind-logistics,ridgeline-dental-group,harbor-point-credit-union,cascade-manufacturing',
    msp='beacon-managed-it', techs='demo.ipatel,demo.mokafor,demo.lchen', owner='demo.tech')

# The fixed link token of the one secure message whose "Show the message"
# page the gallery shows (/core/secret/<token>/). Invented; the demo instance
# is never exposed.
SECURE_LINK_TOKEN = 'demo-docs-secure-message-link-not-a-real-token'


def _customer_person(username, first, last, email, organization, role='editor'):
    """A customer portal person who can't sign in."""
    from accounts.models import Membership, UserProfile, UserType
    u, _ = User.objects.get_or_create(
        username=username, defaults={'email': email, 'first_name': first, 'last_name': last})
    u.set_unusable_password()
    u.is_staff = u.is_superuser = False
    u.save()
    profile, _ = UserProfile.objects.get_or_create(user=u)
    profile.user_type = UserType.ORG_USER
    profile.save()
    Membership.objects.get_or_create(user=u, organization=organization,
                                     defaults={'role': role, 'is_active': True})
    return u


def seed_named_approvers():
    """At Northwind, access requests are approved by Aaron Lindqvist — plus
    Grace Holt, who has since left, so the staff page flags a departed
    approver — and equipment requests by Aaron. Dana then asks for access,
    which waits on Aaron in the portal's approvals list."""
    from accounts.models import Membership
    from core.models import SystemSetting
    from psa.models import ServiceCatalogItem, ServiceRequestApprover, Ticket
    from psa.service_requests import FIELD_PREFIX, submit_request, validate_submission

    s = SystemSetting.get_settings()
    s.psa_portal_customer_approvals_enabled = True
    s.save()
    nwl, lead = org('Northwind Logistics'), user('demo.tech')
    aaron = _customer_person('demo.alindqvist', 'Aaron', 'Lindqvist', 'aaron.lindqvist@northwind.example', nwl)
    left = _customer_person('demo.gholt', 'Grace', 'Holt', 'grace.holt@northwind.example', nwl)
    Membership.objects.filter(user=left, organization=nwl).update(is_active=False)
    for slug, people in (('portal-access-request', [aaron, left]), ('portal-new-equipment', [aaron])):
        item = ServiceCatalogItem.objects.filter(slug=slug).first()
        if item is None:
            print(f'  approvers: no catalog item {slug}; run psa_seed_portal_requests first')
            continue
        for person in people:
            ServiceRequestApprover.objects.get_or_create(catalog_item=item, organization=nwl, user=person,
                                                         defaults={'added_by': lead})
    item = ServiceCatalogItem.objects.filter(slug='portal-access-request').first()
    if item and not Ticket.objects.filter(organization=nwl, subject__startswith='Access request').exists():

        class _Post(dict):
            def getlist(self, key, default=None):
                v = self.get(key, default if default is not None else [])
                return v if isinstance(v, list) else [v]

        post = {'person': 'Sam Okonkwo', 'system': 'Inventory share (\\\\fs01\\inventory)',
                'access_level': 'Read and write'}
        answers, errors = validate_submission(
            item.get_form_schema(), _Post({FIELD_PREFIX + k: v for k, v in post.items()}))
        if errors:
            raise SystemExit(f'access request did not validate: {errors}')
        submit_request(item=item, organization=nwl, user=user('demo.dwhitfield'), answers=answers)
    print('  approvers:', ServiceRequestApprover.objects.count())


def seed_readiness_custom_fields():
    """Two custom asset fields on servers, and a Network baseline requirement
    that they are filled in; one Northwind server has them, the others not."""
    from assets.models import Asset, AssetCustomField
    from readiness.models import DocumentationStandard, StandardRequirement as R
    from readiness.params import validate_params

    lead = user('demo.tech')
    for i, (key, label, kind, help_text) in enumerate((
            ('support_contract_id', 'Vendor support contract', 'text', 'Contract or service tag for hardware support.'),
            ('backup_policy', 'Backup policy', 'text', 'Which backup job protects this server.'))):
        AssetCustomField.objects.get_or_create(key=key, defaults=dict(
            label=label, field_type=kind, help_text=help_text, asset_types=['server'], order=i, created_by=lead))
    std = DocumentationStandard.objects.filter(name='Network baseline').first()
    if std and not std.requirements.filter(title='Servers have a support contract and backup policy').exists():
        R.objects.create(
            standard=std, title='Servers have a support contract and backup policy', kind=R.KIND_ASSET_FIELDS,
            params=validate_params(R.KIND_ASSET_FIELDS, {
                'asset_type': 'server', 'fields': [], 'custom_fields': ['support_contract_id', 'backup_policy']}),
            weight=2, order=std.requirements.count(),
            description='Custom asset fields (Assets → Custom Fields): who to call when the hardware fails, '
                        'and what protects the data.')
    dc = Asset.objects.filter(organization=org('Northwind Logistics'), name='NWL-DC01').first()
    if dc:
        dc.custom_fields = {**(dc.custom_fields or {}), 'support_contract_id': 'ProSupport 7XK2-NWL-0142',
                            'backup_policy': 'Nightly image, 30-day retention'}
        dc.save(update_fields=['custom_fields'])
    print('  readiness custom fields:', AssetCustomField.objects.count())


def seed_secure_link():
    """One unopened secure message with a known link token, so the gallery
    can show the "Show the message" page a recipient lands on."""
    from core.models import SecureNote
    from psa.models import Ticket
    from psa.ticket_secure import create_secure_message

    digest = SecureNote.hash_access_token(SECURE_LINK_TOKEN)
    if SecureNote.objects.filter(access_token_hash=digest).exists():
        return
    ticket = Ticket.objects.get(ticket_number='PSA-2026-000001')
    note = create_secure_message(ticket=ticket, sender=user('demo.tech'),
                                 text='Sample secret for the documentation screenshots.', expires_hours=72)
    SecureNote.objects.filter(pk=note.pk).update(access_token_hash=digest)
    print('  secure link: /core/secret/' + SECURE_LINK_TOKEN + '/')


def seed_ticket_ai():
    """Ticket AI Assist (OPTIONAL AI) configured but never called: two model
    profiles with placeholder sealed keys (the demo has no gateway and sends
    nothing), Northwind's AI policy, and the L2 preset for the demo technicians
    at Northwind. Turns psa_ai_enabled on."""
    from core.models import SystemSetting
    from psa_ai.models import AIBusinessPolicy, AIModelProfile
    from tech_access.models import AccessAssignment, AccessPreset

    s = SystemSetting.get_settings()
    s.psa_ai_enabled = True
    s.save()
    from psa_ai.services import gateway_keys

    # The gateway key pair lives under $DEMO_DIR (demo_settings.AI_GATEWAY_KEY_DIR).
    if not str(gateway_keys.key_dir()).startswith(os.environ['DEMO_DIR']):
        raise SystemExit(f'Refusing to seed ticket AI: gateway key dir {gateway_keys.key_dir()} is not under $DEMO_DIR.')
    if not (gateway_keys.key_dir() / 'private.key').exists():
        gateway_keys.generate()
    nwl, lead = org('Northwind Logistics'), user('demo.tech')
    profiles = []
    for name, provider, model, cheap, inp, outp in (
            ('Claude — everyday', 'anthropic', 'claude-haiku-4-5', True, 10, 50),
            ('OpenAI — second opinion', 'openai', 'gpt-5-mini', False, 3, 20)):
        p, created = AIModelProfile.objects.get_or_create(name=name, defaults=dict(
            provider=provider, model=model, enabled=True, economical=cheap,
            credential_owner=AIModelProfile.OWNER_MSP, input_price_per_1k=inp, output_price_per_1k=outp))
        if created or not p.has_api_key:
            # A placeholder string, sealed like a real key; no model is ever called.
            p.set_api_key('demo-placeholder-not-a-key')
            p.save(update_fields=['sealed_api_key'])
        p.assigned_organizations.add(nwl)
        profiles.append(p)
    policy, _ = AIBusinessPolicy.objects.get_or_create(organization=nwl, defaults=dict(
        analysis_enabled=True, compare_enabled=True, default_profile=profiles[0], daily_budget_cents=500))
    policy.allowed_profiles.add(*profiles)
    l2 = AccessPreset.objects.filter(key='l2').first() or AccessPreset.objects.order_by('-level').first()
    l1 = AccessPreset.objects.filter(key='l1').first()
    if l2:
        for username, preset in (('demo.tech', l2), ('demo.ipatel', l2), ('demo.mokafor', l1 or l2)):
            AccessAssignment.objects.get_or_create(user=user(username), organization=nwl, preset=preset,
                                                   defaults={'granted_by': lead})
    print('  ticket AI: profiles', AIModelProfile.objects.count(), '| assignments', AccessAssignment.objects.count())


def seed_superuser_approval():
    """Lena Chen becomes the second administrator, Superuser Approval is
    turned on, and Jordan has asked for Priya to be made a superuser — a grant
    waiting for Lena's approval. No mail leaves the demo (locmem backend)."""
    from tech_access import services as TA

    lena, lead, priya = user('demo.lchen'), user('demo.tech'), user('demo.ipatel')
    if not lena.is_superuser:
        lena.is_superuser = True
        lena.save()
    TA.enable_superuser_policy(lead)
    if not priya.is_superuser:
        change = TA.propose_superuser_grant(priya, lead)
        # As if Jordan had re-entered his password: the grant now waits on Lena.
        type(change).objects.filter(pk=change.pk, requester_reauth_at=None).update(requester_reauth_at=now)
    print('  superuser approval: on | pending grant for', priya.username)


def seed_rmm_fixture():
    """A Tactical RMM connection for Ridgeline that never syncs (sync off, an
    invented .example host, no credentials), one device it 'reported',
    linked to RDG-SRV01, and the open backup-verification ticket pointed at
    that asset — so the ticket page shows its RMM card without any network.

    seed_rmm_pairing pairs this same connection for ticket-rmm-v1 (cached
    capabilities, no network) for the RMM ticket-integration screens.
    """
    from assets.models import Asset
    from integrations.models import RMMConnection, RMMDevice
    from psa.models import Ticket

    rdg = org('Ridgeline Dental Group')
    srv = Asset.objects.get(organization=rdg, name='RDG-SRV01')
    conn, _ = RMMConnection.objects.get_or_create(
        organization=rdg, name='Ridgeline — Tactical RMM', provider_type='tactical_rmm',
        defaults=dict(base_url='https://rmm.beaconmanaged.example', console_base_url='https://rmm.beaconmanaged.example',
                      sync_enabled=False, sync_alerts=False, is_active=True, last_sync_status='success',
                      last_sync_at=now - timedelta(minutes=25)))
    dev, _ = RMMDevice.objects.get_or_create(
        connection=conn, external_id='agent-7f3c21', defaults=dict(
            organization=rdg, device_name='RDG-SRV01', hostname='srv01', device_type='server',
            manufacturer='HPE', model='ProLiant DL360 Gen11', serial_number=srv.serial_number or 'CZJ2DEMO01',
            os_type='windows', os_version='Windows Server 2022 Standard', ip_address='10.20.1.5',
            client_id='3', client_name='Ridgeline Dental Group', site_id='5', site_name='Boise clinic',
            is_online=True, last_seen=now - timedelta(minutes=4), linked_asset=srv, link_status='auto',
            data_refreshed_at=now - timedelta(minutes=25)))
    ticket = Ticket.objects.filter(organization=rdg, subject='Backup restore verification — February').first()
    if ticket and ticket.related_asset_id is None:
        Ticket.objects.filter(pk=ticket.pk).update(related_asset=srv)
    print('  rmm fixture: connection', conn.pk, '| device', dev.pk, '| ticket', ticket and ticket.ticket_number)


RMM_PAIRING_CAPS = ['rmm_handoff', 'diagnostics_readonly', 'remote_view', 'remote_control',
                    'signed_actions']
RMM_PAIRING_DIAGNOSTICS = [
    {'key': 'disk_space', 'label': 'Disk space', 'description': 'Free space per volume',
     'device_classes': ['workstation', 'laptop', 'desktop']},
    {'key': 'pending_reboot', 'label': 'Pending reboot', 'description': 'Whether Windows is waiting to restart',
     'device_classes': ['workstation', 'laptop', 'desktop']},
    {'key': 'top_processes', 'label': 'Top processes', 'description': 'The ten busiest processes right now',
     'device_classes': ['workstation', 'laptop', 'desktop']},
]
RMM_DIAG_RESULT = """Volume  Label     Size     Free     Free %
C:      OS        237 GB   9.8 GB   4%
D:      Imaging   931 GB   612 GB   66%

Largest folders on C:
  C:\\ProgramData\\XrayBridge\\cache   148 GB
  C:\\Windows\\WinSxS                  11 GB
  C:\\Users                            19 GB"""


def seed_rmm_pairing():
    """Pair the Ridgeline Tactical RMM connection for ticket-rmm-v1 — by
    writing the rows an approved pairing and a successful capabilities check
    leave behind (placeholder secrets, an invented key ID, a cached
    capabilities document) — and give one open workstation ticket three RMM
    requests in finished states. Nothing calls the RMM: the connection's
    host is a .example name and sync stays off.
    """
    import hashlib
    from assets.models import Asset
    from integrations import ticket_rmm
    from integrations.models import RMMConnection, RMMDevice
    from psa.models import Ticket, TicketComment
    from psa_ai.models import RMMRequest, RMMRequestEvent
    from tech_access.models import AccessAssignment
    from tech_access.services import builtin

    rdg = org('Ridgeline Dental Group')
    lead = user('demo.tech')
    conn = RMMConnection.objects.get(organization=rdg, name='Ridgeline — Tactical RMM')
    conn.customer_scope = RMMConnection.CUSTOMER_SCOPE_SINGLE
    creds = dict(conn.get_credentials() or {})
    creds.update({'api_key': 'demo-placeholder-not-a-key',
                  ticket_rmm.OUTBOUND: 'demo-outbound-placeholder-secret-not-real-0001',
                  ticket_rmm.INBOUND: 'demo-inbound-placeholder-secret-not-real-00001'})
    conn.set_credentials(creds)
    conn.field_mappings = dict(conn.field_mappings or {}, **{
        ticket_rmm.ENABLED: True, ticket_rmm.KEY_ID: 'kid-ridgeline-demo', ticket_rmm.LOCATION: 'hosted',
        ticket_rmm.URL: 'https://rmm.beaconmanaged.example/ticket-rmm'})
    conn.save()
    if not ticket_rmm.is_processor(conn):
        ticket_rmm.record_capabilities(conn, {
            'contract': ticket_rmm.CONTRACT, 'tenant': {'id': 'beacon-ridgeline', 'name': 'Ridgeline Dental Group'},
            'capabilities': RMM_PAIRING_CAPS, 'diagnostics': RMM_PAIRING_DIAGNOSTICS})
        conn.refresh_from_db()
    assert ticket_rmm.is_processor(conn), ticket_rmm.status(conn)

    pc = Asset.objects.get(organization=rdg, name='RDG-OP3-PC')
    dev, _ = RMMDevice.objects.get_or_create(
        connection=conn, external_id='agent-2b91e4', defaults=dict(
            organization=rdg, device_name='RDG-OP3-PC', hostname='op3', device_type='workstation',
            manufacturer='Dell', model='OptiPlex 7010', serial_number=pc.serial_number or 'DLOP3DEMO',
            os_type='windows', os_version='Windows 11 Pro 23H2', ip_address='10.20.1.43',
            client_id='3', client_name='Ridgeline Dental Group', site_id='5', site_name='Boise clinic',
            is_online=True, last_seen=now - timedelta(minutes=2), linked_asset=pc, link_status='auto',
            data_refreshed_at=now - timedelta(minutes=25)))

    # demo.tech works Ridgeline tickets on the L2 preset (handoffs, read-only
    # diagnostics and low-risk fix referrals; remote sessions on request).
    if not AccessAssignment.objects.filter(user=lead, organization=rdg).exists():
        AccessAssignment.objects.create(preset=builtin('l2'), organization=rdg, user=lead)

    subject = 'Operatory 3 PC slow to open X-rays'
    ticket = Ticket.objects.filter(organization=rdg, subject=subject).first()
    if ticket is None:
        model = Ticket.objects.get(organization=rdg, subject='Backup restore verification — February')
        created = now - timedelta(hours=5)
        ticket = Ticket.objects.create(
            organization=rdg, subject=subject, related_asset=pc, assigned_to=lead,
            description='Since yesterday the imaging bridge takes over a minute to open each X-ray in '
                        'operatory 3. The other operatories are fine. — front desk',
            status=model.status, priority=model.priority, ticket_type=model.ticket_type, queue=model.queue,
            client_can_view=True, source='portal',
            first_response_due_at=created + timedelta(hours=1),
            resolution_due_at=created + timedelta(hours=24),
            first_response_at=created + timedelta(minutes=18))
        Ticket.objects.filter(pk=ticket.pk).update(created_at=created)
        note = TicketComment.objects.create(
            ticket=ticket, author=lead, is_internal=True,
            body='Handed off to the RMM and ran a disk check: C: is 96% full, almost all of it the '
                 'X-ray bridge cache. Referred the cache clean-up fix.')
        TicketComment.objects.filter(pk=note.pk).update(created_at=now - timedelta(minutes=90))

    def add(kind, status, minutes_ago, events, **fields):
        if RMMRequest.objects.filter(ticket=ticket, kind=kind).exists():
            return
        payload = {'contract': ticket_rmm.CONTRACT, 'kind': kind, 'ticket': ticket.ticket_number,
                   'device_id': dev.external_id, **{k: v for k, v in fields.items()
                                                    if k in ('diagnostic_key', 'fix_title', 'fix_risk')}}
        digest = hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest()
        at = now - timedelta(minutes=minutes_ago)
        req = RMMRequest.objects.create(
            organization=rdg, ticket=ticket, connection=conn, device=dev, device_external_id=dev.external_id,
            device_name=dev.device_name, tenant_id=ticket_rmm.settings(conn)['tenant_id'], actor=lead,
            kind=kind, status=status, payload=payload, payload_digest=digest,
            idempotency_key=hashlib.sha256(f'demo-{kind}-{ticket.pk}'.encode()).hexdigest()[:64],
            remote_id='tr-' + digest[:8], last_event_sequence=len(events), confirmed_at=at, **fields)
        RMMRequest.objects.filter(pk=req.pk).update(created_at=at, updated_at=at + timedelta(minutes=3))
        for seq, event_type in enumerate(events, 1):
            RMMRequestEvent.objects.create(request=req, event_id=f'{event_type}-{seq}', sequence=seq,
                                           event_type=event_type, applied=True)

    add('handoff', 'sent', 140, ['handoff.received'],
        status_note='Ticket context received; queued for the Ridgeline team.')
    add('diagnostic', 'completed', 120, ['diagnostic.accepted', 'diagnostic.running', 'diagnostic.completed'],
        diagnostic_key='disk_space', diagnostic_label='Disk space', result_text=RMM_DIAG_RESULT,
        result_bytes=len(RMM_DIAG_RESULT.encode()), status_note='Finished in 6 s.')
    add('fix_referral', 'approved', 95, ['fix.received', 'fix.approved'],
        fix_title='Clear the X-ray bridge image cache (keep the last 7 days)', fix_risk='low',
        status_note='Approved by R. Okafor in the RMM; scheduled for 12:30 between patients.')
    print('  rmm pairing:', ticket_rmm.status(conn)['label'], '| device', dev.pk, '| ticket', ticket.ticket_number)


# ---------------------------------------------------------------------------
# 3.17.680 top bar: Favorites and Recent for demo.tech
# ---------------------------------------------------------------------------

NAV_FAVORITES = ['/reports/', '/psa/t/PSA-2026-000001/', '/hardware/devices/1/',
                 '/psa/projects/1/', '/psa/dispatch/']
NAV_RECENT = ['/vault/', '/monitoring/ipam/', '/psa/t/PSA-2026-000007/', '/assets/9/',
              '/docs/runbook-warehouse-scanner-onboarding/', '/psa/t/PSA-2026-000001/']


def seed_navigation():
    """Starred pages and a recent-pages trail for the top bar's Favorites and
    Recent menus (paths only; the menus resolve each one against access)."""
    from core.models import PageFavorite, RecentPage

    tech = user('demo.tech')
    PageFavorite.objects.filter(user=tech).delete()
    now = timezone.now()
    for i, path in enumerate(NAV_FAVORITES):  # the last one is listed first
        fav = PageFavorite.objects.create(user=tech, path=path)
        PageFavorite.objects.filter(pk=fav.pk).update(
            created_at=now - timedelta(days=len(NAV_FAVORITES) - i))
    RecentPage.objects.filter(user=tech).delete()
    for i, path in enumerate(NAV_RECENT):  # last is the most recent
        RecentPage.objects.create(user=tech, path=path,
                                  visited_at=now - timedelta(minutes=5 * (len(NAV_RECENT) - i)))
    print(f'  navigation: {len(NAV_FAVORITES)} favorites, {len(NAV_RECENT)} recent pages')


def seed_operations():
    """Derived-data sources for the operations pages: RMM alerts on the
    Ridgeline Tactical RMM fixture, one website monitor down, backup monitoring
    (a PBS connection for Northwind, a restic push connection for Harbor Point,
    with systems, repositories, jobs, runs and alerts), licensing subscriptions,
    a 'Service Desk' wallboard, and API access rules plus a trusted proxy.

    Nothing contacts anything: connections are inactive, sync is off and every
    host is an invented .example name. The global API access modes stay
    Unrestricted so the demo API keeps working. The events, health score and
    advisor pages are filled by the app's own commands, which setup_demo.py
    runs after the seeding.
    """
    from assets.models import Asset
    from backup_monitoring import models as bm
    from integrations.models import RMMAlert, RMMConnection, RMMDevice
    from licensing.models import LicenseAssignment, LicenseSubscription, SoftwareProduct
    from monitoring.models import WebsiteMonitor
    from psa.models import Ticket

    # 1. RMM alerts ---------------------------------------------------------
    rdg = org('Ridgeline Dental Group')
    conn = RMMConnection.objects.get(organization=rdg, name='Ridgeline — Tactical RMM')
    dev = RMMDevice.objects.get(connection=conn, external_id='agent-7f3c21')
    for ext, atype, msg, sev, status, ago, resolved in [
        ('alert-1001', 'Disk space', 'Drive C: has 4% free space (9.8 GB of 237 GB)', 'critical', 'active',
         timedelta(hours=3), None),
        ('alert-1002', 'Service stopped', 'Service "Veeam Backup Service" is not running', 'warning',
         'acknowledged', timedelta(hours=9), None),
        ('alert-1003', 'Pending reboot', 'Windows has been waiting for a restart for 6 days', 'warning',
         'active', timedelta(days=1, hours=2), None),
        ('alert-1004', 'High CPU', 'CPU above 95% for 15 minutes', 'error', 'resolved',
         timedelta(days=2), timedelta(days=2) - timedelta(minutes=50)),
    ]:
        RMMAlert.objects.update_or_create(
            connection=conn, external_id=ext, defaults=dict(
                organization=rdg, device=dev, alert_type=atype, message=msg, severity=sev, status=status,
                triggered_at=now - ago, resolved_at=(now - resolved) if resolved else None,
                raw_data={'demo': True}))

    # 2. One website monitor down -------------------------------------------
    mon = WebsiteMonitor.objects.filter(organization=org('Cascade Manufacturing'),
                                        url='https://plant.cascade-mfg.example').first() \
        or WebsiteMonitor.objects.order_by('pk').first()
    WebsiteMonitor.objects.filter(pk=mon.pk).update(
        status='down', alert_state='down', consecutive_failures=3, last_status_code=None,
        last_error='Connection timed out after 15 seconds (3 consecutive failures)',
        last_checked_at=now - timedelta(minutes=3))

    # 3. Backup monitoring --------------------------------------------------
    nwl, hpc = org('Northwind Logistics'), org('Harbor Point Credit Union')
    tib = 1024 ** 4
    pbs, _ = bm.BackupConnection.objects.get_or_create(
        organization=nwl, name='Northwind — Proxmox Backup Server', provider=bm.PROVIDER_PBS,
        defaults=dict(base_url='https://pbs.northwind.example:8007', verify_tls=True, active=False,
                      last_poll_at=now - timedelta(minutes=12), last_poll_status='ok'))
    rst, _ = bm.BackupConnection.objects.get_or_create(
        organization=hpc, name='Harbor Point — restic reports', provider=bm.PROVIDER_RESTIC,
        defaults=dict(active=False, last_ingest_at=now - timedelta(hours=2),
                      last_poll_at=now - timedelta(hours=2), last_poll_status='ok'))

    def system(conn_, cust, name, ext, asset_name):
        asset = Asset.objects.filter(organization=cust, name=asset_name).first()
        obj, _ = bm.ProtectedSystem.objects.get_or_create(
            connection=conn_, external_id=ext, defaults=dict(customer=cust, asset=asset, name=name))
        return obj

    s_dc = system(pbs, nwl, 'NWL-DC01', 'vm/101', 'NWL-DC01')
    s_fs = system(pbs, nwl, 'NWL-FS01', 'vm/102', 'NWL-FS01')
    s_nas = system(pbs, nwl, 'NWL-NAS01', 'host/nas01', 'NWL-NAS01')
    s_hv1 = system(rst, hpc, 'HPC-HV01', 'hpc-hv01', 'HPC-HV01')
    s_hv2 = system(rst, hpc, 'HPC-HV02', 'hpc-hv02', 'HPC-HV02')

    def repo(conn_, cust, name, ext, total, used, **kw):
        obj, _ = bm.BackupRepository.objects.update_or_create(
            connection=conn_, external_id=ext, defaults=dict(
                organization=cust, name=name, total_bytes=int(total * tib), used_bytes=int(used * tib),
                last_checked_at=now - timedelta(minutes=12), **kw))
        return obj

    r_main = repo(pbs, nwl, 'datastore-main', 'datastore-main', 12, 8.1)
    repo(pbs, nwl, 'datastore-offsite', 'datastore-offsite', 8, 3.2)
    r_hpc = repo(rst, hpc, 'sftp:backup.harborpoint.example/restic', 'restic-main', 6, 5.4)

    def job(conn_, cust, sys_, ext, name, schedule, retention, runs):
        """runs: [(hours_ago, status, GB, minutes, message)], newest first."""
        j, _ = bm.BackupJob.objects.get_or_create(
            connection=conn_, external_id=ext, defaults=dict(
                organization=cust, system=sys_, name=name, schedule=schedule, retention=retention))
        for i, (h, status, gb, mins, msg) in enumerate(runs):
            started = now - timedelta(hours=h)
            bm.BackupRun.objects.get_or_create(
                connection=conn_, external_id=f'{ext}-run-{i}', defaults=dict(
                    job=j, started_at=started, finished_at=started + timedelta(minutes=mins),
                    status=status, bytes_processed=int(gb * 1024 ** 3) if gb else None,
                    duration_seconds=mins * 60, message=msg))
        newest = runs[0]
        ok = next((r for r in runs if r[1] in ('success', 'warning')), None)
        bm.BackupJob.objects.filter(pk=j.pk).update(
            last_run_at=now - timedelta(hours=newest[0]), last_status=newest[1],
            last_success_at=(now - timedelta(hours=ok[0])) if ok else None)
        return j

    ok = lambda h, gb, m: (h, 'success', gb, m, 'Backup completed')
    j_dc = job(pbs, nwl, s_dc, 'vm-101-nightly', 'NWL-DC01 nightly', 'daily 01:00', 'keep 14 daily, 8 weekly',
               [ok(7, 38, 21), ok(31, 36, 20), ok(55, 37, 22)])
    j_fs = job(pbs, nwl, s_fs, 'vm-102-nightly', 'NWL-FS01 nightly', 'daily 01:30', 'keep 14 daily, 8 weekly',
               [(7, 'failed', None, 4, 'Datastore write error: no space left on device (ENOSPC)'),
                (31, 'failed', None, 3, 'Datastore write error: no space left on device (ENOSPC)'),
                ok(55, 212, 64)])
    job(pbs, nwl, s_nas, 'host-nas01-weekly', 'NWL-NAS01 weekly', 'Sun 03:00', 'keep 8 weekly',
        [ok(70, 840, 190), ok(238, 836, 188)])
    j_h1 = job(rst, hpc, s_hv1, 'hpc-hv01-restic', 'HPC-HV01 restic', 'daily 22:00', 'keep 30 daily, 12 monthly',
               [ok(2, 96, 47), ok(26, 95, 46), ok(50, 94, 46)])
    j_h2 = job(rst, hpc, s_hv2, 'hpc-hv02-restic', 'HPC-HV02 restic', 'daily 22:30', 'keep 30 daily, 12 monthly',
               [ok(52, 88, 43), ok(76, 87, 44), ok(100, 87, 43)])
    bm.BackupJob.objects.filter(pk=j_h2.pk).update(last_status='missed')

    def alert(conn_, cust, kind, sev, title, detail, key, **kw):
        obj, _ = bm.BackupAlert.objects.get_or_create(
            connection=conn_, dedup_key=key, status=bm.ALERT_OPEN, defaults=dict(
                organization=cust, kind=kind, severity=sev, title=title, detail=detail,
                first_seen_at=now - timedelta(hours=6), last_seen_at=now - timedelta(minutes=30),
                occurrences=2, **kw))
        return obj

    ticket = Ticket.objects.filter(organization=nwl).order_by('pk').first()
    alert(pbs, nwl, 'repeated_failures', 'critical', 'NWL-FS01 nightly: last 2 runs failed',
          'Datastore write error: no space left on device (ENOSPC).', f'repeat:{j_fs.pk}',
          job=j_fs, system=s_fs, ticket=ticket)
    alert(rst, hpc, 'missed', 'warning', 'HPC-HV02 restic: no successful run in 52 hours',
          'Expected a run every 26 hours; the last good run was two days ago.', f'missed:{j_h2.pk}',
          job=j_h2, system=s_hv2)
    alert(rst, hpc, 'capacity', 'warning', 'restic repository is 90% full',
          '5.4 TiB of 6 TiB used on sftp:backup.harborpoint.example/restic.', f'capacity:{r_hpc.pk}',
          repository=r_hpc)

    # 4. Licensing ----------------------------------------------------------
    nwl_sub = []
    cmf = org('Cascade Manufacturing')
    for cust, vendor, pname, sku, qty, consumed, cost, price, renew_days, ltype in [
        (nwl, 'Microsoft', '365 Business Premium', 'DEMO-M365-BP', 25, 22, '16.50', '22.00', 142, 'per_user'),
        (nwl, 'Microsoft', '365 E3', 'DEMO-M365-E3', 8, 8, '29.00', '36.00', 18, 'per_user'),
        (nwl, 'Huntress', 'Managed EDR', 'DEMO-EDR', 60, 57, '3.60', '5.50', 201, 'per_device'),
        (cmf, 'Microsoft', '365 Business Premium', 'DEMO-M365-BP', 40, 31, '16.50', '22.00', 96, 'per_user'),
        (cmf, 'Bitdefender', 'GravityZone Business Security', 'DEMO-AV', 55, 58, '2.90', '4.50', 74, 'per_device'),
    ]:
        product, _ = SoftwareProduct.objects.get_or_create(
            vendor=vendor, vendor_sku=sku, defaults=dict(name=pname, license_type=ltype))
        sub, _ = LicenseSubscription.objects.get_or_create(
            organization=cust, product=product, source='manual', vendor_subscription_id='', defaults=dict(
                quantity_purchased=qty, vendor_consumed=consumed, unit_cost=Decimal(cost),
                unit_price=Decimal(price), billing_frequency='monthly' if ltype == 'per_user' else 'annual',
                term_start=today - timedelta(days=365 - renew_days), renewal_date=today + timedelta(days=renew_days),
                auto_renew=True, status='active'))
        if cust == nwl and sku == 'DEMO-M365-E3':
            nwl_sub.append(sub)
    # Seat-level assignments for the E3 subscription (the others use the vendor count).
    for i, who in enumerate(['avery.cole', 'mina.park', 'luis.ortega', 'sara.nguyen',
                             'tom.bell', 'priya.rao', 'ken.ito', 'dee.walsh']):
        LicenseAssignment.objects.get_or_create(
            subscription=nwl_sub[0], assigned_to=f'{who}@northwind.example', defaults=dict(
                assigned_at=today - timedelta(days=200 - i * 9)))

    # 5. Wallboard ----------------------------------------------------------
    from reports.models import Wallboard, WallboardWidget
    board = Wallboard.objects.filter(organization__isnull=True, name='Service Desk').first() \
        or Wallboard.objects.create(organization=None, name='Service Desk', refresh_seconds=60, order=10,
                                    description='Queue health and what is on fire, for the NOC screen.',
                                    created_by=user('demo.tech'))
    # The widget type comes from the source's recommended type, as the
    # wallboard editor does (a pie fed by a table source draws nothing).
    from reports.widget_sources import DATA_SOURCE_CHOICES
    kinds = {k: t for k, _label, t in DATA_SOURCE_CHOICES}
    WallboardWidget.objects.filter(wallboard=board).exclude(title__in=[
        'Open tickets', 'Overdue tickets', 'Monitors down', 'SSL certificates expiring',
        'Monitor status', 'Tickets opened, 30 days', 'Tickets by priority']).delete()
    for order, (title, source, x, y, w, h) in enumerate([
        ('Open tickets', 'open_tickets_count', 0, 0, 3, 2),
        ('Overdue tickets', 'overdue_tickets_count', 3, 0, 3, 2),
        ('Monitors down', 'monitors_down', 6, 0, 3, 2),
        ('SSL certificates expiring', 'ssl_expiring_soon', 9, 0, 3, 2),
        ('Monitor status', 'monitors_status_breakdown', 0, 2, 4, 4),
        ('Tickets opened, 30 days', 'tickets_opened_30d', 4, 2, 5, 4),
        ('Tickets by priority', 'tickets_by_priority', 9, 2, 3, 4),
    ]):
        WallboardWidget.objects.update_or_create(
            wallboard=board, title=title, defaults=dict(
                widget_type=kinds[source], data_source=source, order=order * 10,
                position={'x': x, 'y': y, 'width': w, 'height': h}))

    # 5b. Recurring contract amounts and technician cost rates, so the
    # business overview shows MRR and margin instead of "incomplete".
    import datetime as _dt
    from decimal import Decimal as _D
    from psa.models import Contract
    from resourcing.models import TechCostRate
    for name, freq, amount in (('Northwind — Managed Services', 'monthly', '4850.00'),
                               ('Ridgeline — Block Hours 40', 'quarterly', '5400.00'),
                               ('Harbor Point — Managed + Compliance', 'monthly', '6200.00')):
        Contract.objects.filter(name=name).update(billing_frequency=freq, recurring_amount=_D(amount))
    for username, rate in (('demo.tech', '48.00'), ('demo.ipatel', '42.00'), ('demo.mokafor', '55.00')):
        TechCostRate.objects.get_or_create(user=user(username), effective_from=_dt.date(2025, 1, 1),
                                           defaults={'rate_per_hour': _D(rate)})

    # 6. API access control -------------------------------------------------
    from api_access.models import ApiAccessRule, ApiAccessSettings, TrustedProxy
    admin = user('demo.tech')
    created = 0
    for name, net, action, scope, target, desc, active in [
        ('RMM server', '198.51.100.0/24', 'allow', 'endpoint_group', 'integration_api',
         'The Rem0te server that calls the integration API', True),
        ('Blocked scanner', '203.0.113.0/24', 'deny', 'global', '',
         'Vulnerability scanner that kept probing the API', True),
        ('Old VPN range', '192.0.2.0/24', 'allow', 'global', '',
         'Retired site-to-site VPN; kept for reference', False),
    ]:
        _, made = ApiAccessRule.objects.get_or_create(
            name=name, network=net, defaults=dict(
                action=action, surface='api', scope=scope, target=target, description=desc,
                is_active=active, created_by=admin))
        created += made
    _, made = TrustedProxy.objects.get_or_create(
        network='10.0.0.10/32', defaults=dict(description='Edge proxy', created_by=admin))
    if created or made:
        ApiAccessSettings.bump(admin)  # modes stay Unrestricted; this only refreshes the policy cache
    print('  operations: 4 RMM alerts, 1 monitor down, 2 backup connections, 3 backup alerts, '
          '5 subscriptions, 1 wallboard, 3 API rules, 1 trusted proxy')


# --- 3.17.742-761 screens ---------------------------------------------------
# Billing queue, prepaid ledger, contract e-signature, viewed tracking,
# customer follow-up, access groups, off-host backups and Connected
# Applications. Everything uses the app's own services where one exists and
# invented .example hosts; nothing contacts anything.

def seed_access_groups():
    """Members for the built-in access groups, so the list shows who holds what."""
    from tech_access.models import TechnicianGroup
    plan = {'L1 Tech': ['demo.sam.okafor', 'demo.priya.raman'], 'L2 Tech': ['demo.ipatel', 'demo.mokafor'],
            'L3 Tech': ['demo.tech', 'demo.lchen'], 'Managers': ['demo.alindqvist'], 'Owners': ['demo.admin'],
            'Billing': ['demo.dwhitfield'], 'Sales': ['demo.hannah.price']}
    for name, names in plan.items():
        grp = TechnicianGroup.objects.filter(name=name).first()
        if grp:
            for u in User.objects.filter(username__in=names):
                try:
                    grp.members.add(u)
                except Exception:  # customer-type demo users are refused: groups hold MSP staff only
                    pass
    print('  access groups: members added')


def seed_billing_queue():
    """Ready for Billing: three customers with tickets sent to billing, account
    charges (one held, one adjustment), a next fee due; then one consolidated
    draft for Northwind built through the app's own service."""
    from psa import models as pm
    from psa.billing import queue as bq
    nwl, hpc, rdg = org('Northwind Logistics'), org('Harbor Point Credit Union'), org('Ridgeline Dental Group')
    msp, tech = org('Beacon Managed IT'), user('demo.tech')
    pm.Ticket.objects.filter(pk__in=[3, 10, 11]).update(billing_status='ready', billing_status_at=now,
                                                         billing_status_by=tech)

    def charge(client, desc, amount, **kw):
        c, _ = pm.Charge.objects.get_or_create(
            organization=msp, client_org=client, description=desc,
            defaults=dict(amount=Decimal(str(amount)), charge_date=today - timedelta(days=2), created_by=tech, **kw))
        return c
    held = charge(hpc, 'Hardware tokens (10) for branch staff', 420.00)
    charge(hpc, 'Domain renewal — harborpoint.example', 18.00)
    charge(rdg, 'Imaging sensor cable (replacement)', 64.50)
    n1 = charge(nwl, 'Label printer ribbon and tape (warehouse)', 36.00)
    n2 = charge(nwl, 'Wi-Fi survey licence (month)', 79.00)
    bq.decide(hpc, [f'charge:{held.pk}'], 'hold', actor=tech, reason='Waiting for the purchase order number',
              hold_until=today + timedelta(days=10))
    bq.add_adjustment(rdg, actor=tech, description='Goodwill credit for the missed appointment', amount=Decimal('50'),
                      is_credit=True, reason='Technician was 90 minutes late', msp_org=msp)
    # Harbor Point's managed agreement is due today, so the picker offers its fee.
    pm.Contract.objects.filter(client_org=hpc, name__startswith='Harbor Point').update(next_billing_date=today)
    # Northwind: ticket 9's billable work and two charges, as one consolidated draft.
    pm.Ticket.objects.filter(pk=9).update(billing_status='ready', billing_status_at=now, billing_status_by=tech)
    if not pm.Invoice.objects.filter(client_org=nwl, status='draft').exists():
        inv, notes = bq.draft_consolidated_from_queue(nwl, actor=tech, msp_org=msp, ticket_ids=[9],
                                                      include_charges=True)
        print('  consolidated draft:', inv.pk if inv else None, notes)
    print('  billing queue seeded')


def seed_viewed_tracking():
    """Quote and invoice links the customer has opened (first/last view, count)."""
    from psa.models import Invoice, Quote
    Quote.objects.filter(title__startswith='Warehouse Wi-Fi').update(
        first_viewed_at=now - timedelta(days=2, hours=3), last_viewed_at=now - timedelta(hours=5), view_count=4)
    inv = Invoice.objects.filter(status='sent').first()
    if inv:
        Invoice.objects.filter(pk=inv.pk).update(first_viewed_at=now - timedelta(days=1, hours=6),
                                                 last_viewed_at=now - timedelta(days=1), view_count=2)
    print('  viewed tracking set')


def seed_contract_esign():
    """A 12-month managed-services contract sent for e-signature and viewed by
    the customer, built with the contracts app's own services."""
    from contracts import services as cs
    from contracts.models import ContractDocument, ContractSigner, ContractTemplate
    nwl, tech = org('Northwind Logistics'), user('demo.tech')
    if ContractDocument.objects.filter(organization=nwl, title__startswith='Managed Services Agreement').exists():
        return
    tpl = ContractTemplate.objects.filter(is_sample=True, sample_key__icontains='12').first() \
        or ContractTemplate.objects.filter(is_sample=True).first()
    c = cs.create_contract(nwl, tech, template=None, title='Managed Services Agreement — 12 months', kind='msa')
    sections = [
        {'title': 'Services', 'type': 'text', 'body': '<p>Beacon Managed IT provides monitoring, patching, help desk '
         'and a named technician for Northwind Logistics, as listed in the schedule.</p>'},
        {'title': 'Term and notice', 'type': 'text', 'body': '<p>The agreement runs for twelve months from the '
         'effective date and renews for a further twelve months unless either party gives 60 days\' notice.</p>'},
        {'title': 'Signatures', 'type': 'signatures', 'body': ''}]
    cs.save_draft(c, {
        'sections': sections, 'term_type': 'annual', 'duration_months': 12, 'notice_period_days': 60,
        'auto_renew': True, 'billing_frequency': 'monthly', 'effective_date': today + timedelta(days=14),
        'line_items': [{'description': 'Managed services — 45 users, 62 devices', 'kind': 'recurring',
                        'quantity': '1', 'unit_price': '2450.00', 'taxable': False}],
        'signers': [{'role': ContractSigner.CLIENT, 'name': 'Dana Whitaker', 'email': 'dana.whitaker@northwind.example',
                     'title': 'Operations Director', 'order': 1}]}, tech)
    c.refresh_from_db()
    cs.submit(c, tech)
    c.refresh_from_db()
    if c.status == ContractDocument.PENDING_APPROVAL:
        cs.decide(c, user('demo.admin'), approve=True, content_hash=c.current_version.content_hash)
        c.refresh_from_db()
    cs.send(c, tech, email=False)
    ContractDocument.objects.filter(pk=c.pk).update(
        status=ContractDocument.VIEWED, first_viewed_at=now - timedelta(days=1, hours=2),
        last_viewed_at=now - timedelta(hours=4), view_count=3)
    from contracts.models import ContractInvitation
    ContractInvitation.objects.filter(contract=c).update(
        first_viewed_at=now - timedelta(days=1, hours=2), last_viewed_at=now - timedelta(hours=4),
        view_count=3, verified_view_count=0)
    print('  contract awaiting signature:', c.reference)


def seed_followup():
    """Customer follow-up switched on (the demo shows the settings and a ticket
    that is waiting on the customer, with its next follow-up and close dates)."""
    from psa.models import FollowUpPolicy, Ticket
    pol = FollowUpPolicy.objects.first() or FollowUpPolicy()
    pol.enabled = True
    pol.save()
    from psa.models import TicketStatus
    waiting = TicketStatus.objects.filter(name='Waiting on Client').first()
    if waiting:
        # PSA-2026-000013: waiting on the customer for four days, so the first follow-up is due.
        Ticket.objects.filter(pk=13).update(status=waiting, sla_paused_at=now - timedelta(days=4),
                                            followup_wait_since=now - timedelta(days=4))
    print('  follow-up policy on; ticket 13 waiting on the customer')


def seed_offhost_backups():
    """An off-host backup destination (SFTP, invented host) with a few runs.
    No key material: the fingerprints are invented placeholders."""
    from core.models import OffhostBackupConfig, OffhostBackupRun
    admin = user('demo.admin')
    OffhostBackupConfig.objects.exclude(pk=1).delete()
    cfg = OffhostBackupConfig.get()
    cfg.enabled, cfg.destination_type = True, 'sftp'
    cfg.sftp_host, cfg.sftp_port, cfg.sftp_username = 'backup01.beaconmanaged.example', 22, 'clientst0r-backup'
    cfg.sftp_path = '/srv/backups/clientst0r'
    cfg.host_key_type = 'ssh-ed25519'
    cfg.host_key = 'AAAAC3NzaC1lZDI1NTE5AAAAIDemoHostKeyOnlyNotARealKeyxxxxxxxxxxxxxxxx'
    cfg.host_key_fingerprint = 'SHA256:Zk3J1q0DemoFingerprintOnlyNotRealxxxxxxxxxx'
    cfg.host_key_approved_at, cfg.host_key_approved_by = now - timedelta(days=20), admin
    cfg.sftp_password = 'demo-placeholder-not-a-password'  # sealed; invented, the host does not exist
    cfg.backup_key = 'demo-placeholder-backup-key-not-real'
    cfg.backup_key_fingerprint = 'DEMO-4F2A-9C11-77B0'
    cfg.backup_key_created_at = now - timedelta(days=20)
    cfg.backup_key_acknowledged_at, cfg.backup_key_acknowledged_by = now - timedelta(days=20), admin
    cfg.last_backup_at = cfg.last_success_at = now - timedelta(hours=7)
    cfg.last_backup_status, cfg.last_success_name = 'success', 'clientst0r-20261121T020000Z.tar.gz.enc'
    cfg.last_verify_at = cfg.last_verified_ok_at = now - timedelta(days=3)
    cfg.last_verify_status = 'success'
    cfg.last_verified_name = 'clientst0r-20261118T020000Z.tar.gz.enc'
    cfg.last_verify_detail = 'Hash, manifest and database integrity check passed.'
    cfg.save()
    if not OffhostBackupRun.objects.exists():
        rows = []
        for d in range(6, -1, -1):
            rows.append(('backup', 'scheduler', 'success', now - timedelta(days=d, hours=-2 + 0),
                         f'clientst0r-2026112{1 - d if d < 2 else 0}T020000Z.tar.gz.enc', 'Uploaded 38.4 MB; retention kept 11 archives.'))
        for r in OffhostBackupRun.objects.none():
            pass
        for kind, trig, status, at, name, detail in rows:
            run = OffhostBackupRun.objects.create(kind=kind, trigger=trig, status=status, remote_name=name,
                                                  size_bytes=40_265_318, finished_at=at, detail=detail,
                                                  destination='sftp://backup01.beaconmanaged.example/srv/backups/clientst0r')
            OffhostBackupRun.objects.filter(pk=run.pk).update(started_at=at - timedelta(minutes=4))
        v = OffhostBackupRun.objects.create(kind='verify', trigger='scheduler', status='success',
                                            remote_name='clientst0r-20261118T020000Z.tar.gz.enc', finished_at=now - timedelta(days=3),
                                            detail='Hash, manifest and database integrity check passed.')
        OffhostBackupRun.objects.filter(pk=v.pk).update(started_at=now - timedelta(days=3, minutes=6))
    print('  off-host backups seeded')


def seed_connected_apps():
    """Two Agit8or Connect connections for the Connected Applications pages:
    a healthy Rem0te link and a degraded second application with an incident.
    Rows only: invented .example addresses, no keys, nothing is ever contacted."""
    from connect.models import Connection, ConnectIncident, DiagnosticRun, TenantGrant
    from connect.diagnostics import STEPS
    nwl, rdg = org('Northwind Logistics'), org('Ridgeline Dental Group')
    specs = [
        ('11111111-1111-4111-8111-111111111111', 'rem0te', 'Rem0te', 'https://remote.beaconmanaged.example',
         Connection.HEALTH_CONNECTED, ['connection:read', 'customers:read', 'events:publish'],
         [nwl, rdg]),
        ('22222222-2222-4222-8222-222222222222', 'other', 'Service wallboard feed', 'https://wallboard.beaconmanaged.example',
         Connection.HEALTH_DEGRADED, ['connection:read', 'events:publish'], [nwl]),
    ]
    for pk, app, name, url, health, scopes, orgs in specs:
        conn, _ = Connection.objects.get_or_create(pk=pk, defaults=dict(
            direction=Connection.OUTBOUND, state=Connection.ACTIVE, remote_app_type=app, remote_display_name=name,
            remote_installation_id=f'demo-{app}-installation', remote_app_version='1.4.0', base_url=url,
            inbound_scopes=scopes, outbound_scopes=scopes))
        Connection.objects.filter(pk=conn.pk).update(
            health=health, last_success_at=now - timedelta(minutes=1 if health == Connection.HEALTH_CONNECTED else 40),
            last_check_at=now - timedelta(seconds=40), remote_protocol_version='1.1',
            consecutive_fail=0 if health == Connection.HEALTH_CONNECTED else 2, retry_step=0 if health == Connection.HEALTH_CONNECTED else 1,
            last_error='' if health == Connection.HEALTH_CONNECTED else 'The other application did not answer the last two checks.')
        for o in orgs:
            TenantGrant.objects.get_or_create(connection=conn, organization=o, defaults=dict(
                remote_tenant_id=f'tenant-{o.pk}', remote_tenant_label=o.name, scopes=scopes))
        if not conn.diagnostic_runs.exists():
            fail = health != Connection.HEALTH_CONNECTED
            steps = []
            for n, sid, label in STEPS:
                bad = fail and sid in ('tcp', 'tls')
                skipped = fail and n > 3 and n < 15
                steps.append({'n': n, 'id': sid, 'name': label,
                              'status': 'fail' if bad else ('skipped' if skipped and sid != 'tls' else 'pass'),
                              'code': 'timeout' if bad else '',
                              'explanation': ('Connection timed out after 10 s.' if bad else ('Not run: an earlier step failed.' if skipped else f'{label}: OK.')),
                              'next_action': 'Check that the other application is running and reachable.' if bad else '',
                              'at': now.isoformat(), 'duration_ms': 40 + n * 7, 'data': {}})
            DiagnosticRun.objects.create(connection=conn, trigger='manual', started_at=now - timedelta(minutes=12),
                                         finished_at=now - timedelta(minutes=12) + timedelta(seconds=3), steps=steps,
                                         result='fail' if fail else 'pass', run_by=user('demo.admin'))
        if health != Connection.HEALTH_CONNECTED and not conn.incidents.exists():
            ConnectIncident.objects.create(connection=conn, status='degraded', worst_status='degraded',
                                           code='timeout', opened_at=now - timedelta(minutes=35), updated_at=now)
    print('  connected apps seeded')



def main():
    steps = [seed_showcase, seed_presentation, seed_asset_detail, seed_commercial,
             rename_msp_tenant, seed_project_work, seed_visual, seed_dispatch,
             seed_my_work, seed_document_lifecycle, seed_readiness, seed_portal_request,
             seed_scheduler_history, seed_rack_artwork, seed_named_approvers,
             seed_readiness_custom_fields, seed_secure_link, seed_ticket_ai, seed_superuser_approval,
             seed_rmm_fixture, seed_rmm_pairing, seed_navigation, seed_operations,
             seed_access_groups, seed_billing_queue, seed_viewed_tracking, seed_contract_esign,
             seed_followup, seed_offhost_backups, seed_connected_apps]
    only = set(sys.argv[1:])
    for step in steps:
        if only and step.__name__ not in only:
            continue
        print(step.__name__)
        step()


if __name__ == '__main__':
    main()
