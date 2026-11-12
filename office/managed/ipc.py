"""Client for the Office service helper's socket.

    call(op, args=None, timeout=None) -> dict          the helper's "result"
    submit(op, args=None) -> dict                      {"id", "op", "state"} of an accepted operation

The vocabulary is fixed here as it is in the helper; nothing else can be
sent. Errors:

    HelperUnavailable   socket missing / connection refused / timeout. The
                        rest of clientst0r keeps working; only the managed
                        editor's controls are affected.
    HelperRefused       the helper answered and refused (``.busy`` when
                        another operation is running).

The JWT secret (op ``secret``) is returned to the caller and never logged.
"""
from __future__ import annotations

import json
import socket

from django.conf import settings

SOCKET_PATH = '/run/clientst0r-office/helper.sock'
OPS = ('preflight', 'status', 'releases', 'logs', 'secret',
       'install', 'start', 'stop', 'restart', 'update', 'rollback', 'uninstall')
ASYNC_OPS = ('install', 'start', 'stop', 'restart', 'update', 'rollback', 'uninstall')
MAX_REPLY = 2 * 1024 * 1024


class HelperError(Exception):
    pass


class HelperUnavailable(HelperError):
    pass


class HelperRefused(HelperError):
    def __init__(self, message, busy=False):
        super().__init__(message)
        self.busy = busy


def socket_path():
    return getattr(settings, 'OFFICE_MANAGED_SOCKET', SOCKET_PATH)


def _exchange(payload, timeout):
    path = socket_path()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path)
        sock.sendall((json.dumps(payload) + '\n').encode())
        data = b''
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_REPLY:
                raise HelperUnavailable('The Office service helper sent an oversized reply.')
    except FileNotFoundError:
        raise HelperUnavailable('The Office service helper is not installed or not enabled on this '
                                'server (no socket). See Managed Local ONLYOFFICE setup.')
    except (ConnectionRefusedError, PermissionError) as e:
        raise HelperUnavailable(f'The Office service helper refused the connection ({type(e).__name__}).')
    except socket.timeout:
        raise HelperUnavailable('The Office service helper did not answer in time.')
    except OSError as e:
        raise HelperUnavailable(f'The Office service helper is unreachable ({type(e).__name__}).')
    finally:
        sock.close()
    try:
        reply = json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise HelperUnavailable('The Office service helper sent an unreadable reply.')
    if not isinstance(reply, dict):
        raise HelperUnavailable('The Office service helper sent an unexpected reply.')
    return reply


def _validated(op, args):
    if op not in OPS:
        raise ValueError(f'unknown helper operation {op!r}')
    args = dict(args or {})
    if op == 'update':
        if set(args) != {'release'} or not isinstance(args['release'], str):
            raise ValueError('update takes exactly one release id')
    elif op == 'logs':
        if set(args) - {'lines'} or not isinstance(args.get('lines', 200), int):
            raise ValueError('logs takes only lines')
    elif args:
        raise ValueError(f'{op} takes no arguments')
    return {'op': op, 'args': args}


def call(op, args=None, timeout=None):
    if op in ASYNC_OPS:
        raise ValueError('use submit() for lifecycle operations')
    reply = _exchange(_validated(op, args), timeout or (60 if op == 'preflight' else 30))
    if not reply.get('ok'):
        raise HelperRefused(str(reply.get('error') or 'refused')[:1000], busy=bool(reply.get('busy')))
    return reply.get('result') or {}


def submit(op, args=None, timeout=30):
    if op not in ASYNC_OPS:
        raise ValueError(f'{op} is not a lifecycle operation')
    reply = _exchange(_validated(op, args), timeout)
    if not reply.get('ok') or not reply.get('accepted'):
        raise HelperRefused(str(reply.get('error') or 'refused')[:1000], busy=bool(reply.get('busy')))
    return reply.get('operation') or {}
