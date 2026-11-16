"""Key rotation state machine (PROTOCOL.md §9).

    staged ──validate ok──▶ active ──(next key activated)──▶ retiring ──overlap over──▶ retired
       │                                                     (still accepted for verification)
       └──validate failed──▶ failed     (the old active key is untouched)

Exactly one active key per connection per side. Only active signs. A peer
accepts signatures/assertions by active and retiring keys; staged keys are
published (endorsed by the active key) so the peer can fetch them before
they are used, and validation is "the peer accepted a token request signed
with the staged key". Revocation retires every key at once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

STAGED, ACTIVE, RETIRING, RETIRED, FAILED = 'staged', 'active', 'retiring', 'retired', 'failed'
STATES = (STAGED, ACTIVE, RETIRING, RETIRED, FAILED)
TRANSITIONS = {
    (STAGED, 'validated'): ACTIVE,
    (STAGED, 'validation_failed'): FAILED,
    (STAGED, 'revoke'): RETIRED,
    (ACTIVE, 'superseded'): RETIRING,
    (ACTIVE, 'revoke'): RETIRED,
    (RETIRING, 'overlap_over'): RETIRED,
    (RETIRING, 'revoke'): RETIRED,
}
VERIFYING_STATES = (ACTIVE, RETIRING)
PUBLISHED_STATES = (STAGED, ACTIVE, RETIRING)


class RotationError(ValueError):
    pass


def transition(state: str, event: str) -> str:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        raise RotationError(f'cannot {event} a {state} key') from None


@dataclass
class KeyInfo:
    kid: str
    state: str
    activated_at: Optional[int] = None
    retire_after: Optional[int] = None


def due_for_rotation(keys: Iterable[KeyInfo], now: int, interval_s: int) -> bool:
    keys = list(keys)
    if any(k.state == STAGED for k in keys):
        return False
    active = [k for k in keys if k.state == ACTIVE]
    if not active:
        return False
    return (active[0].activated_at or 0) + interval_s <= now


def to_retire(keys: Iterable[KeyInfo], now: int) -> List[str]:
    return [k.kid for k in keys if k.state == RETIRING and k.retire_after is not None and k.retire_after <= now]
