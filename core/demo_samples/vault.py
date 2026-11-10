"""Sample data group: vault (v3.17.657). See core/demo_samples/__init__.py.

A few credentials on the first two demo customers that show the notes card,
encrypted secure notes and a live two-factor code. Every secret goes through
the model's own setters (set_password / set_secure_notes / set_otp_secret),
so it is encrypted exactly like an entry typed into the form. Passwords and
TOTP secrets are random for each install; nothing is a real credential.
Keyed by (customer, title); existing entries are never touched.
"""
import secrets
import string

ENTRIES = [
    {
        'title': 'Microsoft 365 global admin (break-glass)',
        'password_type': 'website', 'username': 'breakglass@{domain}',
        'url': 'https://admin.microsoft.com/', 'otp_issuer': 'Microsoft',
        'notes': 'Emergency-only global administrator. Excluded from conditional access. '
                 'Sign-ins alert the support desk; record every use on a ticket.',
        'secure_notes': 'Recovery codes (single use):\n{codes}\n\n'
                        'Stored copy: sealed envelope in the office safe, shelf 2.',
    },
    {
        'title': 'Domain registrar account',
        'password_type': 'website', 'username': 'it@{domain}',
        'url': 'https://registrar.example.com/login', 'otp_issuer': 'Registrar',
        'notes': 'Holds {domain} and the two typo domains. Auto-renew is on; renewal notices go '
                 'to the shared IT mailbox.',
        'secure_notes': 'Account PIN for phone support: {pin}\nSecurity question (first car): '
                        'blue estate\nTransfer lock: enabled — unlock needs the PIN.',
    },
    {
        'title': 'Firewall admin portal',
        'password_type': 'network_device', 'username': 'msp-admin',
        'url': 'https://fw-01.{domain}:8443/', 'otp_issuer': 'FortiGate',
        'notes': 'Reachable from the management VLAN and the MSP VPN only. Config backups are '
                 'taken after every change.',
        'secure_notes': 'Console cable password (local, if HTTPS is down): {console}\n'
                        'HA heartbeat key is in the change ticket that built the pair.',
    },
    {
        'title': 'Accounting software administrator',
        'password_type': 'website', 'username': 'finance.admin@{domain}',
        'url': 'https://accounts.example.com/', 'otp_issuer': 'Accounts',
        'notes': 'Owned by the finance manager; the MSP holds a copy for licence and user '
                 'administration only.',
        'secure_notes': '',
    },
]


def _password(n=20):
    alphabet = string.ascii_letters + string.digits + '!#%*+-=?@_'
    return ''.join(secrets.choice(alphabet) for _ in range(n))


def _domain(org):
    return f'{org.slug.replace("demo-", "")}.example.com'


def seed(ctx):
    import pyotp
    from vault.models import Password
    from . import has_webhook
    for org in ctx.customers[:2]:
        if has_webhook(org, 'password.created'):
            ctx.out.write(f'  vault: skipped {org.slug} (password.created webhook)')
            continue
        domain = _domain(org)
        for spec in ENTRIES:
            if Password.objects.filter(organization=org, title=spec['title']).exists():
                continue
            fill = {
                'domain': domain,
                'codes': '\n'.join(f'{secrets.randbelow(10 ** 4):04d}-{secrets.randbelow(10 ** 4):04d}'
                                   for _ in range(5)),
                'pin': f'{secrets.randbelow(10 ** 6):06d}',
                'console': _password(16),
            }
            pw = Password(
                organization=org, title=spec['title'], password_type=spec['password_type'],
                username=spec['username'].format(**fill), url=spec['url'].format(**fill),
                notes=spec['notes'].format(**fill), otp_issuer=spec['otp_issuer'],
                created_by=ctx.admin, last_modified_by=ctx.admin,
            )
            pw.set_password(_password())
            pw.set_secure_notes(spec['secure_notes'].format(**fill))
            pw.set_otp_secret(pyotp.random_base32())
            pw.save()
            ctx.created('vault.Password')
