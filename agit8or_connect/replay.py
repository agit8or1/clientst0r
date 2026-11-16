"""Replay / idempotency store interface.

`add(namespace, key, expires_at)` records a one-time value and returns True
the first time, False if it was already recorded and has not expired. Hosts
implement it on a table with a UNIQUE(namespace, key) constraint so that two
workers racing on the same value cannot both win (Clientst0r:
connect.ReplayRecord; Rem0te: the IntegrationReplayGuard INSERT ON CONFLICT
pattern). Record only AFTER the signature verified, so unauthenticated
callers cannot fill the table.

Namespaces used by the protocol: "assertion" (client assertion jti),
"dpop" (DPoP proof jti), "event" (webhook event id), "pairing" (pairing
request jti), "poll" (pairing status proof jti).
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Protocol, Tuple


class ReplayStore(Protocol):
    def add(self, namespace: str, key: str, expires_at: int) -> bool: ...


class MemoryReplayStore:
    def __init__(self, clock=time.time):
        self._seen: Dict[Tuple[str, str], int] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def add(self, namespace: str, key: str, expires_at: int) -> bool:
        now = self._clock()
        with self._lock:
            if len(self._seen) > 10000:
                self._seen = {k: v for k, v in self._seen.items() if v > now}
            k = (namespace, key)
            if k in self._seen and self._seen[k] > now:
                return False
            self._seen[k] = int(expires_at)
            return True
