"""Seed a few invented consultation requests so Administration -> Communications
-> Consultation Requests shows a real list. Isolated demo database only; every
name, company and address is invented (.example domains). Idempotent."""
import os, sys

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from core.models import ConsultRequest

ROWS = [
    dict(name='Rowan Fairweather', email='rowan@fairweather-print.example', company='Fairweather Print Co.',
         phone='555-0142', areas_of_interest='margins,tools',
         description='We run twelve clients on three different tools and cannot see which contracts lose money.',
         best_time='Weekday mornings', heard_from='A conference talk', is_read=False),
    dict(name='Imani Osei', email='imani@osei-dental.example', company='Osei Dental Group',
         phone='', areas_of_interest='security',
         description='Our cyber insurer asked for evidence of MFA and backups.',
         best_time='', heard_from='', is_read=False),
    dict(name='Tomas Brandt', email='tomas@brandt-surveying.example', company='Brandt Surveying',
         phone='555-0177', areas_of_interest='growth,sales',
         description='Looking to take on more small-business clients without hiring.',
         best_time='After 3 pm', heard_from='A colleague', is_read=True),
]

for r in ROWS:
    ConsultRequest.objects.get_or_create(email=r['email'], defaults=r)
print('consult requests:', ConsultRequest.objects.count())
