"""Scopes: namespaced `resource:action`, four risk tiers.

  read       reads data
  write      creates or changes data
  high_risk  acts on customer systems (remote actions, scripts, sessions)
             or reveals secrets. Never in a default set; granting one needs
             a second administrator on Clientst0r (protected change), and
             every USE needs a per-action authorization (PROTOCOL.md §7.3).
  admin      changes the connection or the other installation's settings.
             Never in a default set; same rules as high_risk.

A scope is never a wildcard: there is no "*", no "all", no prefix match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

from .errors import ConnectError, INVALID_SCOPE

READ, WRITE, HIGH_RISK, ADMIN = 'read', 'write', 'high_risk', 'admin'
RISKS = (READ, WRITE, HIGH_RISK, ADMIN)
ELEVATED_RISKS = (HIGH_RISK, ADMIN)
SCOPE_RE = re.compile(r'^[a-z][a-z0-9_]{0,40}(\.[a-z][a-z0-9_]{0,40}){0,3}:[a-z][a-z0-9_]{0,40}$')
MAX_SCOPES = 64


def valid_scope_name(name: str) -> bool:
    return isinstance(name, str) and bool(SCOPE_RE.match(name))


def parse_scope_string(s: str) -> List[str]:
    if not isinstance(s, str):
        raise ConnectError(INVALID_SCOPE, 'scope must be a string')
    out = sorted(set(p for p in s.split(' ') if p))
    if len(out) > MAX_SCOPES or not all(valid_scope_name(p) for p in out):
        raise ConnectError(INVALID_SCOPE, 'malformed scope')
    return out


@dataclass(frozen=True)
class Scope:
    name: str
    description: str
    risk: str
    available: bool = True       # implemented by this installation today
    events: Tuple[str, ...] = ()  # event types this scope lets the holder deliver / receive

    def __post_init__(self):
        if not valid_scope_name(self.name):
            raise ValueError(f'bad scope name {self.name!r}')
        if self.risk not in RISKS:
            raise ValueError(f'bad risk {self.risk!r}')

    @property
    def resource(self) -> str:
        return self.name.split(':', 1)[0]

    @property
    def action(self) -> str:
        return self.name.split(':', 1)[1]

    @property
    def elevated(self) -> bool:
        return self.risk in ELEVATED_RISKS

    def as_dict(self) -> dict:
        d = {'scope': self.name, 'description': self.description, 'risk': self.risk, 'available': self.available}
        if self.events:
            d['events'] = list(self.events)
        return d


@dataclass
class Catalog:
    scopes: Sequence[Scope] = field(default_factory=list)

    def __post_init__(self):
        self.by_name: Dict[str, Scope] = {s.name: s for s in self.scopes}

    def get(self, name):
        return self.by_name.get(name)

    def as_list(self) -> List[dict]:
        return [s.as_dict() for s in self.scopes]

    def default_set(self) -> List[str]:
        """What a wizard pre-ticks: available read scopes only."""
        return [s.name for s in self.scopes if s.available and s.risk == READ]

    def elevated(self, names: Iterable[str]) -> List[str]:
        return sorted(n for n in set(names) if self.by_name.get(n) and self.by_name[n].elevated)

    def grouped(self, names=None) -> Dict[str, List[Scope]]:
        out = {r: [] for r in RISKS}
        for s in self.scopes:
            if names is None or s.name in names:
                out[s.risk].append(s)
        return out

    def check_known(self, names: Iterable[str]) -> List[str]:
        names = sorted(set(names))
        unknown = [n for n in names if n not in self.by_name]
        if unknown:
            raise ConnectError(INVALID_SCOPE, f'unknown scope {unknown[0]}')
        return names

    @classmethod
    def from_list(cls, items) -> 'Catalog':
        """Tolerant parse of a peer's catalog: entries with unknown risk or a
        bad name are skipped, unknown members ignored."""
        out = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            try:
                out.append(Scope(str(it.get('scope')), str(it.get('description') or '')[:300],
                                 str(it.get('risk')), bool(it.get('available', True)),
                                 tuple(str(e) for e in (it.get('events') or []) if isinstance(e, str))[:32]))
            except ValueError:
                continue
        return cls(out[:200])


def require_subset(requested: Iterable[str], granted: Iterable[str]) -> List[str]:
    """Requested scopes if all are granted, else invalid_scope (never a
    silent narrowing: a client asking for more than it holds is told so)."""
    req, have = set(requested), set(granted)
    extra = sorted(req - have)
    if extra:
        raise ConnectError(INVALID_SCOPE, f'scope not granted: {extra[0]}', 400)
    return sorted(req)
