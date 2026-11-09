"""
Permission checks for AI Assist, answered by technician access
(tech_access.resolver).

Every AI capability is technician-only and per customer: a technician holds
it at a customer only through a live technician-access assignment there
(Settings → Security → Technician Access). Customer portal users never hold
one. Staff, editor, admin and superuser flags grant nothing here on their
own — a superuser who works tickets needs an assignment like anyone else.

The older psa_ai_* RoleTemplate flags no longer grant AI capabilities; the
`tech_access_report` command lists roles that still set them so an
administrator can choose matching presets.

Names used by AI code → technician-access capability:

  view_output      ai_analyze or ai_draft   see AI suggestions and results
  analyze          ai_analyze               "Analyze ticket" (one model)
  compare          ai_compare               "Compare models"
  draft            ai_draft                 put an AI draft into the composer
  send_reply       ai_send                  send a reviewed AI draft (normal Send)
  apply_change     ai_apply_change          apply an AI-suggested ticket change
  create_workflow  ai_apply_change          start an AI-suggested workflow
  approve_others   review_others            act on someone else's AI request
  rmm_handoff      rmm_handoff
  diagnose         diagnostics_readonly
  remote_launch    remote_view
  fix_review       fix_refer
  profile_admin    (security administrators only)

Each check reads current rows, so revoking access applies to the next call,
including calls made on a technician's behalf for a queued job.
"""
from __future__ import annotations

ALIASES = {
    'analyze': 'ai_analyze',
    'compare': 'ai_compare',
    'draft': 'ai_draft',
    'send_reply': 'ai_send',
    'apply_change': 'ai_apply_change',
    'create_workflow': 'ai_apply_change',
    'approve_others': 'review_others',
    'rmm_handoff': 'rmm_handoff',
    'diagnose': 'diagnostics_readonly',
    'remote_launch': 'remote_view',
    'fix_review': 'fix_refer',
}


def _is_technician(user) -> bool:
    from tech_access.resolver import is_technician
    return is_technician(user)


def decision(user, organization, capability, ticket=None, asset=None):
    from tech_access.resolver import Decision, decide
    if capability == 'view_output':
        a = decide(user, organization, 'ai_analyze', ticket=ticket)
        return a if a.allowed else decide(user, organization, 'ai_draft', ticket=ticket)
    if capability == 'profile_admin':
        ok = _is_technician(user) and user.is_superuser
        return Decision('allowed' if ok else 'off', 'Security administrators only.', '', capability)
    return decide(user, organization, ALIASES.get(capability, capability), ticket=ticket, asset=asset)


def has_capability(user, organization, capability: str, ticket=None, asset=None) -> bool:
    """The one check every AI path uses. `organization` is the ticket's."""
    return decision(user, organization, capability, ticket=ticket, asset=asset).allowed


def _ticket_of(suggestion):
    return suggestion.native_ticket if suggestion.native_ticket_id else None


def can_view_suggestion(user, suggestion, request=None) -> bool:
    return has_capability(user, suggestion.organization, 'view_output', ticket=_ticket_of(suggestion))


def can_send_reply(user, suggestion, request=None) -> bool:
    """AI replies are never sent from the suggestion itself: the draft goes
    into the composer and the normal Send publishes it. This answers whether
    the technician may send a reply that started as an AI draft."""
    if suggestion.kind != 'reply':
        return False
    return has_capability(user, suggestion.organization, 'send_reply', ticket=_ticket_of(suggestion))


def can_apply_action(user, suggestion, request=None) -> bool:
    if suggestion.kind != 'action':
        return False
    return has_capability(user, suggestion.organization, 'apply_change', ticket=_ticket_of(suggestion))


def can_request_triage(user, organization, request=None) -> bool:
    return has_capability(user, organization, 'analyze')


def can_approve_others(user, suggestion, request=None) -> bool:
    """Act on someone else's pending AI request: needs review_others and the
    capability the request itself needs."""
    if not has_capability(user, suggestion.organization, 'approve_others'):
        return False
    need = 'send_reply' if suggestion.kind == 'reply' else 'apply_change'
    return has_capability(user, suggestion.organization, need)
