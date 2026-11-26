"""Synthetic scale dataset for the UX performance work (increment 113.7).

Builds a NEW SQLite database: runs the migrations, then generates a
deterministic (fixed random seed) MSP with many customers, endpoints, tickets
with history, documents, vault entries, contracts and billing charges, plus a
few technicians with access groups. Everything is invented (``.example``
domains, RFC 1918 addresses, placeholder secrets).

    nice -n 10 python scripts/ux/seed_scale.py /var/tmp/clientst0r-scale-60/demo.sqlite3 --profile medium

Profiles (customers / endpoints): small 10/100, medium 60/1,200, large
200/5,000, xl = ``--customers N --endpoints M`` (defaults 500/15,000).
``--with-rmm`` also writes an RMM device row per endpoint on one inactive
connection (no outbound calls are ever made).

Safety: the target must not exist or must be an empty file, must live under
/var/tmp or a Claude scratchpad directory, and must not be the production
database. The settings used are ``scripts/demo/demo_settings.py`` (throwaway
encryption keys, nothing read from the deployment's .env).

The data generator itself (``generate``) works on whatever database the
current Django process is connected to, so a test can run it in a test
database with tiny counts.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import random
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[2]

PROD_DB = pathlib.Path('/home/administrator/db.sqlite3')
ALLOWED_ROOTS = (pathlib.Path('/var/tmp'), pathlib.Path('/tmp/claude-1000'))

# customers, endpoints, tickets (3 years), documents (incl. KB), credentials,
# contacts, invoices - ratios from docs/ux/WORKFLOW_BENCHMARKS.md section 4.
PROFILES = {
    'small': dict(customers=10, endpoints=100, tickets=1000, documents=150, credentials=100, contacts=100,
                  invoices=120),
    'medium': dict(customers=60, endpoints=1200, tickets=15000, documents=900, credentials=600, contacts=600,
                   invoices=720),
    'large': dict(customers=200, endpoints=5000, tickets=60000, documents=3000, credentials=2000,
                  contacts=2000, invoices=2400),
}


class SeedRefused(SystemExit):
    """Raised by the guards; a SystemExit so the command line exits non-zero."""


def check_target(path, allowed_roots=ALLOWED_ROOTS):
    """Return the resolved Path of a database this script may create, or raise
    SeedRefused. Pure (no Django), so it runs before anything is imported."""
    p = pathlib.Path(path).expanduser().resolve()
    if p == PROD_DB.resolve() or 'db.sqlite3' == p.name and p.parent == PROD_DB.parent:
        raise SeedRefused(f'Refusing: {p} is the production database.')
    if not any(p == r or r.resolve() in p.parents for r in allowed_roots):
        roots = ', '.join(str(r) for r in allowed_roots)
        raise SeedRefused(f'Refusing: {p} is not under an allowed location ({roots}).')
    if p.exists():
        if p.is_dir():
            raise SeedRefused(f'Refusing: {p} is a directory.')
        if p.stat().st_size > 0:
            raise SeedRefused(f'Refusing: {p} already exists and is not empty.')
    for sidecar in (p.with_name(p.name + '-wal'), p.with_name(p.name + '-shm')):
        if sidecar.exists() and sidecar.stat().st_size > 0:
            raise SeedRefused(f'Refusing: {sidecar} exists (leftover of another database).')
    return p


def plan(profile=None, customers=None, endpoints=None):
    """Counts to generate. An explicit customers/endpoints pair scales the
    other figures by the profile ratios (about 12 tickets per endpoint)."""
    if profile in PROFILES and customers is None and endpoints is None:
        return dict(PROFILES[profile])
    c = customers or (PROFILES.get(profile) or {}).get('customers') or 500
    e = endpoints or (PROFILES.get(profile) or {}).get('endpoints') or 15000
    return dict(customers=c, endpoints=e, tickets=int(e * 12), documents=c * 15, credentials=c * 10,
                contacts=c * 10, invoices=c * 12)


# ---------------------------------------------------------------------------
# invented vocabulary
# ---------------------------------------------------------------------------

ADJ = ['Alder', 'Birch', 'Cedar', 'Dune', 'Elm', 'Fjord', 'Garnet', 'Harbor', 'Iris', 'Juniper', 'Kestrel',
       'Larch', 'Maple', 'Nectar', 'Opal', 'Pine', 'Quartz', 'Ridge', 'Sable', 'Tidal', 'Umber', 'Vale',
       'Willow', 'Yarrow', 'Zephyr']
NOUN = ['Point', 'Hollow', 'Crossing', 'Meadow', 'Summit', 'Bay', 'Field', 'Grove', 'Landing', 'Works']
KIND = ['Dental', 'Logistics', 'Credit Union', 'Manufacturing', 'Law', 'Clinic', 'Realty', 'Architects',
        'Foods', 'Printing', 'Insurance', 'Veterinary', 'Accounting', 'Marine', 'Schools']
FIRST = ['Avery', 'Blake', 'Casey', 'Drew', 'Emery', 'Finley', 'Gray', 'Harper', 'Indy', 'Jules', 'Kai',
         'Logan', 'Morgan', 'Noel', 'Oakley', 'Parker', 'Quinn', 'Reese', 'Sage', 'Tatum']
LAST = ['Adler', 'Brandt', 'Corvin', 'Dalloway', 'Ellery', 'Farrow', 'Gantry', 'Holloway', 'Ibsen', 'Jarrow',
        'Keller', 'Lindqvist', 'Marlowe', 'Nystrom', 'Okonkwo', 'Prescott', 'Quill', 'Rasmussen', 'Strand',
        'Thorne']
TITLES = ['Office Manager', 'Owner', 'Operations Lead', 'Finance Manager', 'IT Contact', 'Receptionist']
CITIES = [('Columbus', 'OH', '43215'), ('Boise', 'ID', '83702'), ('Portland', 'ME', '04101'),
          ('Tacoma', 'WA', '98402'), ('Austin', 'TX', '78701'), ('Duluth', 'MN', '55802')]
ASSET_KINDS = [  # type, manufacturer, model, hostname prefix, weight
    ('workstation', 'Lenovo', 'ThinkCentre M70q', 'ws', 40), ('laptop', 'Dell', 'Latitude 5440', 'lt', 28),
    ('server', 'Dell', 'PowerEdge R450', 'srv', 4), ('printer', 'HP', 'LaserJet M404', 'prn', 6),
    ('switch', 'Aruba', 'CX 6100', 'sw', 6), ('wireless_ap', 'Ubiquiti', 'U6 Pro', 'ap', 7),
    ('firewall', 'Fortinet', 'FortiGate 60F', 'fw', 2), ('nas', 'Synology', 'DS923+', 'nas', 2),
    ('ups', 'APC', 'Smart-UPS 1500', 'ups', 3), ('phone', 'Yealink', 'T54W', 'ph', 2)]
SUBJECTS = ['Printer offline', 'Cannot sign in to email', 'Slow laptop', 'New hire setup', 'Wi-Fi drops in the back office',
            'Backup job failed overnight', 'Shared drive not mapping', 'VPN will not connect', 'Disk space low',
            'Phone has no dial tone', 'Replace failed monitor', 'Password reset request', 'Software install request',
            'Switch port flapping', 'Firewall rule change', 'Licence renewal', 'Outlook keeps crashing',
            'Scanner does not email', 'Offboard departed employee', 'Monthly patch review']
REPLIES = ['Looking into this now.', 'Restarted the service and confirmed it is working again.',
           'Could you tell us if this is still happening?', 'Replaced the part; please test and confirm.',
           'Scheduled for the next maintenance window.', 'Waiting on the vendor for a firmware fix.',
           'Applied the change and verified from the user side.', 'Escalating to the second line.']
KB_TOPICS = ['Resetting a password', 'Mapping a network drive', 'Adding a shared mailbox', 'Joining the guest Wi-Fi',
             'Clearing the print queue', 'Enrolling in MFA', 'Restoring a deleted file', 'Setting up a new laptop',
             'Connecting to the VPN', 'Reading a backup report']


def _wchoice(rng, rows):
    total = sum(r[-1] for r in rows)
    x = rng.uniform(0, total)
    for r in rows:
        x -= r[-1]
        if x <= 0:
            return r
    return rows[-1]


@contextmanager
def explicit_timestamps(*models):
    """Let bulk_create keep created_at values we pass (auto_now_add would
    overwrite them), so the history is spread over three years."""
    changed = []
    for m in models:
        for f in m._meta.fields:
            if getattr(f, 'auto_now_add', False):
                f.auto_now_add = False
                changed.append(f)
    try:
        yield
    finally:
        for f in changed:
            f.auto_now_add = True


def _chunks(seq, n=1000):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _bulk(model, rows, batch=500):
    for part in _chunks(rows, batch):
        model.objects.bulk_create(part, batch_size=batch)


# ---------------------------------------------------------------------------
# generator (runs against the connected database)
# ---------------------------------------------------------------------------

def generate(counts, *, with_rmm=False, seed=20261125, technicians=None, log=print):
    """Create the dataset. `counts` is the dict from plan(). Returns a dict of
    row counts per model. Deterministic for a given seed and counts."""
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.utils import timezone
    from django.utils.text import slugify

    from accounts.models import RoleTemplate, UserProfile, UserType
    from assets.models import Asset, Contact
    from core.models import Organization, SystemSetting
    from docs.models import Document, DocumentCategory
    from locations.models import Location
    from psa.models import (
        Charge, ClientPSASettings, Contract, Invoice, Queue, Quote, Ticket, TicketComment, TicketPriority,
        TicketStatus, TicketTimeEntry, TicketType,
    )
    from vault.models import Password, PasswordFolder

    rng = random.Random(seed)
    User = get_user_model()
    now = timezone.now()
    today = timezone.localdate()
    n_cust, n_end = counts['customers'], counts['endpoints']
    t0 = time.perf_counter()

    ss = SystemSetting.get_settings()
    ss.psa_enabled = True
    ss.save()

    # -- technicians -------------------------------------------------------
    n_tech = technicians or max(4, min(12, n_cust // 8 + 2))

    def role(name):
        return RoleTemplate.objects.filter(name=name).first()

    def make_user(username, first, last, *, superuser=False, role_name=None):
        u, _ = User.objects.get_or_create(username=username, defaults={'email': f'{username}@scale.example'})
        u.first_name, u.last_name, u.is_staff, u.is_superuser = first, last, True, superuser
        u.set_unusable_password()
        u.save()
        prof, _ = UserProfile.objects.get_or_create(user=u)
        prof.user_type = UserType.STAFF
        if role_name and role(role_name):
            prof.global_role_template = role(role_name)
        prof.save()
        return u

    su = make_user('scale.super', 'Sam', 'Superuser', superuser=True)
    l1 = make_user('scale.l1', 'Lee', 'Level-One', role_name='L1 Tech')
    techs = [su, l1]
    for i in range(n_tech - 2):
        name = ('L2 Tech', 'L3 Tech', 'L2 Tech')[i % 3]
        techs.append(make_user(f'scale.tech{i + 1:02d}', FIRST[i % len(FIRST)], LAST[i % len(LAST)], role_name=name))

    # -- customers, locations, contacts -----------------------------------
    msp = Organization.objects.create(name='Scale MSP Services', slug='scale-msp-services', is_active=True,
                                      description='The MSP tenant of the synthetic scale dataset.')
    orgs = []
    for i in range(n_cust):
        a, n, k = ADJ[i % len(ADJ)], NOUN[(i // len(ADJ)) % len(NOUN)], KIND[i % len(KIND)]
        name = f'{a} {n} {k} {i + 1:03d}'
        city, st, zipc = CITIES[i % len(CITIES)]
        slug = slugify(name)
        orgs.append(Organization.objects.create(
            name=name, slug=slug, is_active=True, city=city, state=st, postal_code=zipc,
            website=f'https://{slug}.example', description='Synthetic customer (scale dataset).',
            primary_contact_name=f'{FIRST[i % len(FIRST)]} {LAST[(i * 3) % len(LAST)]}'))
    with transaction.atomic():
        for o in orgs + [msp]:
            ClientPSASettings.objects.update_or_create(organization=o, defaults={'enabled': True})

    # scope the L1 technician to ~10% of customers; access-group membership
    scope = orgs[:max(1, n_cust // 10)]
    l1.profile.client_scope = 'selected'
    l1.profile.save()
    l1.profile.scope_organizations.set(scope)
    try:
        from tech_access.models import TechnicianGroup
        for gname, users in (('L1 Tech', [l1]), ('L2 Tech', techs[2::3]), ('L3 Tech', techs[3::3] + [su])):
            grp = TechnicianGroup.objects.filter(name=gname).first()
            if grp:
                grp.members.add(*users)
    except Exception as exc:  # groups are a convenience; the dataset is usable without them
        log(f'  note: access groups not populated ({exc!r})')

    locations = []
    for i, o in enumerate(orgs):
        for j in range(1 + (i % 3 == 0) + (i % 7 == 0)):
            city, st, zipc = CITIES[(i + j) % len(CITIES)]
            locations.append(Location(organization=o, name=f'{o.name.split()[0]} site {j + 1}',
                                      location_type='office', street_address=f'{100 + i * 3 + j} Example Street',
                                      city=city, state=st, postal_code=zipc))
    _bulk(Location, locations)

    per_cust = max(1, counts['contacts'] // n_cust)
    contacts = []
    for i, o in enumerate(orgs):
        for j in range(per_cust):
            f, l_ = FIRST[(i + j) % len(FIRST)], LAST[(i * 7 + j) % len(LAST)]
            contacts.append(Contact(organization=o, first_name=f, last_name=l_, title=TITLES[j % len(TITLES)],
                                    email=f'{f.lower()}.{l_.lower()}.{i}.{j}@{o.slug}.example',
                                    phone=f'+1 555 {i % 1000:03d} {j:04d}'))
    _bulk(Contact, contacts)
    contacts_by_org = {}
    for c in Contact.objects.filter(organization__in=orgs).only('id', 'organization_id'):
        contacts_by_org.setdefault(c.organization_id, []).append(c.pk)
    log(f'  customers {len(orgs)}, locations {len(locations)}, contacts {len(contacts)}')

    # -- endpoints ---------------------------------------------------------
    assets = []
    for k in range(n_end):
        i = k % n_cust
        o = orgs[i]
        kind, mfr, model, pre, _w = _wchoice(rng, ASSET_KINDS)
        name = f'{o.slug[:10].upper()}-{pre}{k // n_cust + 1:04d}'
        assets.append(Asset(organization=o, name=name, asset_type=kind, manufacturer=mfr, model=model,
                            hostname=f'{pre}{k // n_cust + 1:04d}.{o.slug}.example',
                            ip_address=f'10.{(i % 250) + 1}.{(k // n_cust) // 250}.{(k // n_cust) % 250 + 1}',
                            serial_number=f'SN{rng.randint(10**7, 10**8 - 1)}', asset_tag=f'AT-{k + 1:06d}',
                            custom_fields={'status': 'active'}))
    _bulk(Asset, assets)
    asset_rows = list(Asset.objects.filter(organization__in=orgs).order_by('id').values_list('id', 'organization_id'))
    assets_by_org = {}
    for aid, oid in asset_rows:
        assets_by_org.setdefault(oid, []).append(aid)
    log(f'  assets {len(assets)}')

    n_rmm = 0
    if with_rmm:
        from integrations.models import RMMConnection, RMMDevice
        conn = RMMConnection.objects.create(organization=msp, provider_type='tactical_rmm', name='Scale RMM (inactive)',
                                            base_url='https://rmm.scale.example', is_active=False,
                                            sync_enabled=False)
        devs = []
        for a in Asset.objects.filter(organization__in=orgs).order_by('id').iterator(chunk_size=2000):
            if a.asset_type not in ('workstation', 'laptop', 'server'):
                continue
            devs.append(RMMDevice(organization_id=a.organization_id, connection=conn, external_id=f'scale-{a.pk}',
                                  device_name=a.name, device_type='server' if a.asset_type == 'server' else a.asset_type,
                                  hostname=a.hostname, ip_address=a.ip_address, serial_number=a.serial_number,
                                  os_type='windows', os_version='Windows 11 Pro', linked_asset_id=a.pk,
                                  client_name=orgs[0].name))
        _bulk(RMMDevice, devs)
        n_rmm = len(devs)
        log(f'  rmm devices {n_rmm}')

    # -- documents and knowledge base -------------------------------------
    cat, _ = DocumentCategory.objects.get_or_create(name='Scale runbooks', defaults={'slug': 'scale-runbooks'})
    per_org_docs = max(1, (counts['documents'] - len(KB_TOPICS)) // n_cust)
    body = ('<h2>Overview</h2><p>' + ' '.join(['Synthetic documentation text for the scale dataset.'] * 6) +
            '</p><ol><li>Step one.</li><li>Step two.</li><li>Step three.</li></ol>')
    docs = []
    with explicit_timestamps(Document):
        for i, o in enumerate(orgs):
            for j in range(per_org_docs):
                ts = now - timedelta(days=rng.randint(1, 1000))
                title = f'{KB_TOPICS[j % len(KB_TOPICS)]} - {o.name.split()[0]} {j + 1}'
                docs.append(Document(organization=o, title=title, slug=slugify(title), body=body, category=cat,
                                     is_published=True, content_type='html', created_by=su, created_at=ts))
        for j, topic in enumerate(KB_TOPICS):
            docs.append(Document(organization=None, title=topic, slug=slugify(topic), body=body, is_global=True,
                                 is_published=True, category=cat, content_type='html', created_by=su,
                                 created_at=now - timedelta(days=rng.randint(1, 600))))
        _bulk(Document, docs)
    log(f'  documents {len(docs)}')

    # -- vault (metadata + encrypted placeholder values via the model API) --
    per_org_creds = max(1, counts['credentials'] // n_cust)
    pw_rows = []
    folders = {o.pk: PasswordFolder.objects.create(name='Infrastructure', organization=o) for o in orgs}
    for i, o in enumerate(orgs):
        for j in range(per_org_creds):
            p = Password(title=f'{o.name.split()[0]} credential {j + 1}', organization=o, folder=folders[o.pk],
                         username=f'svc_{j + 1}', url=f'https://app{j + 1}.{o.slug}.example', notes='Synthetic entry.',
                         created_by=su)
            p.set_password(f'Placeholder-{rng.randint(100000, 999999)}')
            pw_rows.append(p)
    with explicit_timestamps(Password):
        for p in pw_rows:
            p.created_at = now - timedelta(days=rng.randint(1, 900))
        _bulk(Password, pw_rows)
    log(f'  vault entries {len(pw_rows)}')

    # -- contracts, quotes, charges, invoices -----------------------------
    contracts = []
    for i, o in enumerate(orgs):
        managed = i % 3 != 2
        contracts.append(Contract(organization=msp, client_org=o, name=f'{o.name.split()[0]} managed services',
                                  contract_type='managed' if managed else 'block_hours', status='active',
                                  start_date=today - timedelta(days=400), end_date=today + timedelta(days=330),
                                  hourly_rate=Decimal('150.00'), total_hours=Decimal('0' if managed else '40')))
    _bulk(Contract, contracts)
    for i, o in enumerate(orgs):
        Quote.objects.create(organization=msp, client_org=o, title=f'{o.name.split()[0]} firewall refresh',
                             status='sent' if i % 2 else 'draft')
    charges = []
    for i, o in enumerate(orgs):
        for j in range(12):
            charges.append(Charge(organization=msp, client_org=o, description=f'Monthly licence block {j + 1}',
                                  amount=Decimal(str(20 + (i * j) % 80)), charge_date=today - timedelta(days=30 * j),
                                  invoiced=j > 1, created_by=su, created_at=now - timedelta(days=30 * j)))
    with explicit_timestamps(Charge):
        _bulk(Charge, charges)
    per_org_inv = max(1, counts['invoices'] // n_cust)
    invoices = []
    with explicit_timestamps(Invoice):
        for i, o in enumerate(orgs):
            for j in range(per_org_inv):
                total = Decimal(str(300 + (i * 37 + j * 91) % 2500))
                paid = j < per_org_inv - 2
                invoices.append(Invoice(
                    invoice_number=f'SCALE-INV-{i + 1:04d}-{j + 1:02d}', organization=msp, client_org=o,
                    title=f'{o.name.split()[0]} services', status='paid' if paid else 'sent',
                    invoice_date=today - timedelta(days=30 * (per_org_inv - j)), subtotal=total, total=total,
                    amount_paid=total if paid else 0, created_at=now - timedelta(days=30 * (per_org_inv - j))))
        _bulk(Invoice, invoices)
    log(f'  contracts {len(contracts)}, quotes {len(orgs)}, charges {len(charges)}, invoices {len(invoices)}')

    # -- tickets with history ---------------------------------------------
    statuses = list(TicketStatus.objects.all())
    open_s = [s for s in statuses if not s.is_terminal] or statuses
    done_s = [s for s in statuses if s.is_terminal] or statuses
    prios = list(TicketPriority.objects.all())
    types = list(TicketType.objects.all())
    queues = list(Queue.objects.all())
    year_next = {}
    n_t = counts['tickets']
    rows = []
    meta = []  # (created, terminal, org_id)
    with explicit_timestamps(Ticket):
        for k in range(n_t):
            i = rng.randrange(n_cust)
            o = orgs[i]
            age_h = int((rng.random() ** 1.6) * 3 * 365 * 24) + 1
            created = now - timedelta(hours=age_h)
            terminal = rng.random() < (0.97 if age_h > 24 * 45 else 0.45)
            status = rng.choice(done_s if terminal else open_s)
            yr = created.year
            year_next[yr] = year_next.get(yr, 0) + 1
            cl = contacts_by_org.get(o.pk) or [None]
            al = assets_by_org.get(o.pk) or [None]
            rows.append(Ticket(
                ticket_number=f'PSA-{yr}-{year_next[yr]:06d}', organization=o,
                contact_id=rng.choice(cl), subject=f'{rng.choice(SUBJECTS)} ({k + 1})',
                description='Synthetic ticket for the scale dataset. ' * 3, status=status,
                priority=rng.choice(prios), ticket_type=rng.choice(types), queue=rng.choice(queues),
                assigned_to=rng.choice(techs) if rng.random() < 0.85 else None,
                related_asset_id=rng.choice(al) if rng.random() < 0.6 else None, source='manual',
                client_can_view=True, created_at=created,
                first_response_at=created + timedelta(minutes=rng.randint(5, 90)),
                resolved_at=created + timedelta(hours=rng.randint(1, 72)) if terminal else None,
                billing_status='ready' if terminal and age_h < 24 * 20 and rng.random() < 0.25 else ''))
            meta.append((created, terminal, o.pk))
        _bulk(Ticket, rows)
    ids = list(Ticket.objects.filter(ticket_number__startswith='PSA-').order_by('id').values_list('id', flat=True))
    ids = ids[-n_t:]
    comments, entries = [], []
    with explicit_timestamps(TicketComment):
        for tid, (created, terminal, _o) in zip(ids, meta):
            for c in range(rng.randint(2, 6)):
                comments.append(TicketComment(
                    ticket_id=tid, author=rng.choice(techs), body=rng.choice(REPLIES),
                    is_internal=rng.random() < 0.3, created_at=created + timedelta(minutes=40 * (c + 1))))
        _bulk(TicketComment, comments)
    with explicit_timestamps(TicketTimeEntry):
        for tid, (created, terminal, _o) in zip(ids, meta):
            for _ in range(rng.randint(0, 3)):
                mins = rng.choice((15, 30, 45, 60, 90))
                start = created + timedelta(hours=rng.randint(1, 30))
                entries.append(TicketTimeEntry(ticket_id=tid, user=rng.choice(techs), started_at=start,
                                               ended_at=start + timedelta(minutes=mins), duration_minutes=mins,
                                               is_billable=rng.random() < 0.8, notes='Synthetic time entry.',
                                               created_at=start))
        _bulk(TicketTimeEntry, entries)
    log(f'  tickets {len(rows)}, comments {len(comments)}, time entries {len(entries)}')

    result = {
        'technicians': len(techs), 'organizations': Organization.objects.count(), 'customers': len(orgs),
        'locations': len(locations), 'contacts': len(contacts), 'assets': len(assets), 'rmm_devices': n_rmm,
        'documents': len(docs), 'vault_entries': len(pw_rows), 'contracts': len(contracts), 'quotes': len(orgs),
        'charges': len(charges), 'invoices': len(invoices), 'tickets': len(rows), 'comments': len(comments),
        'time_entries': len(entries), 'seconds': round(time.perf_counter() - t0, 1),
    }
    return result


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('db', help='path of the NEW SQLite database to create (under /var/tmp or the scratchpad)')
    ap.add_argument('--profile', choices=['small', 'medium', 'large', 'xl'], default='small')
    ap.add_argument('--customers', type=int)
    ap.add_argument('--endpoints', type=int)
    ap.add_argument('--with-rmm', action='store_true', help='also write an RMM device row per endpoint')
    ap.add_argument('--template', help='migrated empty database to start from (skips the slow migrations)')
    ap.add_argument('--save-template', help='after migrating, also save the empty migrated database here')
    ap.add_argument('--seed', type=int, default=20261125)
    args = ap.parse_args(argv)

    path = check_target(args.db)  # before Django is imported
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    sys.path[:0] = [str(ROOT), str(ROOT / 'scripts' / 'demo')]
    os.environ['DEMO_DIR'] = str(path.parent)
    os.environ['DJANGO_SETTINGS_MODULE'] = 'demo_settings'
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections

    settings.DATABASES['default']['NAME'] = str(path)
    connections['default'].settings_dict['NAME'] = str(path)
    if str(connections['default'].settings_dict['NAME']) != str(path):
        raise SeedRefused('could not point Django at the target database')

    # A throwaway database: trade durability for speed (migrations fsync a lot).
    from django.db.backends.signals import connection_created

    def fast(sender, connection, **kw):
        if connection.vendor == 'sqlite':
            connection.cursor().execute('PRAGMA synchronous=OFF')
            connection.cursor().execute('PRAGMA journal_mode=MEMORY')
    connection_created.connect(fast)

    counts = plan(args.profile, args.customers, args.endpoints)
    print(f'target {path}\nplan {counts}', flush=True)
    t0 = time.perf_counter()
    if args.template:  # a migrated, otherwise empty scale database made by an earlier run with --save-template
        import sqlite3
        src = sqlite3.connect(f'file:{args.template}?mode=ro', uri=True)
        dst = sqlite3.connect(str(path))
        src.backup(dst)
        dst.close()
        src.close()
    call_command('migrate', interactive=False, verbosity=0)
    if args.save_template:
        import sqlite3
        connections.close_all()
        pathlib.Path(args.save_template).parent.mkdir(parents=True, exist_ok=True)
        s2, d2 = sqlite3.connect(str(path)), sqlite3.connect(args.save_template)
        s2.backup(d2)
        d2.close()
        s2.close()
    print(f'  migrated in {time.perf_counter() - t0:.0f}s', flush=True)
    call_command('psa_seed_defaults', verbosity=0)
    result = generate(counts, with_rmm=args.with_rmm, seed=args.seed)
    print('counts', result)
    print(f'total elapsed {time.perf_counter() - t0:.0f}s')
    return result


if __name__ == '__main__':
    main()
