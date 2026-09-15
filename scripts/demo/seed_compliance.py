"""Enrol demo clients in the compliance frameworks and fill in a believable
spread of attestation state, so the compliance screens show a real programme
in progress rather than an empty checklist.

Isolated demo database only. Every note and evidence link is invented.
"""
import os, random, sys
from datetime import timedelta

sys.path.insert(0, os.environ['DEMO_ROOT']); os.chdir(os.environ['DEMO_ROOT'])
os.environ['DJANGO_SETTINGS_MODULE'] = 'demo_settings_wt'
import django; django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from compliance.models import (
    ComplianceFramework, OrganizationCompliance, OrganizationComplianceItem,
)
from core.models import Organization

User = get_user_model()
random.seed(31)
now = timezone.now()
lead = User.objects.get(username='demo.tech')
priya = User.objects.get(username='demo.ipatel')

NOTES = {
    'compliant': [
        'Verified during the quarterly review; evidence attached.',
        'Enforced by group policy across the in-scope segment.',
        'Confirmed with the vendor and recorded in the runbook.',
        'Covered by the managed agreement and checked monthly.',
    ],
    'partial': [
        'In place for servers; workstation rollout finishes next quarter.',
        'Policy written and approved, technical enforcement still manual.',
        'Applies to the primary site; the depot is scheduled.',
    ],
    'non_compliant': [
        'Gap accepted by the client for now — remediation quoted.',
        'Blocked on a vendor limitation; tracked as a change request.',
    ],
    'not_applicable': [
        'No card data is processed in this environment.',
        'Not applicable: the client outsources this function.',
    ],
}

# Weighted so a programme looks under way rather than perfect or abandoned.
def pick(i, total):
    r = random.random()
    if r < 0.62:  return 'compliant'
    if r < 0.80:  return 'partial'
    if r < 0.88:  return 'non_compliant'
    if r < 0.94:  return 'not_applicable'
    return 'unanswered'

PLAN = [
    ('Harbor Point Credit Union', 'pci-dss-v4', priya, 250),
    ('Harbor Point Credit Union', 'hipaa-security-rule', priya, None),
    ('Ridgeline Dental Group',    'hipaa-security-rule', lead, 120),
]

for org_name, slug, who, recert_days_ago in PLAN:
    org = Organization.objects.filter(name=org_name).first()
    fw = ComplianceFramework.objects.filter(slug=slug).first()
    if not org or not fw:
        print('  skip', org_name, slug, '(missing)'); continue

    oc, _ = OrganizationCompliance.objects.get_or_create(
        organization=org, framework=fw,
        defaults=dict(enrolled_by=who, recertification_interval_days=365,
                      recertification_emails_enabled=True,
                      notify_email='compliance@beaconmanaged.example',
                      notes='Reviewed alongside the quarterly service review.'),
    )
    if recert_days_ago is not None:
        OrganizationCompliance.objects.filter(pk=oc.pk).update(
            last_recertified_at=now - timedelta(days=recert_days_ago))

    items = list(fw.categories.all().prefetch_related('items')) if hasattr(fw, 'categories') else []
    checks = [it for cat in items for it in cat.items.all()]
    for n, check in enumerate(checks):
        status = pick(n, len(checks))
        row, created = OrganizationComplianceItem.objects.get_or_create(
            org_compliance=oc, item=check, defaults={'status': status})
        if not created:
            continue
        if status != 'unanswered':
            OrganizationComplianceItem.objects.filter(pk=row.pk).update(
                status=status,
                notes=random.choice(NOTES.get(status, [''])),
                evidence_link=('https://docs.beaconmanaged.example/evidence/'
                               f'{slug}/{check.pk}') if status == 'compliant' and n % 3 == 0 else '',
                last_reviewed_at=now - timedelta(days=random.randint(3, 90)),
                last_reviewed_by=who,
            )
    done = OrganizationComplianceItem.objects.filter(
        org_compliance=oc).exclude(status='unanswered').count()
    print(f'  {org_name} / {fw.name}: {done}/{len(checks)} answered')

print('enrolments:', OrganizationCompliance.objects.count())
