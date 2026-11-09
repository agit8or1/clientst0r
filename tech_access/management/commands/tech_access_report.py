"""
Report how existing roles map onto technician access, without changing
anything.

Technician access is never inferred from Django staff/superuser flags,
membership roles (owner/admin/editor) or role templates. This lists what an
administrator should look at when choosing presets:

  * technicians with no assignment (they have no AI/RMM capabilities);
  * role templates that still set the older psa_ai_* flags, which no longer
    grant anything — with the preset that would come closest;
  * superusers and membership admins/owners, who are NOT L3 by default;
  * customer users who are members somewhere (outside technician access);
  * built-in presets that differ from what this release ships.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Membership, RoleTemplate
from tech_access.models import AccessAssignment
from tech_access.resolver import is_technician
from tech_access.services import seed_presets

OLD_FLAGS = ['psa_ai_view', 'psa_ai_send_low_risk', 'psa_ai_send_high_risk', 'psa_ai_approve_reply',
             'psa_ai_apply_low_risk', 'psa_ai_apply_high_risk', 'psa_ai_approve_action', 'psa_ai_run_script',
             'psa_ai_create_workflow', 'psa_ai_billing', 'psa_ai_admin', 'psa_ai_request_triage']


def closest_preset(template):
    flags = {f for f in OLD_FLAGS if getattr(template, f, False)}
    if flags & {'psa_ai_approve_reply', 'psa_ai_approve_action', 'psa_ai_apply_high_risk', 'psa_ai_send_high_risk'}:
        return 'L3 (review — approval flags have no direct equivalent)'
    if flags & {'psa_ai_send_low_risk', 'psa_ai_apply_low_risk', 'psa_ai_create_workflow'}:
        return 'L2'
    if flags & {'psa_ai_view', 'psa_ai_request_triage'}:
        return 'L1'
    return 'none'


def build_report():
    User = get_user_model()
    out = {'unassigned': [], 'legacy_roles': [], 'privileged_not_l3': [], 'customer_users': 0,
           'presets': seed_presets(), 'ambiguous': []}
    assigned = set(AccessAssignment.objects.live().exclude(user=None).values_list('user_id', flat=True))
    assigned |= set(AccessAssignment.objects.live().exclude(group=None).values_list('group__members', flat=True))
    for u in User.objects.filter(is_active=True).select_related('profile').order_by('username'):
        if not is_technician(u):
            if Membership.objects.filter(user=u, is_active=True).exists():
                out['customer_users'] += 1
            continue
        if u.pk not in assigned:
            out['unassigned'].append(u.username)
        if u.is_superuser or Membership.objects.filter(user=u, is_active=True, role__in=['owner', 'admin']).exists():
            out['privileged_not_l3'].append(u.username)
    for t in RoleTemplate.objects.order_by('name'):
        set_flags = [f for f in OLD_FLAGS if getattr(t, f, False)]
        if set_flags:
            row = {'template': t.name, 'system': t.is_system_template, 'flags': set_flags,
                   'closest': closest_preset(t), 'users': t.staff_users.count() + t.memberships.count()}
            out['legacy_roles'].append(row)
            if row['closest'].startswith('L3') or (not t.is_system_template and row['users']):
                out['ambiguous'].append(row)
    return out


class Command(BaseCommand):
    help = 'Report how existing roles map onto technician-access presets (read-only).'

    def handle(self, *args, **opts):
        r = build_report()
        w = self.stdout.write
        w('Built-in presets: ' + ', '.join(f'{k} {v}' for k, v in r['presets'].items()))
        w(f'\nTechnicians without any assignment ({len(r["unassigned"])}): no AI or RMM capabilities until assigned.')
        for name in r['unassigned']:
            w(f'  - {name}')
        w(f'\nSuperusers / owners / admins ({len(r["privileged_not_l3"])}): NOT given L3 automatically.')
        for name in r['privileged_not_l3']:
            w(f'  - {name}')
        w(f'\nRole templates with older psa_ai_* flags ({len(r["legacy_roles"])}): kept as-is; they grant no AI capability now.')
        for row in r['legacy_roles']:
            w(f'  - {row["template"]}{" (system)" if row["system"] else ""}: {len(row["flags"])} flag(s), '
              f'{row["users"]} user(s); closest preset {row["closest"]}')
        if r['ambiguous']:
            w(self.style.WARNING(f'\nAmbiguous mappings to review by hand ({len(r["ambiguous"])}):'))
            for row in r['ambiguous']:
                w(f'  - {row["template"]}: {", ".join(row["flags"])}')
        w(f'\nCustomer portal users with memberships: {r["customer_users"]} (outside technician access).')
