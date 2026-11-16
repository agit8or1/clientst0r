"""Claim normalisation (the IdP-specific adapter) and the MFA decision.

Default shape is Keycloak's (ARCHITECTURE.md §4.4):

    "organization": {"acme-msp": {"id": "6f1c…"}}      (or ["acme-msp"])
    "resource_access": {"<client_id>": {"roles": [
        "acme-msp:technician",
        "acme-msp:customer:cust-0193:technician"]}}

Only roles carrying the pinned MSP alias prefix count, and only when the
token's organization claim contains that alias (and id, when pinned).
Other organizations' entries are discarded before any mapping.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .tokens import TokenError


@dataclass
class TokenRoles:
    staff: Set[str] = field(default_factory=set)              # role keys
    customers: Dict[str, Set[str]] = field(default_factory=dict)  # customer key -> role keys
    has_customer_claims: bool = False


def claim_path(claims, path, client_id=''):
    """Value at a dotted path ({client_id} replaced per segment), or None."""
    if not path:
        return None
    node = claims
    for segment in path.split('.'):
        segment = segment.replace('{client_id}', client_id)
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


def check_msp_pin(provider, claims):
    """Raise TokenError('org_mismatch') unless the token is for the pinned MSP."""
    if not provider.org_claim:
        return  # an OP / realm dedicated to this MSP: the issuer pin separates
    alias = (provider.msp_org_alias or '').strip()
    if not alias:
        raise TokenError('org_not_configured', 'No MSP organization is pinned for this provider')
    value = claim_path(claims, provider.org_claim, provider.client_id)
    org_id = None
    if isinstance(value, dict):
        if alias not in value:
            raise TokenError('org_mismatch', 'Token is not for this MSP organization')
        entry = value.get(alias)
        if isinstance(entry, dict):
            org_id = entry.get('id')
    elif isinstance(value, list):
        if alias not in [v for v in value if isinstance(v, str)]:
            raise TokenError('org_mismatch', 'Token is not for this MSP organization')
    elif isinstance(value, str):
        if value != alias:
            raise TokenError('org_mismatch', 'Token is not for this MSP organization')
    else:
        raise TokenError('org_mismatch', 'Token has no organization claim')
    pinned_id = (provider.msp_org_id or '').strip()
    if pinned_id and org_id != pinned_id:
        raise TokenError('org_mismatch', 'Token organization id does not match the pinned MSP')


def extract_roles(provider, claims) -> TokenRoles:
    raw = claim_path(claims, provider.roles_claim, provider.client_id)
    out = TokenRoles()
    if not isinstance(raw, list):
        return out
    alias = (provider.msp_org_alias or '').strip()
    prefix = f'{alias}:' if alias else ''
    for item in raw:
        if not isinstance(item, str) or len(item) > 300:
            continue
        if prefix:
            if not item.startswith(prefix):
                continue  # another organization's role: discarded
            item = item[len(prefix):]
        parts = item.split(':')
        if len(parts) == 1 and parts[0]:
            out.staff.add(parts[0])
        elif len(parts) == 3 and parts[0] == 'customer' and parts[1] and parts[2]:
            out.has_customer_claims = True
            out.customers.setdefault(parts[1], set()).add(parts[2])
    return out


def mfa_satisfied(provider, claims) -> bool:
    """Did the OP perform MFA for this sign-in, per the configured values?

    acr in the configured list, or amr containing a configured second-factor
    value. An acr claiming MFA while amr says password only is inconsistent
    and does not count.
    """
    acr = claims.get('acr')
    amr = claims.get('amr')
    amr_values = [a for a in amr if isinstance(a, str)] if isinstance(amr, list) else []
    if amr_values and set(amr_values) <= {'pwd'}:
        return False
    if isinstance(acr, str) and acr in provider.mfa_acr_list():
        return True
    return bool(set(amr_values) & set(provider.mfa_amr_list()))


def display_names(claims):
    def s(name, limit):
        v = claims.get(name)
        return v.strip()[:limit] if isinstance(v, str) else ''
    return s('given_name', 150), s('family_name', 150), s('email', 254), s('preferred_username', 150)


def email_verified(claims) -> Optional[bool]:
    v = claims.get('email_verified')
    return v if isinstance(v, bool) else None


def as_list(value) -> List[str]:
    return sorted(value) if value else []
