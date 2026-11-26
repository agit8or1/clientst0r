"""Two shared dashboards with widgets and a spread of analytics events, so the
Dashboards and Analytics pages of the Reports section show something to read.

Isolated demo database only. Idempotent: a dashboard is matched by name and an
event batch is only added when the demo has no events yet. Everything is invented.
"""
import os, random, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Organization
from reports.models import AnalyticsEvent, Dashboard, DashboardWidget
from reports.widget_sources import DATA_SOURCE_CHOICES

User = get_user_model()
random.seed(47)
now = timezone.now()
lead = User.objects.get(username='demo.tech')
org = Organization.objects.get(name='Northwind Logistics')
TYPES = {k: (label, wt) for k, label, wt in DATA_SOURCE_CHOICES}

DASHBOARDS = [
    ('Owner morning view', 'Revenue, queue health and what is at risk, for the first look of the day.', True, [
        'revenue_this_period', 'open_tickets_count', 'overdue_tickets_count', 'unbilled_hours',
        'revenue_trend_30d', 'tickets_by_priority']),
    ('Service desk wall', 'Queue and SLA figures for the service desk.', False, [
        'open_tickets_count', 'avg_resolution_hours', 'tickets_opened_30d', 'sla_breach_trend']),
]
for name, desc, default, sources in DASHBOARDS:
    d, created = Dashboard.objects.get_or_create(
        name=name, organization=org, defaults={'description': desc, 'is_default': default, 'created_by': lead})
    if created:
        for i, ds in enumerate(sources):
            label, wt = TYPES[ds]
            DashboardWidget.objects.create(
                dashboard=d, title=label.rsplit(' (', 1)[0], widget_type=wt, data_source=ds,
                query_params={}, position={'x': i % 4, 'y': i // 4})
    print('  dashboard', name, 'created' if created else 'exists')

if not AnalyticsEvent.objects.exists():
    people = [lead] + list(User.objects.filter(username__in=['demo.ipatel', 'demo.mokafor']))
    names = {
        'user': ['ticket.created', 'asset.viewed', 'document.opened', 'password.revealed'],
        'system': ['backup.completed', 'sync.finished', 'report.generated'],
        'api': ['api.tickets.list', 'api.assets.get'],
        'security': ['login.failed', 'login.succeeded'],
    }
    for n in range(140):
        cat = random.choices(list(names), weights=[6, 3, 3, 1])[0]
        ev = AnalyticsEvent.objects.create(
            event_name=random.choice(names[cat]), event_category=cat,
            user=random.choice(people) if cat != 'system' else None, organization=org)
        AnalyticsEvent.objects.filter(pk=ev.pk).update(
            timestamp=now - timedelta(hours=random.randint(1, 24 * 28)))
    print('  analytics events:', AnalyticsEvent.objects.count())
