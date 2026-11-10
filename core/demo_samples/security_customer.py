"""Sample data group: security_customer (v3.17.655). See core/demo_samples/__init__.py.

Status pages, security alerts / incidents / playbooks, portal banners, asset
intelligence (relationships, services, groups, advisories, policies,
baselines), contact notes, password links, diagram notes and core relations.

Kept harmless on purpose: no SecurityVendorConnection or SIEMWebhookEndpoint
rows (nothing that polls or accepts inbound traffic), no new monitors (they
would be polled), no playbook `send_email` steps, and no compliance
recertification reminders (those rows record e-mail actually sent, and their
presence suppresses the next real reminder).
"""
from datetime import timedelta

# --- Status pages ----------------------------------------------------------

STATUS_PAGES = [
    {
        'title': 'Service status',
        'visibility': 'public',
        'intro': 'Live status of the services we run for you. Planned work is posted here in advance.',
        'maintenance': [
            ('Firewall firmware upgrade', 3, 2,
             'We are applying a firmware update to the office firewall. Internet access and VPN '
             'will drop for up to 15 minutes during the window.'),
            ('Mail server patching', -9, 2,
             'Monthly security updates on the mail platform. Webmail may be slow for a few minutes.'),
        ],
        'incidents': [
            {
                'title': 'Website slow to load',
                'started_days_ago': 12, 'duration_hours': 3,
                'root_cause': 'A failed disk in the web server array caused a rebuild that slowed page loads. '
                              'The disk was replaced and the array rebuilt overnight.',
                'updates': [
                    ('investigating', 0, 'We are looking into reports that the website is slow to load.'),
                    ('identified', 40, 'A storage problem on the web server has been found and we are working on it.'),
                    ('monitoring', 120, 'Load times are back to normal. We are keeping an eye on it.'),
                    ('resolved', 180, 'This has been resolved. Thank you for your patience.'),
                ],
            },
            {
                'title': 'Intermittent VPN disconnects',
                'started_days_ago': 0, 'duration_hours': None, 'started_hours_ago': 5,
                'root_cause': '',
                'updates': [
                    ('investigating', 0, 'Some remote users are being disconnected from the VPN. We are investigating.'),
                    ('identified', 50, 'An upstream routing change at the internet provider is the likely cause.'),
                    ('monitoring', 150, 'The provider has rolled back the change. Connections look stable; we are monitoring.'),
                ],
            },
        ],
    },
    {
        'title': 'Client portal status',
        'visibility': 'portal',
        'intro': 'Status of your business systems, for signed-in staff.',
        'maintenance': [
            ('Backup appliance replacement', 6, 4,
             'The on-site backup appliance is being replaced. Nightly backups continue to the cloud copy.'),
            ('Wi-Fi access point swap', -20, 1,
             'Access points on the second floor were replaced. Wi-Fi was briefly unavailable on that floor.'),
        ],
        'incidents': [
            {
                'title': 'Shared drive unavailable',
                'started_days_ago': 25, 'duration_hours': 2,
                'root_cause': 'A Windows update restarted the file server outside the maintenance window.',
                'updates': [
                    ('investigating', 0, 'The shared drive is not reachable. We are on it.'),
                    ('resolved', 110, 'The file server is back online and the shared drive is available again.'),
                ],
            },
        ],
    },
]

PAGE_SERVICES = [('Website', 'Public website'), ('Customer API', 'Ordering and account integrations'),
                 ('Staff portal', 'Administration and reporting')]

# --- Security alerts / incidents ------------------------------------------

ALERT_RULES = [
    {'name': 'Critical EDR alerts open a P1 ticket', 'priority': 10, 'match_category': 'edr',
     'match_severity_min': 'critical', 'ticket_priority_code': 'P1',
     'notes': 'Anything critical from endpoint protection goes straight to the queue as P1.'},
    {'name': 'High firewall alerts during business hours', 'priority': 50, 'match_category': 'firewall',
     'match_severity_min': 'high', 'ticket_priority_code': 'P2',
     'suppress_start_hour': 22, 'suppress_end_hour': 6,
     'notes': 'Overnight firewall noise is reviewed in the morning instead of paging.'},
]

# (external_id, severity, status, minutes ago, title, description, host index, source)
ALERTS = [
    ('sample-edr-0001', 'critical', 'acknowledged', 190,
     'Suspicious inbox rule created after sign-in from new country',
     'A mailbox rule forwarding all mail to an external address was created minutes after a sign-in '
     'from an unfamiliar location. Sample alert for demonstration.', 0, 'Microsoft Defender (sample)'),
    ('sample-edr-0002', 'high', 'acknowledged', 185,
     'Impossible travel: sign-ins 4,000 km apart within 20 minutes',
     'Two successful sign-ins for the same user from distant locations. Sample alert.', 0,
     'Microsoft Defender (sample)'),
    ('sample-edr-0003', 'critical', 'resolved', 60 * 24 * 6,
     'Ransomware behaviour blocked: mass file renames',
     'Endpoint protection stopped a process renaming files to a .locked extension and isolated the '
     'workstation. Sample alert.', 1, 'SentinelOne (sample)'),
    ('sample-fw-0004', 'medium', 'new', 45,
     'Repeated VPN login failures from one address',
     '27 failed VPN logins in 10 minutes from a single public IP. Sample alert.', 2,
     'Fortinet FortiGate (sample)'),
    ('sample-av-0005', 'low', 'dismissed', 60 * 30,
     'Potentially unwanted program detected: browser toolbar',
     'Adware toolbar quarantined during a scheduled scan. Sample alert.', 1, 'Bitdefender (sample)'),
]

INCIDENTS = [
    {
        'title': 'Compromised Microsoft 365 account',
        'severity': 'critical', 'status': 'investigating', 'opened_minutes_ago': 180,
        'description': 'A user account shows a malicious inbox forwarding rule and impossible-travel '
                       'sign-ins. Session tokens revoked; scope of mailbox access under review.',
        'alerts': ['sample-edr-0001', 'sample-edr-0002'], 'host': 0,
        'events': [
            ('opened', 0, 'Incident opened from alert: suspicious inbox rule.'),
            ('alert_added', 2, 'Impossible-travel alert correlated to this incident.'),
            ('acknowledged', 9, 'Acknowledged by on-call technician.'),
            ('note', 15, 'Password reset, all sessions revoked, MFA re-registered with the user on the phone.'),
            ('note', 40, 'Forwarding rule removed. Message trace shows 14 messages forwarded before removal.'),
            ('status_change', 41, 'open → investigating'),
        ],
    },
    {
        'title': 'Ransomware blocked on a workstation',
        'severity': 'critical', 'status': 'resolved', 'opened_minutes_ago': 60 * 24 * 6,
        'description': 'Endpoint protection stopped mass file encryption on one workstation and isolated '
                       'it from the network. No spread found; files restored from the previous night.',
        'alerts': ['sample-edr-0003'], 'host': 1,
        'events': [
            ('opened', 0, 'Incident opened from alert: ransomware behaviour blocked.'),
            ('acknowledged', 6, 'Acknowledged.'),
            ('contained', 20, 'Workstation network-isolated by the EDR agent; user moved to a loaner laptop.'),
            ('note', 90, 'Initial access was a malicious attachment. Same sender blocked tenant-wide.'),
            ('resolved', 60 * 26, 'Machine reimaged, 212 files restored from backup, user retrained.'),
        ],
        'acknowledged': 6, 'contained': 20, 'resolved': 60 * 26,
    },
    {
        'title': 'VPN brute-force attempts',
        'severity': 'medium', 'status': 'open', 'opened_minutes_ago': 44,
        'description': 'Repeated failed VPN logins from a single address. Watching for success before blocking.',
        'alerts': ['sample-fw-0004'], 'host': 2,
        'events': [
            ('opened', 0, 'Incident opened from alert: repeated VPN login failures.'),
        ],
    },
]

SLA_POLICIES = [
    # (severity, client-pinned?, ack, contain, resolve)
    ('critical', False, 15, 60, 60 * 24),
    ('high', False, 30, 240, 60 * 48),
    ('medium', False, 120, 60 * 24, 60 * 24 * 5),
    ('critical', True, 10, 45, 60 * 12),
]

PLAYBOOKS = [
    {
        'name': 'Compromised Microsoft 365 account', 'priority': 10, 'match_severity_min': 'high',
        'description': 'Containment for a suspected account takeover: ticket, flag the device, then the '
                       'manual checklist (revoke sessions, reset password, remove rules, review sign-ins).',
        'steps': [
            (10, 'create_ticket', {'priority_code': 'P1'}),
            (20, 'quarantine_asset_flag', {}),
        ],
        'notes': 'Manual follow-up: revoke sessions, reset password, re-register MFA, remove inbox rules, '
                 'run a message trace for the last 72 hours.',
    },
    {
        'name': 'Ransomware on a workstation', 'priority': 5, 'match_severity_min': 'critical',
        'description': 'Isolate first, investigate second. Opens a P1 ticket and tags the machine for '
                       'quarantine so nobody plugs it back in.',
        'steps': [
            (10, 'quarantine_asset_flag', {}),
            (20, 'create_ticket', {'priority_code': 'P1'}),
        ],
        'notes': 'Manual follow-up: confirm EDR isolation, check backups are intact before restoring, '
                 'look for the same hash on other endpoints.',
    },
]

# --- Portal ------------------------------------------------------------------

ANNOUNCEMENTS = [
    ('Planned firewall upgrade this weekend', 'warning', 7, True,
     'Internet and VPN access will be briefly interrupted on Saturday morning while we upgrade the '
     'office firewall. Details are on the status page.'),
    ('New: request software from the portal', 'success', 30, True,
     'You can now ask for software installs from the Requests page. Approved titles are installed '
     'automatically.'),
    ('Phishing campaign targeting invoices', 'danger', 5, False,
     'We are seeing fake invoice e-mails with a "view document" link. Do not enter your password '
     'from an e-mailed link; forward suspicious messages to the help desk.'),
]

# --- Assets ----------------------------------------------------------------

BUSINESS_SERVICES = [
    ('Email', 'high', 'operational', 'Microsoft 365 mail, calendars and Teams.'),
    ('Line-of-business application', 'critical', 'operational', 'Main business application and its database.'),
    ('Remote access VPN', 'medium', 'degraded', 'Remote staff connect through the office firewall.'),
    ('File shares', 'medium', 'operational', 'Departmental shared drives on the file server.'),
]

ASSET_GROUPS = [
    ('All servers', 'Every server, physical or virtual.', {'asset_type': 'server'}),
    ('End-user devices', 'Desktops, laptops and workstations.',
     {'asset_type__in': ['desktop', 'laptop', 'workstation']}),
    ('Network gear', 'Switches, firewalls, routers and access points.',
     {'asset_type__in': ['network', 'switch', 'firewall', 'router', 'access_point']}),
    ('Dell hardware', 'Warranty tracking cohort.', {'manufacturer__icontains': 'Dell'}),
]

# (cve_id, title, severity, cvss, pattern, fixed_version, days ago published)
VULNERABILITIES = [
    ('CVE-2021-44228', 'Apache Log4j remote code execution (Log4Shell)', 'critical', '10.0',
     'Log4j', '2.17.1', 1400),
    ('CVE-2023-4863', 'libwebp heap buffer overflow in Chrome', 'high', '8.8',
     'Google Chrome', '116.0.5845.187', 790),
    ('CVE-2024-3400', 'PAN-OS GlobalProtect command injection', 'critical', '10.0',
     'GlobalProtect', '11.1.2-h3', 570),
    ('CVE-2023-36884', 'Office and Windows HTML remote code execution', 'high', '8.8',
     'Microsoft Office', 'July 2023 security update', 850),
]
VULN_NOTE = 'Sample advisory for demonstration. Matched against RMM software inventory by name.'

SOFTWARE_POLICIES = [
    ('No unmanaged remote-control tools', 'TeamViewer', 'deny', 'high',
     'Remote access goes through the RMM only.'),
    ('No consumer file sync', 'Dropbox', 'deny', 'medium', 'Company files live in OneDrive / SharePoint.'),
    ('Endpoint protection installed', 'SentinelOne', 'require', 'critical', 'Every endpoint must run the EDR agent.'),
    ('Backup agent installed on servers', 'Veeam', 'require', 'high', ''),
]

CONTACT_NOTES = [
    ('Prefers a phone call over e-mail for anything urgent. Best reached before 10am.', False),
    ('Approves purchases up to $2,500 without a second sign-off.', False),
]
CONTACT_RATINGS = [
    (5, 'Quick to respond and had the details ready.'),
    (4, 'Helpful; needed a reminder to confirm the change window.'),
]

DIAGRAM_ANNOTATIONS = [
    ('Second ISP link is not drawn yet; add it after the circuit goes live.', 'issue', 120, 80, False),
    ('Core switch replaced last quarter; model on the diagram is current.', 'note', 340, 210, True),
    ('Consider splitting guest Wi-Fi onto its own VLAN.', 'suggestion', 520, 300, False),
]


def seed(ctx):
    owner = ctx.msp
    _status_pages(ctx)
    for i, org in enumerate(ctx.customers[:3]):
        _security(ctx, owner or org, org, i)
        _announcements(ctx, org)
        _assets(ctx, org)
        _links(ctx, org)
    _security_shared(ctx, owner or ctx.customer(0), ctx.customer(0))
    _status_phrases(ctx)


def _ago(ctx, **kw):
    return ctx.now - timedelta(**kw)


def _hosts(org):
    from assets.models import Asset
    names = list(Asset.objects.filter(organization=org).order_by('pk').values_list('name', flat=True)[:3])
    fallback = [f'{org.slug}-ws-014', f'{org.slug}-ws-022', f'{org.slug}-fw-01']
    return names + fallback[len(names):]


# --- Status pages ----------------------------------------------------------

def _status_pages(ctx):
    from monitoring.models import WebsiteMonitor
    from statuspage.models import (IncidentUpdate, MaintenanceWindow, StatusPage,
                                   StatusPageIncident, StatusPageService)
    with_monitors = [o for o in ctx.customers if WebsiteMonitor.objects.filter(organization=o).exists()]
    orgs = (with_monitors + [o for o in ctx.customers if o not in with_monitors])[:2]
    for spec, org in zip(STATUS_PAGES, orgs):
        page = StatusPage.objects.filter(organization=org, title=spec['title']).first()
        if page is None:
            page = StatusPage.objects.create(
                organization=org, title=spec['title'], intro=spec['intro'], visibility=spec['visibility'],
                is_enabled=True, show_uptime=True, created_by=ctx.admin)
            ctx.created('statuspage.StatusPage')

        monitors = WebsiteMonitor.objects.filter(organization=org).order_by('pk')[:3]
        for n, monitor in enumerate(monitors):
            if not StatusPageService.objects.filter(page=page, monitor=monitor).exists():
                name, desc = PAGE_SERVICES[n]
                StatusPageService.objects.create(page=page, monitor=monitor, display_name=name,
                                                 description=desc, sort_order=n * 10)
                ctx.created('statuspage.StatusPageService')
        services = list(page.services.all())

        for title, start_days, hours, body in spec['maintenance']:
            if MaintenanceWindow.objects.filter(page=page, title=title).exists():
                continue
            starts = (ctx.now + timedelta(days=start_days)).replace(hour=7, minute=0, second=0, microsecond=0)
            window = MaintenanceWindow.objects.create(
                page=page, title=title, body=body, starts_at=starts,
                ends_at=starts + timedelta(hours=hours), created_by=ctx.admin)
            if services:
                window.services.add(services[0])
            ctx.created('statuspage.MaintenanceWindow')

        for inc in spec['incidents']:
            if StatusPageIncident.objects.filter(page=page, title=inc['title']).exists():
                continue
            started = _ago(ctx, days=inc['started_days_ago'], hours=inc.get('started_hours_ago', 0))
            resolved = started + timedelta(hours=inc['duration_hours']) if inc['duration_hours'] else None
            incident = StatusPageIncident.objects.create(
                page=page, title=inc['title'], started_at=started, resolved_at=resolved,
                root_cause=inc['root_cause'], created_by=ctx.admin)
            if services:
                incident.services.add(services[-1])
            ctx.created('statuspage.StatusPageIncident')
            for stage, minutes, body in inc['updates']:
                update = IncidentUpdate.objects.create(
                    incident=incident, stage=stage, body=body, posted_by=ctx.techs[minutes % len(ctx.techs)])
                IncidentUpdate.objects.filter(pk=update.pk).update(posted_at=started + timedelta(minutes=minutes))
                ctx.created('statuspage.IncidentUpdate')


# --- Security --------------------------------------------------------------

def _security(ctx, owner, client, i):
    from security_alerts.models import SecurityAlert, SecurityIncident, SecurityIncidentEvent
    hosts = _hosts(client)
    # Each customer gets the alert set, offset a little so the lists interleave.
    shift = i * 37
    alerts = {}
    for ext, sev, status, minutes, title, desc, host, source in ALERTS:
        ext_id = f'{ext}-{client.slug}'
        alert = SecurityAlert.objects.filter(organization=owner, client_org=client, external_id=ext_id).first()
        if alert is None:
            seen = _ago(ctx, minutes=minutes + shift)
            alert = SecurityAlert.objects.create(
                organization=owner, client_org=client, external_id=ext_id, severity=sev, title=title,
                description=desc, asset_hint=hosts[host], status=status,
                raw_payload={'source': source, 'sample': True, 'device': hosts[host], 'id': ext_id},
                acknowledged_by=ctx.techs[i % len(ctx.techs)] if status != 'new' else None,
                acknowledged_at=seen + timedelta(minutes=8) if status != 'new' else None,
                resolved_at=seen + timedelta(hours=26) if status == 'resolved' else None)
            SecurityAlert.objects.filter(pk=alert.pk).update(seen_at=seen)
            ctx.created('security_alerts.SecurityAlert')
        alerts[ext] = alert

    for spec in INCIDENTS:
        if SecurityIncident.objects.filter(organization=owner, client_org=client, title=spec['title']).exists():
            continue
        opened = _ago(ctx, minutes=spec['opened_minutes_ago'] + shift)
        stamp = {f'{k}_at': opened + timedelta(minutes=spec[k])
                 for k in ('acknowledged', 'contained', 'resolved') if k in spec}
        if spec['status'] != 'open' and 'acknowledged_at' not in stamp:
            stamp['acknowledged_at'] = opened + timedelta(minutes=9)
        incident = SecurityIncident.objects.create(
            organization=owner, client_org=client, title=spec['title'], description=spec['description'],
            severity=spec['severity'], status=spec['status'], asset_hint=hosts[spec['host']],
            assigned_to=ctx.techs[(i + 1) % len(ctx.techs)], created_by=ctx.admin, **stamp)
        SecurityIncident.objects.filter(pk=incident.pk).update(opened_at=opened)
        incident.alerts.add(*[alerts[e] for e in spec['alerts']])
        ctx.created('security_alerts.SecurityIncident')
        for kind, minutes, message in spec['events']:
            event = SecurityIncidentEvent.objects.create(
                incident=incident, kind=kind, message=message,
                actor=None if kind in ('opened', 'alert_added') else ctx.techs[(i + 1) % len(ctx.techs)],
                alert=alerts[spec['alerts'][-1]] if kind == 'alert_added' else None)
            SecurityIncidentEvent.objects.filter(pk=event.pk).update(occurred_at=opened + timedelta(minutes=minutes))
            ctx.created('security_alerts.SecurityIncidentEvent')


def _security_shared(ctx, owner, client):
    """Rules, SLA targets and playbooks: one set for the tenant that owns the alerts."""
    from security_alerts.models import (RemediationPlaybook, RemediationPlaybookStep,
                                        SecurityAlertRule, SecurityIncidentSLAPolicy)
    for spec in ALERT_RULES:
        if not SecurityAlertRule.objects.filter(organization=owner, name=spec['name']).exists():
            SecurityAlertRule.objects.create(organization=owner, ticket_assignee=ctx.techs[-1], **spec)
            ctx.created('security_alerts.SecurityAlertRule')

    for severity, pinned, ack, contain, resolve in SLA_POLICIES:
        scope = client if pinned else None
        if SecurityIncidentSLAPolicy.objects.filter(organization=owner, client_org=scope, severity=severity).exists():
            continue
        SecurityIncidentSLAPolicy.objects.create(
            organization=owner, client_org=scope, severity=severity, acknowledge_minutes=ack,
            contain_minutes=contain, resolve_minutes=resolve,
            notes=f'Tighter targets agreed in the {client.name} security addendum.' if pinned else '')
        ctx.created('security_alerts.SecurityIncidentSLAPolicy')

    for spec in PLAYBOOKS:
        if RemediationPlaybook.objects.filter(organization=owner, name=spec['name']).exists():
            continue
        playbook = RemediationPlaybook.objects.create(
            organization=owner, name=spec['name'], description=spec['description'], priority=spec['priority'],
            match_severity_min=spec['match_severity_min'], notes=spec['notes'], created_by=ctx.admin)
        ctx.created('security_alerts.RemediationPlaybook')
        for order, action, config in spec['steps']:
            RemediationPlaybookStep.objects.create(playbook=playbook, order=order, action=action, config=config)
            ctx.created('security_alerts.RemediationPlaybookStep')


# --- Portal ----------------------------------------------------------------

def _announcements(ctx, org):
    from portal.models import PortalAnnouncement
    for title, severity, days, dismissable, body in ANNOUNCEMENTS:
        if PortalAnnouncement.objects.filter(organization=org, title=title).exists():
            continue
        PortalAnnouncement.objects.create(
            organization=org, title=title, body=body, severity=severity, is_dismissable=dismissable,
            expires_at=ctx.now + timedelta(days=days), created_by=ctx.admin)
        ctx.created('portal.PortalAnnouncement')


def _status_phrases(ctx):
    """Only rows that restate the default mapping for statuses whose default
    never varies by ticket (terminal, or waiting on a vendor / third party).
    TicketStatus is global, so any other phrase would change what every
    customer's portal says."""
    from django.db.models import Q
    from portal.models import PortalStatusPhrase
    from portal.progress import default_phrase_for_status
    from psa.models import TicketStatus
    fixed = Q(is_terminal=True) | Q(pauses_sla=True, slug__icontains='vendor') | Q(pauses_sla=True, slug__icontains='third')
    for status in TicketStatus.objects.filter(fixed, portal_phrase__isnull=True):
        PortalStatusPhrase.objects.create(status=status, phrase=default_phrase_for_status(status))
        ctx.created('portal.PortalStatusPhrase')


# --- Assets, contacts, links ----------------------------------------------

def _rel(ctx, org, src, src_id, tgt, tgt_id, kind, notes=''):
    from assets.models import Relationship
    key = dict(source_type=src, source_id=src_id, target_type=tgt, target_id=tgt_id, relation_type=kind)
    if not Relationship.objects.filter(**key).exists():
        Relationship.objects.create(organization=org, notes=notes, **key)
        ctx.created('assets.Relationship')


def _assets(ctx, org):
    from assets.models import (Asset, AssetBaseline, AssetGroup, Contact, ContactNote,
                               ContactRating, Service, SoftwarePolicy, Vulnerability)
    for name, criticality, status, desc in BUSINESS_SERVICES:
        if not Service.objects.filter(organization=org, name=name).exists():
            Service.objects.create(organization=org, name=name, description=desc, criticality=criticality,
                                   status=status, owner=ctx.techs[len(name) % len(ctx.techs)],
                                   last_status_change=_ago(ctx, days=len(desc) % 20))
            ctx.created('assets.Service')
    for name, desc, criteria in ASSET_GROUPS:
        if not AssetGroup.objects.filter(organization=org, name=name).exists():
            AssetGroup.objects.create(organization=org, name=name, description=desc, criteria=criteria)
            ctx.created('assets.AssetGroup')
    for cve, title, severity, cvss, pattern, fixed, days in VULNERABILITIES:
        if not Vulnerability.objects.filter(organization=org, cve_id=cve).exists():
            Vulnerability.objects.create(
                organization=org, cve_id=cve, title=title, severity=severity, cvss_score=cvss,
                affected_pattern=pattern, fixed_version=fixed, notes=VULN_NOTE,
                description=f'{title}. Patch to {fixed} or later. {VULN_NOTE}',
                published_at=(ctx.now - timedelta(days=days)).date())
            ctx.created('assets.Vulnerability')
    for name, pattern, action, severity, notes in SOFTWARE_POLICIES:
        if not SoftwarePolicy.objects.filter(organization=org, name=name).exists():
            SoftwarePolicy.objects.create(organization=org, name=name, pattern=pattern, action=action,
                                          severity=severity, notes=notes)
            ctx.created('assets.SoftwarePolicy')

    assets = list(Asset.objects.filter(organization=org).order_by('pk')[:6])
    contacts = list(Contact.objects.filter(organization=org).order_by('pk')[:3])

    # Asset relationships: chain the first few assets, servers depend on network gear.
    for a, b in zip(assets, assets[1:4]):
        _rel(ctx, org, 'asset', a.pk, 'asset', b.pk, 'depends' if b.asset_type in
             ('network', 'switch', 'firewall', 'router') else 'related')
    for contact, asset in zip(contacts, assets):
        _rel(ctx, org, 'contact', contact.pk, 'asset', asset.pk, 'related', 'Primary user / owner.')
    services = list(Service.objects.filter(organization=org).order_by('name'))
    for svc, asset in zip(services, assets):
        _rel(ctx, org, 'service', svc.pk, 'asset', asset.pk, 'depends')

    for asset in assets[:2]:
        if not AssetBaseline.objects.filter(asset=asset).exists():
            baseline = asset.capture_baseline(label='Post-onboarding baseline', user=ctx.admin)
            AssetBaseline.objects.filter(pk=baseline.pk).update(created_at=_ago(ctx, days=45))
            ctx.created('assets.AssetBaseline')

    for n, contact in enumerate(contacts[:2]):
        body, private = CONTACT_NOTES[n]
        if not ContactNote.objects.filter(contact=contact, body=body).exists():
            ContactNote.objects.create(contact=contact, body=body, is_private=private,
                                       author=ctx.techs[n % len(ctx.techs)])
            ctx.created('assets.ContactNote')
        for m, (rating, feedback) in enumerate(CONTACT_RATINGS):
            if not ContactRating.objects.filter(contact=contact, feedback=feedback).exists():
                ContactRating.objects.create(contact=contact, rating=rating, feedback=feedback,
                                             rated_by=ctx.techs[(n + m) % len(ctx.techs)])
                ctx.created('assets.ContactRating')


def _links(ctx, org):
    """Link existing passwords, documents and diagrams; never creates parents."""
    from django.contrib.contenttypes.models import ContentType
    from assets.models import Asset
    from core.models import Relation
    from docs.models import Diagram, DiagramAnnotation, Document
    from vault.models import Password, PasswordRelation

    assets = list(Asset.objects.filter(organization=org).order_by('pk')[:3])
    docs = list(Document.objects.filter(organization=org).order_by('pk')[:3])
    passwords = list(Password.objects.filter(organization=org).order_by('pk')[:3])

    for pwd, asset in zip(passwords, assets):
        if not PasswordRelation.objects.filter(password=pwd, relation_type='asset', relation_id=asset.pk).exists():
            PasswordRelation.objects.create(password=pwd, relation_type='asset', relation_id=asset.pk)
            ctx.created('vault.PasswordRelation')
    for pwd, doc in zip(passwords, docs):
        if not PasswordRelation.objects.filter(password=pwd, relation_type='document', relation_id=doc.pk).exists():
            PasswordRelation.objects.create(password=pwd, relation_type='document', relation_id=doc.pk)
            ctx.created('vault.PasswordRelation')

    ct = ContentType.objects.get_for_model
    pairs = [(a, d, 'documented_by') for a, d in zip(assets, docs)]
    pairs += [(a, p, 'credentials') for a, p in zip(assets, passwords)]
    for src, tgt, kind in pairs:
        key = dict(organization=org, relation_type=kind, source_content_type=ct(src), source_object_id=src.pk,
                   target_content_type=ct(tgt), target_object_id=tgt.pk)
        if not Relation.objects.filter(**key).exists():
            Relation.objects.create(**key)
            ctx.created('core.Relation')

    diagram = Diagram.objects.filter(organization=org).order_by('pk').first()
    if diagram is not None:
        for n, (text, kind, x, y, resolved) in enumerate(DIAGRAM_ANNOTATIONS):
            if not DiagramAnnotation.objects.filter(diagram=diagram, text=text).exists():
                DiagramAnnotation.objects.create(diagram=diagram, text=text, annotation_type=kind, position_x=x,
                                                 position_y=y, is_resolved=resolved,
                                                 created_by=ctx.techs[n % len(ctx.techs)])
                ctx.created('docs.DiagramAnnotation')
