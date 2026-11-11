"""
RMM permission and security model (Phase 8).

The API other code calls (see docs/plans/coordination/phase8-permissions.md):

    from rmm_permissions import can, rmm_action, require, record_remote_refusal

    can(user, organization, action, device=None, ticket=None) -> Decision
    rmm_action(user, organization, action, device=None, ticket=None, digest='', request=None) -> Decision
    require(...)  -> Decision, or raises RMMPermissionDenied
    record_remote_refusal(decision, user, organization, code='', message='', request=None) -> Decision

Decision: allowed, needs_approval, approval_level, reason, grant, source,
rem0te_scope, approval_id, steps; `permitted_now` (and bool()) = may run now.
"""
from .decision import (Decision, RMMPermissionDenied, Step, audit_denial, can, effective,  # noqa: F401
                       record_remote_refusal, require, rmm_action)
