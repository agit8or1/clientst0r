"""Object-level checks shared by browser, mobile, REST and extension vault handlers."""
from accounts.permission_utils import user_has_org_perm


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
