"""
Integrations views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import JsonResponse
from core.middleware import get_request_organization
from core.decorators import require_admin
from .models import PSAConnection, PSACompany, PSAContact, PSATicket, RMMConnection, RMMDevice, RMMAlert, RMMSoftware
from .forms import PSAConnectionForm, RMMConnectionForm
from .sync import PSASync
from .providers import get_provider
from vault.encryption import EncryptionError
import logging

logger = logging.getLogger('integrations')


@login_required
def integration_list(request):
    """List PSA and RMM connections."""
    org = get_request_organization(request)
    psa_connections = PSAConnection.objects.for_organization(org)
    rmm_connections = RMMConnection.objects.for_organization(org)

    return render(request, 'integrations/integration_list.html', {
        'psa_connections': psa_connections,
        'rmm_connections': rmm_connections,
    })


@login_required
@require_admin
def integration_create(request):
    """Create new PSA connection."""
    org = get_request_organization(request)

    # Require organization to be selected
    if not org:
        messages.error(request, "Please select an organization first.")
        return redirect('accounts:access_management')

    if request.method == 'POST':
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
                        "<code>cd /home/administrator<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/huduglue/issues/4' target='_blank'>Issue #4</a> for details.",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Encryption error: {error_msg}")
    else:
        form = PSAConnectionForm(organization=org)

    return render(request, 'integrations/integration_form.html', {
        'form': form,
        'action': 'Create',
    })


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
                        "<code>cd /home/administrator<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/huduglue/issues/4' target='_blank'>Issue #4</a> for details.",
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
                connection.organization = org
                connection.save()
                messages.success(request, f"RMM connection '{connection.name}' created successfully.")
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
                        "<code>cd /home/administrator<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/huduglue/issues/4' target='_blank'>Issue #4</a> for details.",
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
                        "<code>cd /home/administrator<br>"
                        "./scripts/fix_gunicorn_env.sh</code><br><br>"
                        "<strong>Or run diagnostic to see what's wrong:</strong><br>"
                        "<code>./diagnose_gunicorn_fix.sh</code><br><br>"
                        "This will configure Gunicorn to load environment variables from your .env file. "
                        "See <a href='https://github.com/agit8or1/huduglue/issues/4' target='_blank'>Issue #4</a> for details.",
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
        connection.delete()
        messages.success(request, f"RMM connection '{name}' deleted successfully.")
        return redirect('integrations:integration_list')

    return render(request, 'integrations/rmm_confirm_delete.html', {
        'connection': connection,
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
        device_id=device.external_id
    ).order_by('-triggered_at')[:10]
    
    return render(request, 'integrations/rmm_device_detail.html', {
        'device': device,
        'software': software,
        'alerts': alerts,
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
def psa_organization_mapping(request, pk):
    """
    Map PSA companies to existing HuduGlue organizations.
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
    Map RMM sites to existing HuduGlue organizations.
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
    # Get unique site names from RMM devices
    from django.db.models import Count
    site_data = RMMDevice.objects.filter(
        connection=connection
    ).exclude(
        Q(site_name='') | Q(site_name__isnull=True)
    ).values('site_name', 'site_id').annotate(
        device_count=Count('id')
    ).order_by('site_name')

    # Get all organizations
    all_organizations = Organization.objects.all().order_by('name')

    # Build site list with potential matches
    site_mapping_data = []
    for site in site_data:
        site_name = site['site_name']

        # Apply prefix if configured
        if connection.org_name_prefix:
            org_name = f"{connection.org_name_prefix}{site_name}"
        else:
            org_name = site_name

        # Check if organization exists with this name
        existing_org = Organization.objects.filter(name=org_name).first()

        # Try exact match without prefix
        suggested_org = Organization.objects.filter(name__iexact=site_name).first()

        site_mapping_data.append({
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
