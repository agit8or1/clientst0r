"""
PSA signal handlers - fire WorkflowRule engine on ticket / comment events,
plus tech notifications when a ticket gets assigned or scheduled.

Kept minimal: a status change is detected via a pre_save snapshot of the
old status_id, then post_save dispatches the appropriate trigger. Each
handler swallows engine errors so workflow misconfiguration never blocks
ticket save flow.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Ticket, TicketComment


logger = logging.getLogger('psa.signals')


# Ticket ids currently inside _sync_sla_state. The SLA helpers save the
# ticket, which re-fires post_save; this stops that recursing.
_SLA_SYNCING = set()

# ticket_id -> {status_id, assigned_to_id, resolution_due_at} captured pre_save
_PRIOR_TICKET = {}


@receiver(pre_save, sender=Ticket)
def _enforce_operational_signoff(sender, instance, **kwargs):
    """Phase 20 v9 (v3.17.277): block transitions INTO a ticket status
    flagged `requires_signoff=True` unless `signed_off_at` is populated.

    The check runs only for existing tickets where the status_id
    actually changed (not on every save), so updating arbitrary fields
    on a closed ticket doesn't unexpectedly throw.
    """
    if not instance.pk or not instance.status_id:
        return
    try:
        prev_status_id = (Ticket.objects.only('status_id')
                          .get(pk=instance.pk).status_id)
    except Ticket.DoesNotExist:
        return
    if prev_status_id == instance.status_id:
        return
    target = instance.status
    if target is None or not getattr(target, 'requires_signoff', False):
        return
    if instance.signed_off_at is None:
        from django.core.exceptions import ValidationError as _VE
        raise _VE(
            f'Ticket {instance.ticket_number or instance.pk} cannot move to '
            f'"{target.name}" without an operational sign-off. Run '
            f'Ticket.sign_off() first.'
        )
    # Phase 21 v8 (v3.17.312): block sign-off-required transitions
    # while any required checklist item is still incomplete.
    if instance.has_outstanding_checklist:
        from django.core.exceptions import ValidationError as _VE
        raise _VE(
            f'Ticket {instance.ticket_number or instance.pk} cannot move to '
            f'"{target.name}" — required checklist items are incomplete.'
        )


@receiver(pre_save, sender=Ticket)
def _capture_prior_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            prev = Ticket.objects.only(
                'status_id', 'assigned_to_id', 'resolution_due_at',
            ).get(pk=instance.pk)
            _PRIOR_TICKET[instance.pk] = {
                'status_id': prev.status_id,
                'assigned_to_id': prev.assigned_to_id,
                'resolution_due_at': prev.resolution_due_at,
            }
        except Ticket.DoesNotExist:
            _PRIOR_TICKET[instance.pk] = {
                'status_id': None,
                'assigned_to_id': None,
                'resolution_due_at': None,
            }
    else:
        _PRIOR_TICKET[instance.pk] = {
            'status_id': None,
            'assigned_to_id': None,
            'resolution_due_at': None,
        }


def _sync_sla_state(instance, prior, created):
    """Open or close an SLA pause on a status change, then refresh breach flags.

    Re-entrancy: the helpers below call `ticket.save(update_fields=...)`, which
    fires this signal again. `_SLA_SYNCING` holds the ticket ids currently
    being adjusted so the nested pass returns immediately.
    """
    from psa import sla

    if instance.pk in _SLA_SYNCING:
        return
    _SLA_SYNCING.add(instance.pk)
    try:
        status_changed = (
            created or prior.get('status_id') != instance.status_id
        )
        if status_changed and instance.status_id:
            if instance.status.pauses_sla:
                sla.pause_sla(instance)
            else:
                sla.resume_sla(instance)
        sla.refresh_breach_flags(instance)
    finally:
        _SLA_SYNCING.discard(instance.pk)


@receiver(post_save, sender=Ticket)
def _fire_ticket_workflow(sender, instance, created, **kwargs):
    prior = _PRIOR_TICKET.pop(instance.pk, {
        'status_id': None,
        'assigned_to_id': None,
        'resolution_due_at': None,
    })

    # v3.17.563 — SLA pause accounting and breach state.
    #
    # Hooked here rather than in the ticket views because status changes arrive
    # from several places: the detail view, the mobile API, the inbound email
    # ingester, workflow actions and bulk imports. A pause that only counted
    # when a human clicked the status dropdown would be worse than none.
    #
    # Wrapped and logged: an SLA bookkeeping error must never stop a ticket
    # being saved.
    try:
        _sync_sla_state(instance, prior, created)
    except Exception:
        logger.exception('PSA SLA state sync failed for ticket %s', instance.pk)

    try:
        from .workflow_engine import fire
        if created:
            fire('ticket_created', instance)
        else:
            prior_status_id = prior.get('status_id')
            if prior_status_id is not None and prior_status_id != instance.status_id:
                fire('status_changed', instance, prior_status=prior_status_id)
            fire('ticket_updated', instance)
    except Exception:
        logger.exception('PSA ticket workflow signal failed')

    # Tech notifications - never block save flow
    try:
        from .notifications import notify_tech_assigned, notify_tech_scheduled
        by_user = getattr(instance, 'updated_by', None) or getattr(instance, 'created_by', None)
        # Assignment changed (including new ticket with an assignee)
        if instance.assigned_to_id and instance.assigned_to_id != prior.get('assigned_to_id'):
            notify_tech_assigned(instance, by_user=by_user)
        # Schedule changed (resolution_due_at set or changed) - only when assigned
        if (
            instance.assigned_to_id
            and instance.resolution_due_at
            and instance.resolution_due_at != prior.get('resolution_due_at')
        ):
            notify_tech_scheduled(
                instance,
                by_user=getattr(instance, 'updated_by', None),
                prior_due_date=prior.get('resolution_due_at'),
            )
    except Exception:
        logger.exception('PSA tech notification signal failed')

    # Phase 12 v1 (v3.17.231): CSAT email when ticket transitions to a
    # terminal status. Idempotent — TicketCSATSurvey is OneToOne, so a
    # survey only ever gets created (and emailed) on the first transition.
    try:
        prior_status_id = prior.get('status_id')
        moved_status = (prior_status_id is not None
                        and prior_status_id != instance.status_id)
        if (moved_status
                and instance.status_id
                and getattr(instance.status, 'is_terminal', False)):
            from .csat import maybe_send_csat
            maybe_send_csat(instance)
    except Exception:
        logger.exception('PSA CSAT survey hook failed')

    # Phase 12 v8 (v3.17.238): SMS portal-side requester on status change.
    try:
        prior_status_id = prior.get('status_id')
        if prior_status_id is not None and prior_status_id != instance.status_id:
            from .notifications import notify_portal_status_change
            notify_portal_status_change(instance)
    except Exception:
        logger.exception('PSA portal SMS notify hook failed')


@receiver(post_save, sender=TicketComment)
def _fire_comment_workflow(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from .workflow_engine import fire
        fire('comment_added', instance.ticket)
    except Exception:
        logger.exception('PSA comment workflow signal failed')


# ---------------------------------------------------------------------------
# Phase 7 -- two-way outsourcing sync (outbound side)
# ---------------------------------------------------------------------------

@receiver(post_save, sender=TicketComment)
def _fan_out_comment_to_partners(sender, instance, created, **kwargs):
    """When a comment lands on a ticket with active TicketShare rows,
    fire an HMAC-signed POST to each partner's webhook. Failures are
    logged but never block the comment save flow.

    Comments authored by the partner (source='partner') are skipped to
    avoid loops. Internal-only notes are skipped -- partners only see
    public-visible comments.
    """
    if not created:
        return
    if getattr(instance, 'source', '') == 'partner':
        return
    if instance.is_internal:
        return
    try:
        import time as _time

        from .views import _phase7_post_to_partner

        active_shares = instance.ticket.shares.filter(status__in=['accepted']).select_related('partner_org')
        for share in active_shares:
            try:
                payload = {
                    'event': 'comment',
                    'ticket_number': instance.ticket.ticket_number,
                    'share_pk': share.pk,
                    'payload': {
                        'body': instance.body or '',
                        'author': (
                            instance.author.get_username() if instance.author_id
                            else (instance.author_name or 'system')
                        ),
                        'author_email': instance.author_email or (
                            instance.author.email if instance.author_id else ''
                        ),
                        'is_internal': False,
                    },
                    'ts': int(_time.time()),
                }
                _phase7_post_to_partner(share, payload)
            except Exception:
                logger.exception('Outbound partner comment fan-out failed for share %s', share.pk)
    except Exception:
        logger.exception('Outbound partner comment fan-out top-level failed')


@receiver(post_save, sender=Ticket)
def _fan_out_status_to_partners(sender, instance, created, **kwargs):
    """When a Ticket status changes, fire an HMAC-signed POST to each
    partner with an active share. Fan-out is best-effort -- failures
    log but never block ticket save.

    Reuses the prior-status snapshot captured by `_capture_prior_status`.
    Note: that handler pops the snapshot in `_fire_ticket_workflow`; we
    must run BEFORE it -- since signal order is registration order, we
    instead recompute by checking what the workflow engine logs. To keep
    the fan-out independent of receiver ordering, we re-fetch the prior
    status via a separate snapshot dict.
    """
    if created:
        return
    try:
        prior = _PRIOR_STATUS_FOR_PARTNERS.pop(instance.pk, None)
        if prior is None or prior == instance.status_id:
            return
        active_shares = instance.shares.filter(status__in=['accepted']).select_related('partner_org')
        if not active_shares.exists():
            return
        import time as _time

        from .views import _phase7_post_to_partner

        status_slug = instance.status.slug if instance.status_id else ''
        for share in active_shares:
            try:
                payload = {
                    'event': 'status',
                    'ticket_number': instance.ticket_number,
                    'share_pk': share.pk,
                    'payload': {
                        'status': status_slug,
                        'status_name': (instance.status.name if instance.status_id else ''),
                    },
                    'ts': int(_time.time()),
                }
                _phase7_post_to_partner(share, payload)
            except Exception:
                logger.exception('Outbound partner status fan-out failed for share %s', share.pk)
    except Exception:
        logger.exception('Outbound partner status fan-out top-level failed')


# Separate snapshot dict so the fan-out handler is independent of
# `_fire_ticket_workflow` consuming `_PRIOR_TICKET`.
_PRIOR_STATUS_FOR_PARTNERS = {}


@receiver(pre_save, sender=Ticket)
def _capture_prior_status_for_partners(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        prev = Ticket.objects.only('status_id').get(pk=instance.pk)
        _PRIOR_STATUS_FOR_PARTNERS[instance.pk] = prev.status_id
    except Ticket.DoesNotExist:
        _PRIOR_STATUS_FOR_PARTNERS[instance.pk] = None


# v3.17.276 — Phase 20 v8: change-request transition tracking. Capture
# any implementation_status field change that didn't go through the
# `transition_status()` method (legacy admin edits, direct ORM updates)
# so the audit trail stays complete.
from .models import ChangeRequest, ChangeRequestTransition

_PRIOR_CHANGE_STATUS = {}


@receiver(pre_save, sender=ChangeRequest)
def _capture_prior_change_status(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        prev = ChangeRequest.objects.only('implementation_status').get(pk=instance.pk)
        _PRIOR_CHANGE_STATUS[instance.pk] = prev.implementation_status
    except ChangeRequest.DoesNotExist:
        _PRIOR_CHANGE_STATUS[instance.pk] = None


@receiver(post_save, sender=ChangeRequest)
def _record_change_status_transition(sender, instance, created, **kwargs):
    prev = _PRIOR_CHANGE_STATUS.pop(instance.pk, None)
    if created or prev is None:
        return
    if prev == instance.implementation_status:
        return
    # `transition_status()` sets this flag while it saves to avoid
    # double-recording the transition (it writes the row itself with
    # by_user attribution and the caller's note).
    if getattr(instance, '_suppress_transition_signal', False):
        return
    try:
        ChangeRequestTransition.objects.create(
            change_request=instance,
            from_status=prev,
            to_status=instance.implementation_status,
            by_user=None,
            note='Captured by post_save signal (no by_user on direct edit)',
        )
    except Exception:
        logger.exception('Change request transition signal failed')


@receiver(post_save, sender=Ticket)
def _auto_create_change_request(sender, instance, created, **kwargs):
    """When a Ticket of type 'change' is created, auto-spawn a draft
    ChangeRequest. The ticket_type slug 'change' is the link contract."""
    if not created:
        return
    try:
        if instance.ticket_type and instance.ticket_type.slug == 'change':
            from .models import ChangeRequest
            ChangeRequest.objects.get_or_create(
                ticket=instance,
                defaults={'organization': instance.organization},
            )
    except Exception:
        logger.exception('PSA change request auto-create signal failed')


# v3.17.259 — Phase 20 v2: auto-flag Invoice for approval when its total
# crosses the SystemSetting thresholds. Fires on every save; skips if
# the invoice is already approved or already pending.
from .models import Invoice


@receiver(post_save, sender=Invoice)
def _auto_flag_invoice_approval(sender, instance, created, **kwargs):
    if instance.requires_approval or instance.approved_at:
        return  # already handled or already approved
    try:
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
    except Exception:
        return
    total_thresh = float(ss.invoice_approval_threshold_total or 0)
    pct_thresh = int(ss.invoice_approval_overage_pct or 0)
    if total_thresh <= 0 and pct_thresh <= 0:
        return  # both knobs disabled
    flagged = instance.flag_for_approval(
        total_threshold=total_thresh if total_thresh > 0 else None,
        overage_pct_threshold=pct_thresh if pct_thresh > 0 else None,
    )
    if flagged:
        # flag_for_approval mutates fields but doesn't save — persist now,
        # using update() to dodge re-firing this signal.
        Invoice.objects.filter(pk=instance.pk).update(
            requires_approval=True,
            approval_reason=instance.approval_reason,
        )


# v3.17.273 — Phase 20 v5: conditional approval auto-routing on Quote.
# Fires when total >= threshold AND no open approval chain exists yet.
from .models import Quote, PSAApproval


@receiver(post_save, sender=Quote)
def _auto_route_quote_for_approval(sender, instance, created, **kwargs):
    if instance.status not in ('draft', 'sent'):
        return  # only route on early statuses; later transitions are sealed
    try:
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
    except Exception:
        return
    threshold = float(ss.quote_approval_threshold_total or 0)
    if threshold <= 0:
        return  # disabled
    if not instance.total or float(instance.total) < threshold:
        return  # below threshold — no auto-route
    # Skip if any open chain already exists for this quote
    open_qs = PSAApproval.objects.filter(
        object_type='psa.Quote', object_id=instance.pk,
    ).exclude(status__in=['approved', 'denied', 'cancelled'])
    if open_qs.exists():
        return
    try:
        instance.send_for_approval(
            user=getattr(instance, 'created_by', None),
            default_threshold_total=threshold,
        )
    except Exception:
        logger.exception('Auto-route quote for approval failed')
