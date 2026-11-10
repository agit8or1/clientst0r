"""Sample data for modules the other demo seeders leave empty (v3.17.655).

``manage.py seed_module_samples`` builds a ``Context`` and calls ``seed(ctx)``
in each group module listed in ``GROUPS``. Every group is additive and
idempotent: it looks rows up by a natural key (name, number, title) and only
creates what is missing, never edits or deletes existing data, and touches
only the demo organizations below. Nothing here contacts the outside world:
no integration connections, no webhooks, no e-mail (the command swaps in the
dummy mail backend while it runs).
"""
from __future__ import annotations

from dataclasses import dataclass, field

GROUPS = ('psa_extras', 'operations', 'security_customer', 'documents', 'vault', 'assets')

# Customer organizations used for demo data, in order of preference.
CUSTOMER_SLUGS = ('demo-acme', 'demo-globex', 'demo-initech', 'demo', 'acme-corporation')
MSP_SLUG = 'demo-msp'

# Demo technicians (MSP staff who can't sign in).
TECHS = (
    ('Jordan', 'Reyes', 'jordan.reyes@msp.example.com'),
    ('Alex', 'Kim', 'alex.kim@msp.example.com'),
    ('Morgan', 'Shah', 'morgan.shah@msp.example.com'),
)


@dataclass
class Context:
    customers: list          # Organization rows that exist, CUSTOMER_SLUGS order
    msp: object              # the MSP Organization, or None
    admin: object            # a superuser to own rows (created_by etc.)
    techs: list              # admin + demo technicians, all MSP staff
    out: object              # stdout-like
    now: object              # timezone.now() at start
    counts: dict = field(default_factory=dict)

    def created(self, label, n=1):
        """Record that `n` rows of `label` (e.g. 'crm.Lead') were created."""
        if n:
            self.counts[label] = self.counts.get(label, 0) + n

    def customer(self, i=0):
        """The i-th customer organization, wrapping round."""
        return self.customers[i % len(self.customers)] if self.customers else None


def make_techs(msp, customers, out):
    """The demo technicians: staff users with unusable passwords, members of
    the MSP and of each demo customer."""
    from django.contrib.auth import get_user_model
    from accounts.models import Membership, Role, UserProfile, UserType
    User = get_user_model()
    techs = []
    for first, last, email in TECHS:
        username = f'demo.tech.{first}.{last}'.lower()
        user = User.objects.filter(username=username).first()
        if user is None:
            user = User(username=username, first_name=first, last_name=last, email=email)
            user.set_unusable_password()
            user.save()
            out.write(f'  demo technician {username}')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if profile.user_type != UserType.STAFF:
            profile.user_type = UserType.STAFF
            profile.save()
        for org in [msp, *customers]:
            if org is not None:
                Membership.objects.get_or_create(user=user, organization=org,
                                                 defaults={'role': Role.EDITOR, 'is_active': True})
        techs.append(user)
    return techs


def build_context(out):
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from core.models import Organization
    User = get_user_model()
    found = {o.slug: o for o in Organization.objects.filter(slug__in=CUSTOMER_SLUGS + (MSP_SLUG,), is_active=True)}
    customers = [found[s] for s in CUSTOMER_SLUGS if s in found]
    msp = found.get(MSP_SLUG)
    admin = (User.objects.filter(username='admin', is_superuser=True).first()
             or User.objects.filter(is_superuser=True, is_active=True).order_by('pk').first())
    techs = make_techs(msp, customers, out)
    return Context(customers=customers, msp=msp, admin=admin,
                   techs=[u for u in [admin, *techs] if u is not None], out=out, now=timezone.now())


def has_webhook(org, event):
    """True when an active webhook of `org` subscribes to `event`. Groups
    whose saves fire that event (document.created, password.created,
    asset.created) skip such organizations, so seeding never posts to a real
    endpoint."""
    from core.models import Webhook
    return any(event in (events or []) for events in
               Webhook.objects.filter(organization=org, is_active=True).values_list('events', flat=True))
