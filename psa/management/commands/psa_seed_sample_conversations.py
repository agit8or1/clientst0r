"""Sample tickets with real-looking conversations, for demo and evaluation
installs (v3.17.654).

    manage.py psa_seed_sample_conversations [--tech USERNAME]

Adds demo customer people (portal accounts that can't sign in, with
example.com addresses) to the demo customers that exist, and tickets they
opened by e-mail or in the portal. Between them the tickets show:

* the opening request, customer and technician replies, threaded replies,
  internal notes and status events;
* people copied on replies (Cc), files attached by either side, logged time;
* secure messages in each state (opened, waiting, expired);
* every "Next" state on the ticket list: needs reply, waiting on customer,
  follow up, waiting on vendor, closed — plus a new unassigned ticket.

No mail is sent. Safe to run again: a sample ticket that already exists is
skipped.

``--org-map SAMPLE=TARGET`` (repeatable) files one sample customer's tickets
under another organization instead, for a demo instance with its own invented
customers, e.g. ``--org-map demo-globex=northwind-logistics``. The sample
people's e-mail domain and the sample company name in the text are rewritten
to the target's (its website host, else ``<slug>.example``), and a customer
person with the same name already at the target is reused. Only mapped
samples are created in that mode. The secure messages are real encrypted SecureNotes whose one-time
links were never sent anywhere, so nobody can open them.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from psa.models import (Queue, Ticket, TicketAttachment, TicketComment, TicketPriority, TicketStatus,
                        TicketTimeEntry, TicketType)
from psa.ticket_secure import create_secure_message

# Demo customer people per organization slug: (first, last, e-mail).
PEOPLE = {
    'demo-globex': [('Dana', 'Whitfield', 'dana.whitfield@globex.example.com'),
                    ('Marcus', 'Bell', 'marcus.bell@globex.example.com')],
    'demo-initech': [('Priya', 'Raman', 'priya.raman@initech.example.com'),
                     ('Sam', 'Okafor', 'sam.okafor@initech.example.com')],
    'demo-acme': [('Luis', 'Ortega', 'luis.ortega@acme-industries.example.com'),
                  ('Hannah', 'Price', 'hannah.price@acme-industries.example.com')],
    'demo': [('Ellen', 'Marsh', 'ellen.marsh@demo-company.example.com')],
}
# Existing portal users to use instead, where the customer already has them.
EXISTING = {'acme-corporation': ['demo.editor', 'demo.viewer']}
# How each sample customer is named in the sample text, and its e-mail
# domain; --org-map rewrites both to the target organization's.
LABELS = {
    'demo-globex': ('Globex', 'globex.example.com'),
    'demo-initech': ('Initech', 'initech.example.com'),
    'demo-acme': ('ACME Industries', 'acme-industries.example.com'),
    'demo': ('Demo Company', 'demo-company.example.com'),
    'acme-corporation': ('Acme Corporation', 'acme.example.com'),
}

T, C, NOTE, EVENT, FILE, TIME = 'tech', 'customer', 'note', 'event', 'file', 'time'

SAMPLES = [
    {'org': 'demo-globex', 'by': 0, 'via': 'email', 'subject': 'Outlook keeps asking for my password',
     'cc': ['office.manager@globex.example.com'], 'status': 'Resolved', 'priority': 'High', 'type': 'Incident',
     'age': 52,
     'description': "Since this morning Outlook pops up a password box every few minutes. I type my password "
                    "and it comes back. Webmail works fine.\n\nDana\nAccounts Payable, Globex",
     'thread': [
         {'k': EVENT, 'body': 'Status changed from New to In Progress', 'h': 51},
         {'k': T, 'h': 50, 'email': True, 'cc': True,
          'body': "Hi Dana, thanks for the detail — webmail working tells me your account is fine and it's the "
                  "saved sign-in on your PC. Roughly when did you last change your password?"},
         {'k': C, 'h': 49, 'parent': 1, 'body': "I changed it on Friday when the reminder came up. Does that matter?"},
         {'k': NOTE, 'h': 48, 'body': "Stale credential in Credential Manager, plus the old Office build's "
                                      "modern-auth registry key. Clearing both remotely."},
         {'k': TIME, 'h': 48, 'minutes': 35, 'body': 'Remote session: cleared cached credentials, Office repair.'},
         {'k': T, 'h': 47, 'parent': 2, 'email': True, 'secure': 'opened',
          'body': "Yes, that's the cause: Outlook was still trying the old password. I've cleared the saved copy. "
                  "Your account was locked a few times this morning, so I've set a temporary password — it's in "
                  "the secure message below, and you'll be asked to change it at the next sign-in."},
         {'k': C, 'h': 30, 'parent': 5, 'body': "That did it, no more pop-ups. Thank you!"},
         {'k': EVENT, 'h': 29, 'body': 'Status changed from In Progress to Resolved'},
     ]},
    {'org': 'demo-globex', 'by': 1, 'via': 'email', 'subject': 'VPN drops every 20 minutes when working from home',
     'cc': [], 'status': 'In Progress', 'priority': 'Normal', 'type': 'Incident', 'age': 30,
     'description': "The VPN disconnects about every 20 minutes and I have to log in again. Started this week.",
     'thread': [
         {'k': T, 'h': 28, 'email': True,
          'body': "Hi Marcus, could you send me the log from the VPN client? Settings → Diagnostics → Export log."},
         {'k': C, 'h': 3, 'parent': 0, 'body': "Here you go — attached. It dropped twice while I was exporting it."},
         {'k': FILE, 'h': 2.9, 'by': C, 'name': 'vpn-client-log.txt',
          'text': "2026-11-09 08:01:12 Tunnel up\n2026-11-09 08:21:40 DPD timeout, reconnecting\n"
                  "2026-11-09 08:21:44 Tunnel up\n2026-11-09 08:41:52 DPD timeout, reconnecting\n"},
     ]},
    {'org': 'demo-initech', 'by': 0, 'via': 'email', 'subject': 'New starter on Monday — accounts and laptop',
     'cc': ['hr@initech.example.com', 'it.lead@initech.example.com'], 'status': 'In Progress',
     'priority': 'Normal', 'type': 'Onboarding', 'age': 26,
     'description': "Hi team,\n\nTom Becker joins Finance on Monday. He needs:\n- e-mail and Teams\n"
                    "- access to the Finance share\n- a laptop (the spare ThinkPad is fine)\n\nThanks,\nPriya",
     'thread': [
         {'k': T, 'h': 25, 'email': True, 'cc': True,
          'body': "Thanks Priya. Tom's account and the laptop will be ready by Friday afternoon. Should he have the "
                  "same Finance share permissions as Maria?"},
         {'k': C, 'h': 23, 'parent': 0,
          'body': "Yes please, same as Maria. HR is copied so they know the start date is confirmed."},
         {'k': NOTE, 'h': 20, 'body': "One Business Premium seat free. Laptop LT-0142 imaged and enrolled."},
         {'k': FILE, 'h': 20, 'by': T, 'internal': True, 'name': 'lt-0142-build-checklist.txt',
          'text': "BitLocker: on\nIntune: enrolled\nDefender: healthy\nOffice: installed\n"},
         {'k': TIME, 'h': 20, 'minutes': 50, 'body': 'Account creation, licence, laptop build.'},
         {'k': T, 'h': 4, 'parent': 1, 'email': True, 'secure': 'waiting',
          'body': "All set: account created, Finance share matches Maria's, laptop LT-0142 is ready to collect. "
                  "Tom's first-day password is in the secure message — please hand it to him on Monday; it "
                  "expires in 3 days."},
     ]},
    {'org': 'demo-initech', 'by': 1, 'via': 'portal', 'subject': 'Printer on 2nd floor jams on tray 2',
     'cc': [], 'status': 'Waiting on Vendor', 'vendor': True, 'priority': 'Low', 'type': 'Incident', 'age': 120,
     'description': "The big printer upstairs jams every time someone prints from tray 2.",
     'thread': [
         {'k': T, 'h': 118, 'body': "Thanks Sam. I'll check it on Thursday's site visit."},
         {'k': NOTE, 'h': 70, 'body': "Pickup roller worn. Logged with the vendor (case 4471-22), part on order."},
         {'k': T, 'h': 69, 'body': "The pickup roller for tray 2 is worn; the replacement part is on order with "
                                   "the vendor. Tray 1 works fine in the meantime."},
         {'k': EVENT, 'h': 69, 'body': 'Status changed from In Progress to Waiting on Vendor'},
     ]},
    {'org': 'demo-acme', 'by': 0, 'via': 'email', 'subject': 'Wi-Fi password for the visitor network',
     'cc': [], 'status': 'Waiting on Client', 'priority': 'Low', 'type': 'Service Request', 'age': 200,
     'description': "Could you send me the guest Wi-Fi password for the visitors coming next week?",
     'thread': [
         {'k': T, 'h': 198, 'email': True, 'secure': 'expired',
          'body': "Hi Luis, the guest network password is in the secure message below."},
         {'k': NOTE, 'h': 120, 'body': "The secure link expired unopened."},
         {'k': T, 'h': 119, 'email': True,
          'body': "Hi Luis, the secure message I sent expired before it was opened. Reply here when you're ready "
                  "and I'll send a fresh one."},
         {'k': EVENT, 'h': 119, 'body': 'Status changed from In Progress to Waiting on Client'},
     ]},
    {'org': 'demo-acme', 'by': 1, 'via': 'email', 'subject': 'Laptop screen flickering', 'unassigned': True,
     'cc': ['facilities@acme-industries.example.com'], 'status': 'New', 'priority': 'Normal',
     'type': 'Incident', 'age': 0.7,
     'description': "My laptop screen flickers when I move the lid. It's a Latitude 5440, asset tag AC-2291. "
                    "Facilities is copied because it's a loan unit.", 'thread': []},
    {'org': 'acme-corporation', 'by': 0, 'via': 'portal', 'subject': 'Shared mailbox for the sales team',
     'cc': ['sales.lead@acme.example.com'], 'status': 'Waiting on Client', 'priority': 'Normal',
     'type': 'Service Request', 'age': 30,
     'description': "We'd like a shared mailbox sales@ that the four people in sales can send from.",
     'thread': [
         {'k': T, 'h': 28, 'email': True, 'cc': True,
          'body': "Happy to set that up. Should replies sent from sales@ be saved in the shared mailbox's Sent "
                  "Items, or in each person's own?"},
         {'k': C, 'h': 26, 'parent': 0, 'body': "In the shared mailbox please, so everyone sees what was sent."},
         {'k': NOTE, 'h': 25, 'body': "Needs MessageCopyForSentAsEnabled on the mailbox. No licence needed."},
         {'k': T, 'h': 6, 'parent': 1, 'email': True,
          'body': "Done — sales@ is live and the four of you have Send As. Please send a test from Outlook and let "
                  "me know it lands in the shared Sent Items."},
         {'k': EVENT, 'h': 6, 'body': 'Status changed from In Progress to Waiting on Client'},
     ]},
    {'org': 'acme-corporation', 'by': 1, 'via': 'portal', 'subject': "Can't open the HR share since this morning",
     'cc': [], 'status': 'In Progress', 'priority': 'High', 'type': 'Access Request', 'age': 5,
     'description': "Opening \\\\files\\HR gives me 'Access is denied'. It worked yesterday.",
     'thread': [
         {'k': T, 'h': 4.5, 'body': "Thanks — did anything change on your account yesterday, a password reset or "
                                    "a new laptop?"},
         {'k': C, 'h': 1, 'parent': 0, 'body': "No changes that I know of. Screenshot of the error attached."},
         {'k': FILE, 'h': 0.9, 'by': C, 'name': 'hr-share-error.txt',
          'text': "Windows cannot access \\\\files\\HR\nYou do not have permission to access \\\\files\\HR.\n"},
     ]},
    {'org': 'demo', 'by': 0, 'via': 'email', 'subject': 'Quote for five new monitors',
     'cc': [], 'status': 'In Progress', 'priority': 'Low', 'type': 'Procurement', 'age': 170,
     'description': "Could we get a quote for five 27\" monitors for the design team?",
     'thread': [
         {'k': T, 'h': 168, 'email': True,
          'body': "Hi Ellen, do you want USB-C monitors so the laptops charge from them, or standard HDMI?"},
     ]},
    {'org': 'demo', 'by': 0, 'via': 'email', 'subject': 'Website showing an error page', 'cc': [],
     'status': 'Closed', 'priority': 'Critical', 'type': 'Incident', 'age': 76,
     'description': "Our website shows '502 Bad Gateway' since about 9am.",
     'thread': [
         {'k': T, 'h': 75.8, 'email': True, 'body': "Looking now — the web host had an outage; it's back up. "
                                                    "Can you confirm it loads for you?"},
         {'k': TIME, 'h': 75.8, 'minutes': 15, 'body': 'Checked hosting status, verified recovery.'},
         {'k': C, 'h': 75.5, 'parent': 0, 'body': "Yes, it's working again. Thanks for the quick help."},
         {'k': EVENT, 'h': 75, 'body': 'Status changed from In Progress to Closed'},
     ]},
]


class Command(BaseCommand):
    help = 'Create demo customer people and sample tickets with conversations, Cc, files and secure messages.'

    def add_arguments(self, parser):
        parser.add_argument('--tech', default='', help='Username of the technician who replies (default: the '
                                                       'first active superuser).')
        parser.add_argument('--org-map', action='append', default=[], metavar='SAMPLE=TARGET',
                            help='File the tickets of sample customer SAMPLE (e.g. demo-globex) under the '
                                 'organization with slug TARGET instead. Repeatable; when given, only mapped '
                                 'samples are created.')

    def _parse_map(self, pairs):
        from core.models import Organization
        mapping = {}
        for pair in pairs:
            sample, sep, target = pair.partition('=')
            sample, target = sample.strip(), target.strip()
            if not sep or sample not in LABELS or not target:
                raise CommandError(f'--org-map {pair!r}: expected SAMPLE=TARGET with SAMPLE one of '
                                   f'{", ".join(LABELS)}.')
            org = Organization.objects.filter(slug=target, is_active=True).first()
            if org is None:
                raise CommandError(f'--org-map {pair!r}: no active organization with slug {target!r}.')
            mapping[sample] = org
        return mapping

    @staticmethod
    def _target_domain(org):
        from urllib.parse import urlparse
        host = urlparse(org.website or '').hostname if getattr(org, 'website', '') else None
        return (host[4:] if host and host.startswith('www.') else host) or f'{org.slug}.example'

    def _rewrite(self, value, sample, org):
        """The sample text with the sample company's name and domain replaced
        by the target organization's."""
        label, domain = LABELS[sample]
        new_domain = self._target_domain(org)
        if isinstance(value, str):
            return value.replace(domain, new_domain).replace(label, org.name)
        if isinstance(value, list):
            return [self._rewrite(v, sample, org) for v in value]
        if isinstance(value, dict):
            return {k: self._rewrite(v, sample, org) for k, v in value.items()}
        return value

    def handle(self, *args, **opts):
        User = get_user_model()
        self.mapping = self._parse_map(opts.get('org_map') or [])
        tech = (User.objects.filter(username=opts['tech'], is_active=True).first() if opts['tech'] else
                User.objects.filter(is_active=True, is_superuser=True).order_by('pk').first())
        if tech is None:
            raise CommandError('No technician to attribute replies to. Pass --tech USERNAME.')
        self.lookups = {
            'queue': Queue.objects.order_by('pk').first(),
            'status': {s.name: s for s in TicketStatus.objects.all()},
            'priority': {p.name: p for p in TicketPriority.objects.all()},
            'type': {t.name: t for t in TicketType.objects.all()},
        }
        if not self.lookups['status'] or self.lookups['queue'] is None:
            raise CommandError('Run manage.py psa_seed_defaults first.')
        created = 0
        people_cache = {}
        for spec in SAMPLES:
            if self.mapping:
                if spec['org'] not in self.mapping:
                    continue
                org = self.mapping[spec['org']]
                spec = {**self._rewrite(spec, spec['org'], org), 'org': spec['org']}
            else:
                org = self._org(spec['org'])
            if org is None:
                self.stdout.write(f'skip "{spec["subject"]}": no active customer {spec["org"]}')
                continue
            if Ticket.objects.filter(organization=org, subject=spec['subject']).exists():
                self.stdout.write(f'exists: "{spec["subject"]}" at {org.name}')
                continue
            key = (org.pk, spec['org'])
            if key not in people_cache:
                people_cache[key] = self._people(org, spec['org'])
            people = people_cache[key]
            if not people:
                self.stdout.write(f'skip "{spec["subject"]}": no customer people at {org.name}')
                continue
            with transaction.atomic():
                ticket = self._make(org, spec, tech, people[spec['by'] % len(people)])
            created += 1
            self.stdout.write(self.style.SUCCESS(f'created {ticket.ticket_number} "{spec["subject"]}" at {org.name}'))
        self.stdout.write(f'Sample conversations: {created} created.')

    @staticmethod
    def _org(slug):
        from core.models import Organization
        return Organization.objects.filter(slug=slug, is_active=True).first()

    def _people(self, org, slug):
        """Customer users for the org: existing portal users, else demo people
        who can't sign in (unusable password)."""
        from accounts.models import Membership, Role, UserProfile, UserType
        User = get_user_model()
        mapped = bool(self.mapping)
        existing = [] if mapped else EXISTING.get(slug, [])
        people = [u for u in User.objects.filter(username__in=existing, is_active=True).order_by('username')]
        if people:
            return people
        for first, last, email in PEOPLE.get(slug, []):
            username = f'demo.{first}.{last}'.lower()
            user = User.objects.filter(username=username).first()
            if mapped:
                email = self._rewrite(email, slug, org)
                # A customer person of that name already at the target (say the
                # demo's own portal user) is reused rather than duplicated.
                user = user or User.objects.filter(
                    first_name=first, last_name=last, is_active=True, is_staff=False,
                    memberships__organization=org, memberships__is_active=True).order_by('pk').first()
            if user is None:
                user = User(username=username, first_name=first, last_name=last, email=email)
                user.set_unusable_password()
                user.save()
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.user_type = UserType.ORG_USER
                profile.save()
                self.stdout.write(f'  demo customer {username} at {org.name}')
            Membership.objects.get_or_create(user=user, organization=org,
                                             defaults={'role': Role.EDITOR, 'is_active': True})
            people.append(user)
        return people

    def _make(self, org, spec, tech, person):
        now = timezone.now()
        lk = self.lookups
        at = lambda hours: now - timedelta(hours=hours)  # noqa: E731
        status = lk['status'].get(spec['status']) or next(iter(lk['status'].values()))
        name = person.get_full_name() or person.username
        ticket = Ticket.objects.create(
            organization=org, subject=spec['subject'], description=spec['description'],
            queue=lk['queue'], status=status, priority=lk['priority'].get(spec['priority']),
            ticket_type=lk['type'].get(spec['type']), source=spec['via'], visibility='client',
            client_can_view=True, requester_name=name, requester_email=person.email,
            cc_emails=list(spec['cc']), assigned_to=None if spec.get('unassigned') else tech,
            created_by=person if spec['via'] == 'portal' else None,
            waiting_on_vendor=bool(spec.get('vendor')),
        )
        stamps = {'created_at': at(spec['age'])}
        if status.is_terminal:
            stamps['closed_at'] = at(min(r['h'] for r in spec['thread'])) if spec['thread'] else now
        posted = {}  # thread row index → comment
        first_response = last_tech = last_client = None
        for i, row in enumerate(spec['thread']):
            kind, when = row['k'], at(row['h'])
            if kind == FILE:
                uploader = tech if row['by'] == T else person
                f = TicketAttachment(ticket=ticket, uploaded_by=uploader, filename=row['name'],
                                     content_type='text/plain', size_bytes=len(row['text'].encode()),
                                     is_internal=bool(row.get('internal')),
                                     comment=posted[max(posted)] if posted and row['by'] == C else None)
                f.file.save(row['name'], ContentFile(row['text'].encode()), save=False)
                f.save()
                TicketAttachment.objects.filter(pk=f.pk).update(created_at=when)
                continue
            if kind == TIME:
                TicketTimeEntry.objects.create(ticket=ticket, user=tech, started_at=when - timedelta(
                    minutes=row['minutes']), ended_at=when, duration_minutes=row['minutes'], notes=row['body'])
                continue
            parent = posted[row['parent']] if row.get('parent') is not None else None
            fields = {'ticket': ticket, 'body': row['body'], 'parent_comment': parent}
            if kind == EVENT:
                fields.update(is_system=True, author=tech, parent_comment=None)
            elif kind == NOTE:
                fields.update(is_internal=True, author=tech)
            elif kind == T:
                fields.update(author=tech, cc_emails=list(spec['cc']) if row.get('cc') else [])
                if row.get('secure'):
                    fields['secure_note'] = self._secure(ticket, tech, row['secure'], when)
                first_response = first_response or when
                last_tech = when
            else:
                if spec['via'] == 'portal':
                    fields.update(author=person, source='portal')
                else:
                    fields.update(author_name=name, author_email=person.email, source='email')
                last_client = when
            comment = TicketComment.objects.create(**fields)
            TicketComment.objects.filter(pk=comment.pk).update(created_at=when)
            posted[i] = comment
        stamps.update(first_response_at=first_response, last_tech_response_at=last_tech,
                      last_client_response_at=last_client)
        Ticket.objects.filter(pk=ticket.pk).update(**stamps)
        return ticket

    @staticmethod
    def _secure(ticket, tech, state, sent):
        note = create_secure_message(ticket=ticket, sender=tech,
                                     text='Sample secret — this link was never sent.', expires_hours=72)
        changes = {'created_at': sent, 'expires_at': sent + timedelta(hours=72)}
        if state == 'opened':
            changes.update(read_count=1, is_deleted=True)
        type(note).objects.filter(pk=note.pk).update(**changes)
        note.refresh_from_db()
        return note
