"""
Shared test helpers for the PSA test suite.

These get imported by every test module in this package. The legacy
single-file `psa/tests.py` (5,465 lines) was split into this package in
v3.17.192 — these helpers used to live at the top of that file.
"""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone


# Tests bypass the project-wide 2FA enforcement middleware so we can exercise
# the views directly. Same list every PSA test module uses.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _setup_seed():
    """Seed PSA defaults — queues, statuses, priorities, types."""
    call_command('psa_seed_defaults', verbosity=0)


def _enable_psa_global():
    """Flip the system-wide PSA feature flag on."""
    from core.models import SystemSetting
    s = SystemSetting.get_settings()
    s.psa_enabled = True
    s.save()


def _enable_psa_for(org):
    """Flip the per-client PSA feature flag on for a given org."""
    from psa.models import ClientPSASettings
    cps, _ = ClientPSASettings.objects.get_or_create(organization=org)
    cps.enabled = True
    cps.save()
    return cps


def _make_msp_tech(user):
    """Mark `user` as MSP staff (a technician, profile user_type=Staff).

    Users who only hold customer memberships are customer users and get the
    portal ticket rule (psa/visibility.py): only `client_can_view` tickets, no
    internal comments. Tests whose acting user plays a technician — assigning,
    replying, internal notes, time, closing, merging — must mark them staff.
    """
    from accounts.models import UserProfile, UserType
    # Update the profile cached on `user` (the post_save signal attaches it),
    # not a fresh copy: force_login() saves the user, and a save_user_profile
    # signal then re-saves that cached profile, which would undo the change.
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.save()
    return user


def _use_prepaid_hours(contract, minutes, *, user=None, days_ago=0):
    """Phase 101.4: record `minutes` of approved billable time under
    `contract`'s customer, so the prepaid-hour ledger consumes it (what used
    to be faked by setting `Contract.hours_used_minutes`). The entry is dated
    inside the contract's window. Returns the time entry."""
    from datetime import datetime, time as _time

    from psa.models import (Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
                            TimesheetSubmission)
    if not Queue.objects.exists():
        _setup_seed()
    if user is None:
        user, _ = User.objects.get_or_create(username='prepaid-approver',
                                             defaults={'is_superuser': True, 'is_staff': True})
    on = timezone.localdate() - timedelta(days=days_ago)
    if contract.end_date and on > contract.end_date:
        on = contract.end_date
    if on < contract.start_date:
        on = contract.start_date
    start = timezone.make_aware(datetime.combine(on, _time(9, 0)))
    ticket = Ticket.objects.create(
        organization=contract.client_org, subject='Prepaid work', queue=Queue.objects.first(),
        priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
        status=TicketStatus.objects.first())
    te = TicketTimeEntry.objects.create(
        ticket=ticket, user=user, started_at=start, ended_at=start + timedelta(minutes=minutes),
        duration_minutes=minutes, is_billable=True, billing_contract=contract, billing_contract_chosen=True)
    sub = TimesheetSubmission.objects.create(
        user=user, period_start=on, period_end=on,
        revision=TimesheetSubmission.objects.filter(user=user).count() + 1, status='pending')
    TicketTimeEntry.objects.filter(pk=te.pk).update(submission=sub)
    sub.approve(user=user)
    return te
