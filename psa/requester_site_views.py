"""Staff page: default ticket sites for the selected customer's contacts and
portal users (psa.RequesterDefaultSite, read at ticket intake and as the
portal new-ticket form's preselected site)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from core.middleware import get_request_organization
from psa.feature_flags import require_psa_enabled


def _int(value):
    value = (value or '').strip()
    return int(value) if value.isdigit() else None


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def requester_sites(request):
    from accounts.models import Membership
    from accounts.permission_utils import has_perm_for_org
    from assets.models import Contact
    from locations.models import Location
    from psa.models import RequesterDefaultSite
    from psa.ticket_site import set_default, sites_for
    from psa.visibility import is_msp_staff

    if not is_msp_staff(request.user):
        raise PermissionDenied('MSP technicians only.')
    org = get_request_organization(request)
    if org is None:
        messages.info(request, 'Select a customer to manage its requesters\' default sites.')
        return redirect('psa:ticket_list')
    if not has_perm_for_org(request.user, org, 'tickets_edit'):
        raise PermissionDenied("Your role does not include 'tickets_edit' for this customer.")

    if request.method == 'POST':
        kind = request.POST.get('kind')
        target_id = _int(request.POST.get('target'))
        loc_id = _int(request.POST.get('site'))
        contact = user = None
        if kind == 'contact':
            contact = Contact.objects.filter(pk=target_id, organization=org).first()
        elif kind == 'user':
            m = Membership.objects.filter(user_id=target_id, organization=org,
                                          is_active=True).select_related('user').first()
            user = m.user if m else None
        location = Location.objects.filter(pk=loc_id).first() if loc_id else None
        if (contact is None and user is None) or (loc_id and location is None):
            messages.error(request, 'That contact, user or site does not belong to this customer.')
            return redirect('psa:requester_sites')
        try:
            set_default(org, location, contact=contact, user=user, actor=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('psa:requester_sites')
        who = f'contact {contact}' if contact else f'portal user {user.get_username()}'
        what = location.name if location else 'none'
        AuditLog.log(
            user=request.user, action='update', organization=org,
            object_type='psa.RequesterDefaultSite', object_repr=f'{who} @ {what}'[:255],
            description=f'Default ticket site for {who} at {org.name}: {what}',
            path=request.path,
            extra_data={'kind': kind, 'target_id': target_id,
                        'location_id': location.pk if location else None},
        )
        messages.success(request, f'Default site for {who}: {what}.')
        return redirect('psa:requester_sites')

    defaults = {}
    for row in RequesterDefaultSite.objects.filter(organization=org).select_related('location'):
        defaults[('contact', row.contact_id) if row.contact_id else ('user', row.user_id)] = row.location
    contacts = list(Contact.objects.filter(organization=org).order_by('last_name', 'first_name')[:500])
    members = [m.user for m in Membership.objects.filter(
        organization=org, is_active=True).select_related('user').order_by('user__username')[:500]
        if not is_msp_staff(m.user)]
    return render(request, 'psa/requester_sites.html', {
        'organization': org,
        'sites': list(sites_for(org)[:500]),
        'contact_rows': [(c, defaults.get(('contact', c.pk))) for c in contacts],
        'user_rows': [(u, defaults.get(('user', u.pk))) for u in members],
    })
