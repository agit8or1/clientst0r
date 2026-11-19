"""Short, readable text for a failed website check.

The requests/urllib3 exception text (pool class names, retry counts, nested
reprs) is useful in logs, not on the monitor page.
"""
import logging
import re

logger = logging.getLogger('monitoring')

_PATTERNS = [
    (r'NameResolutionError|Name or service not known|nodename nor servname|getaddrinfo failed'
     r'|Temporary failure in name resolution|No address associated',
     "Couldn't find the server: the name {host} does not resolve (DNS)."),
    (r'CERTIFICATE_VERIFY_FAILED|certificate verify failed|SSLCertVerificationError',
     "The server's certificate isn't trusted (expired, self-signed or for another name)."),
    (r'SSLError|SSL:|TLS', "The secure (TLS) connection to {host} failed."),
    (r'Connection refused|ECONNREFUSED|Errno 111', 'Connection refused: nothing is accepting connections on {host}{port}.'),
    (r'Network is unreachable|No route to host|Errno 101|Errno 113', "{host} isn't reachable from this server (no route)."),
    (r'Connection reset|Errno 104|RemoteDisconnected|Connection aborted',
     '{host} closed the connection before answering.'),
    (r'timed out|ConnectTimeout|ReadTimeout', '{host} did not answer in time.'),
    (r'TooManyRedirects|Exceeded \d+ redirects', 'Too many redirects.'),
]


def describe(exc, host='', port=None):
    text = str(exc)
    logger.info('website check failed for %s: %s', host, text)
    where = host or 'the server'
    port_txt = f' port {port}' if port else ''
    for pattern, message in _PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return message.format(host=where, port=port_txt)
    return 'The check failed: ' + (re.sub(r'\s+', ' ', text)[:200] or exc.__class__.__name__)
