"""
Signal handlers that turn server-side state changes into mobile pushes
(v3.17.463 baseline, expanded v3.17.467). Triggers:

  * `psa.Ticket` assignment (new + reassignment) → push to assignee.
  * `psa.TicketComment` create → push the ticket's assignee, unless
    the commenter IS the assignee (so techs don't push themselves).
  * `scheduling.TaskAssignment` create → push the newly-assigned user.
  * `processes.ProcessExecution` create → push the `assigned_to` user
    when the execution is created by someone else (or for self-assign,
    the user already knows).
  * `vault.VaultRevealRequest` `status` flips to `approved` → push the
    original requester so they know they can reveal.

Each receiver is wrapped in try/except — a push failure must never
disrupt the save that triggered it. Apps that aren't installed (e.g.
`psa` missing) are skipped silently in the registration.

Registered in `api_mobile.apps.ApiMobileConfig.ready()`.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger('api_mobile.signals')

# Sentinel attrs set during pre_save so post_save can compare. Scoped to
# the in-memory instance for the duration of the save.
_PRESAVE_ASSIGNEE_ATTR = '_api_mobile_prev_assigned_to_id'
_PRESAVE_STATUS_ATTR = '_api_mobile_prev_status'


def _dispatch_push(user, title: str, body: str, data: dict) -> None:
    """
    Single point of egress for every receiver in this file. Wrapped here
    so tests can patch `api_mobile.signals._dispatch_push` without
    chasing the per-receiver `from .push import send_push_to_user` shape.
    """
    try:
        from .push import send_push_to_user
        send_push_to_user(user, title=title, body=body, data=data)
    except Exception as e:  # noqa: BLE001
        logger.exception('dispatch_push failed: %s', e)


# ============================================================
# Tickets — assignment + comments
# ============================================================
def _register_ticket_signals():
    try:
        from psa.models import Ticket, TicketComment
    except Exception:
        return

    @receiver(pre_save, sender=Ticket, dispatch_uid='api_mobile_ticket_presave_v1', weak=False)
    def _ticket_presave(sender, instance, **kwargs):
        if instance.pk:
            try:
                prev = Ticket.objects.filter(pk=instance.pk).only('assigned_to_id').first()
                setattr(instance, _PRESAVE_ASSIGNEE_ATTR, prev.assigned_to_id if prev else None)
            except Exception:
                setattr(instance, _PRESAVE_ASSIGNEE_ATTR, None)
        else:
            setattr(instance, _PRESAVE_ASSIGNEE_ATTR, None)

    @receiver(post_save, sender=Ticket, dispatch_uid='api_mobile_ticket_postsave_v1', weak=False)
    def _ticket_postsave(sender, instance, created, **kwargs):
        prev_assignee = getattr(instance, _PRESAVE_ASSIGNEE_ATTR, None)
        new_assignee_id = instance.assigned_to_id
        if not new_assignee_id:
            return
        if created or (prev_assignee != new_assignee_id):
            try:
                ticket_num = instance.ticket_number or f'#{instance.pk}'
                subject = (instance.subject or 'Ticket')[:80]
                _dispatch_push(
                    instance.assigned_to,
                    title=f'Assigned: {ticket_num}',
                    body=subject,
                    data={
                        'kind': 'ticket',
                        'ticket_id': instance.pk,
                        'route': f'/tickets/{instance.pk}',
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.exception('ticket assignment push failed: %s', e)

    @receiver(post_save, sender=TicketComment, dispatch_uid='api_mobile_ticket_comment_v1', weak=False)
    def _ticket_comment_postsave(sender, instance, created, **kwargs):
        """Push the ticket's assignee when someone else comments on
        their ticket. Internal comments still push — the assignee
        usually wants the visibility, and internal/external is the
        comment's audience scope, not whether to notify the owner."""
        if not created:
            return
        try:
            ticket = instance.ticket
            if not ticket or not ticket.assigned_to_id:
                return
            # Don't push the assignee for their own comment
            if instance.author_id and instance.author_id == ticket.assigned_to_id:
                return
            ticket_num = ticket.ticket_number or f'#{ticket.pk}'
            author_name = (
                instance.author.get_full_name() or instance.author.username
                if instance.author_id else 'Someone'
            )
            body = (instance.body or '')[:160]
            _dispatch_push(
                ticket.assigned_to,
                title=f'New comment on {ticket_num}',
                body=f'{author_name}: {body}',
                data={
                    'kind': 'ticket_comment',
                    'ticket_id': ticket.pk,
                    'comment_id': instance.pk,
                    'route': f'/tickets/{ticket.pk}',
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.exception('ticket comment push failed: %s', e)


# ============================================================
# Scheduled tasks — assignment
# ============================================================
def _register_scheduling_signals():
    try:
        from scheduling.models import TaskAssignment
    except Exception:
        return

    @receiver(post_save, sender=TaskAssignment, dispatch_uid='api_mobile_task_assignment_v1', weak=False)
    def _task_assignment_postsave(sender, instance, created, **kwargs):
        if not created:
            return
        try:
            task = instance.task
            if not task:
                return
            _dispatch_push(
                instance.user,
                title=f'New task: {task.title[:60]}',
                body=(task.description or 'Tap to view')[:160],
                data={
                    'kind': 'task',
                    'task_id': task.pk,
                    'assignment_id': instance.pk,
                    'route': '/dispatch',
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.exception('task assignment push failed: %s', e)


# ============================================================
# Workflow / Process executions — new run assigned
# ============================================================
def _register_process_signals():
    try:
        from processes.models import ProcessExecution
    except Exception:
        return

    @receiver(post_save, sender=ProcessExecution,
              dispatch_uid='api_mobile_process_exec_v1', weak=False)
    def _process_exec_postsave(sender, instance, created, **kwargs):
        if not created:
            return
        # Self-starts don't need a push — the user already has the screen
        # open. Only push when someone else assigned this run.
        if instance.assigned_to_id and instance.assigned_to_id == instance.started_by_id:
            return
        try:
            if not instance.assigned_to_id:
                return
            proc_title = instance.process.title if instance.process_id else 'Workflow'
            _dispatch_push(
                instance.assigned_to,
                title=f'Workflow assigned: {proc_title[:60]}',
                body='Tap to start the run',
                data={
                    'kind': 'process_execution',
                    'execution_id': instance.pk,
                    'route': f'/workflows/exec/{instance.pk}',
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.exception('process execution push failed: %s', e)


# ============================================================
# Vault reveal requests — approval notification
# ============================================================
def _register_vault_signals():
    try:
        from vault.models import VaultRevealRequest
    except Exception:
        return

    @receiver(pre_save, sender=VaultRevealRequest,
              dispatch_uid='api_mobile_vault_reveal_presave_v1', weak=False)
    def _vrr_presave(sender, instance, **kwargs):
        if instance.pk:
            try:
                prev = VaultRevealRequest.objects.filter(pk=instance.pk).only('status').first()
                setattr(instance, _PRESAVE_STATUS_ATTR, prev.status if prev else None)
            except Exception:
                setattr(instance, _PRESAVE_STATUS_ATTR, None)
        else:
            setattr(instance, _PRESAVE_STATUS_ATTR, None)

    @receiver(post_save, sender=VaultRevealRequest,
              dispatch_uid='api_mobile_vault_reveal_postsave_v1', weak=False)
    def _vrr_postsave(sender, instance, created, **kwargs):
        # Fire when transitioning from non-approved → approved.
        prev = getattr(instance, _PRESAVE_STATUS_ATTR, None)
        if instance.status != 'approved':
            return
        if not created and prev == 'approved':
            return  # already-approved save, e.g. mark_revealed
        try:
            if not instance.requester_id:
                return
            try:
                pw_title = instance.password.title if instance.password_id else 'a credential'
            except Exception:
                pw_title = 'a credential'
            _dispatch_push(
                instance.requester,
                title='Vault reveal approved',
                body=f'You can now reveal {pw_title[:80]}',
                data={
                    'kind': 'vault_reveal_approved',
                    'password_id': instance.password_id,
                    'route': f'/vault/{instance.password_id}'
                            if instance.password_id else '/vault',
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.exception('vault reveal approval push failed: %s', e)


def register():
    """Called from AppConfig.ready(). Idempotent — Django signals dedupe
    on `dispatch_uid`."""
    _register_ticket_signals()
    _register_scheduling_signals()
    _register_process_signals()
    _register_vault_signals()


# ---------------------------------------------------------------------------
# Token lifecycle: a new password ends every mobile session.
# ---------------------------------------------------------------------------
# Mobile tokens have no expiry by default. Before this, a password change or
# an administrator's password reset after a compromise left a stolen phone
# token working until someone revoked mobile sessions by hand. Deactivation
# was already covered (MobileTokenAuthentication rejects inactive users).

from django.contrib.auth import get_user_model as _get_user_model

_PRESAVE_PASSWORD_ATTR = '_api_mobile_prev_password'


@receiver(pre_save, sender=_get_user_model(), dispatch_uid='api_mobile_remember_password')
def _remember_password(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        return
    try:
        prev = sender.objects.filter(pk=instance.pk).values_list('password', flat=True).first()
    except Exception:
        prev = None
    setattr(instance, _PRESAVE_PASSWORD_ATTR, prev)


@receiver(post_save, sender=_get_user_model(), dispatch_uid='api_mobile_revoke_on_password_change')
def _revoke_on_password_change(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw or created:
        return
    # Django re-hashes an unchanged password on login when the hasher
    # settings change, saving update_fields={'password'}; that is not a new
    # password and must not sign the user out of their phone.
    if update_fields is not None and set(update_fields) == {'password'}:
        return
    prev = getattr(instance, _PRESAVE_PASSWORD_ATTR, None)
    if prev is None or prev == instance.password:
        return
    try:
        from .models import MobileAuthToken
        MobileAuthToken.revoke_all_for(instance)
    except Exception:
        logger.exception('Could not revoke mobile sessions after a password change')
