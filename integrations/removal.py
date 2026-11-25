"""What deleting an RMM connection does, in counts and plain words.

Used by the delete page (integrations.views.rmm_delete) before anything is
removed, and to explain a refused delete. Deleting removes the connection's
mirrored RMM data (devices, alerts, software, snapshots) and never tickets,
assets or the record of which alert opened which ticket (kept with the
connection's name, integrations.signals). Ticket RMM requests and analysis
jobs are the connection's own audit history and keep it from being deleted
(PROTECT): such a connection can only be disabled.
"""
from __future__ import annotations


def impact(connection) -> dict:
    from psa.routing.models import AlertTicketLink
    from psa_ai.models import AnalysisJob, Rem0teAlertTicket, RMMRequest

    links = AlertTicketLink.objects.filter(connection=connection)
    rem0te_links = Rem0teAlertTicket.objects.filter(connection=connection)
    tickets = set(links.exclude(ticket__isnull=True).values_list('ticket_id', flat=True))
    tickets |= set(rem0te_links.exclude(ticket__isnull=True).values_list('ticket_id', flat=True))
    requests = RMMRequest.objects.filter(connection=connection).count()
    jobs = AnalysisJob.objects.filter(connection=connection).count()
    imported = connection.imported_organizations()
    out = {
        'devices': connection.devices.count(),
        'alerts': connection.alerts.count(),
        'ticket_links': links.count() + rem0te_links.count(),
        'linked_tickets': len(tickets),
        'fix_requests': requests,
        'analysis_jobs': jobs,
        'imported_organizations': [o.name for o in imported],
    }
    out['blockers'] = blockers(out)
    out['can_delete'] = not out['blockers']
    return out


def _n(count, one, many):
    return f'{count} {one if count == 1 else many}'


def blockers(counts) -> list[str]:
    """Plain sentences naming what keeps the connection from being deleted."""
    out = []
    if counts.get('fix_requests'):
        out.append(f"{_n(counts['fix_requests'], 'ticket request', 'ticket requests')} (diagnostics, fix "
                   'referrals or hand-offs) were sent through this connection. They are part of those tickets\' '
                   'history and name the connection that received them.')
    if counts.get('analysis_jobs'):
        out.append(f"{_n(counts['analysis_jobs'], 'ticket analysis', 'ticket analyses')} were processed by this "
                   'connection and are kept as ticket history.')
    return out


def explain_refusal(exc) -> list[str]:
    """Plain sentences for a ProtectedError / RestrictedError raised by a
    delete the page did not foresee (a request created in the meantime)."""
    objs = list(getattr(exc, 'protected_objects', None) or getattr(exc, 'restricted_objects', None) or ())
    by_type: dict[str, int] = {}
    for o in objs:
        label = str(getattr(o._meta, 'verbose_name_plural', o._meta.model_name))
        by_type[label] = by_type.get(label, 0) + 1
    if not by_type:
        return ['Other records still refer to this connection.']
    return [f'{count} {label} still refer to this connection.' for label, count in sorted(by_type.items())]
