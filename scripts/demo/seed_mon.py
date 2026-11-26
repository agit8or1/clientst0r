"""Fill the monitoring pages of the demo: Expirations rows and WAN connections
that are monitored, so Monitoring -> WAN Connections and Expirations show real
rows. Isolated demo database only; every name is invented and every host is a
`.example` name. Nothing here runs a check or sends a request: the check
results are written as rows, and the demo has no scheduler.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.utils import timezone
from core.models import Organization
from locations.models import WAN
from monitoring.models import Expiration

now = timezone.now()
org = Organization.objects.get(name='Northwind Logistics')

ROWS = [
    # name, type, days from now, warning days, auto-renew, cost, notes
    ('northwind.example', 'domain', 41, 60, True, '18.00', 'Registered with the customer\'s registrar account.'),
    ('wms.northwind.example certificate', 'ssl_cert', 12, 30, False, None, 'Wildcard renewal waits on the customer\'s approval.'),
    ('Dispatch software licence (25 seats)', 'license', 96, 30, False, '1450.00', 'Renewal quote requested.'),
    ('Warehouse firewall warranty', 'warranty', -9, 30, False, None, 'Support contract lapsed; quote pending.'),
    ('Cyber liability policy', 'insurance', 160, 45, False, '3200.00', ''),
    ('Forklift operator certification', 'certification', 24, 30, False, None, 'Annual refresher booked.'),
]
for name, kind, days, warn, auto, cost, notes in ROWS:
    Expiration.objects.update_or_create(
        organization=org, name=name,
        defaults=dict(expiration_type=kind, expires_at=now + timedelta(days=days),
                      warning_days=warn, auto_renew=auto, renewal_cost=cost, notes=notes))

WANS = {
    'Primary Internet': dict(target='gw1.northwind.example', interval=5, result='up', rtt=14, status='active'),
    'Backup Broadband': dict(target='gw2.northwind.example', interval=5, result='down', rtt=None, status='down'),
}
for wan in WAN.objects.filter(organization=org, name__in=WANS):
    d = WANS[wan.name]
    wan.monitoring_enabled = True
    wan.monitor_target = d['target']
    wan.monitor_interval_minutes = d['interval']
    wan.status = d['status']
    wan.last_checked_at = now - timedelta(minutes=2)
    wan.last_check_result = d['result']
    wan.last_response_time_ms = d['rtt']
    wan.uptime_percentage = 99.94 if d['result'] == 'up' else 97.2
    if d['result'] == 'down':
        wan.alert_state = 'down'
        wan.consecutive_failures = 6
        wan.last_down_at = now - timedelta(minutes=27)
        wan.last_error = 'No answer to ping.'
    wan.save()
print('monitoring demo rows ready')
