"""
Customer portal views.

Hard rules:
  * Tickets visible: organization belongs to the user via Membership AND
    visibility != 'staff' AND client_can_view=True (when staff visibility flag).
    Internal-only comments and attachments are filtered out at queryset time.
  * Per-client opt-in: ClientPSASettings.portal_enabled must be True for
    the user's organization.
  * No staff/MSP nav, no internal-staff routes — the portal_base.html
    template provides a stripped layout.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Membership
from audit.models import AuditLog
from psa.feature_flags import is_psa_enabled, is_psa_enabled_for_client
from psa.models import (
    ClientPSASettings, Queue, Ticket, TicketAttachment,
    TicketComment, TicketPriority, TicketStatus, TicketType,
)


def _portal_membership(request):
    """Return the active Membership for the request's user OR None.
    Restricted to users with at least one active membership in an org
    that has portal_enabled=True. Superusers are NOT auto-granted —
    the portal is for clients, period.
    """
    user = request.user
    if not user.is_authenticated:
        return None
    qs = Membership.objects.filter(user=user, is_active=True).select_related('organization')
    for m in qs:
        try:
            settings = m.organization.psa_settings
            if settings.portal_enabled:
                return m
        except ClientPSASettings.DoesNotExist:
            continue
    return None


def portal_required(view_func):
    """Decorator: 404 if PSA is off globally OR the user has no portal-enabled org."""
    from functools import wraps

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/account/login/?next=' + request.path)
        if not is_psa_enabled():
            raise Http404('Portal is unavailable')
        m = _portal_membership(request)
        if m is None:
            raise Http404('Portal is not enabled for your account')
        request.portal_membership = m
        return view_func(request, *args, **kwargs)

    return wrapped


def _portal_feature_enabled(name) -> bool:
    """v3.17.243: lookup a Phase 12 portal feature flag on SystemSetting."""
    try:
        from core.models import SystemSetting
        return bool(getattr(SystemSetting.get_settings(), name, False))
    except Exception:
        return False


def _active_announcements(request, organization):
    """v3.17.232: announcements visible to the requester for this org.
    Filters out session-dismissed IDs so each portal user only sees
    each dismissable banner once (until they clear their session).
    Returns an empty list when `psa_portal_announcements_enabled` is off
    (v3.17.243 feature toggle).
    """
    if not _portal_feature_enabled('psa_portal_announcements_enabled'):
        return []
    from .models import PortalAnnouncement
    dismissed = set(request.session.get('portal_dismissed_announcements') or [])
    return [
        a for a in PortalAnnouncement.active_for_org(organization)
        if a.pk not in dismissed
    ]


@portal_required
def ticket_list(request):
    """Tickets owned by the user's portal organization, client-visible only."""
    m = request.portal_membership
    qs = Ticket.objects.filter(organization=m.organization).select_related(
        'status', 'priority', 'queue', 'ticket_type',
    )
    qs = qs.filter(client_can_view=True)
    status = request.GET.get('status')
    if status == 'open':
        qs = qs.filter(status__is_terminal=False)
    elif status == 'closed':
        qs = qs.filter(status__is_terminal=True)
    return render(request, 'portal/ticket_list.html', {
        'tickets': qs.order_by('-created_at')[:200],
        'status_filter': status or '',
        'organization': m.organization,
        'announcements': _active_announcements(request, m.organization),
    })


@portal_required
@require_http_methods(['POST'])
def announcement_dismiss(request, pk):
    """v3.17.232: portal user dismisses an announcement for the rest of
    the session. Only works on `is_dismissable=True` announcements; the
    flag is enforced server-side in case the client lies.
    """
    if not _portal_feature_enabled('psa_portal_announcements_enabled'):
        raise Http404('Announcements are not enabled')
    from .models import PortalAnnouncement
    m = request.portal_membership
    try:
        ann = PortalAnnouncement.objects.get(pk=pk, organization=m.organization)
    except PortalAnnouncement.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)
    if not ann.is_dismissable:
        return JsonResponse({'error': 'not dismissable'}, status=400)
    dismissed = list(request.session.get('portal_dismissed_announcements') or [])
    if pk not in dismissed:
        dismissed.append(pk)
        request.session['portal_dismissed_announcements'] = dismissed
        request.session.modified = True
    return JsonResponse({'ok': True})


@portal_required
def ticket_detail(request, ticket_number):
    from psa.models import TicketVote
    m = request.portal_membership
    ticket = get_object_or_404(
        Ticket.objects.filter(organization=m.organization, client_can_view=True),
        ticket_number=ticket_number,
    )
    raw_comments = list(
        ticket.comments.filter(is_internal=False)
            .select_related('parent_comment').order_by('created_at')
    )
    # v3.17.237: build a top-level + replies tree so the template can
    # render indented threads. Replies whose parent is internal/missing
    # collapse to top-level.
    by_id = {c.id: c for c in raw_comments}
    threads = []
    for c in raw_comments:
        c.replies_in_thread = []
    for c in raw_comments:
        if c.parent_comment_id and c.parent_comment_id in by_id:
            by_id[c.parent_comment_id].replies_in_thread.append(c)
        else:
            threads.append(c)
    attachments = ticket.attachments.filter(is_internal=False)
    voting_enabled = _portal_feature_enabled('psa_portal_voting_enabled')
    vote_count = TicketVote.objects.filter(ticket=ticket).count() if voting_enabled else 0
    user_voted = (TicketVote.objects.filter(ticket=ticket, user=request.user).exists()
                  if voting_enabled else False)
    escalation_enabled = _portal_feature_enabled('psa_portal_escalation_enabled')
    return render(request, 'portal/ticket_detail.html', {
        'ticket': ticket,
        'threads': threads,
        'attachments': attachments,
        'organization': m.organization,
        'vote_count': vote_count,
        'user_voted': user_voted,
        'voting_enabled': voting_enabled,
        'escalation_enabled': escalation_enabled,
    })


@portal_required
@require_http_methods(['POST'])
def ticket_escalate(request, ticket_number):
    """
    Phase 12 v6 (v3.17.236): portal user escalates a ticket. Sets
    escalated_at/by/reason + posts a public TicketComment so the staff
    timeline shows the escalation in order.
    Idempotent — a second post just updates the reason.
    """
    if not _portal_feature_enabled('psa_portal_escalation_enabled'):
        raise Http404('Customer escalation is not enabled')
    m = request.portal_membership
    ticket = get_object_or_404(
        Ticket.objects.filter(organization=m.organization, client_can_view=True),
        ticket_number=ticket_number,
    )
    reason = (request.POST.get('reason') or '').strip()[:500]
    if not reason:
        messages.error(request, 'Please describe why this needs urgent attention.')
        return redirect('portal:ticket_detail', ticket_number=ticket_number)
    was_escalated = ticket.escalated_at is not None
    ticket.escalated_at = timezone.now()
    ticket.escalated_by = request.user
    ticket.escalation_reason = reason
    ticket.save(update_fields=['escalated_at', 'escalated_by',
                                'escalation_reason', 'updated_at'])
    TicketComment.objects.create(
        ticket=ticket, author=request.user,
        body=f'[Escalated by client] {reason}',
        is_internal=False, source='portal',
        author_name=request.user.get_full_name() or request.user.username,
        author_email=request.user.email or '',
    )
    if was_escalated:
        messages.info(request, 'Escalation reason updated.')
    else:
        messages.success(request, 'Ticket escalated. The team has been notified.')
    return redirect('portal:ticket_detail', ticket_number=ticket_number)


@portal_required
@require_http_methods(['POST'])
def ticket_vote(request, ticket_number):
    """v3.17.235: toggle a portal user's "I care about this too" vote."""
    if not _portal_feature_enabled('psa_portal_voting_enabled'):
        raise Http404('Ticket voting is not enabled')
    from psa.models import TicketVote
    m = request.portal_membership
    ticket = get_object_or_404(
        Ticket.objects.filter(organization=m.organization, client_can_view=True),
        ticket_number=ticket_number,
    )
    existing = TicketVote.objects.filter(ticket=ticket, user=request.user).first()
    if existing:
        existing.delete()
        voted = False
    else:
        TicketVote.objects.create(ticket=ticket, user=request.user)
        voted = True
    count = TicketVote.objects.filter(ticket=ticket).count()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'voted': voted, 'count': count})
    return redirect('portal:ticket_detail', ticket_number=ticket_number)


@portal_required
@require_http_methods(['POST'])
def post_reply(request, ticket_number):
    m = request.portal_membership
    ticket = get_object_or_404(
        Ticket.objects.filter(organization=m.organization, client_can_view=True),
        ticket_number=ticket_number,
    )
    body = (request.POST.get('body') or '').strip()
    if not body:
        messages.error(request, 'Reply cannot be empty.')
        return redirect('portal:ticket_detail', ticket_number=ticket_number)
    if len(body) > 50000:
        body = body[:50000]

    # v3.17.237: threaded reply support. parent_id must reference a
    # comment on the same ticket; missing/invalid → fall back to a
    # top-level reply.
    parent = None
    parent_id = request.POST.get('parent_id')
    if parent_id:
        try:
            parent = TicketComment.objects.get(pk=int(parent_id), ticket=ticket,
                                                is_internal=False)
        except (TicketComment.DoesNotExist, ValueError, TypeError):
            parent = None

    TicketComment.objects.create(
        ticket=ticket, author=request.user, body=body,
        is_internal=False, source='portal',
        author_name=request.user.get_full_name() or request.user.username,
        author_email=request.user.email or '',
        parent_comment=parent,
    )
    ticket.last_client_response_at = timezone.now()
    ticket.save(update_fields=['last_client_response_at'])
    messages.success(request, 'Reply added.')
    return redirect('portal:ticket_detail', ticket_number=ticket_number)


@portal_required
@require_http_methods(['GET', 'POST'])
def ticket_create(request):
    """Client-side ticket submission."""
    m = request.portal_membership

    if request.method == 'POST':
        subject = (request.POST.get('subject') or '').strip()[:300]
        description = (request.POST.get('description') or '').strip()[:50000]
        if not subject:
            messages.error(request, 'Subject is required.')
            return redirect(request.path)

        # Use the client's default queue/priority/type — fall back to any.
        queue = Queue.objects.filter(is_active=True).first()
        priority = TicketPriority.objects.order_by('sort_order').first()
        ticket_type = TicketType.objects.filter(is_active=True).first()
        new_status = TicketStatus.objects.filter(slug='new').first()
        if not (queue and priority and ticket_type and new_status):
            messages.error(request, 'PSA is not configured. Contact support.')
            return redirect('portal:ticket_list')

        ticket = Ticket.objects.create(
            organization=m.organization,
            subject=subject, description=description,
            queue=queue, priority=priority, ticket_type=ticket_type,
            status=new_status, source='portal',
            visibility='client', client_can_view=True,
            requester_name=request.user.get_full_name() or request.user.username,
            requester_email=request.user.email or '',
            created_by=request.user,
        )
        AuditLog.log(
            user=request.user, action='create',
            organization=m.organization,
            object_type='psa.Ticket', object_id=ticket.pk,
            object_repr=ticket.ticket_number,
            description=f'Portal ticket {ticket.ticket_number}: {subject}',
            path=request.path,
        )
        messages.success(request, f'Ticket {ticket.ticket_number} created.')
        return redirect('portal:ticket_detail', ticket_number=ticket.ticket_number)

    return render(request, 'portal/ticket_create.html', {
        'organization': m.organization,
    })


# ---------------------------------------------------------------------------
# Customer-facing quote signing — opaque token URL, no portal login required
# ---------------------------------------------------------------------------

import json as _json_qs

from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods


def _client_ip_qs(request):
    from core.client_ip import get_client_ip
    return get_client_ip(request)


@require_http_methods(['GET', 'POST'])
def quote_sign(request, token):
    """
    Public sign-and-accept page. The token is on `Quote.customer_token`
    and is generated server-side; only the customer with the link can
    sign. POSTing a signature flips the quote to 'accepted', creates the
    QuoteSignature record, and runs Quote.mark_accepted (which optionally
    creates a ticket).
    """
    from psa.models import (
        Queue, Quote, QuoteSignature,
        TicketPriority, TicketStatus, TicketType,
    )

    quote = get_object_or_404(Quote.objects.select_related('client_org'),
                              customer_token=token)

    if request.method == 'POST':
        if quote.status in ('accepted', 'rejected'):
            return render(request, 'portal/quote_sign.html', {
                'quote': quote,
                'organization': quote.client_org,
                'already': True,
            })

        signed_by_name = (request.POST.get('signed_by_name') or '').strip()[:200]
        signed_by_email = (request.POST.get('signed_by_email') or '').strip()[:254]
        signed_by_title = (request.POST.get('signed_by_title') or '').strip()[:200]
        signature_data = (request.POST.get('signature_data') or '').strip()

        if not signed_by_name or not signed_by_email or not signature_data.startswith('data:image/'):
            messages.error(request, 'Please complete the form and draw your signature.')
            return redirect(request.path)
        if len(signature_data) > 200_000:
            messages.error(request, 'Signature image is too large.')
            return redirect(request.path)

        QuoteSignature.objects.update_or_create(
            quote=quote,
            defaults={
                'signed_by_name': signed_by_name,
                'signed_by_email': signed_by_email,
                'signed_by_title': signed_by_title,
                'signature_data': signature_data,
                'ip_address': _client_ip_qs(request),
                'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:400],
            },
        )

        # Flip status + optionally create ticket
        queue = Queue.objects.filter(is_active=True).first()
        priority = TicketPriority.objects.order_by('sort_order').first()
        ttype = TicketType.objects.filter(is_active=True).first()
        new_status = TicketStatus.objects.filter(slug='new').first()
        try:
            quote.mark_accepted(
                user=None, create_ticket=True,
                queue=queue, priority=priority,
                ticket_type=ttype, status=new_status,
            )
        except Exception:
            quote.status = 'accepted'
            quote.save()

        try:
            from audit.models import AuditLog
            AuditLog.log(
                user=None, action='update',
                organization=quote.organization,
                object_type='psa.Quote', object_id=quote.pk,
                object_repr=quote.quote_number,
                description=f'Quote {quote.quote_number} signed by {signed_by_name} <{signed_by_email}> from IP {_client_ip_qs(request)}',
                path=request.path,
                extra_data={'signed_by_email': signed_by_email,
                            'signed_by_name': signed_by_name},
            )
        except Exception:
            pass

        return render(request, 'portal/quote_sign.html', {
            'quote': quote,
            'organization': quote.client_org,
            'just_signed': True,
        })

    return render(request, 'portal/quote_sign.html', {
        'quote': quote,
        'organization': quote.client_org,
        'line_items': quote.line_items.all(),
    })


# ---------------------------------------------------------------------------
# Customer portal KB — articles staff have marked is_client_visible=True
# ---------------------------------------------------------------------------

@portal_required
def kb_list(request):
    """
    List KB articles available to the requesting client. Featured
    articles surface at the top; the rest sort by `portal_view_count`
    (v3.17.234) so popular content is easy to find.
    """
    from django.db.models import Q
    from docs.models import Document
    m = request.portal_membership
    q = (request.GET.get('q') or '').strip()
    qs = Document.objects.filter(
        is_client_visible=True, is_published=True, is_archived=False,
    ).filter(
        Q(is_global=True) | Q(organization=m.organization)
    )
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    featured = list(qs.filter(is_featured_in_portal=True)
                       .order_by('-updated_at')[:10])
    others = list(qs.filter(is_featured_in_portal=False)
                     .order_by('-portal_view_count', '-updated_at')[:200])
    return render(request, 'portal/kb_list.html', {
        'featured': featured,
        'articles': others,
        'query': q,
        'organization': m.organization,
    })


@portal_required
def kb_detail(request, slug):
    """Show a single KB article. Same visibility rule as kb_list."""
    from django.db.models import Q, F
    from docs.models import Document
    m = request.portal_membership
    qs = Document.objects.filter(
        is_client_visible=True, is_published=True, is_archived=False,
    ).filter(
        Q(is_global=True) | Q(organization=m.organization)
    )
    article = get_object_or_404(qs, slug=slug)
    # v3.17.234: increment view counter on each portal open. F() avoids
    # a read-modify-write race when two users open the same article
    # simultaneously.
    Document.objects.filter(pk=article.pk).update(
        portal_view_count=F('portal_view_count') + 1,
    )
    return render(request, 'portal/kb_detail.html', {
        'article': article,
        'organization': m.organization,
    })


# ---------------------------------------------------------------------------
# Customer portal — Vault access (Password reveal + Org-admin management)
# ---------------------------------------------------------------------------

@portal_required
def vault_list(request):
    """List passwords this portal user is allowed to see."""
    from vault.models import Password
    m = request.portal_membership
    qs = Password.objects.filter(
        organization=m.organization,
        is_personal=False,
        client_visible=True,
    ).exclude(client_access_mode='none')
    # Filter to actually-visible: cheap way is iterate with the helper.
    visible = [p for p in qs.order_by('title')[:1000] if p.visible_to_portal_user(request.user)]
    return render(request, 'portal/vault_list.html', {
        'passwords': visible,
        'organization': m.organization,
        'is_org_admin': bool(m.is_org_admin),
    })


@portal_required
@require_http_methods(['POST'])
def vault_reveal(request, pk):
    """Audit-logged password reveal — returns the plaintext as JSON."""
    from django.http import JsonResponse
    from vault.models import Password
    from audit.models import AuditLog
    m = request.portal_membership
    pwd = get_object_or_404(Password, pk=pk, organization=m.organization,
                            is_personal=False, client_visible=True)
    if not pwd.visible_to_portal_user(request.user):
        return JsonResponse({'error': 'Not authorised.'}, status=403)
    try:
        plaintext = pwd.password
    except Exception as exc:
        return JsonResponse({'error': f'decrypt failed: {exc}'}, status=500)
    try:
        AuditLog.log(
            user=request.user, action='view',
            organization=pwd.organization,
            object_type='vault.Password', object_id=pwd.pk,
            object_repr=pwd.title,
            description=f'Portal reveal of {pwd.title} by {request.user.email}',
            path=request.path,
        )
    except Exception:
        pass
    return JsonResponse({'password': plaintext, 'title': pwd.title,
                         'username': pwd.username})


# --- Org Admin management UI -----------------------------------------------

def _require_org_admin(view_func):
    """Decorator: portal_required + must have is_org_admin on the membership."""
    from functools import wraps

    @wraps(view_func)
    @portal_required
    def wrapped(request, *args, **kwargs):
        if not request.portal_membership.is_org_admin:
            raise Http404()
        return view_func(request, *args, **kwargs)

    return wrapped


@_require_org_admin
def org_admin_vault(request):
    """
    Org admin landing — list every password in this org that's in
    `org_admin_managed` mode plus a count of how many users currently
    have access. Click a row to manage individual users.
    """
    from vault.models import Password
    m = request.portal_membership
    items = (Password.objects
             .filter(organization=m.organization, is_personal=False,
                     client_visible=True, client_access_mode='org_admin_managed')
             .prefetch_related('client_allowed_users')
             .order_by('title'))
    return render(request, 'portal/org_admin_vault.html', {
        'items': items,
        'organization': m.organization,
    })


@_require_org_admin
@require_http_methods(['GET', 'POST'])
def org_admin_vault_item(request, pk):
    """Per-item access management — add/remove individual users."""
    from accounts.models import Membership
    from vault.models import Password
    m = request.portal_membership
    pwd = get_object_or_404(
        Password, pk=pk, organization=m.organization,
        is_personal=False, client_visible=True,
        client_access_mode='org_admin_managed',
    )
    if request.method == 'POST':
        # Replace allowed_users with the posted set (only members of the org).
        org_member_ids = set(Membership.objects.filter(
            organization=m.organization, is_active=True,
        ).values_list('user_id', flat=True))
        try:
            posted = {int(x) for x in request.POST.getlist('allowed_user_ids')}
        except ValueError:
            posted = set()
        clean = posted & org_member_ids
        pwd.client_allowed_users.set(list(clean))

        try:
            from audit.models import AuditLog
            AuditLog.log(
                user=request.user, action='update',
                organization=pwd.organization,
                object_type='vault.Password', object_id=pwd.pk,
                object_repr=pwd.title,
                description=f'Org admin {request.user.email} updated access list '
                            f'for {pwd.title} (now {len(clean)} users)',
                path=request.path,
                extra_data={'allowed_user_ids': sorted(clean)},
            )
        except Exception:
            pass
        messages.success(request, f'Updated access for "{pwd.title}".')
        return redirect('portal:org_admin_vault')

    # Prefetch every active org member with their grant state
    members = (Membership.objects
               .filter(organization=m.organization, is_active=True)
               .select_related('user')
               .order_by('user__username'))
    granted_ids = set(pwd.client_allowed_users.values_list('pk', flat=True))
    rows = [
        {'user': mb.user, 'granted': mb.user_id in granted_ids,
         'is_self': mb.user_id == request.user.pk}
        for mb in members
    ]
    return render(request, 'portal/org_admin_vault_item.html', {
        'pwd': pwd,
        'rows': rows,
        'organization': m.organization,
    })


@portal_required
def preferences(request):
    """v3.17.233: portal user notification preferences."""
    from accounts.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        profile.portal_notify_ticket_reply = request.POST.get('reply') == 'on'
        profile.portal_notify_status_change = request.POST.get('status') == 'on'
        profile.portal_notify_csat_invite = request.POST.get('csat') == 'on'
        profile.portal_notify_sms_status_change = request.POST.get('sms_status') == 'on'
        # v3.17.238: portal user can supply / update phone for SMS.
        new_phone = (request.POST.get('phone') or '').strip()[:50]
        if new_phone != profile.phone:
            profile.phone = new_phone
        profile.save(update_fields=[
            'portal_notify_ticket_reply',
            'portal_notify_status_change',
            'portal_notify_csat_invite',
            'portal_notify_sms_status_change',
            'phone',
            'updated_at',
        ])
        messages.success(request, 'Preferences saved.')
        return redirect('portal:preferences')
    return render(request, 'portal/preferences.html', {
        'profile': profile,
        'organization': request.portal_membership.organization,
    })


@portal_required
def approvals_list(request):
    """
    Phase 12 v9 (v3.17.239): pending customer approvals routed to the
    portal user's org. Shows kind, requested_at, related_ticket, and
    accept/reject buttons.
    """
    if not _portal_feature_enabled('psa_portal_customer_approvals_enabled'):
        raise Http404('Customer approvals are not enabled')
    from psa.models import PSAApproval
    m = request.portal_membership
    pending = (PSAApproval.objects
               .filter(organization=m.organization,
                       is_client_approval=True,
                       status='pending')
               .select_related('related_ticket', 'requested_by')
               .order_by('-requested_at'))
    decided = (PSAApproval.objects
               .filter(organization=m.organization,
                       is_client_approval=True)
               .exclude(status='pending')
               .select_related('related_ticket', 'decided_by')
               .order_by('-decided_at')[:25])
    return render(request, 'portal/approvals_list.html', {
        'pending': pending,
        'decided': decided,
        'organization': m.organization,
    })


@portal_required
@require_http_methods(['POST'])
def approval_decide(request, pk):
    """v3.17.239: portal user approves/denies a client-side approval."""
    if not _portal_feature_enabled('psa_portal_customer_approvals_enabled'):
        raise Http404('Customer approvals are not enabled')
    from psa.models import PSAApproval
    m = request.portal_membership
    approval = get_object_or_404(
        PSAApproval,
        pk=pk, organization=m.organization,
        is_client_approval=True, status='pending',
    )
    decision = request.POST.get('decision') or ''
    comment = (request.POST.get('comment') or '').strip()[:5000]
    if decision not in ('approve', 'deny'):
        messages.error(request, 'Pick Approve or Deny.')
        return redirect('portal:approvals_list')
    approval.decide(user=request.user, approved=(decision == 'approve'),
                    comment=comment)
    messages.success(
        request,
        f'Approval marked as {"Approved" if decision == "approve" else "Denied"}.',
    )
    return redirect('portal:approvals_list')
