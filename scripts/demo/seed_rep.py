"""Fill the demo's Reports pages: the built-in report templates, a short report
history (PDF, CSV, a scheduled run and a failed one) and installed software on
the demo RMM devices, so Generate Reports, Report History and Software
Compliance show a working install rather than empty tables.

Isolated demo database only. Idempotent; every name is invented.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone

from core.models import Organization
from integrations.models import RMMConnection, RMMDevice, RMMSoftware
from reports.generators import generate_report
from reports.models import GeneratedReport, ReportTemplate, ScheduledReport

User = get_user_model()
tech = User.objects.get(username='demo.tech')
now = timezone.now()

if 'demo' not in os.environ.get('DJANGO_SETTINGS_MODULE', ''):
    raise SystemExit('Refusing to run outside the demo settings.')

# ---- templates: the eight the product ships ---------------------------------
BUILT_IN = [
    ('Asset Summary Report', 'asset_summary', 'Comprehensive overview of all assets in your organization including counts by type, status, and location.'),
    ('Asset Lifecycle Report', 'asset_lifecycle', 'Track asset age, warranty status, and planned replacements.'),
    ('Password Security Audit', 'password_audit', 'Analyze password age, complexity, and identify accounts that may need attention.'),
    ('Document Usage Report', 'document_usage', 'Track document creation, updates, and access patterns.'),
    ('Monitor Uptime Report', 'monitor_uptime', 'Website and WAN connection uptime statistics and incident history.'),
    ('Expiration Forecast', 'expiration_forecast', 'View upcoming expirations for SSL certificates, domains, and credentials.'),
    ('User Activity Report', 'user_activity', 'Track user logins, actions, and system usage patterns.'),
    ('Organization Metrics', 'organization_metrics', 'High-level metrics and KPIs for your organization.'),
]
templates = {}
for name, rtype, desc in BUILT_IN:
    t, _ = ReportTemplate.objects.get_or_create(
        name=name, report_type=rtype, is_global=True, organization=None,
        defaults={'description': desc, 'query_template': '', 'created_by': tech})
    templates[rtype] = t

# ---- report history ----------------------------------------------------------
org = Organization.objects.get(name='Northwind Logistics')
HISTORY = [
    # (type, format, hours ago, by_scheduled)
    ('organization_metrics', 'pdf', 3, False),
    ('asset_summary', 'csv', 27, False),
    ('expiration_forecast', 'pdf', 51, True),
    ('monitor_uptime', 'json', 120, False),
]
if not GeneratedReport.objects.filter(organization=org).exists():
    sched = ScheduledReport.objects.filter(organization=org).first()
    for rtype, fmt, hours, by_sched in HISTORY:
        t = templates[rtype]
        filename, data = generate_report(t, output_format=fmt, organization=org, parameters={'include_vault': True})
        stamp = now - timedelta(hours=hours)
        g = GeneratedReport(template=t, organization=org, format=fmt, status='completed',
                            generated_by=None if by_sched else tech, scheduled_report=sched if by_sched else None,
                            parameters={'include_vault': True})
        g.file.save(filename, ContentFile(data), save=False)
        g.file_size = len(data); g.completed_at = stamp
        g.save()
        GeneratedReport.objects.filter(pk=g.pk).update(created_at=stamp, completed_at=stamp)
    g = GeneratedReport.objects.create(
        template=templates['user_activity'], organization=org, generated_by=None, format='pdf',
        status='failed', scheduled_report=sched,
        error_message='Not run: this schedule has no owner, and a "user_activity" report needs a person whose access can be checked.')
    GeneratedReport.objects.filter(pk=g.pk).update(created_at=now - timedelta(hours=200))

# ---- installed software on the demo RMM devices ------------------------------
conn = RMMConnection.objects.first()
if conn and not RMMSoftware.objects.exists():
    SOFT = {
        'RDG-SRV01': [('Microsoft SQL Server 2019', '15.0', 'Microsoft'), ('Veeam Backup Agent', '6.1', 'Veeam'),
                      ('SentinelOne Agent', '23.4', 'SentinelOne'), ('TeamViewer', '15.51', 'TeamViewer GmbH')],
        'RDG-OP3-PC': [('Microsoft 365 Apps', '16.0', 'Microsoft'), ('Dropbox', '188.4', 'Dropbox, Inc.'),
                       ('Open Dental', '23.3', 'Open Dental Software')],
    }
    for dev in RMMDevice.objects.filter(device_name__in=SOFT):
        for i, (name, ver, vendor) in enumerate(SOFT[dev.device_name]):
            RMMSoftware.objects.create(organization=dev.organization, connection=dev.connection, device=dev,
                                       external_id=f'{dev.pk}-{i}', name=name, version=ver, vendor=vendor)
print('Reports demo data ready:', ReportTemplate.objects.filter(is_global=True).count(), 'global templates,',
      GeneratedReport.objects.count(), 'generated reports,', RMMSoftware.objects.count(), 'software rows.')
