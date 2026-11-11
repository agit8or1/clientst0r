"""
Build the context payload fed into the AI for a given ticket.

CRITICAL RULES:
  * Never include vault.Password.encrypted_password or any decryption.
  * Never include API keys, tokens, or anything from .env.
  * Sanitize every user-supplied string before it lands in the prompt.
  * Cap total context tokens to keep cost bounded and prompt focused.
  * Cross-tenant contamination is prevented at the queryset layer
    (ticket.organization is the only org we read from).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .guardrails import sanitize_input, wrap_user_content


def _policy_masker(ticket, policy):
    """The customer's sharing rules as a text filter (troubleshoot._Masker):
    contact names and network identifiers replaced, secrets redacted."""
    from .tenant_rules import sharing_rules
    from .troubleshoot import _Masker, _contact_names
    hosts = []
    asset = getattr(ticket, 'related_asset', None)
    if asset is not None:
        hosts.append(getattr(asset, 'hostname', '') or '')
        hosts += [d.hostname for d in asset.rmm_devices.all()] + [d.device_name for d in asset.rmm_devices.all()]
    names = _contact_names(ticket) if hasattr(ticket, 'requester_name') else []
    return sharing_rules(policy), _Masker(sharing_rules(policy), names, hosts)


def build_ticket_context(ticket, policy=None) -> Dict[str, Any]:
    """
    `ticket` is a psa.Ticket OR integrations.PSATicket instance. Returns
    a dict ready for prompt templating + a separate, sanitised+wrapped
    `prompt_text` view for the model.

    With `policy` (the customer's AIBusinessPolicy) the sharing rules apply:
    contact names and network identifiers are masked unless shared, device
    details and KB titles are left out unless shared, every string is
    redacted (services/evidence.redact). The AI routes always pass it
    (services/policy_call.py).
    """
    org = ticket.organization
    rules = mask = None
    if policy is not None:
        rules, mask = _policy_masker(ticket, policy)

    def clean(text, max_chars):
        text = sanitize_input(text or '', max_chars=max_chars)
        return mask(text, max_chars) if mask is not None else text

    subject = clean(getattr(ticket, 'subject', '') or '', 300)
    description = clean(getattr(ticket, 'description', '') or '', 4000)

    # Native ticket → comments. Synced ticket may not have comments in the
    # same shape; degrade gracefully.
    recent_comments: List[Dict[str, str]] = []
    comments_qs = getattr(ticket, 'comments', None)
    if comments_qs is not None:
        for c in comments_qs.select_related('author').order_by('-created_at')[:10]:
            # NEVER expose internal notes' bodies to the model — they're
            # staff-only and might contain sensitive notes.
            if getattr(c, 'source', '') == 'rmm':
                # Device job output (attacker-influenceable endpoint text):
                # never fed to these drafts.
                recent_comments.append({'when': c.created_at.isoformat() if c.created_at else '',
                                        'author': '(device)', 'body': '[DEVICE OUTPUT — withheld from AI]'})
                continue
            if getattr(c, 'is_internal', False):
                recent_comments.append({
                    'when': c.created_at.isoformat() if c.created_at else '',
                    'author': '(staff)',
                    'body': '[INTERNAL NOTE — content withheld from AI]',
                })
                continue
            author = c.author.username if c.author_id else 'system'
            if rules is not None and not rules.contact_data and c.author_id:
                from psa.visibility import is_msp_staff
                author = 'technician' if is_msp_staff(c.author) else 'customer'
            recent_comments.append({
                'when': c.created_at.isoformat() if c.created_at else '',
                'author': author,
                'body': clean(c.body or '', 1500),
            })
        recent_comments.reverse()  # chronological in the prompt

    # Linked asset metadata (no secrets, no IPs that look like credentials).
    asset_blob: Dict[str, Any] = {}
    asset = getattr(ticket, 'related_asset', None)
    if asset is not None and (rules is None or rules.device_data):
        asset_blob = {
            'name': clean(getattr(asset, 'name', '') or '', 120),
            'asset_type': getattr(asset, 'asset_type', '') or '',
            'hostname': (clean(getattr(asset, 'hostname', '') or '', 120)
                         if rules is None or rules.network_identifiers else ''),
            'serial': clean(getattr(asset, 'serial_number', '') or '', 80),
        }

    # KB hint — top 5 docs whose title shares any non-trivial token with
    # the subject. Phase 1 similarity is intentionally trivial; pgvector
    # comes later.
    kb_hits: List[Dict[str, Any]] = []
    try:
        from docs.models import Document
        tokens = [t for t in subject.lower().split() if len(t) > 3][:5]
        if tokens and (rules is None or rules.kb_titles):
            from django.db.models import Q
            q = Q()
            for t in tokens:
                q |= Q(title__icontains=t)
            doc_qs = Document.objects.filter(q).filter(
                Q(organization=org) | Q(is_global=True)
            )[:5]
            for d in doc_qs:
                kb_hits.append({
                    'id': d.id,
                    'title': clean(d.title or '', 200),
                })
    except Exception:
        pass

    # Build the wrapped prompt-text payload.
    parts: List[str] = []
    parts.append(f'Client: {sanitize_input(org.name or "", max_chars=200)}')
    parts.append(f'Ticket: {ticket.ticket_number if hasattr(ticket, "ticket_number") else ticket.pk}')
    parts.append(f'Subject: {subject}')
    if description:
        parts.append(f'Description:\n{description}')
    if asset_blob:
        parts.append(
            f'Linked asset: {asset_blob["name"]} ({asset_blob.get("asset_type") or "asset"}) '
            f'host={asset_blob.get("hostname") or "—"} sn={asset_blob.get("serial") or "—"}'
        )
    if recent_comments:
        parts.append('Recent comments (chronological):')
        for c in recent_comments:
            parts.append(f'  [{c["when"]}] {c["author"]}: {c["body"]}')
    if kb_hits:
        parts.append('Possibly-relevant KB articles (titles only):')
        for d in kb_hits:
            parts.append(f'  - #{d["id"]}: {d["title"]}')

    raw_text = '\n'.join(parts)
    return {
        'organization_id': org.id,
        'organization_name': org.name,
        'ticket_number': getattr(ticket, 'ticket_number', None),
        'subject': subject,
        'description': description,
        'recent_comments': recent_comments,
        'asset': asset_blob,
        'kb_hits': kb_hits,
        # Prompt-text is the wrapped, sanitized payload the model sees.
        'prompt_text': wrap_user_content(raw_text),
    }
