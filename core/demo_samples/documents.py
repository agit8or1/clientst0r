"""Sample data group: documents (v3.17.657). See core/demo_samples/__init__.py.

Real, openable files for each demo customer — a Word network handover and
new-starter checklist, Excel hardware inventory and licence renewals, a PDF
backup runbook and a CSV phone list — plus two written HTML / Markdown
documents with proper content. The files are generated in code
(core.demo_samples.sample_files) and stored through the Document ``file``
field exactly as an upload is, so /media/ serves them under the usual
document rules. Each document is keyed by (customer, slug): a second run adds
nothing and existing documents are never touched.
"""
import mimetypes
import random
from datetime import date

from django.core.files.base import ContentFile
from django.utils.text import slugify

from . import sample_files as F


def _short(org):
    return org.name.replace('Demo ', '').strip() or org.name


def _network_handover(org, rnd):
    name = _short(org)
    third = rnd.randint(10, 60)
    return F.build_docx(f'Network handover — {name}', [
        ('title', f'Network handover — {name}'),
        ('p', f'This document hands over the day-to-day running of the {name} office network to the '
              'support desk. It lists what is installed, how it is addressed and who to call. Keep it '
              'with the rack and update it whenever something changes.'),
        ('h1', 'Summary'),
        ('bullet', 'One internet connection (fibre, 500/500 Mbps) with a 4G failover router.'),
        ('bullet', 'Firewall in an active/passive pair; site-to-site VPN to the cloud tenant.'),
        ('bullet', 'Two stacked 48-port PoE switches and four ceiling-mounted Wi-Fi access points.'),
        ('bullet', 'All configuration backups are stored in the documentation vault.'),
        ('h1', 'Addressing and VLANs'),
        ('table', [
            ('VLAN', 'Name', 'Subnet', 'Gateway', 'DHCP'),
            ('10', 'Staff', f'10.{third}.10.0/24', f'10.{third}.10.1', 'Firewall'),
            ('20', 'Voice', f'10.{third}.20.0/24', f'10.{third}.20.1', 'Firewall (option 66)'),
            ('30', 'Guest Wi-Fi', f'10.{third}.30.0/24', f'10.{third}.30.1', 'Firewall, isolated'),
            ('99', 'Management', f'10.{third}.99.0/24', f'10.{third}.99.1', 'Static only'),
        ]),
        ('h1', 'Key devices'),
        ('table', [
            ('Device', 'Model', 'Management address', 'Notes'),
            ('fw-01 / fw-02', 'FortiGate 60F (HA pair)', f'10.{third}.99.2', 'Admin over HTTPS from VLAN 99 only'),
            ('sw-core-01', 'Aruba 2930F 48G PoE+ (stack of 2)', f'10.{third}.99.10', 'Uplinks on ports 49-50'),
            ('ap-01 … ap-04', 'Aruba AP-515', 'DHCP on VLAN 99', 'Managed from the cloud portal'),
            ('nas-01', 'Synology RS1221+', f'10.{third}.10.20', 'File shares and local backup target'),
        ]),
        ('h1', 'Contacts and escalation'),
        ('p', 'Internet faults go to the carrier first (circuit reference on the label in the rack). '
              'Anything else comes to the support desk; out of hours, call the on-call number on the '
              'service status page.'),
        ('h2', 'Before you change anything'),
        ('bullet', 'Raise a change ticket and agree a window with the office manager.'),
        ('bullet', 'Take a configuration backup and attach it to the ticket.'),
        ('bullet', 'Update this document and the rack diagram afterwards.'),
    ])


def _new_starter(org):
    name = _short(org)
    return F.build_docx('New starter IT checklist', [
        ('title', 'New starter IT checklist'),
        ('p', f'Use this checklist for every new member of staff at {name}. Tick each item and attach the '
              'completed checklist to the onboarding ticket.'),
        ('h1', 'Before day one'),
        ('table', [
            ('Task', 'Owner', 'Done'),
            ('Create the Microsoft 365 account and assign a licence', 'Support desk', '☐'),
            ('Add to the department security groups and shared mailboxes', 'Support desk', '☐'),
            ('Prepare and enrol a laptop in device management', 'Support desk', '☐'),
            ('Order a phone handset or set up the softphone', 'Office manager', '☐'),
            ('Print a building access card', 'Office manager', '☐'),
        ]),
        ('h1', 'On day one'),
        ('bullet', 'Sign in together and set up multi-factor authentication on their phone.'),
        ('bullet', 'Show where files are kept and how to share them.'),
        ('bullet', 'Explain how to report a problem: the portal, e-mail or phone.'),
        ('bullet', 'Run through the acceptable use policy and collect the signed copy.'),
        ('h1', 'After the first week'),
        ('p', 'Check in to make sure everything works and that they can reach every system they need. '
              'Close the onboarding ticket once the manager confirms.'),
    ])


def _hardware_inventory(org, rnd):
    kit = [
        ('Laptop', 'Dell', 'Latitude 7440', 1249.00),
        ('Laptop', 'Lenovo', 'ThinkPad T14 Gen 4', 1189.00),
        ('Desktop', 'HP', 'EliteDesk 800 G9', 899.00),
        ('Monitor', 'Dell', 'P2723DE 27"', 329.00),
        ('Firewall', 'Fortinet', 'FortiGate 60F', 1095.00),
        ('Switch', 'Aruba', '2930F 48G PoE+', 2310.00),
        ('Access point', 'Aruba', 'AP-515', 640.00),
        ('NAS', 'Synology', 'RS1221+', 1580.00),
        ('UPS', 'APC', 'Smart-UPS 1500 RM', 845.00),
        ('Printer', 'Brother', 'MFC-L8900CDW', 699.00),
    ]
    people = ['Reception', 'Finance', 'Sales', 'Operations', 'Server room', 'Director']
    rows = []
    for i in range(24):
        kind, make, model, price = kit[i % len(kit)]
        year = 2021 + (i % 4)
        rows.append([
            f'{_short(org)[:3].upper()}-{1001 + i}', kind, make, model,
            f'{make[:2].upper()}{rnd.randint(10 ** 7, 10 ** 8 - 1)}',
            people[rnd.randrange(len(people))],
            date(year, rnd.randint(1, 12), rnd.randint(1, 28)),
            price, '=IF(G{r}+1095<TODAY(),"Out of warranty","In warranty")',
        ])
    return F.build_xlsx(
        'Inventory',
        ['Asset tag', 'Type', 'Manufacturer', 'Model', 'Serial number', 'Location', 'Purchased',
         'Cost', 'Warranty (3 yr)'],
        rows, widths=[12, 14, 14, 22, 16, 14, 12, 11, 18], number_formats={'G': 'yyyy-mm-dd', 'H': '#,##0.00'},
        total_row=('Total', {'H': '=SUM(H2:H{last})'}), title='Hardware inventory')


def _licence_renewals(org, rnd):
    products = [
        ('Microsoft 365 Business Premium', 'Microsoft', 25, 22.00),
        ('Microsoft 365 Business Basic', 'Microsoft', 8, 6.00),
        ('Adobe Acrobat Pro', 'Adobe', 6, 19.99),
        ('SentinelOne Control', 'SentinelOne', 33, 6.50),
        ('Backup for Microsoft 365', 'Veeam', 33, 2.50),
        ('FortiGate UTP bundle', 'Fortinet', 1, 690.00),
        ('Aruba Central Foundation', 'HPE Aruba', 4, 95.00),
        ('Password manager (Teams)', 'Bitwarden', 25, 4.00),
        ('Domain name', 'Registrar', 1, 18.00),
        ('Wildcard TLS certificate', 'Certificate authority', 1, 249.00),
    ]
    rows = []
    for i, (product, vendor, seats, per_seat) in enumerate(products):
        month = (i * 5 + rnd.randint(0, 3)) % 12 + 1
        rows.append([product, vendor, seats, date(2027, month, rnd.randint(1, 28)), per_seat,
                     '=C{r}*E{r}', '=D{r}-TODAY()',
                     'Monthly' if per_seat < 50 else 'Annual'])
    return F.build_xlsx(
        'Renewals',
        ['Product', 'Vendor', 'Seats', 'Renewal date', 'Price per seat', 'Annual cost', 'Days left', 'Billing'],
        rows, widths=[32, 20, 8, 14, 14, 13, 10, 10],
        number_formats={'D': 'yyyy-mm-dd', 'E': '#,##0.00', 'F': '#,##0.00', 'G': '0'},
        total_row=('Total', {'F': '=SUM(F2:F{last})'}), title='Licence renewals')


def _backup_runbook(org):
    name = _short(org)
    return F.build_pdf('Backup and recovery runbook', [
        ('h', 'What is backed up'),
        ('table', [
            ('System', 'Method', 'Schedule', 'Kept for'),
            ('File server (nas-01)', 'Snapshot + offsite copy', 'Hourly snapshots, nightly copy', '30 days / 1 year'),
            ('Microsoft 365 mail, OneDrive, SharePoint', 'Cloud-to-cloud backup', 'Four times a day', '1 year'),
            ('Line-of-business database', 'Native dump to NAS', 'Nightly 01:00', '14 days'),
            ('Firewall and switch configs', 'Config export to the vault', 'After every change', 'All versions'),
        ]),
        ('h', 'Daily check (support desk)'),
        ('steps', [
            'Open the backup dashboard and confirm every job shows Success for the last night.',
            'Any Warning or Failed job: open a ticket at P3, attach the job log, and re-run the job.',
            'Two failures in a row on the same job: raise to P2 and tell the account manager.',
        ]),
        ('h', 'Restoring a file or folder'),
        ('steps', [
            'Confirm the exact path and the last time the user saw the file as they expect.',
            'Restore to an alternate location first (\\\\nas-01\\restore) — never over the live copy.',
            'Ask the user to check the restored copy, then move it into place.',
            'Record what was restored and from which point in time on the ticket.',
        ]),
        ('h', 'Full server recovery'),
        ('p', 'Declare an incident and follow the incident response plan. Restore the latest good image '
              'to the spare host, re-point DNS, then restore data from the most recent snapshot. Target: '
              'files back within 4 hours (RTO), losing at most 1 hour of changes (RPO).'),
        ('h', 'Quarterly test restore'),
        ('bullets', [
            'Restore one random folder and one mailbox to the test area and compare checksums.',
            'Time the restore and record it on the test-restore ticket.',
            'Update this runbook if anything has changed.',
        ]),
    ], subtitle=f'{name} — reviewed quarterly by the support desk')


def _phone_extensions(org, rnd):
    first = ['Amelia', 'Ben', 'Chloe', 'Daniel', 'Ella', 'Finn', 'Grace', 'Harry', 'Isla', 'Jack',
             'Lily', 'Mason', 'Nora', 'Oscar', 'Poppy', 'Ryan', 'Sofia', 'Theo']
    last = ['Adams', 'Baker', 'Clarke', 'Davies', 'Evans', 'Foster', 'Green', 'Hughes', 'Irving',
            'Jones', 'Khan', 'Lewis', 'Morgan', 'Nash', 'Owen', 'Patel', 'Reid', 'Shaw']
    depts = ['Reception', 'Finance', 'Sales', 'Operations', 'Management', 'Warehouse']
    rows = [['Reception (main line)', '200', 'Reception', '555-0100', '']]
    for i in range(18):
        rows.append([f'{first[i]} {last[(i * 7) % len(last)]}', str(201 + i), depts[rnd.randrange(len(depts))],
                     f'555-01{i + 1:02d}', f'555-02{rnd.randint(10, 99)}' if i % 3 else ''])
    rows.append(['Conference room', '250', 'Shared', '', ''])
    rows.append(['Out-of-hours support', '299', 'IT', '555-0199', ''])
    return F.build_csv(['Name', 'Extension', 'Department', 'Direct dial', 'Mobile'], rows)


def _network_overview_html(org, rnd):
    third = rnd.randint(10, 60)
    name = _short(org)
    return f"""<h2>Site network overview</h2>
<p>The {name} office runs on a single routed site with four VLANs behind an active/passive firewall pair.
Internet arrives on a 500/500&nbsp;Mbps fibre circuit with a 4G router as automatic failover.</p>
<h3>Subnets</h3>
<table class="table table-sm table-bordered">
<thead><tr><th>VLAN</th><th>Purpose</th><th>Subnet</th><th>Gateway</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>10</td><td>Staff devices</td><td>10.{third}.10.0/24</td><td>10.{third}.10.1</td><td>DHCP from the firewall, 8-hour lease</td></tr>
<tr><td>20</td><td>Voice</td><td>10.{third}.20.0/24</td><td>10.{third}.20.1</td><td>QoS tagged; phones get option 66</td></tr>
<tr><td>30</td><td>Guest Wi-Fi</td><td>10.{third}.30.0/24</td><td>10.{third}.30.1</td><td>Internet only, client isolation on</td></tr>
<tr><td>99</td><td>Management</td><td>10.{third}.99.0/24</td><td>10.{third}.99.1</td><td>Static addresses; admin access from here only</td></tr>
</tbody>
</table>
<h3>Traffic flow</h3>
<ul>
<li>All inter-VLAN traffic is routed and filtered by the firewall.</li>
<li>The site-to-site VPN to the cloud tenant carries only VLAN 10 and 99.</li>
<li>DNS: the firewall forwards to the filtering resolver; internal names resolve from the domain controllers.</li>
</ul>
<h3>Where to look first</h3>
<ol>
<li>Is the internet up? Check the firewall dashboard and the carrier status page.</li>
<li>Is it one VLAN or all of them? Test from a staff PC and from the guest Wi-Fi.</li>
<li>Check the switch uplinks (ports 49-50) and the firewall HA status.</li>
</ol>"""


_BACKUP_MD = """## Nightly backup checklist

Run this every morning before 10:00. It takes about five minutes.

1. **Open the backup console** and filter to *Last 24 hours*.
2. **Check every job shows _Success_.** The jobs that must run are:
   - File server snapshot copy (01:00)
   - Database dump (01:00)
   - Microsoft 365 backup (00:00, 06:00, 12:00, 18:00)
3. **Warning or Failed?** Open a P3 ticket, attach the job log and re-run the job.
4. **Check free space** on the backup target. Raise a ticket if it is below 20%.
5. **Record the check** on the daily checklist ticket with the time you looked.

| Result | What to do | Priority |
|---|---|---|
| All green | Note it on the ticket | — |
| One warning | Re-run, note the cause | P3 |
| Failed twice in a row | Escalate to the account manager | P2 |
| No backup for 48 hours | Declare an incident | P1 |

> Never restore over live data. Restore to `\\\\nas-01\\restore` first and let the user check it.
"""


def _file_specs(org, rnd):
    name = _short(org)
    return [
        (f'Network handover — {name}', 'network-handover.docx', lambda: _network_handover(org, rnd)),
        ('New starter IT checklist', 'new-starter-it-checklist.docx', lambda: _new_starter(org)),
        ('Hardware inventory', 'hardware-inventory.xlsx', lambda: _hardware_inventory(org, rnd)),
        ('Licence renewals', 'licence-renewals.xlsx', lambda: _licence_renewals(org, rnd)),
        ('Backup and recovery runbook', 'backup-and-recovery-runbook.pdf', lambda: _backup_runbook(org)),
        ('Phone extensions', 'phone-extensions.csv', lambda: _phone_extensions(org, rnd)),
    ]


def _exists(org, slug):
    from docs.models import Document
    return Document.objects.filter(organization=org, slug=slug).exists()


def seed(ctx):
    from docs.models import Document
    from . import has_webhook
    for org in ctx.customers:
        if has_webhook(org, 'document.created'):
            ctx.out.write(f'  documents: skipped {org.slug} (document.created webhook)')
            continue
        rnd = random.Random(f'documents-{org.slug}')
        for title, filename, build in _file_specs(org, rnd):
            slug = slugify(title)
            if _exists(org, slug):
                continue
            data = build()
            doc = Document(
                organization=org, title=title, slug=slug, content_type='file',
                file_size=len(data), file_type=mimetypes.guess_type(filename)[0] or 'application/octet-stream',
                is_published=True, created_by=ctx.admin, last_modified_by=ctx.admin,
            )
            # Same storage path an upload gets (documents/files/%Y/%m/).
            doc.file.save(filename, ContentFile(data), save=False)
            doc.save()
            ctx.created('docs.Document (file)')

        for title, content_type, body in (
            ('Site network overview', 'html', _network_overview_html(org, rnd)),
            ('Nightly backup checklist', 'markdown', _BACKUP_MD),
        ):
            slug = slugify(title)
            if _exists(org, slug):
                continue
            Document.objects.create(
                organization=org, title=title, slug=slug, content_type=content_type, body=body,
                is_published=True, created_by=ctx.admin, last_modified_by=ctx.admin,
            )
            ctx.created('docs.Document')
