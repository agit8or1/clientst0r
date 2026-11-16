"""Database implementations of the SDK interfaces, and key handling."""
from __future__ import annotations

from datetime import datetime, timezone as dt_tz
from typing import Dict, Optional, Tuple

from django.db import IntegrityError, transaction
from django.utils import timezone

from agit8or_connect import keys as sdk_keys
from agit8or_connect.tenants import TenantGrant as SdkGrant


class DbReplayStore:
    """INSERT under UNIQUE(namespace, key): of two racing workers exactly
    one wins. Expired rows are pruned opportunistically."""

    def add(self, namespace: str, key: str, expires_at: int) -> bool:
        from .models import ReplayRecord
        now = timezone.now()
        exp = datetime.fromtimestamp(int(expires_at), tz=dt_tz.utc)
        key = key[:255]
        try:
            with transaction.atomic():
                ReplayRecord.objects.create(namespace=namespace, key=key, expires_at=exp)
            return True
        except IntegrityError:
            with transaction.atomic():
                # Expired leftovers may be reused; live ones are a replay.
                n = ReplayRecord.objects.filter(namespace=namespace, key=key, expires_at__lte=now).update(
                    expires_at=exp)
            return bool(n)
        finally:
            if int(now.timestamp()) % 30 == 0:
                ReplayRecord.objects.filter(expires_at__lt=now).delete()


class DbTenantResolver:
    """(connection, remote tenant id) -> grant, from THIS connection's rows only."""

    def resolve(self, connection_id: str, remote_tenant_id: str) -> Optional[SdkGrant]:
        from .models import TenantGrant
        g = TenantGrant.objects.filter(connection_id=connection_id, remote_tenant_id=remote_tenant_id,
                                       active=True).select_related('organization').first()
        if g is None:
            return None
        return SdkGrant(str(g.connection_id), g.remote_tenant_id, g, tuple(g.scopes or ()), g.active,
                        g.remote_tenant_label)


replay_store = DbReplayStore()
tenant_resolver = DbTenantResolver()


# --- our keys ---------------------------------------------------------------------

def new_key(connection, state='active'):
    from .models import ConnectionKey
    priv = sdk_keys.generate_private_key()
    row = ConnectionKey(connection=connection, state=state, kid=sdk_keys.thumbprint(priv),
                        public_jwk=sdk_keys.public_jwk(priv),
                        activated_at=timezone.now() if state == 'active' else None)
    row.set_private_pem(sdk_keys.private_key_to_pem(priv))  # sealed to row.pk (set by default before save)
    row.save()
    return row, priv


def private_key(row):
    return sdk_keys.private_key_from_pem(row.private_pem())


def active_key(connection) -> Tuple[object, object]:
    from .models import ConnectionKey
    row = connection.keys.filter(state=ConnectionKey.ACTIVE).first()
    if row is None:
        from agit8or_connect.errors import ConnectError
        raise ConnectError('connection_inactive', 'this connection has no active key', 409)
    return row, private_key(row)


def verifying_keys(connection) -> Dict[str, object]:
    """Our keys that may have signed tokens / messages still accepted."""
    from .models import ConnectionKey
    out = {}
    for row in connection.keys.filter(state__in=(ConnectionKey.ACTIVE, ConnectionKey.RETIRING)):
        out[row.kid] = sdk_keys.public_key_from_jwk(row.public_jwk)
    return out


def published_jwks(connection) -> list:
    from .models import ConnectionKey
    return [row.public_jwk for row in connection.keys.filter(
        state__in=(ConnectionKey.STAGED, ConnectionKey.ACTIVE, ConnectionKey.RETIRING))]


# --- their keys ---------------------------------------------------------------------

def remote_keyring(connection) -> Dict[str, object]:
    return sdk_keys.keyring(connection.remote_jwks or {})


def set_remote_keys(connection, ring: Dict[str, object]):
    connection.remote_jwks = {'keys': [sdk_keys.public_jwk(k) for k in list(ring.values())[:sdk_keys.MAX_KEYS]]}
    connection.remote_jwks_fetched_at = timezone.now()
