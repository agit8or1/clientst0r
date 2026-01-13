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
from .models import PSAConnection, PSACompany, PSAContact, PSATicket, RMMConnection, RMMDevice
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
                # Handle malformed APP_MASTER_KEY error
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed. "
                        "Please regenerate it using the following commands:<br><br>"
                        "<code>cd ~/huduglue<br>"
                        "source venv/bin/activate<br>"
                        "NEW_KEY=$(python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")<br>"
                        "sed -i \"s|^APP_MASTER_KEY=.*|APP_MASTER_KEY=${NEW_KEY}|\" .env<br>"
                        "sudo systemctl restart huduglue-gunicorn.service</code><br><br>"
                        "The key must be exactly 44 characters (base64-encoded 32 bytes).",
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
                # Handle malformed APP_MASTER_KEY error
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed. "
                        "Please regenerate it using the following commands:<br><br>"
                        "<code>cd ~/huduglue<br>"
                        "source venv/bin/activate<br>"
                        "NEW_KEY=$(python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")<br>"
                        "sed -i \"s|^APP_MASTER_KEY=.*|APP_MASTER_KEY=${NEW_KEY}|\" .env<br>"
                        "sudo systemctl restart huduglue-gunicorn.service</code><br><br>"
                        "The key must be exactly 44 characters (base64-encoded 32 bytes).",
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
    """Test PSA connection (AJAX)."""
    org = get_request_organization(request)
    connection = get_object_or_404(PSAConnection, pk=pk, organization=org)

    if request.method == 'POST':
        try:
            provider = get_provider(connection)
            success = provider.test_connection()

            if success:
                return JsonResponse({'success': True, 'message': 'Connection successful'})
            else:
                return JsonResponse({'success': False, 'message': 'Connection failed'}, status=400)

        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)

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

            return JsonResponse({
                'success': True,
                'message': 'Sync completed',
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
        return redirect('accounts:access_management')

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
                # Handle malformed APP_MASTER_KEY error
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed. "
                        "Please regenerate it using the following commands:<br><br>"
                        "<code>cd ~/huduglue<br>"
                        "source venv/bin/activate<br>"
                        "NEW_KEY=$(python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")<br>"
                        "sed -i \"s|^APP_MASTER_KEY=.*|APP_MASTER_KEY=${NEW_KEY}|\" .env<br>"
                        "sudo systemctl restart huduglue-gunicorn.service</code><br><br>"
                        "The key must be exactly 44 characters (base64-encoded 32 bytes).",
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
                # Handle malformed APP_MASTER_KEY error
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed. "
                        "Please regenerate it using the following commands:<br><br>"
                        "<code>cd ~/huduglue<br>"
                        "source venv/bin/activate<br>"
                        "NEW_KEY=$(python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")<br>"
                        "sed -i \"s|^APP_MASTER_KEY=.*|APP_MASTER_KEY=${NEW_KEY}|\" .env<br>"
                        "sudo systemctl restart huduglue-gunicorn.service</code><br><br>"
                        "The key must be exactly 44 characters (base64-encoded 32 bytes).",
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
