"""Error model shared by every SDK function.

Every refusal raises ConnectError with a stable machine `code` (the protocol's
error code, PROTOCOL.md §12), an HTTP `status` a server should answer with,
and a `message` that is safe to show and to log: it never contains a token,
a key, a pairing code or a signature.
"""


class ConnectError(Exception):
    def __init__(self, code: str, message: str = '', status: int = 400):
        super().__init__(f'{code}: {message}' if message else code)
        self.code = code
        self.message = message or code
        self.status = status

    def as_dict(self, correlation_id: str = '') -> dict:
        out = {'error': {'code': self.code, 'message': self.message}}
        if correlation_id:
            out['error']['correlation_id'] = correlation_id
        return out


# Stable codes (PROTOCOL.md §12).
INVALID_REQUEST = 'invalid_request'
INVALID_CLIENT = 'invalid_client'
INVALID_GRANT = 'invalid_grant'
INVALID_SCOPE = 'invalid_scope'
INVALID_TOKEN = 'invalid_token'
INVALID_DPOP = 'invalid_dpop_proof'
INSUFFICIENT_SCOPE = 'insufficient_scope'
TENANT_NOT_GRANTED = 'tenant_not_granted'
REPLAYED = 'replayed'
EXPIRED = 'expired'
INVALID_SIGNATURE = 'invalid_signature'
INVALID_PAIRING_CODE = 'invalid_pairing_code'
PAIRING_LOCKED = 'pairing_locked'
RATE_LIMITED = 'rate_limited'
CONNECTION_INACTIVE = 'connection_inactive'
KILL_SWITCH = 'kill_switch'
UNSUPPORTED_VERSION = 'unsupported_version'
TOO_LARGE = 'too_large'
BLOCKED_DESTINATION = 'blocked_destination'
TRANSPORT = 'transport_error'
ACTION_APPROVAL_REQUIRED = 'action_approval_required'
