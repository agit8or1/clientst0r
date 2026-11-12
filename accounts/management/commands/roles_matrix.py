"""Write docs/ROLES_AND_ACCESS.md's generated sections from the permission
registry and the built-in role definitions, so the documented matrix always
matches the code.

    manage.py roles_matrix            rewrite the generated block in place
    manage.py roles_matrix --check    exit 1 if the file is out of date
    manage.py roles_matrix --stdout   print the generated block
"""
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

BEGIN = '<!-- BEGIN GENERATED: manage.py roles_matrix -->'
END = '<!-- END GENERATED: manage.py roles_matrix -->'


def generate():
    from accounts import permission_registry as reg
    from accounts.role_seeds import definitions
    defs = definitions()
    internal = [d for d in defs if d.audience == 'internal']
    customer = [d for d in defs if d.audience == 'customer']
    out = []
    w = out.append

    def matrix(title, roles):
        w(f'### {title}\n')
        w('| Permission | ' + ' | '.join(d.spec_name or d.name for d in roles) + ' |')
        w('|---|' + '---|' * len(roles))
        for mkey, label, _desc, perms in reg.by_module():
            rows = [p for p in perms if any(d.flags.get(p.key) for d in roles)]
            if not rows:
                continue
            w(f'| **{label}** |' + ' |' * len(roles))
            for p in rows:
                w(f'| `{p.key}` | ' + ' | '.join('✔' if d.flags.get(p.key) else '' for d in roles) + ' |')
        w('')

    w('## Default role matrix\n')
    w('Generated from `accounts/role_seeds.py`. A blank cell means the role does not hold the permission. '
      'Roles adopted from earlier releases (Owner, RMM L1/L2/L3) keep the permissions they already had; the '
      'columns show their built-in definition.\n')
    matrix('Internal roles', internal)
    matrix('Customer roles and add-ons', customer)

    w('## Built-in role mapping\n')
    w('| Requirement name | Template in the product | Key | Notes |')
    w('|---|---|---|---|')
    for d in defs:
        note = 'adopted existing template' if d.adopt else 'new template'
        if d.rmm_tier:
            note += f', RMM tier {d.rmm_tier}'
        w(f'| {d.spec_name or d.name} | {d.name} | `{d.key}` | {note} |')
    w('')

    w('## Permission catalog\n')
    w('Sensitivity: `critical` permissions make a role privileged (assigning it needs `org_manage_privileged`). '
      '"Customer" = a customer role may hold it. "Staff only" = never effective for a customer user. Status '
      '`pending` = defined, enforcement being wired up; `unimplemented` = the feature does not exist yet.\n')
    for mkey, label, desc, perms in reg.by_module():
        w(f'### {label}\n')
        w(f'{desc}\n')
        w('| Key | Action | Sensitivity | Customer | Status | Description |')
        w('|---|---|---|---|---|---|')
        for p in perms:
            cust = 'yes' if p.customer_assignable else ('staff only' if p.staff_only else 'no')
            w(f'| `{p.key}` | {p.action_label} | {p.sensitivity} | {cust} | {p.status} | {p.description} |')
        w('')
    w('## Module coverage\n')
    w('| Application | Governed by |')
    w('|---|---|')
    for app, how in reg.MODULE_COVERAGE.items():
        w(f'| `{app}` | {how} |')
    w('')
    return '\n'.join(out)


def doc_path():
    return Path(settings.BASE_DIR) / 'docs' / 'ROLES_AND_ACCESS.md'


class Command(BaseCommand):
    help = 'Regenerate the role / permission matrix in docs/ROLES_AND_ACCESS.md.'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true')
        parser.add_argument('--stdout', action='store_true')

    def handle(self, *args, **opts):
        block = f'{BEGIN}\n{generate()}\n{END}'
        if opts['stdout']:
            self.stdout.write(block)
            return
        path = doc_path()
        text = path.read_text() if path.exists() else f'# Roles and access\n\n{BEGIN}\n{END}\n'
        if BEGIN not in text or END not in text:
            text = text.rstrip() + f'\n\n{BEGIN}\n{END}\n'
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        new = head + block + tail
        if opts['check']:
            if new != text:
                self.stderr.write('docs/ROLES_AND_ACCESS.md is out of date: run manage.py roles_matrix')
                sys.exit(1)
            self.stdout.write('up to date')
            return
        path.write_text(new)
        self.stdout.write(self.style.SUCCESS(f'Wrote {path}'))
