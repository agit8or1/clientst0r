"""
Integrations views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.middleware import get_request_organization
from core.decorators import require_admin
from .models import PSAConnection, PSACompany, PSAContact, PSATicket
from .forms import PSAConnectionForm
from .sync import PSASync
from .providers import get_provider


@login_required
def integration_list(request):
    """List PSA connections."""
    org = get_request_organization(request)
    connections = PSAConnection.objects.for_organization(org)

    return render(request, 'integrations/integration_list.html', {
        'connections': connections,
    })


@login_required
@require_admin
def integration_create(request):
    """Create new PSA connection."""
    org = get_request_organization(request)

    if request.method == 'POST':
        form = PSAConnectionForm(request.POST, organization=org)
        if form.is_valid():
            connection = form.save(commit=False)
            connection.organization = org
            connection.save()
            messages.success(request, f"Connection '{connection.name}' created successfully.")
            return redirect('integrations:integration_detail', pk=connection.pk)
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
            connection = form.save()
            messages.success(request, f"Connection '{connection.name}' updated successfully.")
            return redirect('integrations:integration_detail', pk=connection.pk)
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
