"""Object-level checks shared by browser, mobile, REST and extension vault handlers."""
from accounts.permission_utils import filter_by_org_perm, user_has_org_perm


def visible_passwords(user, qs=None):
    """Entries whose existence (title, username, counts) `user` may see.

    `vault_view` in the entry's customer decides — the same rule as the
    /vault/ section gate, search, REST, GraphQL, mobile and the extension.
    Seeing an entry is separate from revealing it (`vault_view_password`).
    """
    if qs is None:
        from .models import Password
        qs = Password.objects.all()
    return filter_by_org_perm(qs, user, 'vault_view')


def can_access_password(user, password, permission='vault_view_password'):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if password.is_personal:
        return password.personal_owner_id == user.pk
    return user_has_org_perm(user, password.organization_id, permission)


class RevealDenied(Exception):
    """A plaintext reveal was refused. `status` is the HTTP status to answer with."""

    def __init__(self, status, detail, requires_approval=False):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.requires_approval = requires_approval


def _usable_approval(password, user):
    from .models import VaultRevealRequest
    approval = (VaultRevealRequest.objects
                .filter(password=password, requester=user,
                        status='approved', revealed_at__isnull=True)
                .order_by('-decided_at').first())
    if approval is None or not approval.is_currently_valid:
        return None
    return approval


def gate_reveal(request, password):
    """Raise RevealDenied unless request.user may see this password's secret now.

    Every channel that returns plaintext (or a TOTP code) must pass the same
    gates as the web reveal: the per-entry permission, the approval
    requirement, and VaultAccessRule — which fails closed.
    """
    if not can_access_password(request.user, password):
        raise RevealDenied(403, 'Password reveal permission required')
    _gate_approval_and_rules(request, password)


def gate_portal_reveal(request, password):
    """`gate_reveal` for the customer portal (v3.17.660).

    Portal users don't hold staff vault permissions; whether the entry is
    shared with them is the entry's own client-access setting
    (`visible_to_portal_user`). The approval requirement and VaultAccessRule
    apply to them exactly as to technicians — before v3.17.660 the portal
    skipped both.
    """
    if not password.visible_to_portal_user(request.user):
        raise RevealDenied(403, 'Not authorised.')
    _gate_approval_and_rules(request, password)


def _gate_approval_and_rules(request, password):
    if password.requires_reveal_approval and _usable_approval(password, request.user) is None:
        raise RevealDenied(403, 'This credential requires approval before reveal.',
                           requires_approval=True)
    try:
        from .access_rules import evaluate
        decision = evaluate(password, request.user, request)
    except Exception:
        raise RevealDenied(503, 'Vault access policy is temporarily unavailable')
    if not decision.get('allowed', False):
        raise RevealDenied(403, decision.get('reason') or 'Access denied')


def consume_approval(password, user):
    """Mark the single-use approval spent after a successful reveal."""
    if password.requires_reveal_approval:
        approval = _usable_approval(password, user)
        if approval is not None:
            approval.mark_revealed()
