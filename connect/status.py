"""The one displayed status of a connection (DESIGN.md §4.3, roadmap 79.16).

Lifecycle (``Connection.state``) plus health while active
(``Connection.health``) map to the ten owner-facing states. Every page, the
bell, the system warnings and the alerts use ``display()``; nothing else
decides what a connection is called.
"""
from __future__ import annotations

from typing import NamedTuple

PENDING_SETUP = 'pending_setup'
AWAITING_APPROVAL = 'awaiting_approval'
AWAITING_NETWORK = 'awaiting_network'
TESTING = 'testing'
CONNECTED = 'connected'
DEGRADED = 'degraded'
OFFLINE = 'offline'
SECURITY_BLOCKED = 'security_blocked'
SUSPENDED = 'suspended'
REVOKED = 'revoked'
SETUP_FAILED = 'setup_failed'

LABELS = {
    PENDING_SETUP: 'Pending Setup',
    AWAITING_APPROVAL: 'Awaiting Approval',
    AWAITING_NETWORK: 'Awaiting Network Authorization',
    TESTING: 'Testing',
    CONNECTED: 'Connected',
    DEGRADED: 'Degraded',
    OFFLINE: 'Offline',
    SECURITY_BLOCKED: 'Security Blocked',
    SUSPENDED: 'Suspended',
    REVOKED: 'Revoked',
    SETUP_FAILED: 'Setup failed',
}
# Bootstrap contextual colour for the badge.
SEVERITY = {
    PENDING_SETUP: 'info', AWAITING_APPROVAL: 'info', AWAITING_NETWORK: 'warning', TESTING: 'info',
    CONNECTED: 'success', DEGRADED: 'warning', OFFLINE: 'danger', SECURITY_BLOCKED: 'danger',
    SUSPENDED: 'secondary', REVOKED: 'secondary', SETUP_FAILED: 'secondary',
}
# Statuses that are a problem with a connection that was working.
PROBLEM = frozenset({DEGRADED, OFFLINE, SECURITY_BLOCKED})


class Display(NamedTuple):
    key: str
    label: str
    severity: str


def key_for(state: str, health: str) -> str:
    from .models import Connection as C
    if state == C.PENDING_PAIRING:
        return PENDING_SETUP
    if state in (C.AWAITING_REMOTE, C.AWAITING_LOCAL, C.AWAITING_SECOND):
        return AWAITING_APPROVAL
    if state == C.AWAITING_NETWORK:
        return AWAITING_NETWORK
    if state == C.TESTING:
        return TESTING
    if state == C.ACTIVE:
        return {C.HEALTH_DEGRADED: DEGRADED, C.HEALTH_OFFLINE: OFFLINE}.get(health or '', CONNECTED)
    if state == C.SECURITY_BLOCKED:
        return SECURITY_BLOCKED
    if state == C.SUSPENDED:
        return SUSPENDED
    if state == C.FAILED:
        return SETUP_FAILED
    return REVOKED


def display(conn) -> Display:
    k = key_for(conn.state, getattr(conn, 'health', ''))
    return Display(k, LABELS[k], SEVERITY[k])
