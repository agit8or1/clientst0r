"""Browser -> editor reachability, recorded from an administrator's browser.

The Managed page runs static/js/office-managed-probe.js: a credential-less
``fetch(<browser URL><health path>, {mode: 'no-cors'})``. An opaque answer
means DNS, TLS and the reverse proxy let this browser reach the editor; a
network error means they did not (the page cannot tell which). The outcome
is posted back and audited (office_event=browser_probe, object_type
office.managed); the setup checks show the last one.
"""
from __future__ import annotations

OUTCOMES = ('reached', 'failed', 'timeout')
PATHS = {'onlyoffice': 'healthcheck', 'collabora': 'hosting/capabilities'}


def probe_url(instance_or_status_url, engine):
    return instance_or_status_url.rstrip('/') + '/' + PATHS.get(engine, 'healthcheck')


def last_probe():
    from audit.models import AuditLog
    return (AuditLog.objects.filter(object_type='office.managed',
                                    extra_data__office_event='browser_probe')
            .order_by('-pk').first())
