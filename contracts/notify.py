"""Staff alerts: in-app notifications and e-mail, de-duplicated.

Recipients come from the contract settings (owner, account manager, selected
people, staff whose global role is one of the chosen roles) plus the people
named on the contract. Only active MSP staff who may view the contract are
told. E-mail follows each person's existing "e-mail notifications" profile
switch.
"""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import permissions as perms
from .models import ContractAlert, ContractNotification, ContractSettings

logger = logging.getLogger('contracts')


def _wants_email(user) -> bool:
    profile = getattr(user, 'profile', None)
    try:
        return bool(user.email) and (profile is None or profile.email_notifications)
    except Exception:  # noqa: BLE001
        return bool(user.email)


def recipients(contract, settings=None):
    from django.contrib.auth import get_user_model
    settings = settings or ContractSettings.for_organization(contract.organization)
    users = {}
    if settings.notify_owner and contract.owner_id:
        users[contract.owner_id] = contract.owner
    if settings.notify_account_manager and contract.account_manager_id:
        users[contract.account_manager_id] = contract.account_manager
    for u in settings.notify_users.all():
        users[u.pk] = u
    for u in contract.notify_users.all():
        users[u.pk] = u
    role_ids = list(settings.notify_roles.values_list('pk', flat=True))
    if role_ids:
        for u in get_user_model().objects.filter(is_active=True, profile__global_role_template_id__in=role_ids):
            users[u.pk] = u
    return [u for u in users.values() if u.is_active and perms.has(u, perms.VIEW, contract.organization_id)]


def approvers(contract):
    from psa.visibility import msp_technicians
    return [u for u in msp_technicians() if perms.has(u, perms.APPROVE, contract.organization_id)]


def raise_alert(contract, key, kind) -> bool:
    """True the first time `key` is raised, False ever after (race-safe)."""
    try:
        with transaction.atomic():
            ContractAlert.objects.create(contract=contract, key=key[:200], kind=kind)
        return True
    except IntegrityError:
        return False


def notify(contract, kind, message, dedup_key, *, users=None, subject=None, settings=None, link_path=None):
    """Tell staff about something once per (person, dedup_key)."""
    from . import jobs
    settings = settings or ContractSettings.for_organization(contract.organization)
    users = recipients(contract, settings) if users is None else users
    told = 0
    for u in users:
        if settings.notify_in_app:
            try:
                with transaction.atomic():
                    ContractNotification.objects.create(user=u, contract=contract, kind=kind,
                                                        message=message[:500], dedup_key=dedup_key[:200])
                told += 1
            except IntegrityError:
                continue  # already told about this one
        if settings.notify_email and _wants_email(u):
            jobs.enqueue('staff_email', f'staff:{dedup_key}:{u.pk}', contract=contract, payload={
                'to': u.email, 'subject': (subject or f'[{contract.reference}] {message}')[:200],
                'body': message, 'link_path': link_path or f'/contracts/{contract.pk}/'})
            told += 0 if settings.notify_in_app else 1
    return told


def mark_read(user, ids=None):
    qs = ContractNotification.objects.filter(user=user, read_at__isnull=True)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    return qs.update(read_at=timezone.now())
