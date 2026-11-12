"""
Roles & access migration summary: built-in roles, the explicit mapping that
kept existing access, and assignments needing review.

    manage.py roles_migration_report            print the report
    manage.py roles_migration_report --refresh  re-scan memberships and add
                                                newly found review items
                                                (never changes access)
    manage.py roles_migration_report --json     machine-readable
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Summarize the roles & access migration and list assignments needing review.'

    def add_arguments(self, parser):
        parser.add_argument('--refresh', action='store_true', help='Re-scan and record new review items.')
        parser.add_argument('--json', action='store_true', help='Print JSON.')
        parser.add_argument('--all', action='store_true', help='Include resolved / dismissed items.')

    def handle(self, *args, **opts):
        from django.contrib.auth.models import User
        from core.models import Organization
        from accounts.models import Membership, RoleReviewItem, RoleTemplate, UserProfile
        from accounts.role_migration import EXPLICIT_MAPPING, find_review_items, record_review_items

        added = 0
        if opts['refresh']:
            added = record_review_items(
                RoleReviewItem, find_review_items(Membership, UserProfile, RoleTemplate, Organization, User),
                'roles_migration_report')
        builtins = RoleTemplate.objects.filter(organization__isnull=True).exclude(seed_key='').order_by('name')
        items = RoleReviewItem.objects.select_related('user', 'organization', 'role_template')
        if not opts['all']:
            items = items.filter(status='open')
        data = {
            'builtin_roles': [{'name': r.name, 'key': r.seed_key, 'version': r.seed_version,
                               'customized': r.is_customized, 'audience': r.audience,
                               'users': r.memberships.count() + r.additional_memberships.count()
                               + r.staff_users.count()} for r in builtins],
            'mapping': [{'permission': k, 'derived_from': v, 'why': why} for k, v, why in EXPLICIT_MAPPING],
            'memberships': {'total': Membership.objects.count(),
                            'with_template': Membership.objects.filter(role_template__isnull=False).count(),
                            'simple_role': Membership.objects.filter(role_template__isnull=True).count()},
            'review': [{'id': i.pk, 'reason': i.reason, 'status': i.status,
                        'user': getattr(i.user, 'username', None), 'organization': getattr(i.organization, 'name', None),
                        'role': getattr(i.role_template, 'name', None), 'detail': i.detail} for i in items],
            'review_added_now': added,
        }
        if opts['json']:
            self.stdout.write(json.dumps(data, indent=2))
            return
        w = self.stdout.write
        w('Built-in roles')
        for r in data['builtin_roles']:
            w(f"  {r['name']:<34} key={r['key']:<26} v{r['version']} {r['audience']:<8} users={r['users']}"
              + ('  CUSTOMIZED' if r['customized'] else ''))
        w('\nExplicit mapping used for existing roles (no access removed, nothing inferred from names):')
        for m in data['mapping']:
            w(f"  {m['permission']} <- {m['derived_from']}\n      {m['why']}")
        mem = data['memberships']
        w(f"\nMemberships: {mem['total']} ({mem['with_template']} with a role template, "
          f"{mem['simple_role']} on a simple role)")
        w(f"\nAssignments needing review ({len(data['review'])}"
          + (f", {added} new" if opts['refresh'] else '') + '):')
        for i in data['review']:
            who = ' / '.join(x for x in (i['user'], i['organization'], i['role']) if x)
            w(f"  #{i['id']} [{i['reason']}] {who}\n      {i['detail']}")
        if not data['review']:
            w('  none')
