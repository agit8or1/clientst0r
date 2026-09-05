"""
Integrations views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.db import IntegrityError
from core.middleware import get_request_organization
from core.decorators import require_admin, require_write
from django.core.exceptions import PermissionDenied
from .models import PSAConnection, PSACompany, PSAContact, PSATicket, RMMConnection, RMMDevice, RMMAlert, RMMSoftware, UnifiConnection, M365Connection, OmadaConnection, GrandstreamConnection, DistributorConnection, DistributorWebhookEvent, AccountingConnection
from .forms import PSAConnectionForm, RMMConnectionForm, UnifiConnectionForm, M365ConnectionForm, OmadaConnectionForm, GrandstreamConnectionForm
from .status import connection_status
from .sync import PSASync
from .providers import get_provider
from .providers.rmm import get_rmm_provider
from .providers.distributors import get_distributor_provider
from vault.encryption import EncryptionError
from django.conf import settings
import logging

logger = logging.getLogger('integrations')


@login_required
def integration_list(request):
    """
    Unified integrations dashboard. Renders one combined list of every
    connection type (PSA / RMM / UniFi / M365 / Omada / Grandstream /
    Distributor / Accounting) with a status pill, search box, and Tile/List
    view toggle.
    """
    org = get_request_organization(request)

    # Each row: (icon, category, provider_label, name, conn, configure_url,
    # detail_url_or_none, status_dict).
    rows = []

    def _add(qs, *, icon, category, configure_url_name, detail_url_name=None,
             provider_label_attr='get_provider_type_display',
             host_attr=None):
        for conn in qs:
            try:
                if callable(getattr(conn, provider_label_attr, None)):
                    provider_label = getattr(conn, provider_label_attr)()
                else:
                    provider_label = getattr(conn, provider_label_attr, category)
            except Exception:
                provider_label = category
            # Some integration types don't have a get_provider_type_display
            # (UniFi/M365/Omada/Grandstream are single-provider) — fall back
            # to a host string when available so the row still has a useful
            # secondary label.
            if not provider_label or provider_label == category:
                if host_attr:
                    provider_label = getattr(conn, host_attr, '') or category
            try:
                configure_url = configure_url_name and __reverse_safe(configure_url_name, conn.pk)
            except Exception:
                configure_url = None
            try:
                detail_url = detail_url_name and __reverse_safe(detail_url_name, conn.pk)
            except Exception:
                detail_url = None

            rows.append({
                'icon': icon,
                'category': category,
                'provider_label': provider_label,
                'name': conn.name,
                'conn': conn,
                'pk': conn.pk,
                'configure_url': configure_url,
                'detail_url': detail_url,
                'status': connection_status(conn),
            })

    _add(PSAConnection.objects.for_organization(org),
         icon='fas fa-ticket-alt', category='PSA',
         configure_url_name='integrations:integration_edit',
         detail_url_name='integrations:integration_detail')
    _add(RMMConnection.objects.for_organization(org),
         icon='fas fa-desktop', category='RMM',
         configure_url_name='integrations:rmm_edit',
         detail_url_name='integrations:rmm_detail')
    _add(UnifiConnection.objects.for_organization(org),
         icon='fas fa-network-wired', category='UniFi',
         configure_url_name='integrations:unifi_edit',
         detail_url_name='integrations:unifi_detail',
         provider_label_attr='host', host_attr='host')
    _add(M365Connection.objects.for_organization(org),
         icon='fab fa-microsoft', category='Microsoft 365',
         configure_url_name='integrations:m365_edit',
         detail_url_name='integrations:m365_detail',
         provider_label_attr='tenant_id')
    _add(OmadaConnection.objects.for_organization(org),
         icon='fas fa-network-wired', category='Omada',
         configure_url_name='integrations:omada_edit',
         detail_url_name='integrations:omada_detail',
         provider_label_attr='host', host_attr='host')
    _add(GrandstreamConnection.objects.for_organization(org),
         icon='fas fa-wifi', category='Grandstream',
         configure_url_name='integrations:grandstream_edit',
         detail_url_name='integrations:grandstream_detail',
         provider_label_attr='host', host_attr='host')
    try:
        _add(DistributorConnection.objects.for_organization(org),
             icon='fas fa-truck', category='Distributor',
             configure_url_name='integrations:distributor_edit')
    except Exception:
        pass
    try:
        _add(AccountingConnection.objects.for_organization(org),
             icon='fas fa-file-invoice-dollar', category='Accounting',
             configure_url_name='integrations:accounting_edit')
    except Exception:
        pass

    # Search filter — provider label OR name OR category.
    search_q = (request.GET.get('q') or '').strip()
    if search_q:
        needle = search_q.lower()
        rows = [
            r for r in rows
            if needle in (r['name'] or '').lower()
            or needle in (r['provider_label'] or '').lower()
            or needle in (r['category'] or '').lower()
        ]

    # View mode — querystring is source of truth, JS layer mirrors to localStorage.
    view_mode = request.GET.get('view') or 'tile'
    if view_mode not in ('tile', 'list'):
        view_mode = 'tile'

    # Quick counters for the page header.
    counts = {'total': len(rows), 'broken': 0, 'working': 0, 'off': 0, 'unknown': 0}
    for r in rows:
        counts[r['status']['state']] = counts.get(r['status']['state'], 0) + 1

    rows.sort(key=lambda r: (r['category'], r['name'].lower()))

    return render(request, 'integrations/integration_list.html', {
        'rows': rows,
        'search_query': search_q,
        'view_mode': view_mode,
        'counts': counts,
    })


def __reverse_safe(url_name, pk):
    """Internal: reverse a URL name with `pk`, returning None if not registered."""
    from django.urls import reverse, NoReverseMatch
    try:
        return reverse(url_name, args=[pk])
    except NoReverseMatch:
        return None


@login_required
@require_admin
def integration_create(request):
    """Create new PSA connection."""
    from core.models import Organization

    # Get user's organizations
    if request.user.is_superuser:
        user_orgs = Organization.objects.all()
    else:
        user_orgs = Organization.objects.filter(
            memberships__user=request.user,
            memberships__is_active=True
        ).distinct()

    # Auto-select if only one organization
    org = get_request_organization(request)
    if not org and user_orgs.count() == 1:
        org = user_orgs.first()

    # If no org and multiple available, let form handle it
    # If still no orgs available at all, show error
    if user_orgs.count() == 0:
        messages.error(request, "You must be a member of at least one organization to create integrations.")
        return redirect('integrations:integration_list')

    if request.method == 'POST':
        # Get organization from form if not already set
        if not org and 'organization' in request.POST:
            try:
                org_id = request.POST.get('organization')
                org = user_orgs.get(pk=org_id)
            except Organization.DoesNotExist:
                messages.error(request, "Invalid organization selected.")
                return redirect('integrations:integration_create')

        form = PSAConnectionForm(request.POST, organization=org)
        if form.is_valid():
            try:
                connection = form.save(commit=False)
                connection.organization = org
                connection.save()
                messages.success(request, f"Connection '{connection.name}' created successfully.")
                return redirect('integrations:integration_detail', pk=connection.pk)
            except EncryptionError as e:
                # Handle APP_MASTER_KEY errors - usually means Gunicorn isn't loading .env
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower() or 'padding' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 <strong>Encryption Configuration Error</strong><br><br>"
                        "The Gunicorn service is not loading your .env file with the APP_MASTER_KEY. "
                        "This is a common setup issue that's easy to fix!<br><br>"
                        "<strong>Quick Fix:</strong><br>"
                        f"<code>cd {settings.BASE_DIR}<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/clientst0r/issues/4' target='_blank'>Issue #4</a> for details.",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Encryption error: {error_msg}")
    else:
        form = PSAConnectionForm(organization=org)

    context = {
        'form': form,
        'action': 'Create',
        'user_organizations': user_orgs,
        'selected_org': org,
        'show_org_selector': user_orgs.count() > 1 and not org,
    }

    return render(request, 'integrations/integration_form.html', context)


@login_required
def integration_detail(request, pk):
    """View connection details."""
    org = get_request_organization(request)
    connection = get_object_or_404(PSAConnection, pk=pk, organization=org)

    companies = PSACompany.objects.filter(connection=connection)[:10]
    tickets = PSATicket.objects.filter(connection=connection).order_by('-external_updated_at')[:10]

    return render(request, 'integrations/integration_detail.html', {
        'connection': connection,
        'companies': companies,
        'tickets': tickets,
    })


@login_required
@require_admin
def integration_edit(request, pk):
    """Edit PSA connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(PSAConnection, pk=pk, organization=org)

    if request.method == 'POST':
        form = PSAConnectionForm(request.POST, instance=connection, organization=org)
        if form.is_valid():
            try:
                connection = form.save()
                messages.success(request, f"Connection '{connection.name}' updated successfully.")
                return redirect('integrations:integration_detail', pk=connection.pk)
            except EncryptionError as e:
                # Handle APP_MASTER_KEY errors - usually means Gunicorn isn't loading .env
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower() or 'padding' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 <strong>Encryption Configuration Error</strong><br><br>"
                        "The Gunicorn service is not loading your .env file with the APP_MASTER_KEY. "
                        "This is a common setup issue that's easy to fix!<br><br>"
                        "<strong>Quick Fix:</strong><br>"
                        f"<code>cd {settings.BASE_DIR}<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/clientst0r/issues/4' target='_blank'>Issue #4</a> for details.",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Encryption error: {error_msg}")
    else:
        form = PSAConnectionForm(instance=connection, organization=org)

    return render(request, 'integrations/integration_form.html', {
        'form': form,
        'connection': connection,
        'action': 'Edit',
    })


@login_required
@require_admin
def integration_delete(request, pk):
    """Delete PSA connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(PSAConnection, pk=pk, organization=org)

    if request.method == 'POST':
        name = connection.name
        connection.delete()
        messages.success(request, f"Connection '{name}' deleted successfully.")
        return redirect('integrations:integration_list')

    return render(request, 'integrations/integration_confirm_delete.html', {
        'connection': connection,
    })


@login_required
@require_admin
def integration_test(request, pk):
    """Test PSA connection with diagnostic information (AJAX)."""
    org = get_request_organization(request)
    connection = get_object_or_404(PSAConnection, pk=pk, organization=org)

    if request.method == 'POST':
        try:
            provider = get_provider(connection)
            success = provider.test_connection()

            if success:
                # Get diagnostic data - try to fetch a small sample
                diagnostic_info = {
                    'connection_ok': True,
                    'provider': connection.get_provider_type_display(),
                    'base_url': connection.base_url,
                }

                # Try to get sample counts
                try:
                    if connection.sync_companies:
                        companies = provider.list_companies(page_size=1)
                        diagnostic_info['companies_available'] = len(companies) > 0
                        diagnostic_info['sample_company'] = companies[0]['name'] if companies else None

                    if connection.sync_contacts:
                        contacts = provider.list_contacts(page_size=1)
                        diagnostic_info['contacts_available'] = len(contacts) > 0

                    if connection.sync_tickets:
                        tickets = provider.list_tickets(page_size=1)
                        diagnostic_info['tickets_available'] = len(tickets) > 0
                except Exception as e:
                    diagnostic_info['fetch_warning'] = f'Could not fetch sample data: {str(e)}'

                return JsonResponse({
                    'success': True,
                    'message': 'Connection successful! Data is accessible.',
                    'diagnostic': diagnostic_info
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Connection test failed. Please check your credentials and Base URL.',
                    'diagnostic': {
                        'connection_ok': False,
                        'base_url': connection.base_url,
                        'suggestion': 'Verify API credentials and Base URL format'
                    }
                }, status=400)

        except Exception as e:
            error_msg = str(e)
            suggestions = []

            # Provide helpful suggestions based on error type
            if 'authentication' in error_msg.lower() or '401' in error_msg:
                suggestions.append('Check your API key or credentials')
            elif '404' in error_msg or 'not found' in error_msg.lower():
                suggestions.append('Verify Base URL is correct (should include your subdomain)')
            elif 'connection' in error_msg.lower() or 'timeout' in error_msg.lower():
                suggestions.append('Check network connectivity and firewall settings')

            return JsonResponse({
                'success': False,
                'message': f'Connection error: {error_msg}',
                'suggestions': suggestions
            }, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
@require_admin
def integration_sync(request, pk):
    """Trigger manual sync (AJAX)."""
    org = get_request_organization(request)
    connection = get_object_or_404(PSAConnection, pk=pk, organization=org)

    if request.method == 'POST':
        try:
            syncer = PSASync(connection)
            stats = syncer.sync_all()

            # Build detailed message
            sync_messages = []
            if stats.get('companies', {}).get('created', 0) > 0:
                sync_messages.append(f"{stats['companies']['created']} companies created")
            if stats.get('companies', {}).get('updated', 0) > 0:
                sync_messages.append(f"{stats['companies']['updated']} companies updated")
            if stats.get('contacts', {}).get('created', 0) + stats.get('contacts', {}).get('updated', 0) > 0:
                total_contacts = stats.get('contacts', {}).get('created', 0) + stats.get('contacts', {}).get('updated', 0)
                sync_messages.append(f"{total_contacts} contacts synced")
            if stats.get('tickets', {}).get('created', 0) + stats.get('tickets', {}).get('updated', 0) > 0:
                total_tickets = stats.get('tickets', {}).get('created', 0) + stats.get('tickets', {}).get('updated', 0)
                sync_messages.append(f"{total_tickets} tickets synced")
            if stats.get('organizations', {}).get('created', 0) > 0:
                sync_messages.append(f"{stats['organizations']['created']} organizations imported")

            message = 'Sync completed: ' + ', '.join(sync_messages) if sync_messages else 'Sync completed (no changes)'

            return JsonResponse({
                'success': True,
                'message': message,
                'stats': stats
            })

        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def psa_companies(request):
    """List synced PSA companies."""
    org = get_request_organization(request)
    companies = PSACompany.objects.for_organization(org).select_related('connection')

    return render(request, 'integrations/psa_companies.html', {
        'companies': companies,
    })


@login_required
def psa_tickets(request):
    """List synced PSA tickets."""
    org = get_request_organization(request)
    tickets = PSATicket.objects.for_organization(org).select_related('connection', 'company', 'contact')

    return render(request, 'integrations/psa_tickets.html', {
        'tickets': tickets,
    })


@login_required
def psa_company_detail(request, pk):
    """View PSA company details."""
    org = get_request_organization(request)
    company = get_object_or_404(PSACompany, pk=pk, organization=org)

    # Get related contacts and tickets
    contacts = company.contacts.all()
    tickets = company.tickets.order_by('-external_updated_at')[:20]

    return render(request, 'integrations/psa_company_detail.html', {
        'company': company,
        'contacts': contacts,
        'tickets': tickets,
    })


@login_required
def psa_contacts(request):
    """List synced PSA contacts."""
    org = get_request_organization(request)
    contacts = PSAContact.objects.for_organization(org).select_related('connection', 'company')

    return render(request, 'integrations/psa_contacts.html', {
        'contacts': contacts,
    })


@login_required
def psa_contact_detail(request, pk):
    """View PSA contact details."""
    org = get_request_organization(request)
    contact = get_object_or_404(PSAContact, pk=pk, organization=org)

    # Get related tickets
    tickets = contact.tickets.order_by('-external_updated_at')[:20]

    return render(request, 'integrations/psa_contact_detail.html', {
        'contact': contact,
        'tickets': tickets,
    })


@login_required
def psa_ticket_detail(request, pk):
    """View PSA ticket details."""
    org = get_request_organization(request)
    ticket = get_object_or_404(PSATicket, pk=pk, organization=org)

    return render(request, 'integrations/psa_ticket_detail.html', {
        'ticket': ticket,
    })


# RMM Views
@login_required
@require_admin
def rmm_create(request):
    """Create new RMM connection."""
    org = get_request_organization(request)

    # Require organization to be selected
    if not org:
        messages.error(request, "Please select an organization first.")
        return redirect('integrations:integration_list')

    if request.method == 'POST':
        form = RMMConnectionForm(request.POST, organization=org)
        if form.is_valid():
            try:
                connection = form.save(commit=False)
                # Ensure organization is set (should be set by form, but double-check)
                if not connection.organization:
                    connection.organization = org
                connection.save()
                messages.success(request, f"RMM connection '{connection.name}' created successfully.")
                return redirect('integrations:rmm_detail', pk=connection.pk)
            except IntegrityError as e:
                # Handle database integrity errors (like missing organization_id)
                error_msg = str(e)
                if 'organization_id' in error_msg.lower() and 'cannot be null' in error_msg.lower():
                    messages.error(
                        request,
                        "❌ <strong>Organization Required</strong><br><br>"
                        "An organization must be selected before creating an RMM connection. "
                        "Please select an organization from the organization selector in the top navigation bar, "
                        "then try again.<br><br>"
                        "If you're a superuser, make sure you've selected an organization before accessing this page.",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Database error: {error_msg}")
                return redirect('integrations:integration_list')
            except EncryptionError as e:
                # Handle APP_MASTER_KEY errors - usually means Gunicorn isn't loading .env
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower() or 'padding' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 <strong>Encryption Configuration Error</strong><br><br>"
                        "The Gunicorn service is not loading your .env file with the APP_MASTER_KEY. "
                        "This is a common setup issue that's easy to fix!<br><br>"
                        "<strong>Quick Fix:</strong><br>"
                        f"<code>cd {settings.BASE_DIR}<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/clientst0r/issues/4' target='_blank'>Issue #4</a> for details.",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Encryption error: {error_msg}")
    else:
        form = RMMConnectionForm(organization=org)

    return render(request, 'integrations/rmm_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
def rmm_detail(request, pk):
    """View RMM connection details."""
    org = get_request_organization(request)
    connection = get_object_or_404(RMMConnection, pk=pk, organization=org)

    devices = RMMDevice.objects.filter(connection=connection).order_by('-last_seen')[:20]
    total_devices = RMMDevice.objects.filter(connection=connection).count()
    online_devices = RMMDevice.objects.filter(connection=connection, is_online=True).count()

    return render(request, 'integrations/rmm_detail.html', {
        'connection': connection,
        'devices': devices,
        'total_devices': total_devices,
        'online_devices': online_devices,
    })


@login_required
@require_admin
def rmm_edit(request, pk):
    """Edit RMM connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(RMMConnection, pk=pk, organization=org)

    if request.method == 'POST':
        form = RMMConnectionForm(request.POST, instance=connection, organization=org)
        if form.is_valid():
            try:
                connection = form.save()
                messages.success(request, f"RMM connection '{connection.name}' updated successfully.")
                return redirect('integrations:rmm_detail', pk=connection.pk)
            except EncryptionError as e:
                # Handle APP_MASTER_KEY errors - usually means Gunicorn isn't loading .env
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower() or 'padding' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 <strong>Encryption Configuration Error</strong><br><br>"
                        "The Gunicorn service is not loading your .env file with the APP_MASTER_KEY. "
                        "This is a common setup issue that's easy to fix!<br><br>"
                        "<strong>Quick Fix:</strong><br>"
                        f"<code>cd {settings.BASE_DIR}<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/clientst0r/issues/4' target='_blank'>Issue #4</a> for details.",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Encryption error: {error_msg}")
    else:
        form = RMMConnectionForm(instance=connection, organization=org)

    return render(request, 'integrations/rmm_form.html', {
        'form': form,
        'connection': connection,
        'action': 'Edit',
    })


@login_required
@require_admin
def rmm_delete(request, pk):
    """Delete RMM connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(RMMConnection, pk=pk, organization=org)

    if request.method == 'POST':
        name = connection.name
        try:
            # Check for related devices before deletion
            device_count = connection.devices.count()
            if device_count > 0:
                logger.info(f"Deleting RMM connection '{name}' with {device_count} related devices (will cascade)")

            connection.delete()
            messages.success(request, f"✓ RMM connection '{name}' deleted successfully.")
            logger.info(f"RMM connection '{name}' (pk={pk}) deleted successfully")
        except IntegrityError as e:
            error_msg = str(e)
            logger.error(f"IntegrityError deleting RMM connection '{name}': {error_msg}")
            messages.error(request, f"❌ Cannot delete RMM connection: Database integrity error. Related records may exist.")
            return redirect('integrations:integration_list')
        except Exception as e:
            logger.error(f"Error deleting RMM connection '{name}': {e}")
            messages.error(request, f"❌ Error deleting RMM connection: {str(e)[:100]}")
            return redirect('integrations:integration_list')

        return redirect('integrations:integration_list')

    # Get device count for display in confirmation
    device_count = connection.devices.count()

    return render(request, 'integrations/rmm_confirm_delete.html', {
        'connection': connection,
        'device_count': device_count,
    })


@login_required
def rmm_devices(request):
    """List all RMM devices."""
    org = get_request_organization(request)
    devices = RMMDevice.objects.for_organization(org).select_related('connection', 'linked_asset')

    return render(request, 'integrations/rmm_devices.html', {
        'devices': devices,
    })


@login_required
def rmm_alerts(request):
    """List all RMM alerts."""
    org = get_request_organization(request)
    
    # Filter by status if provided
    status_filter = request.GET.get('status', 'active')
    
    alerts = RMMAlert.objects.for_organization(org).select_related('connection')
    
    if status_filter == 'active':
        alerts = alerts.filter(status='active')
    elif status_filter == 'resolved':
        alerts = alerts.filter(status='resolved')
    # 'all' shows everything
    
    # Order by most recent first
    alerts = alerts.order_by('-triggered_at')
    
    return render(request, 'integrations/rmm_alerts.html', {
        'alerts': alerts,
        'status_filter': status_filter,
    })


@login_required
def rmm_software(request):
    """List all software from RMM integrations."""
    org = get_request_organization(request)
    
    # Get search query
    search_query = request.GET.get('q', '').strip()
    
    software = RMMSoftware.objects.for_organization(org).select_related('device', 'device__connection')
    
    if search_query:
        from django.db.models import Q
        software = software.filter(
            Q(name__icontains=search_query) |
            Q(vendor__icontains=search_query) |
            Q(version__icontains=search_query)
        )
    
    # Get unique software (name + vendor)
    from django.db.models import Count
    software_summary = software.values('name', 'vendor', 'version').annotate(
        device_count=Count('device', distinct=True)
    ).order_by('name', 'vendor', 'version')
    
    return render(request, 'integrations/rmm_software.html', {
        'software_summary': software_summary,
        'search_query': search_query,
    })


@login_required
def rmm_device_detail(request, pk):
    """Show details of a single RMM device."""
    org = get_request_organization(request)
    device = get_object_or_404(RMMDevice.objects.for_organization(org).select_related('connection', 'linked_asset'), pk=pk)

    # Get software for this device
    software = RMMSoftware.objects.filter(device=device).order_by('name')

    # Get recent alerts for this device
    alerts = RMMAlert.objects.filter(
        organization=org,
        device=device
    ).order_by('-triggered_at')[:10]

    return render(request, 'integrations/rmm_device_detail.html', {
        'device': device,
        'software': software,
        'alerts': alerts,
    })


@login_required
def rmm_device_delete(request, pk):
    """Delete an RMM device (orphaned or synced)."""
    org = get_request_organization(request)
    device = get_object_or_404(RMMDevice, pk=pk)

    # Check organization access
    if org and device.organization != org:
        messages.error(request, "You don't have access to this device.")
        return redirect('integrations:rmm_devices')

    if request.method == 'POST':
        device_name = device.device_name
        connection_name = device.connection.name if device.connection else 'Unknown'

        try:
            device.delete()
            messages.success(request, f"✓ RMM device '{device_name}' from {connection_name} deleted successfully.")
            logger.info(f"RMM device '{device_name}' (pk={pk}) deleted successfully")
        except Exception as e:
            logger.error(f"Error deleting RMM device '{device_name}': {e}")
            messages.error(request, f"❌ Error deleting device: {str(e)[:100]}")

        return redirect('integrations:rmm_devices')

    return render(request, 'integrations/rmm_device_confirm_delete.html', {
        'device': device,
    })


@login_required
def rmm_device_map_data(request):
    """Return GeoJSON for RMM devices with location data (organization-specific)."""
    organization = request.current_organization

    if not organization:
        return JsonResponse({'error': 'No organization selected'}, status=400)

    # Get all devices for this organization with coordinates
    devices = RMMDevice.objects.filter(
        organization=organization,
        latitude__isnull=False,
        longitude__isnull=False
    ).select_related('connection').values(
        'id', 'device_name', 'device_type', 'manufacturer', 'model',
        'latitude', 'longitude', 'is_online', 'last_seen',
        'connection__id', 'connection__name'
    )

    # Build GeoJSON feature collection
    features = []
    for device in devices:
        # Determine marker color based on status
        color = 'green' if device['is_online'] else 'red'

        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(device['longitude']), float(device['latitude'])]
            },
            'properties': {
                'id': device['id'],
                'name': device['device_name'],
                'type': device['device_type'],
                'manufacturer': device['manufacturer'],
                'model': device['model'],
                'is_online': device['is_online'],
                'last_seen': device['last_seen'].isoformat() if device['last_seen'] else None,
                'connection_id': device['connection__id'],
                'connection_name': device['connection__name'],
                'url': f"/integrations/rmm/devices/{device['id']}/",
                'marker_type': 'device',
                'marker_color': color
            }
        })

    return JsonResponse({
        'type': 'FeatureCollection',
        'features': features
    })


@login_required
def global_rmm_device_map_data(request):
    """Return GeoJSON for RMM devices with location data (all organizations, superusers and staff only)."""
    # Check if user is staff (MSP tech) or superuser
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False

    if not (request.user.is_superuser or is_staff):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    from core.models import Organization

    # Get all devices with coordinates across all organizations
    devices = RMMDevice.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False
    ).select_related('connection', 'organization').values(
        'id', 'device_name', 'device_type', 'manufacturer', 'model',
        'latitude', 'longitude', 'is_online', 'last_seen',
        'connection__id', 'connection__name',
        'organization__id', 'organization__name'
    )

    # Build GeoJSON feature collection
    features = []
    for device in devices:
        # Determine marker color based on status
        color = 'green' if device['is_online'] else 'red'

        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(device['longitude']), float(device['latitude'])]
            },
            'properties': {
                'id': device['id'],
                'name': device['device_name'],
                'type': device['device_type'],
                'manufacturer': device['manufacturer'],
                'model': device['model'],
                'is_online': device['is_online'],
                'last_seen': device['last_seen'].isoformat() if device['last_seen'] else None,
                'connection_id': device['connection__id'],
                'connection_name': device['connection__name'],
                'organization_id': device['organization__id'],
                'organization_name': device['organization__name'],
                'url': f"/integrations/rmm/devices/{device['id']}/",
                'marker_type': 'device',
                'marker_color': color
            }
        })

    return JsonResponse({
        'type': 'FeatureCollection',
        'features': features
    })


@login_required
@require_POST
def rmm_trigger_sync(request, pk):
    """Manually trigger RMM sync for a connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(RMMConnection.objects.for_organization(org), pk=pk)

    try:
        from integrations.sync import RMMSync
        syncer = RMMSync(connection)
        stats = syncer.sync_all()

        messages.success(
            request,
            f'RMM sync completed successfully. '
            f'Devices: {stats["devices"]["created"]} created, {stats["devices"]["updated"]} updated. '
            f'Alerts: {stats["alerts"]["created"]} created. '
            f'Software: {stats["software"]["created"]} created.'
        )
    except Exception as e:
        messages.error(request, f'Sync failed: {str(e)}')
        logger.exception(f'Manual RMM sync failed for {connection}')

    return redirect('integrations:rmm_detail', pk=connection.pk)


@login_required
@require_admin
def rmm_import_clients(request, pk):
    """
    Import RMM clients as organizations.
    Fetches all unique clients from the RMM system and creates corresponding organizations.
    """
    from core.models import Organization
    from django.db import transaction

    org = get_request_organization(request)
    connection = get_object_or_404(RMMConnection.objects.for_organization(org), pk=pk)

    # GET: Show preview of what will be imported
    if request.method == 'GET':
        try:
            provider = get_rmm_provider(connection)

            # Test connection
            if not provider.test_connection():
                messages.error(request, 'RMM connection test failed. Check your API credentials.')
                return redirect('integrations:rmm_detail', pk=connection.pk)

            # Fetch devices to extract clients
            devices = provider.list_devices()

            # Extract unique clients
            clients = {}  # {client_id: {name, device_count}}
            for device in devices:
                client_id = device.get('client_id')
                client_name = device.get('client_name')

                if client_id and client_name:
                    if client_id not in clients:
                        clients[client_id] = {
                            'id': client_id,
                            'name': client_name,
                            'device_count': 0,
                            'existing_org': None,
                        }
                    clients[client_id]['device_count'] += 1

            # Check which clients already exist as organizations
            for client_id in clients:
                existing = Organization.objects.filter(name=clients[client_id]['name']).first()
                if existing:
                    clients[client_id]['existing_org'] = existing

            return render(request, 'integrations/rmm_import_clients.html', {
                'connection': connection,
                'clients': sorted(clients.values(), key=lambda x: x['name']),
                'total_devices': len(devices),
            })

        except Exception as e:
            messages.error(request, f'Failed to fetch clients: {str(e)}')
            logger.exception(f'Failed to fetch RMM clients for import from {connection}')
            return redirect('integrations:rmm_detail', pk=connection.pk)

    # POST: Create organizations
    elif request.method == 'POST':
        selected_clients = request.POST.getlist('clients')  # List of client_ids

        if not selected_clients:
            messages.warning(request, 'No clients selected for import.')
            return redirect('integrations:rmm_import_clients', pk=connection.pk)

        try:
            provider = get_rmm_provider(connection)
            devices = provider.list_devices()

            # Extract selected clients
            clients_to_import = {}
            for device in devices:
                client_id = device.get('client_id')
                client_name = device.get('client_name')

                if client_id in selected_clients and client_id and client_name:
                    clients_to_import[client_id] = client_name

            # Create organizations
            created_count = 0
            skipped_count = 0

            for client_id, client_name in clients_to_import.items():
                # Check if already exists
                if Organization.objects.filter(name=client_name).exists():
                    skipped_count += 1
                    continue

                # Create new organization
                try:
                    with transaction.atomic():
                        org = Organization.objects.create(
                            name=client_name,
                            is_active=True,
                            description=f'Imported from {connection.name} (RMM Client ID: {client_id})'
                        )
                        created_count += 1
                        logger.info(f'Created organization {org.name} from RMM client {client_id}')
                except Exception as e:
                    logger.error(f'Failed to create organization for client {client_name}: {e}')

            if created_count > 0:
                messages.success(
                    request,
                    f'Successfully imported {created_count} client(s) as organization(s). '
                    f'{skipped_count} client(s) skipped (already exist).'
                )
            else:
                messages.info(request, f'No new organizations created. {skipped_count} client(s) already exist.')

            return redirect('integrations:rmm_detail', pk=connection.pk)

        except Exception as e:
            messages.error(request, f'Import failed: {str(e)}')
            logger.exception(f'Failed to import RMM clients from {connection}')
            return redirect('integrations:rmm_import_clients', pk=connection.pk)


@login_required
@require_admin
def psa_organization_mapping(request, pk):
    """
    Map PSA companies to existing Client St0r organizations.
    Allows pre-sync mapping to prevent duplicate organizations.
    """
    from core.models import Organization
    from integrations.models import ExternalObjectMap
    from django.db.models import Q

    org = get_request_organization(request)
    connection = get_object_or_404(PSAConnection, pk=pk, organization=org)

    if request.method == 'POST':
        # Process mappings
        from django.db import transaction
        mappings_created = 0
        mappings_updated = 0

        try:
            with transaction.atomic():
                for key, value in request.POST.items():
                    if key.startswith('mapping_'):
                        # Extract company ID from key (mapping_<company_id>)
                        company_id = key.replace('mapping_', '')
                        action = value

                        if action == 'ignore':
                            continue
                        elif action == 'create_new':
                            # Mark for org creation during next sync
                            continue
                        else:
                            # action is the organization ID to map to
                            try:
                                target_org = Organization.objects.get(pk=int(action))
                                company = PSACompany.objects.get(pk=company_id, connection=connection)

                                # Create or update ExternalObjectMap
                                ext_map, created = ExternalObjectMap.objects.update_or_create(
                                    connection=connection,
                                    external_type='company',
                                    external_id=company.external_id,
                                    defaults={
                                        'organization': target_org,
                                        'local_type': 'organization',
                                        'local_id': target_org.id,
                                    }
                                )

                                if created:
                                    mappings_created += 1
                                else:
                                    mappings_updated += 1

                                logger.info(
                                    f"{'Created' if created else 'Updated'} mapping: "
                                    f"PSA company '{company.name}' -> Organization '{target_org.name}'"
                                )

                            except (ValueError, Organization.DoesNotExist, PSACompany.DoesNotExist) as e:
                                logger.warning(f"Error mapping company {company_id}: {e}")
                                continue

                if mappings_created > 0 or mappings_updated > 0:
                    messages.success(
                        request,
                        f"Organization mapping saved! Created {mappings_created} new mappings, "
                        f"updated {mappings_updated} existing mappings. Future syncs will respect these mappings."
                    )
                else:
                    messages.info(request, "No mappings were changed.")

                return redirect('integrations:psa_organization_mapping', pk=connection.pk)

        except Exception as e:
            messages.error(request, f"Error saving mappings: {str(e)}")
            logger.exception(f"Error in PSA organization mapping for {connection}")

    # GET request - show mapping form
    # Get all companies from this PSA connection
    companies = PSACompany.objects.filter(connection=connection).order_by('name')

    # Get all organizations (for dropdown)
    all_organizations = Organization.objects.all().order_by('name')

    # Get existing mappings
    existing_mappings = {}
    for mapping in ExternalObjectMap.objects.filter(
        connection=connection,
        external_type='company',
        local_type='organization'
    ):
        existing_mappings[mapping.external_id] = mapping.local_id

    # Build company list with mapping info
    company_mapping_data = []
    for company in companies:
        # Check if already mapped
        mapped_org_id = existing_mappings.get(company.external_id)
        mapped_org = None
        if mapped_org_id:
            try:
                mapped_org = Organization.objects.get(pk=mapped_org_id)
            except Organization.DoesNotExist:
                pass

        # Try to find exact name match as suggestion
        suggested_org = None
        if not mapped_org:
            # Try exact match
            suggested_org = Organization.objects.filter(name__iexact=company.name).first()
            if not suggested_org:
                # Try with prefix removed
                if connection.org_name_prefix:
                    name_without_prefix = company.name.replace(connection.org_name_prefix, '', 1).strip()
                    suggested_org = Organization.objects.filter(name__iexact=name_without_prefix).first()

        company_mapping_data.append({
            'company': company,
            'mapped_org': mapped_org,
            'suggested_org': suggested_org,
        })

    return render(request, 'integrations/psa_organization_mapping.html', {
        'connection': connection,
        'company_mapping_data': company_mapping_data,
        'all_organizations': all_organizations,
    })


@login_required
@require_admin
def rmm_organization_mapping(request, pk):
    """
    Map RMM sites to existing Client St0r organizations.
    Note: RMM uses name-based matching instead of ExternalObjectMap.
    """
    from core.models import Organization
    from django.db.models import Q

    org = get_request_organization(request)
    connection = get_object_or_404(RMMConnection, pk=pk, organization=org)

    if request.method == 'POST':
        # For RMM, we can't use ExternalObjectMap (PSA-only)
        # Instead, we'll help users identify which orgs will match by name
        messages.info(
            request,
            "RMM organizations are matched by name during sync. "
            "Use the organization merge tool to combine duplicate organizations after syncing."
        )
        return redirect('integrations:rmm_detail', pk=connection.pk)

    # GET request - show RMM site analysis
    # Group by client+site so that sites with the same name under different
    # clients are shown separately (e.g. "Hometown" for ClientA ≠ "Hometown" for ClientB)
    from django.db.models import Count
    site_data = RMMDevice.objects.filter(
        connection=connection
    ).values('client_name', 'client_id', 'site_name', 'site_id').annotate(
        device_count=Count('id')
    ).order_by('client_name', 'site_name')

    # Get all organizations
    all_organizations = Organization.objects.all().order_by('name')

    # Build site list with potential matches
    site_mapping_data = []
    for site in site_data:
        client_name = site['client_name'] or ''
        site_name = site['site_name'] or ''

        # Org will be named after the client (preferred) or site
        base_name = client_name if client_name else site_name
        if connection.org_name_prefix:
            org_name = f"{connection.org_name_prefix}{base_name}"
        else:
            org_name = base_name

        existing_org = Organization.objects.filter(name=org_name).first()
        suggested_org = Organization.objects.filter(name__iexact=base_name).first()

        site_mapping_data.append({
            'client_name': client_name,
            'site_name': site_name,
            'site_id': site['site_id'],
            'device_count': site['device_count'],
            'will_create_as': org_name,
            'existing_org': existing_org,
            'suggested_match': suggested_org if not existing_org else None,
        })

    return render(request, 'integrations/rmm_organization_mapping.html', {
        'connection': connection,
        'site_mapping_data': site_mapping_data,
        'all_organizations': all_organizations,
    })

# ============================================================================
# UniFi Integration Views
# ============================================================================

@login_required
@require_admin
def unifi_create(request):
    """Create new UniFi connection."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, "Please select an organization first.")
        return redirect('integrations:integration_list')

    if request.method == 'POST':
        form = UnifiConnectionForm(request.POST, organization=org)
        if form.is_valid():
            connection = form.save()
            messages.success(request, f"UniFi connection '{connection.name}' created.")
            return redirect('integrations:unifi_detail', pk=connection.pk)
    else:
        form = UnifiConnectionForm(organization=org)

    return render(request, 'integrations/unifi_form.html', {'form': form, 'action': 'Create'})


@login_required
def unifi_detail(request, pk):
    """View UniFi connection details and cached data."""
    connection = _get_unifi_connection(request, pk)
    data = connection.cached_data or {}
    is_cloud = data.get('mode') == 'cloud'
    has_legacy = data.get('has_legacy_data', False)
    legacy_ok = data.get('legacy_login_ok', False)

    def _norm_device(d):
        """Flatten device dict to safe, consistent keys for template rendering."""
        return {
            'display_name': d.get('name') or d.get('hostname') or d.get('mac') or d.get('macAddress') or '—',
            'product_type': d.get('productType') or d.get('type') or '—',
            'model': d.get('model') or d.get('shortname') or '—',
            'ip': d.get('ip') or d.get('ipAddress') or '—',
            'mac': d.get('mac') or d.get('macAddress') or '—',
            'serial': d.get('serial') or d.get('serialNumber') or d.get('serialno') or '—',
            'firmware': d.get('version') or d.get('firmwareVersion') or '—',
            'online': bool(d.get('online')) or d.get('state') == 1,
        }

    def _norm_vlan(v):
        """Flatten VLAN dict to safe, consistent keys for template rendering."""
        return {
            'name': v.get('name') or v.get('desc') or '—',
            'vlan_id': v.get('vlan_id') or v.get('vlan') or v.get('vlanId') or '—',
            'subnet': v.get('ip_subnet') or v.get('subnet') or v.get('ipSubnet') or '—',
            'purpose': v.get('purpose') or '—',
        }

    def _resolve_zone(zone_map, zid):
        if not zid and zid != 0:
            return 'any'
        name = zone_map.get(zid) or zone_map.get(str(zid))
        if not name:
            try:
                name = zone_map.get(int(zid))
            except (TypeError, ValueError):
                pass
        return name if name else str(zid)

    def _target_str(val):
        if val is None:
            return ''
        if isinstance(val, list):
            shown = val[:8]
            extra = len(val) - len(shown)
            s = ', '.join(str(x) for x in shown)
            return s + (f' (+{extra} more)' if extra else '')
        if isinstance(val, dict):
            return val.get('type') or val.get('name') or str(val)
        return str(val)

    def _norm_policy(r, zone_map):
        r = dict(r)
        src = r.get('source') or {}
        dst = r.get('destination') or {}
        src_zid = (src.get('zone') or src.get('zone_id') or src.get('zoneId') or
                   r.get('sourceZone') or r.get('source_zone') or r.get('sourceZoneId') or
                   r.get('from_zone') or r.get('fromZone') or '')
        dst_zid = (dst.get('zone') or dst.get('zone_id') or dst.get('zoneId') or
                   r.get('destinationZone') or r.get('destination_zone') or r.get('destinationZoneId') or
                   r.get('to_zone') or r.get('toZone') or '')
        # Try zone_map first, then inline zone name from policy object
        src_resolved = _resolve_zone(zone_map, src_zid)
        if src_resolved == str(src_zid) and src_zid:
            src_resolved = src.get('zoneName') or src.get('name') or src_resolved
        dst_resolved = _resolve_zone(zone_map, dst_zid)
        if dst_resolved == str(dst_zid) and dst_zid:
            dst_resolved = dst.get('zoneName') or dst.get('name') or dst_resolved
        r['src_zone_name'] = src_resolved
        r['dst_zone_name'] = dst_resolved
        # Flatten action if needed
        action = r.get('action', '')
        if isinstance(action, dict):
            r['action'] = action.get('type') or action.get('name') or str(action)
        elif isinstance(action, list):
            r['action'] = ', '.join(str(x) for x in action)
        return r

    def _norm_traffic_rule(r):
        r = dict(r)
        mt = r.get('matching_target') or r.get('matchingTarget')
        r['target_display'] = _target_str(mt) if mt else 'all'
        action = r.get('action', '')
        if isinstance(action, dict):
            r['action'] = action.get('type') or action.get('name') or str(action)
        return r

    def _norm_traffic_route(r):
        r = dict(r)
        mt = r.get('matchingTarget') or r.get('matching_target') or r.get('domains') or r.get('ipAddresses')
        r['target_display'] = _target_str(mt) if mt else 'all'
        return r

    sites = []
    for s in data.get('sites', []):
        zone_map = s.get('zone_map', {})
        site_name = s.get('name', '')
        sites.append({
            'name': site_name,
            'assigned_org_id': (connection.site_org_map or {}).get(site_name),
            'devices': [_norm_device(d) for d in s.get('devices', [])],
            'wlans': s.get('wlans', []),
            'vlans': [_norm_vlan(v) for v in s.get('vlans', [])],
            'firewall_policies': [_norm_policy(r, zone_map) for r in s.get('firewall_policies', [])],
            'traffic_rules': [_norm_traffic_rule(r) for r in s.get('traffic_rules', [])],
            'traffic_routes': [_norm_traffic_route(r) for r in s.get('traffic_routes', [])],
            'zone_map': zone_map,
            'client_count': s.get('client_count', 0),
        })

    # Build list of assignable orgs for cloud org selector
    if is_cloud:
        from core.models import Organization
        from accounts.models import Membership
        if request.user.is_superuser or getattr(request, 'is_staff_user', False):
            available_orgs = list(Organization.objects.filter(is_active=True).order_by('name').values('id', 'name'))
        else:
            member_ids = Membership.objects.filter(
                user=request.user, is_active=True, organization__is_active=True
            ).values_list('organization_id', flat=True)
            available_orgs = list(Organization.objects.filter(id__in=member_ids).order_by('name').values('id', 'name'))
    else:
        available_orgs = []

    site_org_map = connection.site_org_map or {}

    total_devices = sum(len(s['devices']) for s in sites)
    return render(request, 'integrations/unifi_detail.html', {
        'connection': connection,
        'sites': sites,
        'is_cloud': is_cloud,
        'has_legacy': has_legacy,
        'legacy_ok': legacy_ok,
        'total_devices': total_devices,
        'available_orgs': available_orgs,
        'site_org_map': site_org_map,
    })


@login_required
@require_admin
def unifi_edit(request, pk):
    """Edit UniFi connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(UnifiConnection, pk=pk, organization=org)

    if request.method == 'POST':
        form = UnifiConnectionForm(request.POST, instance=connection, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f"UniFi connection '{connection.name}' updated.")
            return redirect('integrations:unifi_detail', pk=connection.pk)
    else:
        form = UnifiConnectionForm(instance=connection, organization=org)

    return render(request, 'integrations/unifi_form.html', {'form': form, 'connection': connection, 'action': 'Edit'})


@login_required
@require_admin
def unifi_delete(request, pk):
    """Delete UniFi connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(UnifiConnection, pk=pk, organization=org)

    if request.method == 'POST':
        name = connection.name
        connection.delete()
        messages.success(request, f"UniFi connection '{name}' deleted.")
        return redirect('integrations:integration_list')

    return render(request, 'integrations/unifi_confirm_delete.html', {'connection': connection})


@login_required
@require_admin
@require_POST
def unifi_site_org(request, pk):
    """Save cloud site → organization assignments (AJAX POST)."""
    from core.models import Organization
    connection = _get_unifi_connection(request, pk)

    if getattr(connection, 'mode', 'self_hosted') != UnifiConnection.MODE_CLOUD:
        return JsonResponse({'ok': False, 'error': 'Only available for cloud connections.'}, status=400)

    import json as _json
    try:
        body = _json.loads(request.body)
        site_org_map = body.get('site_org_map', {})
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)

    # Validate org IDs — only allow orgs the admin can access
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        valid_ids = set(Organization.objects.filter(is_active=True).values_list('id', flat=True))
    else:
        from accounts.models import Membership
        valid_ids = set(
            Membership.objects.filter(user=request.user, is_active=True, organization__is_active=True)
            .values_list('organization_id', flat=True)
        )
    # Include null/empty (clear assignment)
    cleaned = {}
    for site_name, org_id in site_org_map.items():
        if not org_id:
            cleaned[site_name] = None
        elif int(org_id) in valid_ids:
            cleaned[site_name] = int(org_id)

    connection.site_org_map = cleaned
    connection.save(update_fields=['site_org_map'])
    return JsonResponse({'ok': True})


def _get_unifi_connection(request, pk):
    """Get UniFi connection by pk. Superusers/staff may access connections cross-org."""
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        return get_object_or_404(UnifiConnection, pk=pk)
    org = get_request_organization(request)
    return get_object_or_404(UnifiConnection, pk=pk, organization=org)


def _get_unifi_provider(connection):
    """Return the appropriate UniFi provider instance based on connection mode."""
    from integrations.providers.unifi import UnifiProvider, UnifiCloudProvider
    creds = connection.get_credentials()
    if getattr(connection, 'mode', 'self_hosted') == UnifiConnection.MODE_CLOUD:
        return UnifiCloudProvider(api_key=creds.get('api_key', ''))
    return UnifiProvider(connection.host, creds.get('api_key', ''), connection.verify_ssl,
                         username=creds.get('username', ''), password=creds.get('password', ''))


@login_required
@require_write
def unifi_test(request, pk):
    """Test UniFi connection."""
    connection = _get_unifi_connection(request, pk)
    provider = _get_unifi_provider(connection)
    result = provider.test_connection()
    if result['success']:
        messages.success(request, f"Connected: {result['message']}")
    else:
        messages.error(request, f"Connection failed: {result['error']}")
    return redirect('integrations:unifi_detail', pk=pk)


@login_required
@require_write
def unifi_sync(request, pk):
    """Sync UniFi data and regenerate documentation."""
    from django.utils import timezone
    from django.utils.text import slugify
    from docs.models import Document
    import html as html_lib

    connection = _get_unifi_connection(request, pk)

    provider = _get_unifi_provider(connection)
    try:
        data = provider.sync()
        connection.cached_data = data
        connection.last_sync_at = timezone.now()
        connection.last_sync_status = 'ok'
        connection.last_error = ''

        # Build documentation HTML
        now_utc = timezone.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        now_display = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')
        has_legacy = data.get('has_legacy_data', False)
        legacy_login_ok = data.get('legacy_login_ok', False)
        site_sections = ''
        for site in data.get('sites', []):
            # Devices table
            device_rows = ''
            for d in site.get('devices', []):
                name = html_lib.escape(d.get('name') or d.get('hostname') or '—')
                model = html_lib.escape(d.get('model') or d.get('shortname') or '—')
                dtype = html_lib.escape(d.get('type') or d.get('productType') or d.get('productLine') or '—')
                ip = html_lib.escape(str(d.get('ip') or d.get('ipAddress') or '—'))
                mac = html_lib.escape(str(d.get('mac') or d.get('macAddress') or '—'))
                serial = html_lib.escape(str(d.get('serial') or d.get('serialNumber') or d.get('serialno') or '—'))
                firmware = html_lib.escape(str(d.get('version') or d.get('firmwareVersion') or '—'))
                # Self-hosted: state=1 or online=True; Cloud Site Manager: status="online"
                is_online = (d.get('online') if d.get('online') is not None
                             else (d.get('state', 0) == 1
                                   or str(d.get('status', '')).lower() == 'online'))
                status_badge = '<span class="badge bg-success">Online</span>' if is_online else '<span class="badge bg-secondary">Offline</span>'
                device_rows += f'<tr><td>{name}</td><td>{dtype}</td><td>{model}</td><td>{ip}</td><td>{mac}</td><td>{serial}</td><td>{firmware}</td><td>{status_badge}</td></tr>'

            devices_table = f'''
<div class="card mb-3">
  <div class="card-header"><i class="fas fa-network-wired me-2"></i>Devices ({len(site["devices"])})</div>
  <div class="card-body p-0">
    <table class="table table-sm table-striped mb-0">
      <thead><tr><th>Name</th><th>Type</th><th>Model</th><th>IP</th><th>MAC</th><th>Serial</th><th>Firmware</th><th>Status</th></tr></thead>
      <tbody>{device_rows or "<tr><td colspan='8' class='text-muted'>No devices found.</td></tr>"}</tbody>
    </table>
  </div>
</div>''' if site.get('devices') else ''

            # WLANs table
            wlan_rows = ''
            for w in site.get('wlans', []):
                ssid = html_lib.escape(w.get('name', '—'))
                enabled = '<span class="badge bg-success">Enabled</span>' if w.get('enabled', True) else '<span class="badge bg-secondary">Disabled</span>'
                security = html_lib.escape(w.get('security', '—'))
                wlan_rows += f'<tr><td>{ssid}</td><td>{security}</td><td>{enabled}</td></tr>'

            wlans_table = f'''
<div class="card mb-3">
  <div class="card-header"><i class="fas fa-wifi me-2"></i>Wireless Networks ({len(site["wlans"])})</div>
  <div class="card-body p-0">
    <table class="table table-sm table-striped mb-0">
      <thead><tr><th>SSID</th><th>Security</th><th>Status</th></tr></thead>
      <tbody>{wlan_rows or "<tr><td colspan='3' class='text-muted'>No wireless networks.</td></tr>"}</tbody>
    </table>
  </div>
</div>''' if site.get('wlans') else ''

            # VLANs table
            vlan_rows = ''
            for v in site.get('vlans', []):
                vname = html_lib.escape(v.get('name', '—'))
                purpose = html_lib.escape(v.get('purpose', '—'))
                subnet = html_lib.escape(v.get('ip_subnet') or v.get('subnet') or '—')
                vlan_id = html_lib.escape(str(v.get('vlan') or v.get('vlan_id') or '—'))
                vlan_rows += f'<tr><td>{vname}</td><td>{vlan_id}</td><td>{subnet}</td><td>{purpose}</td></tr>'

            vlans_table = f'''
<div class="card mb-3">
  <div class="card-header"><i class="fas fa-sitemap me-2"></i>Networks / VLANs ({len(site["vlans"])})</div>
  <div class="card-body p-0">
    <table class="table table-sm table-striped mb-0">
      <thead><tr><th>Name</th><th>VLAN ID</th><th>Subnet</th><th>Purpose</th></tr></thead>
      <tbody>{vlan_rows or "<tr><td colspan='4' class='text-muted'>No networks found.</td></tr>"}</tbody>
    </table>
  </div>
</div>''' if site.get('vlans') else ''

            # Firewall rules table
            fw_rules = site.get('firewall_rules', [])
            fw_rows = ''
            for r in fw_rules:
                rname = html_lib.escape(r.get('name') or r.get('_id') or '—')
                action = html_lib.escape(r.get('action', '—'))
                proto = html_lib.escape(r.get('protocol') or 'all')
                src = html_lib.escape(r.get('src_address') or r.get('src_networkconf_id') or 'any')
                dst = html_lib.escape(r.get('dst_address') or r.get('dst_networkconf_id') or 'any')
                dport = html_lib.escape(r.get('dst_port') or '')
                enabled = '\u2705' if r.get('enabled', True) else '\u274c'
                action_badge = 'bg-danger' if action == 'drop' else ('bg-warning text-dark' if action == 'reject' else 'bg-success')
                fw_rows += f'<tr><td>{enabled} {rname}</td><td><span class="badge {action_badge}">{action}</span></td><td>{proto}</td><td>{src}</td><td>{dst}{(" :" + dport) if dport else ""}</td></tr>'
            if not has_legacy:
                fw_empty = "<tr><td colspan='5' class='text-muted small'><i class='fas fa-info-circle me-1'></i>Legacy API credentials not configured — add a username + password in the connection settings to enable firewall rule data.</td></tr>"
            elif not legacy_login_ok:
                fw_empty = "<tr><td colspan='5' class='text-warning small'><i class='fas fa-exclamation-triangle me-1'></i>Legacy API login failed — verify the username and password in the connection settings are correct for this controller.</td></tr>"
            else:
                fw_empty = "<tr><td colspan='5' class='text-muted'>No firewall rules found for this site.</td></tr>"
            fw_table = f'''
<div class="card mb-3">
  <div class="card-header"><i class="fas fa-fire-alt me-2"></i>Legacy Firewall Rules ({len(fw_rules)})</div>
  <div class="card-body p-0">
    <table class="table table-sm table-striped mb-0">
      <thead><tr><th>Rule</th><th>Action</th><th>Protocol</th><th>Source</th><th>Destination</th></tr></thead>
      <tbody>{fw_rows or fw_empty}</tbody>
    </table>
  </div>
</div>'''

            # Firewall Policies (zone-based, UniFi OS 3.x+)
            zone_map = site.get('zone_map', {})
            zone_diag = site.get('_zone_diag', [])
            fp_rules = site.get('firewall_policies', [])
            fp_rows = ''
            for r in fp_rules:
                rname = html_lib.escape(r.get('name') or r.get('description') or r.get('_id') or '—')
                action_raw = r.get('action') or r.get('ruleAction') or '—'
                if isinstance(action_raw, dict):
                    action_raw = action_raw.get('type') or action_raw.get('name') or str(action_raw)
                elif isinstance(action_raw, (list, tuple)):
                    action_raw = ', '.join(str(x) for x in action_raw)
                action = html_lib.escape(str(action_raw))
                src = r.get('source') or {}
                dst = r.get('destination') or {}
                src_zid = (src.get('zone') or src.get('zone_id') or src.get('zoneId') or
                           r.get('sourceZone') or r.get('source_zone') or r.get('sourceZoneId') or
                           r.get('from_zone') or r.get('fromZone') or '')
                dst_zid = (dst.get('zone') or dst.get('zone_id') or dst.get('zoneId') or
                           r.get('destinationZone') or r.get('destination_zone') or r.get('destinationZoneId') or
                           r.get('to_zone') or r.get('toZone') or '')
                # Zone name: zone_map lookup (str/int fallback), then inline zoneName, then raw ID
                src_zone_name = (zone_map.get(src_zid) or zone_map.get(str(src_zid)) or
                                 src.get('zoneName') or src.get('name') or '')
                if not src_zone_name and src_zid:
                    try:
                        src_zone_name = zone_map.get(int(src_zid)) or ''
                    except (TypeError, ValueError):
                        pass
                src_zone = html_lib.escape(src_zone_name or str(src_zid) if src_zid else 'any')
                dst_zone_name = (zone_map.get(dst_zid) or zone_map.get(str(dst_zid)) or
                                 dst.get('zoneName') or dst.get('name') or '')
                if not dst_zone_name and dst_zid:
                    try:
                        dst_zone_name = zone_map.get(int(dst_zid)) or ''
                    except (TypeError, ValueError):
                        pass
                dst_zone = html_lib.escape(dst_zone_name or str(dst_zid) if dst_zid else 'any')
                enabled = '\u2705' if r.get('enabled', True) else '\u274c'
                action_badge = 'bg-danger' if action.upper() in ('DROP', 'REJECT', 'BLOCK') else 'bg-success'
                fp_rows += f'<tr><td>{enabled} {rname}</td><td><span class="badge {action_badge}">{action}</span></td><td>{src_zone}</td><td>{dst_zone}</td></tr>'
            if not has_legacy:
                fp_empty = "<tr><td colspan='4' class='text-muted small'><i class='fas fa-info-circle me-1'></i>Legacy API credentials not configured — add a username + password in the connection settings to enable firewall policy data.</td></tr>"
            elif not legacy_login_ok:
                fp_empty = "<tr><td colspan='4' class='text-warning small'><i class='fas fa-exclamation-triangle me-1'></i>Legacy API login failed — verify the username and password in the connection settings are correct for this controller.</td></tr>"
            else:
                fp_diag = site.get('_fp_diag', [])
                if fp_diag:
                    diag_rows = ''.join(
                        f"<tr><td class='font-monospace small'>{html_lib.escape(d.get('path',''))}</td>"
                        f"<td>{html_lib.escape(d.get('auth',''))}</td>"
                        f"<td>{html_lib.escape(str(d.get('status','')))} "
                        f"{'✓ empty (' + str(d.get('keys','')) + ')' if 'keys' in d else html_lib.escape(str(d.get('snippet','')))}</td></tr>"
                        for d in fp_diag
                    )
                    fp_empty = (
                        "<tr><td colspan='4' class='text-muted'>No firewall policies found for this site. "
                        "API diagnostic (re-sync to refresh):</td></tr>"
                        f"<tr><td colspan='4' class='p-0'><table class='table table-sm mb-0 small'>"
                        f"<thead><tr><th>Path</th><th>Auth</th><th>Result</th></tr></thead>"
                        f"<tbody>{diag_rows}</tbody></table></td></tr>"
                    )
                else:
                    fp_empty = "<tr><td colspan='4' class='text-muted'>No firewall policies found for this site.</td></tr>"
            # Zone diagnostic (only shown when zone_map is empty and policies exist)
            zone_section = ''
            if not zone_map and zone_diag:
                zone_diag_rows = ''.join(
                    f"<tr><td class='font-monospace small'>{html_lib.escape(d.get('path',''))}</td>"
                    f"<td>{html_lib.escape(d.get('auth',''))}</td>"
                    f"<td>{html_lib.escape(str(d.get('status','')))} "
                    f"{'✓ empty (' + str(d.get('keys','')) + ')' if 'keys' in d else html_lib.escape(str(d.get('snippet','')))}</td></tr>"
                    for d in zone_diag
                )
                zone_section = (
                    f"<div class='card mb-3'>"
                    f"<div class='card-header text-warning'><i class='fas fa-exclamation-triangle me-2'></i>"
                    f"Zone Names Unavailable — API Diagnostic (re-sync to refresh)</div>"
                    f"<div class='card-body p-0'><table class='table table-sm mb-0 small'>"
                    f"<thead><tr><th>Path Tried</th><th>Auth</th><th>Result</th></tr></thead>"
                    f"<tbody>{zone_diag_rows}</tbody></table></div></div>"
                )

            fp_table = f'''
<div class="card mb-3">
  <div class="card-header"><i class="fas fa-shield-alt me-2"></i>Firewall Policies / Zone Rules ({len(fp_rules)})</div>
  <div class="card-body p-0">
    <table class="table table-sm table-striped mb-0">
      <thead><tr><th>Policy</th><th>Action</th><th>Source Zone</th><th>Dest Zone</th></tr></thead>
      <tbody>{fp_rows or fp_empty}</tbody>
    </table>
  </div>
</div>
{zone_section}'''

            # Traffic Rules (UniFi OS 3.x+)
            tr_rules = site.get('traffic_rules', [])
            tr_rows = ''
            for r in tr_rules:
                rname = html_lib.escape(r.get('description') or r.get('name') or r.get('_id') or '—')
                action_raw = r.get('action', '—')
                if isinstance(action_raw, dict):
                    action_raw = action_raw.get('type') or action_raw.get('name') or str(action_raw)
                action = html_lib.escape(str(action_raw))
                matching_raw = r.get('matching_target') or 'all'
                if isinstance(matching_raw, list):
                    shown = matching_raw[:8]
                    extra = len(matching_raw) - len(shown)
                    matching_raw = ', '.join(str(x) for x in shown) + (f' (+{extra} more)' if extra else '')
                elif isinstance(matching_raw, dict):
                    matching_raw = matching_raw.get('type') or matching_raw.get('name') or str(matching_raw)
                matching = html_lib.escape(str(matching_raw))
                enabled = '\u2705' if r.get('enabled', True) else '\u274c'
                action_badge = 'bg-danger' if action in ('BLOCK', 'REJECT') else ('bg-warning text-dark' if action == 'THROTTLE' else 'bg-success')
                tr_rows += f'<tr><td>{enabled} {rname}</td><td><span class="badge {action_badge}">{action}</span></td><td>{matching}</td></tr>'
            if not has_legacy:
                tr_empty = "<tr><td colspan='3' class='text-muted small'><i class='fas fa-info-circle me-1'></i>Legacy API credentials not configured — add a username + password in the connection settings to enable traffic rule data.</td></tr>"
            elif not legacy_login_ok:
                tr_empty = "<tr><td colspan='3' class='text-warning small'><i class='fas fa-exclamation-triangle me-1'></i>Legacy API login failed — verify the username and password in the connection settings are correct for this controller.</td></tr>"
            else:
                tr_empty = "<tr><td colspan='3' class='text-muted'>No traffic rules found.</td></tr>"
            tr_table = f'''
<div class="card mb-3">
  <div class="card-header"><i class="fas fa-traffic-light me-2"></i>Traffic Rules ({len(tr_rules)})</div>
  <div class="card-body p-0">
    <table class="table table-sm table-striped mb-0">
      <thead><tr><th>Rule</th><th>Action</th><th>Target</th></tr></thead>
      <tbody>{tr_rows or tr_empty}</tbody>
    </table>
  </div>
</div>'''

            # Traffic Routes (Network 10.x — website/app routing and blocking)
            troute_rules = site.get('traffic_routes', [])
            troute_rows = ''
            for r in troute_rules:
                rname = html_lib.escape(r.get('name') or r.get('description') or r.get('_id') or '—')
                action_tr = r.get('action') or r.get('type') or '—'
                if isinstance(action_tr, dict):
                    action_tr = action_tr.get('type') or action_tr.get('name') or str(action_tr)
                action = html_lib.escape(str(action_tr))
                target_raw = (r.get('matchingTarget') or r.get('matching_target') or
                              r.get('domains') or r.get('ipAddresses') or 'all')
                if isinstance(target_raw, list):
                    shown = target_raw[:8]
                    extra = len(target_raw) - len(shown)
                    target_raw = ', '.join(str(x) for x in shown) + (f' (+{extra} more)' if extra else '')
                elif isinstance(target_raw, dict):
                    target_raw = target_raw.get('type') or target_raw.get('name') or str(target_raw)
                target = html_lib.escape(str(target_raw))
                enabled = '\u2705' if r.get('enabled', True) else '\u274c'
                action_badge = 'bg-danger' if action.upper() in ('BLOCK', 'DROP', 'REJECT') else 'bg-success'
                troute_rows += f'<tr><td>{enabled} {rname}</td><td><span class="badge {action_badge}">{action}</span></td><td class="small text-muted">{target}</td></tr>'
            troute_table = f'''
<div class="card mb-3">
  <div class="card-header"><i class="fas fa-route me-2"></i>Traffic Routes / App Rules ({len(troute_rules)})</div>
  <div class="card-body p-0">
    <table class="table table-sm table-striped mb-0">
      <thead><tr><th>Route</th><th>Action</th><th>Target</th></tr></thead>
      <tbody>{troute_rows or "<tr><td colspan='3' class='text-muted'>No traffic routes configured.</td></tr>"}</tbody>
    </table>
  </div>
</div>''' if troute_rules else ''

            # Endpoint probe results (shown when both policies and rules are empty)
            probe = site.get('_probe', {})
            probe_section = ''
            if probe:
                probe_rows = ''.join(
                    f"<tr><td class='font-monospace small'>{html_lib.escape(p)}</td>"
                    f"<td class='small text-truncate' style='max-width:400px'>{html_lib.escape(b[:120])}</td></tr>"
                    for p, b in probe.items()
                )
                probe_section = f'''
<div class="card mb-3 border-info">
  <div class="card-header bg-info text-white small">
    <i class="fas fa-search me-2"></i>Endpoint Discovery — paths that returned HTTP 200 (re-sync to refresh)
  </div>
  <div class="card-body p-0">
    <table class="table table-sm mb-0 small">
      <thead><tr><th>Path</th><th>Response snippet</th></tr></thead>
      <tbody>{probe_rows or "<tr><td colspan='2' class='text-muted'>No endpoints discovered at 200 — controller may use a completely different path structure.</td></tr>"}</tbody>
    </table>
  </div>
</div>'''

            site_sections += f'''
<div class="card mb-4">
  <div class="card-header bg-primary text-white">
    <i class="fas fa-map-marker-alt me-2"></i><strong>{html_lib.escape(site["name"])}</strong>
    <span class="badge bg-light text-dark ms-2">{site["client_count"]} clients connected</span>
  </div>
  <div class="card-body">
    {devices_table}{wlans_table}{vlans_table}{fw_table}{fp_table}{tr_table}{troute_table}{probe_section}
  </div>
</div>'''

        cloud_note = ''
        if data.get('mode') == 'cloud':
            cloud_note = '<div class="alert alert-info mb-3"><i class="fas fa-cloud me-2"></i><strong>Cloud mode (UniFi Site Manager):</strong> WLANs, VLANs, firewall rules, zone policies and traffic rules are not available via the Site Manager API. To see these, add a second <strong>Self-Hosted</strong> UniFi connection pointing at the same controller with username + password credentials.</div>'

        synced_by = request.user.get_full_name() or request.user.username if request.user.is_authenticated else ''
        synced_by_html = f' by <strong>{html_lib.escape(synced_by)}</strong>' if synced_by else ''
        content = f'''<div class="container-fluid p-0">
<div class="alert alert-secondary d-flex justify-content-between align-items-center mb-3">
  <span><i class="fas fa-info-circle me-2"></i>Auto-generated from UniFi — last updated <span class="local-time" data-utc="{now_utc}">{now_display}</span>{synced_by_html}</span>
  <span class="badge bg-primary">{len(data.get("sites", []))} site(s)</span>
</div>
{cloud_note}{site_sections or "<p class='text-muted'>No sites found.</p>"}
</div>'''

        # Create or update document
        doc_title = f'{connection.name} — UniFi Network Documentation'
        if connection.doc:
            connection.doc.title = doc_title
            connection.doc.body = content
            connection.doc.content_type = 'html'
            connection.doc.save()
        else:
            base_slug = slugify(f'{connection.name}-unifi-network')
            slug = base_slug
            counter = 1
            while Document.objects.filter(organization=connection.organization, slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            doc = Document.objects.create(
                organization=connection.organization,
                title=doc_title,
                body=content,
                content_type='html',
                slug=slug,
            )
            connection.doc = doc

        connection.save()
        site_count = len(data.get('sites', []))
        messages.success(request, f"Synced {site_count} site(s). Documentation updated.")
    except Exception as e:
        connection.last_sync_status = 'error'
        connection.last_error = str(e)
        connection.save(update_fields=['last_sync_status', 'last_error'])
        messages.error(request, f"Sync failed: {e}")

    return redirect('integrations:unifi_detail', pk=pk)


@login_required
@require_admin
def unifi_import_assets(request, pk):
    """Import UniFi devices into the asset registry."""
    from assets.models import Asset
    from django.core.validators import validate_ipv46_address

    connection = _get_unifi_connection(request, pk)
    org = get_request_organization(request)
    data = connection.cached_data or {}
    is_cloud = data.get('mode') == 'cloud'
    site_org_map = connection.site_org_map or {}
    site_filter = request.GET.get('site', '').strip()
    sites = [s for s in data.get('sites', []) if not site_filter or s.get('name') == site_filter]

    # Map UniFi productType to asset types — handles both prefix codes (local API)
    # and full strings (cloud Site Manager API)
    _TYPE_MAP = [
        # Local API prefix codes (model field prefixes e.g. UAP-AC-Pro, USW-48, U6-Pro)
        ('uap', 'wireless_ap'),   # classic APs
        ('u6', 'wireless_ap'),    # U6-Pro, U6-Enterprise, U6-LR, U6-Mesh, U6-IW
        ('u7', 'wireless_ap'),    # U7-Pro, U7-Enterprise (newer gen)
        ('u2', 'wireless_ap'),    # U2-Nano, U2-Mini
        ('uaf', 'wireless_ap'),   # UAP-FlexHD
        ('ubb', 'wireless_ap'),   # UniFi Building Bridge
        ('usw', 'switch'),
        ('udm', 'router'),
        ('uxg', 'router'),
        ('ugw', 'router'),        # UniFi Security Gateway
        ('usg', 'router'),
        ('ups', 'ups'),
        ('ucg', 'router'),
        # Cloud Site Manager API — camelCase productType (lowercased for matching)
        ('accesspoint', 'wireless_ap'),    # 'accessPoint'
        ('networkswitch', 'switch'),       # 'networkSwitch'
        ('network_switch', 'switch'),      # 'NETWORK_SWITCH' (uppercased variant)
        ('securitygateway', 'router'),     # 'securityGateway'
        ('dreamrouter', 'router'),         # 'dreamRouter'
        ('dreamwall', 'router'),           # 'dreamWall'
        ('dreammachine', 'router'),        # 'dreamMachine'
        ('cloudgateway', 'router'),        # 'cloudGateway'
        ('powerunit', 'ups'),              # 'powerUnit'
        # Cloud API full strings (snake_case / hyphenated / plain)
        ('access_point', 'wireless_ap'),
        ('access-point', 'wireless_ap'),
        ('wireless', 'wireless_ap'),
        ('switch', 'switch'),
        ('switching', 'switch'),
        ('router', 'router'),
        ('routing', 'router'),
        ('gateway', 'router'),
        ('firewall', 'firewall'),
    ]

    def _asset_type(device):
        # Try productType, then type, then model (model prefix encodes type, e.g. UAP-AC-Pro)
        pt = (device.get('productType') or device.get('type') or
              device.get('model') or device.get('shortname') or '').lower()
        for keyword, atype in _TYPE_MAP:
            if pt.startswith(keyword) or pt == keyword:
                return atype
        return 'other'

    def _clean_ip(raw):
        try:
            validate_ipv46_address(raw)
            return raw
        except Exception:
            return ''

    def _norm_preview(d):
        """Normalize raw UniFi device dict to safe keys for template preview."""
        mac = (d.get('mac') or d.get('macAddress') or '').lower().replace('-', ':')
        return {
            'name': d.get('name') or d.get('hostname') or mac or '—',
            'productType': d.get('productType') or d.get('type') or '—',
            'model': d.get('model') or d.get('shortname') or '—',
            'ip': d.get('ip') or d.get('ipAddress') or '—',
            'mac': mac or '—',
            'serial': d.get('serial') or d.get('serialNumber') or d.get('serialno') or '—',
            'version': d.get('version') or d.get('firmwareVersion') or '—',
        }

    # Build flat device list with site context; keep raw dict for POST processing
    # For cloud connections, annotate each device with its assigned org
    from core.models import Organization as _Org
    org_name_cache = {}
    all_devices = []
    for site in sites:
        site_name = site.get('name', '')
        assigned_org_id = site_org_map.get(site_name)
        if assigned_org_id and assigned_org_id not in org_name_cache:
            try:
                org_name_cache[assigned_org_id] = _Org.objects.get(pk=assigned_org_id).name
            except _Org.DoesNotExist:
                org_name_cache[assigned_org_id] = f'Org #{assigned_org_id}'
        for d in site.get('devices', []):
            all_devices.append({
                'site_name': site_name,
                'assigned_org_id': assigned_org_id,
                'assigned_org_name': org_name_cache.get(assigned_org_id, ''),
                'device': _norm_preview(d),
                '_raw': d,
            })

    if request.method == 'POST':
        def _normalize(d):
            mac = (d.get('mac') or d.get('macAddress') or '').lower().replace('-', ':')
            return {
                'name': d.get('name') or d.get('hostname') or mac or 'Unknown Device',
                'mac': mac,
                'ip': _clean_ip(d.get('ip') or d.get('ipAddress') or ''),
                'model': d.get('model') or d.get('shortname') or '',
                'asset_type': _asset_type(d),
                'manufacturer': 'Ubiquiti',
                'serial_number': d.get('serial') or d.get('serialNumber') or d.get('serialno') or '',
                'os_version': d.get('version') or d.get('firmwareVersion') or '',
                'hostname': d.get('hostname') or '',
            }

        totals = {'created': 0, 'updated': 0, 'skipped': 0}

        if is_cloud and site_org_map:
            # Cloud: group devices by assigned org, skip unassigned sites
            groups = {}  # org_id -> list of normalized devices
            for item in all_devices:
                oid = item.get('assigned_org_id')
                if not oid:
                    continue
                groups.setdefault(oid, []).append(_normalize(item['_raw']))
            if not groups:
                messages.warning(request, 'No sites have an organization assigned. Use the org dropdown on the detail page to assign sites before importing.')
                return redirect('integrations:unifi_detail', pk=pk)
            for oid, devs in groups.items():
                try:
                    target_org = _Org.objects.get(pk=oid)
                    r = _import_devices_to_assets(target_org, devs, 'UniFi')
                    totals['created'] += r['created']
                    totals['updated'] += r['updated']
                    totals['skipped'] += r['skipped']
                except _Org.DoesNotExist:
                    pass
        else:
            # Self-hosted or cloud without org map: import all to connection's org
            target_org = connection.organization or org
            normalized = [_normalize(item['_raw']) for item in all_devices]
            r = _import_devices_to_assets(target_org, normalized, 'UniFi')
            totals = r

        messages.success(request, f"Import complete: {totals['created']} created, {totals['updated']} updated, {totals['skipped']} unchanged.")
        return redirect('integrations:unifi_detail', pk=pk)

    return render(request, 'integrations/unifi_import_assets.html', {
        'connection': connection,
        'all_devices': all_devices,
        'is_cloud': is_cloud,
        'site_org_map': site_org_map,
        'site_filter': site_filter,
    })


# ============================================================================
# Shared network asset import helper
# ============================================================================

def _import_devices_to_assets(org, devices, source_label='Network'):
    """
    Create or update Asset records from a list of normalized device dicts.

    Each device dict must have:
        name, mac, ip, model, asset_type, manufacturer, serial_number, os_version
    Optional: hostname

    Devices without a mac AND without a serial_number are skipped.
    Returns {'created': N, 'updated': N, 'skipped': N}.
    """
    from assets.models import Asset
    from django.core.validators import validate_ipv46_address

    def _clean_ip(raw):
        try:
            validate_ipv46_address(str(raw))
            return str(raw)
        except Exception:
            return ''

    created = updated = skipped = 0
    for d in devices:
        mac = (d.get('mac') or '').lower().replace('-', ':').strip()
        serial = (d.get('serial_number') or '').strip()

        # Skip devices with no identifiable key
        if not mac and not serial:
            skipped += 1
            continue

        name = (d.get('name') or '').strip() or mac or serial or 'Unknown Device'
        ip_raw = _clean_ip(d.get('ip') or '')
        hostname = (d.get('hostname') or '').strip()

        fields = {
            'name': name,
            'asset_type': d.get('asset_type') or 'other',
            'manufacturer': d.get('manufacturer') or '',
            'model': d.get('model') or '',
            'serial_number': serial,
            'mac_address': mac,
            'os_version': d.get('os_version') or '',
        }
        if hostname:
            fields['hostname'] = hostname
        if ip_raw:
            fields['ip_address'] = ip_raw

        # Match by MAC first, then serial number
        existing = None
        if mac:
            existing = Asset.objects.filter(organization=org, mac_address__iexact=mac).first()
        if not existing and serial:
            existing = Asset.objects.filter(organization=org, serial_number__iexact=serial).first()

        if existing:
            changed = False
            for k, v in fields.items():
                if v and getattr(existing, k, '') != v:
                    setattr(existing, k, v)
                    changed = True
            if changed:
                existing.save()
                updated += 1
            else:
                skipped += 1
        else:
            Asset.objects.create(organization=org, **{k: v for k, v in fields.items() if v})
            created += 1

    return {'created': created, 'updated': updated, 'skipped': skipped}


# ============================================================================
# Omada Integration Views
# ============================================================================

@login_required
@require_admin
def omada_create(request):
    """Create new Omada connection."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, "Please select an organization first.")
        return redirect('integrations:integration_list')

    if request.method == 'POST':
        form = OmadaConnectionForm(request.POST, organization=org)
        if form.is_valid():
            connection = form.save()
            messages.success(request, f"Omada connection '{connection.name}' created.")
            return redirect('integrations:omada_detail', pk=connection.pk)
    else:
        form = OmadaConnectionForm(organization=org)

    return render(request, 'integrations/omada_form.html', {'form': form, 'action': 'Create'})


@login_required
def omada_detail(request, pk):
    """View Omada connection details and cached data."""
    org = get_request_organization(request)
    connection = get_object_or_404(OmadaConnection, pk=pk, organization=org)
    data = connection.cached_data or {}

    sites = []
    for s in data.get('sites', []):
        devices = s.get('devices', [])
        sites.append({
            'name': s.get('name', ''),
            'devices': devices,
        })

    total_devices = sum(len(s['devices']) for s in sites)
    return render(request, 'integrations/omada_detail.html', {
        'connection': connection,
        'sites': sites,
        'total_devices': total_devices,
    })


@login_required
@require_admin
def omada_edit(request, pk):
    """Edit Omada connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(OmadaConnection, pk=pk, organization=org)

    if request.method == 'POST':
        form = OmadaConnectionForm(request.POST, instance=connection, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f"Omada connection '{connection.name}' updated.")
            return redirect('integrations:omada_detail', pk=connection.pk)
    else:
        form = OmadaConnectionForm(instance=connection, organization=org)

    return render(request, 'integrations/omada_form.html', {'form': form, 'connection': connection, 'action': 'Edit'})


@login_required
@require_admin
def omada_delete(request, pk):
    """Delete Omada connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(OmadaConnection, pk=pk, organization=org)

    if request.method == 'POST':
        name = connection.name
        connection.delete()
        messages.success(request, f"Omada connection '{name}' deleted.")
        return redirect('integrations:integration_list')

    return render(request, 'integrations/omada_confirm_delete.html', {'connection': connection})


@login_required
@require_write
def omada_test(request, pk):
    """Test Omada connection."""
    from integrations.providers.omada import OmadaProvider
    org = get_request_organization(request)
    connection = get_object_or_404(OmadaConnection, pk=pk, organization=org)
    creds = connection.get_credentials()
    provider = OmadaProvider(
        host=connection.host,
        username=creds.get('username', ''),
        password=creds.get('password', ''),
        verify_ssl=connection.verify_ssl,
    )
    result = provider.test_connection()
    if result['success']:
        messages.success(request, f"Connected: {result['message']}")
    else:
        messages.error(request, f"Connection failed: {result.get('error', 'Unknown error')}")
    return redirect('integrations:omada_detail', pk=pk)


@login_required
@require_write
def omada_sync(request, pk):
    """Sync Omada data and optionally import assets."""
    from django.utils import timezone
    from integrations.providers.omada import OmadaProvider

    org = get_request_organization(request)
    connection = get_object_or_404(OmadaConnection, pk=pk, organization=org)
    creds = connection.get_credentials()
    provider = OmadaProvider(
        host=connection.host,
        username=creds.get('username', ''),
        password=creds.get('password', ''),
        verify_ssl=connection.verify_ssl,
    )
    try:
        data = provider.sync()
        connection.cached_data = data
        connection.last_sync_at = timezone.now()
        connection.last_sync_status = 'ok'
        connection.last_error = ''

        if connection.auto_sync_assets:
            all_devices = []
            for s in data.get('sites', []):
                all_devices.extend(s.get('devices', []))
            _import_devices_to_assets(org, all_devices, 'Omada')
            connection.last_asset_sync_at = timezone.now()

        connection.save()
        site_count = len(data.get('sites', []))
        messages.success(request, f"Synced {site_count} site(s).")
    except Exception as e:
        connection.last_sync_status = 'error'
        connection.last_error = str(e)
        connection.save(update_fields=['last_sync_status', 'last_error'])
        messages.error(request, f"Sync failed: {e}")

    return redirect('integrations:omada_detail', pk=pk)


@login_required
@require_admin
def omada_import_assets(request, pk):
    """Import Omada devices into the asset registry."""
    org = get_request_organization(request)
    connection = get_object_or_404(OmadaConnection, pk=pk, organization=org)
    data = connection.cached_data or {}

    all_devices = []
    for site in data.get('sites', []):
        for d in site.get('devices', []):
            all_devices.append({
                'site_name': site.get('name', ''),
                'device': d,
            })

    if request.method == 'POST':
        from django.utils import timezone
        normalized = [item['device'] for item in all_devices]
        result = _import_devices_to_assets(org, normalized, 'Omada')
        connection.last_asset_sync_at = timezone.now()
        connection.save(update_fields=['last_asset_sync_at'])
        messages.success(request, f"Import complete: {result['created']} created, {result['updated']} updated, {result['skipped']} unchanged.")
        return redirect('integrations:omada_detail', pk=pk)

    return render(request, 'integrations/omada_import_assets.html', {
        'connection': connection,
        'all_devices': all_devices,
    })


# ============================================================================
# Grandstream Integration Views
# ============================================================================

@login_required
@require_admin
def grandstream_create(request):
    """Create new Grandstream connection."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, "Please select an organization first.")
        return redirect('integrations:integration_list')

    if request.method == 'POST':
        form = GrandstreamConnectionForm(request.POST, organization=org)
        if form.is_valid():
            connection = form.save()
            messages.success(request, f"Grandstream connection '{connection.name}' created.")
            return redirect('integrations:grandstream_detail', pk=connection.pk)
    else:
        form = GrandstreamConnectionForm(organization=org)

    return render(request, 'integrations/grandstream_form.html', {'form': form, 'action': 'Create'})


@login_required
def grandstream_detail(request, pk):
    """View Grandstream connection details and cached data."""
    org = get_request_organization(request)
    connection = get_object_or_404(GrandstreamConnection, pk=pk, organization=org)
    data = connection.cached_data or {}

    sites = []
    for s in data.get('sites', []):
        devices = s.get('devices', [])
        sites.append({
            'name': s.get('name', ''),
            'devices': devices,
        })

    total_devices = sum(len(s['devices']) for s in sites)
    return render(request, 'integrations/grandstream_detail.html', {
        'connection': connection,
        'sites': sites,
        'total_devices': total_devices,
    })


@login_required
@require_admin
def grandstream_edit(request, pk):
    """Edit Grandstream connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(GrandstreamConnection, pk=pk, organization=org)

    if request.method == 'POST':
        form = GrandstreamConnectionForm(request.POST, instance=connection, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f"Grandstream connection '{connection.name}' updated.")
            return redirect('integrations:grandstream_detail', pk=connection.pk)
    else:
        form = GrandstreamConnectionForm(instance=connection, organization=org)

    return render(request, 'integrations/grandstream_form.html', {'form': form, 'connection': connection, 'action': 'Edit'})


@login_required
@require_admin
def grandstream_delete(request, pk):
    """Delete Grandstream connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(GrandstreamConnection, pk=pk, organization=org)

    if request.method == 'POST':
        name = connection.name
        connection.delete()
        messages.success(request, f"Grandstream connection '{name}' deleted.")
        return redirect('integrations:integration_list')

    return render(request, 'integrations/grandstream_confirm_delete.html', {'connection': connection})


@login_required
@require_write
def grandstream_test(request, pk):
    """Test Grandstream connection."""
    from integrations.providers.grandstream import GrandstreamProvider
    org = get_request_organization(request)
    connection = get_object_or_404(GrandstreamConnection, pk=pk, organization=org)
    creds = connection.get_credentials()
    provider = GrandstreamProvider(
        host=connection.host,
        api_key=creds.get('api_key', ''),
        verify_ssl=connection.verify_ssl,
    )
    result = provider.test_connection()
    if result['success']:
        messages.success(request, f"Connected: {result['message']}")
    else:
        messages.error(request, f"Connection failed: {result.get('error', 'Unknown error')}")
    return redirect('integrations:grandstream_detail', pk=pk)


@login_required
@require_write
def grandstream_sync(request, pk):
    """Sync Grandstream data and optionally import assets."""
    from django.utils import timezone
    from integrations.providers.grandstream import GrandstreamProvider

    org = get_request_organization(request)
    connection = get_object_or_404(GrandstreamConnection, pk=pk, organization=org)
    creds = connection.get_credentials()
    provider = GrandstreamProvider(
        host=connection.host,
        api_key=creds.get('api_key', ''),
        verify_ssl=connection.verify_ssl,
    )
    try:
        data = provider.sync()
        connection.cached_data = data
        connection.last_sync_at = timezone.now()
        connection.last_sync_status = 'ok'
        connection.last_error = ''

        if connection.auto_sync_assets:
            all_devices = []
            for s in data.get('sites', []):
                all_devices.extend(s.get('devices', []))
            _import_devices_to_assets(org, all_devices, 'Grandstream')
            connection.last_asset_sync_at = timezone.now()

        connection.save()
        site_count = len(data.get('sites', []))
        messages.success(request, f"Synced {site_count} network(s).")
    except Exception as e:
        connection.last_sync_status = 'error'
        connection.last_error = str(e)
        connection.save(update_fields=['last_sync_status', 'last_error'])
        messages.error(request, f"Sync failed: {e}")

    return redirect('integrations:grandstream_detail', pk=pk)


@login_required
@require_admin
def grandstream_import_assets(request, pk):
    """Import Grandstream devices into the asset registry."""
    org = get_request_organization(request)
    connection = get_object_or_404(GrandstreamConnection, pk=pk, organization=org)
    data = connection.cached_data or {}

    all_devices = []
    for site in data.get('sites', []):
        for d in site.get('devices', []):
            all_devices.append({
                'site_name': site.get('name', ''),
                'device': d,
            })

    if request.method == 'POST':
        from django.utils import timezone
        normalized = [item['device'] for item in all_devices]
        result = _import_devices_to_assets(org, normalized, 'Grandstream')
        connection.last_asset_sync_at = timezone.now()
        connection.save(update_fields=['last_asset_sync_at'])
        messages.success(request, f"Import complete: {result['created']} created, {result['updated']} updated, {result['skipped']} unchanged.")
        return redirect('integrations:grandstream_detail', pk=pk)

    return render(request, 'integrations/grandstream_import_assets.html', {
        'connection': connection,
        'all_devices': all_devices,
    })


# ============================================================================
# M365 Integration Views
# ============================================================================

@login_required
@require_admin
def m365_create(request):
    """Create new M365 connection."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, "Please select an organization first.")
        return redirect('integrations:integration_list')

    if request.method == 'POST':
        form = M365ConnectionForm(request.POST, organization=org)
        if form.is_valid():
            connection = form.save()
            messages.success(request, f"M365 connection '{connection.name}' created.")
            return redirect('integrations:m365_detail', pk=connection.pk)
    else:
        form = M365ConnectionForm(organization=org)

    return render(request, 'integrations/m365_form.html', {'form': form, 'action': 'Create'})


@login_required
def m365_detail(request, pk):
    """View M365 connection details and cached data."""
    org = get_request_organization(request)
    connection = get_object_or_404(M365Connection, pk=pk, organization=org)
    data = connection.cached_data or {}
    raw_mailbox = data.get('mailbox_usage', [])
    first_mb = raw_mailbox[0] if raw_mailbox else {}
    mailbox_permission_error = bool(first_mb.get('permission_error') or first_mb.get('_permission_error'))
    mailbox_rows = [] if mailbox_permission_error else [
        r for r in raw_mailbox
        if not r.get('permission_error') and not r.get('_permission_error')
    ]
    onedrive_usage = data.get('onedrive_usage', [])
    return render(request, 'integrations/m365_detail.html', {
        'connection': connection,
        'users': data.get('users', []),
        'licenses': data.get('licenses', []),
        'teams': data.get('teams', []),
        'sharepoint_sites': data.get('sharepoint_sites', []),
        'roles': data.get('roles', []),
        'mailbox_rows': mailbox_rows,
        'mailbox_permission_error': mailbox_permission_error,
        'shared_mailboxes': data.get('shared_mailboxes', []),
        'onedrive_usage': onedrive_usage,
    })


@login_required
@require_admin
def m365_edit(request, pk):
    """Edit M365 connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(M365Connection, pk=pk, organization=org)

    if request.method == 'POST':
        form = M365ConnectionForm(request.POST, instance=connection, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f"M365 connection '{connection.name}' updated.")
            return redirect('integrations:m365_detail', pk=connection.pk)
    else:
        form = M365ConnectionForm(instance=connection, organization=org)

    return render(request, 'integrations/m365_form.html', {'form': form, 'connection': connection, 'action': 'Edit'})


@login_required
@require_admin
def m365_delete(request, pk):
    """Delete M365 connection."""
    org = get_request_organization(request)
    connection = get_object_or_404(M365Connection, pk=pk, organization=org)

    if request.method == 'POST':
        name = connection.name
        connection.delete()
        messages.success(request, f"M365 connection '{name}' deleted.")
        return redirect('integrations:integration_list')

    return render(request, 'integrations/m365_confirm_delete.html', {'connection': connection})


@login_required
@require_write
def m365_test(request, pk):
    """Test M365 connection."""
    from integrations.providers.m365 import M365Provider
    org = get_request_organization(request)
    connection = get_object_or_404(M365Connection, pk=pk, organization=org)
    creds = connection.get_credentials()
    provider = M365Provider(connection.tenant_id, creds.get('client_id', ''), creds.get('client_secret', ''))
    result = provider.test_connection()
    if result['success']:
        messages.success(request, f"\u2713 {result['message']}")
    else:
        messages.error(request, f"\u2717 {result['error']}")
    return redirect('integrations:m365_detail', pk=pk)


@login_required
@require_write
def m365_sync(request, pk):
    """Sync M365 data and regenerate documentation."""
    from integrations.providers.m365 import M365Provider
    from django.utils import timezone
    from django.utils.text import slugify
    from docs.models import Document
    import html as html_lib

    org = get_request_organization(request)
    connection = get_object_or_404(M365Connection, pk=pk, organization=org)
    creds = connection.get_credentials()

    provider = M365Provider(connection.tenant_id, creds.get('client_id', ''), creds.get('client_secret', ''))
    try:
        data = provider.sync()
        connection.cached_data = data
        connection.last_sync_at = timezone.now()
        connection.last_sync_status = 'ok'
        connection.last_error = ''

        now_utc = timezone.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        now_display = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')
        users = data.get('users', [])
        licenses = data.get('licenses', [])
        teams = data.get('teams', [])
        sites = data.get('sharepoint_sites', [])
        roles = data.get('roles', [])
        ca_policies = data.get('conditional_access_policies', [])
        secure_score = data.get('secure_score', {})
        devices = data.get('devices', [])
        sp_usage = data.get('sharepoint_usage', [])
        defender_alerts = data.get('defender_alerts', [])
        onedrive_usage = data.get('onedrive_usage', [])

        def _safe_section(fn, label):
            try:
                return fn()
            except Exception as exc:
                logger.error(f"M365 sync: error building {label} section: {exc}")
                return f'<div class="alert alert-warning mb-3"><i class="fas fa-exclamation-triangle me-2"></i>Could not render <strong>{label}</strong> section: {html_lib.escape(str(exc))}</div>'

        def _build_users():
            user_rows = ''
            for u in users[:200]:
                name = html_lib.escape(u.get('displayName') or '\u2014')
                upn = html_lib.escape(u.get('userPrincipalName') or '\u2014')
                title = html_lib.escape(u.get('jobTitle') or '\u2014')
                dept = html_lib.escape(u.get('department') or '\u2014')
                user_rows += f'<tr><td>{name}</td><td>{upn}</td><td>{title}</td><td>{dept}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-users me-2"></i>Licensed Users ({len(users)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Name</th><th>UPN</th><th>Title</th><th>Department</th></tr></thead>
    <tbody>{user_rows or "<tr><td colspan='4' class='text-muted'>No users found.</td></tr>"}</tbody>
  </table></div></div>'''

        def _build_licenses():
            lic_rows = ''
            for lic in licenses:
                sku = html_lib.escape(lic.get('skuPartNumber') or '\u2014')
                consumed = lic.get('consumedUnits') or 0
                available = (lic.get('prepaidUnits') or {}).get('enabled') or 0
                lic_rows += f'<tr><td>{sku}</td><td>{consumed}</td><td>{available}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-key me-2"></i>Assigned Licenses ({len(licenses)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>License SKU</th><th>Assigned</th><th>Available</th></tr></thead>
    <tbody>{lic_rows or "<tr><td colspan='3' class='text-muted'>No licenses found.</td></tr>"}</tbody>
  </table></div></div>'''

        def _build_mailbox_usage():
            raw_mb = data.get('mailbox_usage', [])
            if raw_mb and raw_mb[0].get('permission_error'):
                perm = raw_mb[0].get('required', 'MailboxSettings.Read / Reports.Read.All')
                return f'<div class="alert alert-warning mb-3"><i class="fas fa-key me-2"></i><strong>Mailbox Usage</strong> — missing permission: <code>{html_lib.escape(perm)}</code>. Add this to your Azure AD app registration and grant admin consent.</div>'
            mb_rows = [r for r in raw_mb if not r.get('permission_error')]
            if not mb_rows:
                return '<div class="card mb-3"><div class="card-header"><i class="fas fa-envelope me-2"></i>Mailbox Usage</div><div class="card-body"><p class="text-muted mb-0">No mailbox data returned. Ensure <code>Reports.Read.All</code> is granted and the M365 sync has run.</p></div></div>'
            # v3.17.489 / issue #133 — if any row is still anonymized
            # after the UPN-join de-anonymization in m365.sync(), show
            # a hint about the tenant admin setting that disables the
            # MS Graph privacy hashing entirely.
            anon_remaining = sum(1 for r in mb_rows if r.get('_anonymized'))
            anon_banner = ''
            if anon_remaining:
                anon_banner = (
                    f'<div class="alert alert-info small mb-3">'
                    f'<i class="fas fa-info-circle me-2"></i>'
                    f'<strong>{anon_remaining} of {len(mb_rows)} mailbox rows</strong> still '
                    f'show anonymized names (we couldn\'t match them to a user via UPN). '
                    f'To stop Microsoft Graph from anonymizing report data at all, '
                    f'a tenant admin can turn off "Concealed names" at: '
                    f'<a href="https://admin.microsoft.com/Adminportal/Home#/Settings/Services/:/Settings/L1/Reports" target="_blank" rel="noopener">'
                    f'M365 Admin Center → Settings → Org settings → Reports</a> → '
                    f'uncheck <em>"Display anonymous identifiers instead of names, '
                    f'group names, and sites in all reports"</em> → Save. Re-run the M365 sync after.'
                    f'</div>'
                )
            def _fmt_bytes(b):
                try:
                    b = int(b)
                    if b >= 1_073_741_824:
                        return f'{b/1_073_741_824:.1f} GB'
                    return f'{b/1_048_576:.1f} MB'
                except Exception:
                    return '\u2014'
            rows_html = ''
            for r in mb_rows[:500]:
                name = html_lib.escape(r.get('displayName') or '\u2014')
                upn = html_lib.escape(r.get('userPrincipalName') or '\u2014')
                rtype = html_lib.escape(r.get('recipientType') or '\u2014')
                storage = _fmt_bytes(r.get('storageUsedInBytes') or 0)
                items = r.get('itemCount') or 0
                last_active = html_lib.escape(r.get('lastActivityDate') or '\u2014')
                rows_html += f'<tr><td>{name}</td><td>{upn}</td><td>{rtype}</td><td>{storage}</td><td>{items}</td><td>{last_active}</td></tr>'
            return f'''{anon_banner}<div class="card mb-3">
  <div class="card-header"><i class="fas fa-envelope me-2"></i>Mailbox Usage ({len(mb_rows)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Name</th><th>UPN</th><th>Type</th><th>Storage Used</th><th>Items</th><th>Last Active</th></tr></thead>
    <tbody>{rows_html or "<tr><td colspan='6' class='text-muted'>No mailbox data.</td></tr>"}</tbody>
  </table></div></div>'''

        def _build_shared_mailboxes():
            shared_mbs = data.get('shared_mailboxes', [])
            if not shared_mbs:
                return ''
            smb_rows = ''
            for u in shared_mbs[:100]:
                sname = html_lib.escape(u.get('displayName') or '\u2014')
                mail = html_lib.escape(u.get('mail') or u.get('userPrincipalName') or '\u2014')
                smb_rows += f'<tr><td>{sname}</td><td>{mail}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-envelope me-2"></i>Shared Mailboxes ({len(shared_mbs)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Name</th><th>Address</th></tr></thead>
    <tbody>{smb_rows}</tbody>
  </table></div></div>'''

        def _build_teams():
            if not teams:
                return ''
            team_rows = ''
            for t in teams:
                tname = html_lib.escape(t.get('displayName') or '\u2014')
                vis = html_lib.escape(t.get('visibility') or 'Private')
                desc = html_lib.escape((t.get('description') or '')[:80])
                team_rows += f'<tr><td>{tname}</td><td>{vis}</td><td>{desc}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-comments me-2"></i>Microsoft Teams ({len(teams)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Name</th><th>Visibility</th><th>Description</th></tr></thead>
    <tbody>{team_rows}</tbody>
  </table></div></div>'''

        def _build_sharepoint():
            if not sites:
                return ''
            sp_rows = ''
            for s in sites[:50]:
                sname = html_lib.escape(s.get('displayName') or '\u2014')
                url = html_lib.escape(s.get('webUrl') or '')
                sp_rows += f'<tr><td>{sname}</td><td><a href="{url}" target="_blank">{url}</a></td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-globe me-2"></i>SharePoint Sites ({len(sites)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Name</th><th>URL</th></tr></thead>
    <tbody>{sp_rows}</tbody>
  </table></div></div>'''

        def _build_entra_devices():
            if not devices:
                return ''
            dev_rows = ''
            for d in devices[:200]:
                dname = html_lib.escape(d.get('displayName') or '\u2014')
                os_name = html_lib.escape(d.get('operatingSystem') or '\u2014')
                os_ver = html_lib.escape(d.get('operatingSystemVersion') or '')
                trust = html_lib.escape(d.get('trustType') or '\u2014')
                compliant = '\u2705' if d.get('isCompliant') else ('\u274c' if d.get('isManaged') else '\u2014')
                dev_rows += f'<tr><td>{dname}</td><td>{os_name} {os_ver}</td><td>{trust}</td><td>{compliant}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-laptop me-2"></i>Entra ID Devices ({len(devices)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Device</th><th>OS</th><th>Join Type</th><th>Compliant</th></tr></thead>
    <tbody>{dev_rows}</tbody>
  </table></div></div>'''

        def _build_roles():
            if not roles:
                return ''
            role_rows = ''
            for r in roles:
                rname = html_lib.escape(r.get('displayName') or '\u2014')
                members = r.get('members') or []
                member_names = ', '.join(html_lib.escape(m.get('displayName') or '') for m in members[:5])
                if len(members) > 5:
                    member_names += f' +{len(members)-5} more'
                role_rows += f'<tr><td>{rname}</td><td>{len(members)}</td><td>{member_names}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-shield-alt me-2"></i>Entra ID Roles ({len(roles)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Role</th><th>Members</th><th>Assigned To</th></tr></thead>
    <tbody>{role_rows}</tbody>
  </table></div></div>'''

        def _build_ca_policies():
            ca_rows = ''
            for p in ca_policies:
                if not isinstance(p, dict):
                    continue
                pname = html_lib.escape(p.get('displayName') or '\u2014')
                state = str(p.get('state') or 'unknown')
                badge = {'enabled': 'bg-success', 'disabled': 'bg-secondary', 'enabledForReportingButNotEnforced': 'bg-warning text-dark'}.get(state, 'bg-secondary')
                state_label = html_lib.escape(state.replace('enabledForReportingButNotEnforced', 'Report-only'))
                modified = (p.get('modifiedDateTime') or p.get('createdDateTime') or '')[:10]
                ca_rows += f'<tr><td>{pname}</td><td><span class="badge {badge}">{state_label}</span></td><td>{modified}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-lock me-2"></i>Conditional Access Policies ({len(ca_policies)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Policy</th><th>State</th><th>Modified</th></tr></thead>
    <tbody>{ca_rows or "<tr><td colspan='3' class='text-muted'>No CA policies (may need Policy.Read.All permission).</td></tr>"}</tbody>
  </table></div></div>'''

        def _build_secure_score():
            if not secure_score:
                return ''
            current = float(secure_score.get('currentScore') or 0)
            maximum = float(secure_score.get('maxScore') or 0)
            pct = float(secure_score.get('percentageScore') or (round(current / maximum * 100, 1) if maximum else 0))
            score_date = (secure_score.get('createdDateTime') or '')[:10]
            bar_colour = 'bg-danger' if pct < 40 else ('bg-warning' if pct < 70 else 'bg-success')
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-shield-alt me-2"></i>Microsoft Secure Score</div>
  <div class="card-body">
    <div class="d-flex align-items-center mb-2">
      <span class="display-6 fw-bold me-3">{current:.0f}</span>
      <span class="text-muted">/ {maximum:.0f} points &nbsp;({pct:.1f}%)</span>
      <span class="ms-auto text-muted small">as of {score_date}</span>
    </div>
    <div class="progress" style="height:12px">
      <div class="progress-bar {bar_colour}" style="width:{min(pct,100):.1f}%"></div>
    </div>
  </div>
</div>'''

        def _build_sp_usage():
            if not sp_usage:
                return ''
            if sp_usage[0].get('permission_error'):
                return f'<div class="alert alert-warning mb-3"><i class="fas fa-key me-2"></i><strong>SharePoint Storage Usage</strong> — missing permission: <code>{sp_usage[0].get("required")}</code>. Add this to your Azure AD app registration.</div>'
            if sp_usage[0].get('no_sites'):
                return '<div class="alert alert-info mb-3"><i class="fas fa-info-circle me-2"></i><strong>SharePoint Storage</strong> — no sites returned by the Graph API. Ensure admin consent has been granted for <code>Sites.Read.All</code> and that your tenant has SharePoint Online enabled.</div>'
            sp_rows = ''
            for s in sp_usage[:100]:
                sname = html_lib.escape(s.get('siteUrl') or s.get('siteName') or s.get('displayName') or '\u2014')
                owner = html_lib.escape(s.get('ownerDisplayName') or s.get('ownerPrincipalName') or '\u2014')
                used_bytes = s.get('storageUsedInBytes') or s.get('storageUsedInMB', 0)
                alloc_bytes = s.get('storageAllocatedInBytes') or s.get('storageAllocatedInMB', 0)
                # Handle MB vs bytes — report API returns bytes
                if used_bytes > 1_000_000:
                    used_gb = round(used_bytes / 1_073_741_824, 2)
                    alloc_gb = round(alloc_bytes / 1_073_741_824, 2) if alloc_bytes else 0
                else:
                    used_gb = round(used_bytes / 1024, 2)
                    alloc_gb = round(alloc_bytes / 1024, 2) if alloc_bytes else 0
                pct = round(used_gb / alloc_gb * 100, 1) if alloc_gb else 0
                bar = f'<div class="progress" style="height:6px;min-width:60px"><div class="progress-bar {"bg-danger" if pct>85 else "bg-warning" if pct>60 else "bg-success"}" style="width:{min(pct,100):.1f}%"></div></div>'
                sp_rows += f'<tr><td class="small">{sname}</td><td class="small">{owner}</td><td class="small">{used_gb:.2f} GB</td><td class="small">{alloc_gb:.2f} GB</td><td>{bar} {pct:.1f}%</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-chart-pie me-2"></i>SharePoint Storage Usage ({len(sp_usage)} sites)</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Site</th><th>Owner</th><th>Used</th><th>Quota</th><th>Usage</th></tr></thead>
    <tbody>{sp_rows}</tbody>
  </table></div></div>'''

        def _build_onedrive_usage():
            if not onedrive_usage:
                return ''
            if onedrive_usage[0].get('permission_error'):
                return f'<div class="alert alert-warning mb-3"><i class="fas fa-key me-2"></i><strong>OneDrive Storage</strong> — missing permission: <code>{onedrive_usage[0].get("required")}</code>. Add <code>Reports.Read.All</code> to your Azure AD app registration.</div>'
            od_rows = ''
            for u in onedrive_usage[:200]:
                uname = html_lib.escape(u.get('displayName') or u.get('userPrincipalName') or '—')
                upn = html_lib.escape(u.get('userPrincipalName') or '—')
                used_bytes = u.get('storageUsedInBytes') or 0
                alloc_bytes = u.get('storageAllocatedInBytes') or 0
                file_count = u.get('fileCount') or 0
                last_act = html_lib.escape(u.get('lastActivityDate') or '—')
                used_gb = round(used_bytes / 1_073_741_824, 2) if used_bytes > 1_000_000 else round(used_bytes / 1024, 2)
                alloc_gb = round(alloc_bytes / 1_073_741_824, 2) if alloc_bytes > 1_000_000 else round(alloc_bytes / 1024, 2)
                pct = round(used_gb / alloc_gb * 100, 1) if alloc_gb else 0
                bar = f'<div class="progress" style="height:6px;min-width:60px"><div class="progress-bar {"bg-danger" if pct>85 else "bg-warning" if pct>60 else "bg-success"}" style="width:{min(pct,100):.1f}%"></div></div>'
                od_rows += f'<tr><td class="small">{uname}</td><td class="small text-muted">{upn}</td><td class="small">{used_gb:.2f} GB</td><td class="small">{alloc_gb:.2f} GB</td><td>{bar} {pct:.1f}%</td><td class="small">{file_count:,}</td><td class="small">{last_act}</td></tr>'
            if not od_rows:
                return '<div class="card mb-3"><div class="card-header"><i class="fas fa-cloud me-2"></i>OneDrive Storage</div><div class="card-body"><p class="text-muted mb-0">No OneDrive activity found in the last 30 days.</p></div></div>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-cloud me-2"></i>OneDrive Storage ({len(onedrive_usage)} users)</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Name</th><th>User</th><th>Used</th><th>Quota</th><th>Usage</th><th>Files</th><th>Last Activity</th></tr></thead>
    <tbody>{od_rows}</tbody>
  </table></div></div>'''

        def _build_defender():
            if not defender_alerts:
                return '<div class="card mb-3"><div class="card-header"><i class="fas fa-shield-virus me-2"></i>Microsoft Defender Alerts</div><div class="card-body"><p class="text-muted mb-0"><i class="fas fa-check-circle text-success me-1"></i>No active Defender alerts found.</p></div></div>'
            if defender_alerts[0].get('permission_error'):
                return f'<div class="alert alert-warning mb-3"><i class="fas fa-key me-2"></i><strong>Defender Alerts</strong> — missing permission: <code>{defender_alerts[0].get("required")}</code>. Add <code>SecurityAlert.Read.All</code> to your Azure AD app registration (Application permission) and grant admin consent. <span class="text-muted">If you have already added it and granted consent, re-run the sync — a token issued before consent won\'t carry the new permission.</span></div>'
            if defender_alerts[0].get('unavailable'):
                # Issue #143: permission is fine, but the tenant isn't onboarded/
                # licensed for Microsoft Defender. Show a neutral note, not a
                # scary "you're missing a permission" warning.
                reason = html_lib.escape(defender_alerts[0].get('reason') or '')
                return f'<div class="card mb-3"><div class="card-header"><i class="fas fa-shield-virus me-2"></i>Microsoft Defender Alerts</div><div class="card-body"><p class="text-muted mb-1"><i class="fas fa-circle-info me-1"></i>Defender alerts are unavailable for this tenant. This does not affect the rest of the M365 sync.</p><p class="small text-muted mb-0">{reason}</p></div></div>'
            sev_badge = {'high': 'bg-danger', 'medium': 'bg-warning text-dark', 'low': 'bg-info text-dark', 'informational': 'bg-secondary'}
            da_rows = ''
            for a in defender_alerts[:50]:
                title = html_lib.escape(a.get('title') or '\u2014')
                sev = (a.get('severity') or 'informational').lower()
                status = html_lib.escape(a.get('status') or '—')
                source = html_lib.escape(a.get('serviceSource') or a.get('category') or '—')
                # Format timestamp: Graph API returns UTC ISO 8601; render as local time via JS
                raw_ts = a.get('createdDateTime') or ''
                created = f'<span class="local-time" data-utc="{html_lib.escape(raw_ts)}">{raw_ts[:16].replace("T", " ")} UTC</span>' if raw_ts else '—'
                # Username: assignedTo or first entry in userStates
                assigned = a.get('assignedTo') or ''
                if not assigned:
                    user_states = a.get('userStates') or []
                    if user_states and isinstance(user_states, list):
                        assigned = (user_states[0].get('userPrincipalName') or
                                    user_states[0].get('accountName') or '')
                user_cell = html_lib.escape(assigned) if assigned else '<span class="text-muted">—</span>'
                badge = sev_badge.get(sev, 'bg-secondary')
                da_rows += f'<tr><td>{title}</td><td><span class="badge {badge}">{sev}</span></td><td>{status}</td><td>{source}</td><td>{user_cell}</td><td>{created}</td></tr>'
            return f'''<div class="card mb-3">
  <div class="card-header"><i class="fas fa-shield-virus me-2"></i>Microsoft Defender Alerts ({len(defender_alerts)})</div>
  <div class="card-body p-0"><table class="table table-sm table-striped mb-0">
    <thead><tr><th>Alert</th><th>Severity</th><th>Status</th><th>Source</th><th>User</th><th>Date</th></tr></thead>
    <tbody>{da_rows}</tbody>
  </table></div></div>'''

        score_section    = _safe_section(_build_secure_score,     'Secure Score')
        users_section    = _safe_section(_build_users,            'Users')
        licenses_section = _safe_section(_build_licenses,         'Licenses')
        mailbox_section  = _safe_section(_build_mailbox_usage,    'Mailbox Usage')
        smb_section      = _safe_section(_build_shared_mailboxes, 'Shared Mailboxes')
        teams_section    = _safe_section(_build_teams,            'Teams')
        sp_section       = _safe_section(_build_sharepoint,       'SharePoint')
        devices_section  = _safe_section(_build_entra_devices,    'Entra Devices')
        roles_section    = _safe_section(_build_roles,            'Roles')
        ca_section       = _safe_section(_build_ca_policies,      'Conditional Access')
        sp_usage_section    = _safe_section(_build_sp_usage,         'SharePoint Usage')
        onedrive_section    = _safe_section(_build_onedrive_usage,  'OneDrive Usage')
        defender_section    = _safe_section(_build_defender,         'Defender Alerts')

        m365_synced_by = request.user.get_full_name() or request.user.username if request.user.is_authenticated else ''
        m365_synced_by_html = f' by <strong>{html_lib.escape(m365_synced_by)}</strong>' if m365_synced_by else ''
        content = f'''<div class="container-fluid p-0">
<div class="alert alert-secondary d-flex justify-content-between align-items-center mb-3">
  <span><i class="fas fa-info-circle me-2"></i>Auto-generated from Microsoft 365 \u2014 last updated <span class="local-time" data-utc="{now_utc}">{now_display}</span>{m365_synced_by_html}</span>
  <span class="badge bg-primary">Tenant: {html_lib.escape(connection.tenant_id[:8])}...</span>
</div>
{score_section}
{defender_section}
{users_section}
{licenses_section}
{mailbox_section}
{smb_section}
{teams_section}
{sp_section}
{sp_usage_section}
{onedrive_section}
{devices_section}
{roles_section}
{ca_section}
</div>'''

        doc_title = f'{connection.name} \u2014 M365 Tenant Documentation'
        if connection.doc:
            connection.doc.title = doc_title
            connection.doc.body = content
            connection.doc.content_type = 'html'
            connection.doc.save()
        else:
            base_slug = slugify(f'{connection.name}-m365-tenant')
            slug = base_slug
            counter = 1
            while Document.objects.filter(organization=connection.organization, slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            doc = Document.objects.create(
                organization=connection.organization,
                title=doc_title,
                body=content,
                content_type='html',
                slug=slug,
            )
            connection.doc = doc

        connection.save()
        extras = []
        if ca_policies:
            extras.append(f"{len(ca_policies)} CA policies")
        if secure_score:
            extras.append(f"secure score {secure_score.get('currentScore', 0):.0f}/{secure_score.get('maxScore', 0):.0f}")
        extra_str = (', ' + ', '.join(extras)) if extras else ''
        messages.success(request, f"\u2713 M365 sync complete. {len(users)} users, {len(licenses)} licenses, {len(teams)} teams{extra_str}.")
    except Exception as e:
        connection.last_sync_status = 'error'
        connection.last_error = str(e)
        connection.save(update_fields=['last_sync_status', 'last_error'])
        messages.error(request, f"Sync failed: {e}")

    return redirect('integrations:m365_detail', pk=pk)


# ---------------------------------------------------------------------------
# Distributors (Workstream 8)
# ---------------------------------------------------------------------------

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def distributor_list(request):
    from .models import DistributorConnection
    rows = DistributorConnection.objects.select_related('organization').order_by('name')
    return render(request, 'integrations/distributor_list.html', {'connections': rows})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def distributor_create(request):
    return _distributor_form(request, pk=None)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def distributor_edit(request, pk):
    return _distributor_form(request, pk=pk)


def _distributor_form(request, pk):
    from .models import DistributorConnection
    from core.models import Organization
    from .providers.distributors import PROVIDER_REGISTRY

    item = get_object_or_404(DistributorConnection, pk=pk) if pk else None

    if request.method == 'POST':
        org_id = request.POST.get('organization') or ''
        provider_type = request.POST.get('provider_type') or ''
        name = (request.POST.get('name') or '').strip()
        base_url = (request.POST.get('base_url') or '').strip()
        client_id = (request.POST.get('client_id') or '').strip()
        client_secret = (request.POST.get('client_secret') or '').strip()
        customer_number = (request.POST.get('customer_number') or '').strip()
        webhook_secret = (request.POST.get('webhook_secret') or '').strip()
        is_active = request.POST.get('is_active') == 'on'
        sync_enabled = request.POST.get('sync_enabled') == 'on'

        if provider_type not in PROVIDER_REGISTRY:
            messages.error(request, 'Unsupported distributor provider.')
            return redirect(request.path)

        try:
            org = Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist:
            messages.error(request, 'Pick a valid organization.')
            return redirect(request.path)

        if item is None:
            item = DistributorConnection(organization=org, provider_type=provider_type, name=name)
        else:
            item.organization = org
            item.provider_type = provider_type
            item.name = name
        item.base_url = base_url
        item.is_active = is_active
        item.sync_enabled = sync_enabled

        # Only update credentials if provided. Empty strings keep existing.
        creds = item.get_credentials() or {}
        if client_id:
            creds['client_id'] = client_id
        if client_secret:
            creds['client_secret'] = client_secret
        if customer_number:
            creds['customer_number'] = customer_number
        if creds:
            item.set_credentials(creds)

        if webhook_secret:
            item.set_webhook_secret(webhook_secret)

        item.save()
        from audit.models import AuditLog
        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=org,
            object_type='integrations.DistributorConnection', object_id=item.pk,
            object_repr=item.name,
            description=f'{"Updated" if pk else "Created"} distributor connection {item.name} ({provider_type})',
            path=request.path,
        )
        messages.success(request, f'Saved "{item.name}".')
        return redirect('integrations:distributor_list')

    from core.models import Organization
    return render(request, 'integrations/distributor_form.html', {
        'item': item,
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'provider_types': DistributorConnection.PROVIDER_TYPES,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def distributor_delete(request, pk):
    from .models import DistributorConnection
    item = get_object_or_404(DistributorConnection, pk=pk)
    if request.method == 'POST':
        name = item.name
        item.delete()
        messages.success(request, f'Deleted "{name}".')
        return redirect('integrations:distributor_list')
    return render(request, 'integrations/distributor_confirm_delete.html', {'item': item})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def distributor_test(request, pk):
    from .models import DistributorConnection
    from .providers.distributors import get_distributor_provider
    item = get_object_or_404(DistributorConnection, pk=pk)
    provider = get_distributor_provider(item)
    if provider is None:
        return JsonResponse({'ok': False, 'error': 'No provider for this type'})
    try:
        ok = provider.test_connection()
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)[:300]})
    return JsonResponse({'ok': bool(ok)})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def distributor_pricing(request, pk):
    """Ad-hoc price lookup form. POST: sku, qty → JSON."""
    from .models import DistributorConnection
    from .providers.distributors import get_distributor_provider
    item = get_object_or_404(DistributorConnection, pk=pk)
    provider = get_distributor_provider(item)
    if request.method == 'POST':
        sku = (request.POST.get('sku') or '').strip()
        try:
            qty = int(request.POST.get('qty') or '1')
        except ValueError:
            qty = 1
        if not provider or not sku:
            return JsonResponse({'error': 'Missing sku or unsupported provider'})
        try:
            return JsonResponse(provider.get_pricing(sku, qty=qty))
        except Exception as e:
            return JsonResponse({'error': str(e)[:300]})
    return render(request, 'integrations/distributor_pricing.html', {'item': item})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def distributor_stock_check(request):
    """
    Phase 13 v10 (v3.17.272): query live stock for a SKU across ALL
    active DistributorConnection rows in one shot. Each adapter
    already implements `check_stock(sku)`; this view fans out, captures
    timing, and renders a comparison table so a buyer can pick the
    cheapest in-stock distributor for the same part.
    """
    from .models import DistributorConnection
    from .providers.distributors import get_distributor_provider
    import time as _time

    sku = (request.GET.get('sku') or '').strip()
    results = []

    if sku:
        connections = (DistributorConnection.objects
                       .filter(is_active=True)
                       .order_by('name'))
        for conn in connections:
            provider = get_distributor_provider(conn)
            if provider is None:
                results.append({
                    'connection': conn,
                    'ok': False,
                    'error': 'no provider for this type',
                    'qty': None, 'unit_price': None, 'elapsed_ms': 0,
                })
                continue
            t0 = _time.monotonic()
            try:
                stock = provider.check_stock(sku)
                pricing = {}
                try:
                    pricing = provider.get_pricing(sku, qty=1) or {}
                except Exception:
                    pricing = {}
                elapsed_ms = int((_time.monotonic() - t0) * 1000)
                if 'error' in stock:
                    results.append({
                        'connection': conn,
                        'ok': False,
                        'error': stock.get('error'),
                        'qty': None, 'unit_price': None,
                        'elapsed_ms': elapsed_ms,
                    })
                else:
                    results.append({
                        'connection': conn,
                        'ok': True,
                        'qty': stock.get('total_qty'),
                        'unit_price': pricing.get('unit_price'),
                        'currency': pricing.get('currency') or 'USD',
                        'elapsed_ms': elapsed_ms,
                        'error': '',
                    })
            except Exception as exc:
                results.append({
                    'connection': conn,
                    'ok': False,
                    'error': str(exc)[:300],
                    'qty': None, 'unit_price': None,
                    'elapsed_ms': int((_time.monotonic() - t0) * 1000),
                })

    return render(request, 'integrations/distributor_stock_check.html', {
        'sku': sku,
        'results': results,
        'has_query': bool(sku),
    })


@csrf_exempt
@require_http_methods(['POST'])
def distributor_webhook(request, token):
    """
    Public webhook receiver. Path token + per-connection HMAC signature
    are verified inside the provider's `handle_webhook`. Always returns
    200 to avoid the upstream retrying — failures land in
    DistributorWebhookEvent for review.
    """
    from .models import DistributorConnection, DistributorWebhookEvent
    from .providers.distributors import get_distributor_provider
    conn = DistributorConnection.objects.filter(webhook_token=token, is_active=True).first()
    if conn is None:
        return JsonResponse({'ok': False, 'error': 'unknown token'}, status=404)
    raw_body = request.body or b''
    raw_body = raw_body[:64 * 1024]  # cap
    headers = {k: v for k, v in request.headers.items()}
    headers_summary = {k: v[:200] for k, v in headers.items()
                       if k.lower() in ('content-type', 'x-ingram-signature',
                                         'x-event-type', 'user-agent')}

    provider = get_distributor_provider(conn)
    parsed = {'event_type': '', 'signature_valid': False, 'parsed': {}}
    error = ''
    if provider is None:
        error = 'no provider for connection'
    else:
        try:
            parsed = provider.handle_webhook(headers=headers, raw_body=raw_body)
        except Exception as e:
            error = str(e)[:500]

    DistributorWebhookEvent.objects.create(
        connection=conn,
        event_type=parsed.get('event_type') or '',
        signature_valid=bool(parsed.get('signature_valid')),
        body_truncated=raw_body.decode('utf-8', errors='replace')[:64 * 1024],
        headers_summary=headers_summary,
        processed=not error,
        process_error=error,
    )
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Accounting connections (Workstream 5 — billing)
# ---------------------------------------------------------------------------

import secrets as _secrets


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_list(request):
    rows = DistributorConnection.objects.none()  # placeholder; using AccountingConnection below
    rows = AccountingConnection.objects.select_related('organization').order_by('name')
    return render(request, 'integrations/accounting_list.html', {'connections': rows})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_create(request):
    return _accounting_form(request, pk=None)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_edit(request, pk):
    return _accounting_form(request, pk=pk)


def _accounting_form(request, pk):
    from core.models import Organization
    from .providers.accounting import PROVIDER_REGISTRY

    item = get_object_or_404(AccountingConnection, pk=pk) if pk else None

    if request.method == 'POST':
        org_id = request.POST.get('organization') or ''
        provider_type = request.POST.get('provider_type') or ''
        name = (request.POST.get('name') or '').strip()
        client_id = (request.POST.get('client_id') or '').strip()
        client_secret = (request.POST.get('client_secret') or '').strip()
        is_active = request.POST.get('is_active') == 'on'
        sync_enabled = request.POST.get('sync_enabled') == 'on'

        if provider_type not in PROVIDER_REGISTRY:
            messages.error(request, 'Unsupported accounting provider.')
            return redirect(request.path)
        try:
            org = Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist:
            messages.error(request, 'Pick a valid organization.')
            return redirect(request.path)

        if item is None:
            item = AccountingConnection(organization=org, provider_type=provider_type, name=name)
        else:
            item.organization = org
            item.provider_type = provider_type
            item.name = name
        item.is_active = is_active
        item.sync_enabled = sync_enabled
        try:
            item.default_tax_rate = request.POST.get('default_tax_rate') or 0
        except (TypeError, ValueError):
            item.default_tax_rate = 0

        creds = item.get_credentials() or {}
        if client_id:
            creds['client_id'] = client_id
        if client_secret:
            creds['client_secret'] = client_secret
        item.set_credentials(creds)
        item.save()

        from audit.models import AuditLog
        AuditLog.log(
            user=request.user, action='update' if pk else 'create',
            organization=org,
            object_type='integrations.AccountingConnection', object_id=item.pk,
            object_repr=item.name,
            description=f'{"Updated" if pk else "Created"} accounting connection {item.name}',
            path=request.path,
        )
        messages.success(request, f'Saved "{item.name}". Click Connect to start the OAuth flow.')
        return redirect('integrations:accounting_list')

    return render(request, 'integrations/accounting_form.html', {
        'item': item,
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'provider_types': AccountingConnection.PROVIDER_TYPES,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_delete(request, pk):
    item = get_object_or_404(AccountingConnection, pk=pk)
    if request.method == 'POST':
        name = item.name
        item.delete()
        messages.success(request, f'Deleted "{name}".')
        return redirect('integrations:accounting_list')
    return render(request, 'integrations/accounting_confirm_delete.html', {'item': item})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
@require_POST
def accounting_sync_now(request, pk):
    """Phase 44.3 (v3.17.531): run the sync on demand.

    The RMM and PSA connection pages have had a sync action for releases; the
    accounting page never did, so the only way to pull anything was a shell.
    """
    from django.core.management import call_command
    from io import StringIO

    item = get_object_or_404(AccountingConnection, pk=pk)
    if not (item.is_active and item.sync_enabled):
        messages.error(
            request,
            f'"{item.name}" is inactive or has sync disabled — enable it first.')
        return redirect('integrations:accounting_list')

    out, err = StringIO(), StringIO()
    try:
        call_command('accounting_sync', connection=item.pk,
                     stdout=out, stderr=err, verbosity=1)
    except Exception as exc:
        messages.error(request, f'Sync failed: {exc}')
        return redirect('integrations:accounting_list')

    item.refresh_from_db()
    if item.last_sync_status == 'ok':
        messages.success(request, f'Sync finished. {out.getvalue().strip()[:400]}')
    else:
        messages.warning(
            request,
            f'Sync finished with errors: {item.last_error[:400] or err.getvalue()[:400]}')
    return redirect('integrations:accounting_list')


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_customers(request, pk):
    """Phase 44.1 (v3.17.531): the customer mapping, now that it is queryable.

    Before this the organization -> provider-customer map was a dict inside the
    connection's encrypted credentials, so there was nothing to show. It is now
    a table, and an operator can see which clients are linked, which are not,
    and pull in customers that already exist provider-side.
    """
    from .models import AccountingCustomerLink
    from core.models import Organization

    item = get_object_or_404(AccountingConnection, pk=pk)
    links = AccountingCustomerLink.objects.filter(
        connection=item).select_related('client_org').order_by('display_name')
    linked_ids = set(links.values_list('client_org_id', flat=True))

    return render(request, 'integrations/accounting_customers.html', {
        'item': item,
        'links': links,
        # Clients with no mapping yet — the gap an operator actually wants to see.
        'unlinked': Organization.objects.filter(
            is_active=True).exclude(pk__in=linked_ids).order_by('name')[:200],
    })


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
@require_POST
def accounting_pull_customers(request, pk):
    """Import provider customers and link them to organizations by name."""
    from integrations.providers.accounting import get_accounting_provider

    item = get_object_or_404(AccountingConnection, pk=pk)
    provider = get_accounting_provider(item)
    if provider is None:
        messages.error(request, 'Provider class not registered.')
        return redirect('integrations:accounting_customers', pk=pk)

    try:
        result = provider.pull_customers()
    except Exception as exc:
        messages.error(request, f'Pull failed: {exc}')
        return redirect('integrations:accounting_customers', pk=pk)

    if not result.get('success'):
        messages.error(request, f"Pull failed: {result.get('error', 'unknown')}")
        return redirect('integrations:accounting_customers', pk=pk)

    unmatched = result.get('unmatched') or []
    messages.success(
        request,
        f"Linked {result.get('linked', 0)} customer(s); "
        f"{result.get('already_linked', 0)} already linked.")
    if unmatched:
        # Named rather than counted: the operator has to decide what each one is,
        # and a bare number gives them nothing to act on.
        shown = ', '.join(unmatched[:10])
        more = f' (+{len(unmatched) - 10} more)' if len(unmatched) > 10 else ''
        messages.warning(
            request,
            f'No matching client for: {shown}{more}. '
            f'Rename the client here to match, or ignore.')
    return redirect('integrations:accounting_customers', pk=pk)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
@require_POST
def accounting_push_customer(request, pk, org_pk):
    """Create or update one client in the accounting system."""
    from integrations.providers.accounting import get_accounting_provider
    from core.models import Organization

    item = get_object_or_404(AccountingConnection, pk=pk)
    client_org = get_object_or_404(Organization, pk=org_pk)
    provider = get_accounting_provider(item)
    if provider is None:
        messages.error(request, 'Provider class not registered.')
        return redirect('integrations:accounting_customers', pk=pk)

    try:
        result = provider.push_customer(client_org)
    except Exception as exc:
        messages.error(request, f'Push failed: {exc}')
        return redirect('integrations:accounting_customers', pk=pk)

    if result.get('success'):
        verb = 'Created' if result.get('created') else 'Updated'
        messages.success(request, f'{verb} {client_org.name} '
                                  f"(id {result.get('customer_id')}).")
    else:
        messages.error(request, f"Push failed: {result.get('error', 'unknown')}")
    return redirect('integrations:accounting_customers', pk=pk)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_audit_log(request, pk):
    """Phase 27 v2 (v3.17.260): show every recorded interaction with a
    given accounting connection. Supports a simple `?ok=fail|ok` filter
    plus pagination via Django Paginator (50/page)."""
    from .models import AccountingAuditLog
    from django.core.paginator import Paginator

    item = get_object_or_404(AccountingConnection, pk=pk)
    qs = AccountingAuditLog.objects.filter(connection=item).order_by('-created_at')
    ok_filter = request.GET.get('ok') or ''
    if ok_filter == 'ok':
        qs = qs.filter(success=True)
    elif ok_filter == 'fail':
        qs = qs.filter(success=False)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'integrations/accounting_audit_log.html', {
        'item': item,
        'page_obj': page_obj,
        'ok_filter': ok_filter,
        'total': qs.count(),
    })


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_test(request, pk):
    from .providers.accounting import get_accounting_provider
    item = get_object_or_404(AccountingConnection, pk=pk)
    provider = get_accounting_provider(item)
    if provider is None:
        return JsonResponse({'ok': False, 'error': 'No provider for this type'})
    try:
        ok = provider.test_connection()
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)[:300]})
    return JsonResponse({'ok': bool(ok)})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def accounting_connect(request, pk):
    """Initiate OAuth — redirect the user to the provider's authorize URL."""
    from .providers.accounting import get_accounting_provider
    item = get_object_or_404(AccountingConnection, pk=pk)
    provider = get_accounting_provider(item)
    if provider is None:
        messages.error(request, 'Unknown provider.')
        return redirect('integrations:accounting_list')

    # Generate + persist a CSRF state token.
    state = _secrets.token_urlsafe(32)
    request.session[f'oauth_state_{item.pk}'] = state
    redirect_uri = request.build_absolute_uri(
        '/integrations/accounting/oauth/callback/'
    )
    request.session['oauth_pending_pk'] = item.pk
    try:
        url = provider.build_authorize_url(state=state, redirect_uri=redirect_uri)
    except Exception as exc:
        messages.error(request, f'OAuth setup failed: {exc}')
        return redirect('integrations:accounting_edit', pk=item.pk)
    from django.shortcuts import redirect as _redirect
    return _redirect(url)


@login_required
def accounting_oauth_callback(request):
    """Receive the OAuth callback from QuickBooks Online / Xero / etc."""
    from .providers.accounting import get_accounting_provider
    if not (request.user.is_superuser or request.user.is_staff):
        raise PermissionDenied()
    pk = request.session.get('oauth_pending_pk')
    if not pk:
        messages.error(request, 'No pending OAuth flow.')
        return redirect('integrations:accounting_list')
    item = get_object_or_404(AccountingConnection, pk=pk)
    expected_state = request.session.get(f'oauth_state_{pk}', '')
    state = request.GET.get('state', '')
    if not expected_state or expected_state != state:
        messages.error(request, 'OAuth state mismatch — abort.')
        return redirect('integrations:accounting_list')

    code = request.GET.get('code') or ''
    realm_id = request.GET.get('realmId') or ''  # QBO-specific param
    if not code:
        messages.error(request, f'OAuth callback missing code: {request.GET.get("error", "")}')
        return redirect('integrations:accounting_edit', pk=item.pk)

    provider = get_accounting_provider(item)
    redirect_uri = request.build_absolute_uri('/integrations/accounting/oauth/callback/')
    try:
        provider.handle_callback(code=code, redirect_uri=redirect_uri, realm_id=realm_id or None)
    except Exception as exc:
        messages.error(request, f'OAuth completion failed: {exc}')
        return redirect('integrations:accounting_edit', pk=item.pk)

    # Clean up session keys
    for k in [f'oauth_state_{pk}', 'oauth_pending_pk']:
        request.session.pop(k, None)

    messages.success(request, f'Connected to {item.get_provider_type_display()}.')
    return redirect('integrations:accounting_list')
