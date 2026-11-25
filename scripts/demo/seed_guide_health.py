"""Pulse checks for the Client Health / Pulse Checks guides: turns the module on in
the demo, adds two checks with three rounds of invented answers and a few
opt-outs, then recomputes the health snapshots so the Satisfaction dimension has
data. Isolated demo database only. Idempotent: skips when the checks exist.
Nothing is e-mailed: sends and answers are written as rows.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Organization, SystemSetting
from pulse.models import PulseCheck, PulseOptOut, PulseQuestion, PulseResponse, PulseSend
from health_score import scoring

User = get_user_model()
now = timezone.now()
lead = User.objects.get(username='demo.tech')

ss = SystemSetting.get_settings()
if not ss.pulse_enabled:
    ss.pulse_enabled = True
    ss.save(update_fields=['pulse_enabled'])

if PulseCheck.objects.filter(name='Quarterly service check-in').exists():
    print('  pulse demo data already there')
else:
    check = PulseCheck.objects.create(
        name='Quarterly service check-in', intro='A few quick questions about how we are doing.',
        schedule='quarterly', send_day=5, all_organizations=True, audience='all',
        include_contacts=True, created_by=lead)
    qs = [PulseQuestion.objects.create(pulse_check=check, order=i, kind=k, text=t, required=r)
          for i, (k, t, r) in enumerate([
              ('rating', 'How are we doing overall?', True),
              ('nps', 'How likely are you to recommend us to a colleague?', True),
              ('text', 'Anything we could do better?', False)])]
    onboarding = PulseCheck.objects.create(
        name='New site follow-up', intro='We finished the work at your new site.',
        schedule='none', audience='roles', audience_roles=['owners', 'admins'],
        all_organizations=False, created_by=lead)
    onboarding.organizations.set(Organization.objects.filter(name__in=['Harbor Point Credit Union', 'Ridgeline Dental Group']))
    oq = PulseQuestion.objects.create(pulse_check=onboarding, order=0, kind='rating',
                                      text='How did the move go?', required=True)

    # (days ago, organization, person, rating, nps, comment)
    ROUNDS = [
        (125, 'Q3', [
            ('Northwind Logistics', 'Dana Whitfield', 4, 9, 'Quick on the phone.'),
            ('Northwind Logistics', 'Marcus Oyelaran', 4, 8, ''),
            ('Ridgeline Dental Group', 'Priya Nandakumar', 5, 10, 'Great with our front desk.'),
            ('Harbor Point Credit Union', 'Tomas Wieland', 3, 6, 'Slow to close tickets last month.'),
            ('Harbor Point Credit Union', 'Elena Brandt', None, None, None)]),
        (35, 'Q4', [
            ('Northwind Logistics', 'Dana Whitfield', 5, 10, 'Much better since the new patch window.'),
            ('Northwind Logistics', 'Marcus Oyelaran', 4, 9, ''),
            ('Ridgeline Dental Group', 'Priya Nandakumar', 4, 9, ''),
            ('Harbor Point Credit Union', 'Tomas Wieland', 4, 7, 'Better.'),
            ('Harbor Point Credit Union', 'Elena Brandt', 3, 6, 'Reports arrive late.')]),
    ]
    for days, quarter, rows in ROUNDS:
        when = now - timedelta(days=days)
        send = PulseSend.objects.create(
            pulse_check=check, trigger='schedule', period_key=f'2026-{quarter}', sent_by=None,
            questions=check.question_snapshot(), intro=check.intro,
            expires_at=when + timedelta(days=14), recipient_count=len(rows),
            emailed_count=len(rows), opted_out_count=0)
        PulseSend.objects.filter(pk=send.pk).update(created_at=when)
        for org_name, person, rating, nps, comment in rows:
            org = Organization.objects.get(name=org_name)
            email = person.lower().split()[0] + '@' + org_name.lower().split()[0] + '.example'
            answered = rating is not None
            answers = {str(qs[0].pk): rating, str(qs[1].pk): nps, str(qs[2].pk): comment} if answered else {}
            if answered and not comment:
                answers.pop(str(qs[2].pk))
            PulseResponse.objects.create(
                send=send, organization=org, email=email, name=person, email_status='sent',
                answers=answers, responded_at=(when + timedelta(days=2)) if answered else None,
                responded_via='link' if answered else '')

    # An open round, five days old, half answered.
    when = now - timedelta(days=5)
    send = PulseSend.objects.create(
        pulse_check=onboarding, trigger='manual', sent_by=lead, questions=onboarding.question_snapshot(),
        intro=onboarding.intro, expires_at=when + timedelta(days=14), recipient_count=3,
        emailed_count=3, opted_out_count=1)
    PulseSend.objects.filter(pk=send.pk).update(created_at=when)
    for org_name, person, rating in [('Harbor Point Credit Union', 'Tomas Wieland', 4),
                                     ('Ridgeline Dental Group', 'Priya Nandakumar', None),
                                     ('Ridgeline Dental Group', 'Anika Holm', 5)]:
        org = Organization.objects.get(name=org_name)
        PulseResponse.objects.create(
            send=send, organization=org, email=person.lower().split()[0] + '@' + org_name.lower().split()[0] + '.example',
            name=person, email_status='sent', answers={str(oq.pk): rating} if rating else {},
            responded_at=(when + timedelta(days=1)) if rating else None, responded_via='link' if rating else '')

    PulseOptOut.opt_out('elena@harbor.example', 'email link')
    PulseOptOut.opt_out('yusuf@cascade.example', 'portal')
    PulseOptOut.opt_out('reception@ridgeline.example', 'email link')
    print('  pulse demo data added')

for org in Organization.objects.filter(is_active=True):
    scoring.compute_and_save(org)
print('  health snapshots recomputed')
