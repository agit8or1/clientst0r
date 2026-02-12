"""
Views for webhook management.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.models import Webhook, WebhookDelivery
from core.webhook_forms import WebhookForm, WebhookTestForm
from core.webhook_sender import deliver_webhook
import json


@login_required
def webhook_list(request):
    """List all webhooks for the current organization."""
    webhooks = Webhook.objects.filter(organization=request.user.organization)

    context = {
        'webhooks': webhooks,
        'title': 'Webhooks'
    }
    return render(request, 'core/webhook_list.html', context)


@login_required
def webhook_create(request):
    """Create a new webhook."""
    if request.method == 'POST':
        form = WebhookForm(request.POST)
        if form.is_valid():
            webhook = form.save(commit=False)
            webhook.organization = request.user.organization
            webhook.created_by = request.user
            webhook.save()
            messages.success(request, f'Webhook "{webhook.name}" created successfully.')
            return redirect('webhook_list')
    else:
        form = WebhookForm()

    context = {
        'form': form,
        'title': 'Create Webhook',
        'submit_text': 'Create Webhook'
    }
    return render(request, 'core/webhook_form.html', context)


@login_required
def webhook_edit(request, webhook_id):
    """Edit an existing webhook."""
    webhook = get_object_or_404(
        Webhook,
        id=webhook_id,
        organization=request.user.organization
    )

    if request.method == 'POST':
        form = WebhookForm(request.POST, instance=webhook)
        if form.is_valid():
            form.save()
            messages.success(request, f'Webhook "{webhook.name}" updated successfully.')
            return redirect('webhook_list')
    else:
        form = WebhookForm(instance=webhook)

    context = {
        'form': form,
        'webhook': webhook,
        'title': f'Edit Webhook: {webhook.name}',
        'submit_text': 'Update Webhook'
    }
    return render(request, 'core/webhook_form.html', context)


@login_required
def webhook_delete(request, webhook_id):
    """Delete a webhook."""
    webhook = get_object_or_404(
        Webhook,
        id=webhook_id,
        organization=request.user.organization
    )

    if request.method == 'POST':
        webhook_name = webhook.name
        webhook.delete()
        messages.success(request, f'Webhook "{webhook_name}" deleted successfully.')
        return redirect('webhook_list')

    context = {
        'webhook': webhook,
        'title': f'Delete Webhook: {webhook.name}'
    }
    return render(request, 'core/webhook_delete.html', context)


@login_required
def webhook_test(request, webhook_id):
    """Test webhook delivery."""
    webhook = get_object_or_404(
        Webhook,
        id=webhook_id,
        organization=request.user.organization
    )

    if request.method == 'POST':
        form = WebhookTestForm(request.POST)
        if form.is_valid():
            event_type = form.cleaned_data['test_event']
            test_payload = form.cleaned_data['test_payload']

            # Deliver test webhook
            success = deliver_webhook(webhook, event_type, test_payload)

            if success:
                messages.success(request, 'Test webhook delivered successfully!')
            else:
                messages.error(request, 'Test webhook delivery failed. Check the delivery log for details.')

            return redirect('webhook_deliveries', webhook_id=webhook.id)
    else:
        form = WebhookTestForm()

    context = {
        'form': form,
        'webhook': webhook,
        'title': f'Test Webhook: {webhook.name}'
    }
    return render(request, 'core/webhook_test.html', context)


@login_required
def webhook_deliveries(request, webhook_id):
    """View delivery logs for a webhook."""
    webhook = get_object_or_404(
        Webhook,
        id=webhook_id,
        organization=request.user.organization
    )

    deliveries = WebhookDelivery.objects.filter(webhook=webhook)[:100]  # Last 100 deliveries

    # Calculate stats
    total_deliveries = deliveries.count()
    success_count = deliveries.filter(status=WebhookDelivery.STATUS_SUCCESS).count()
    failed_count = deliveries.filter(status=WebhookDelivery.STATUS_FAILED).count()

    success_rate = (success_count / total_deliveries * 100) if total_deliveries > 0 else 0

    context = {
        'webhook': webhook,
        'deliveries': deliveries,
        'total_deliveries': total_deliveries,
        'success_count': success_count,
        'failed_count': failed_count,
        'success_rate': success_rate,
        'title': f'Webhook Deliveries: {webhook.name}'
    }
    return render(request, 'core/webhook_deliveries.html', context)


@login_required
def webhook_delivery_detail(request, delivery_id):
    """View details of a specific delivery."""
    delivery = get_object_or_404(WebhookDelivery, id=delivery_id)

    # Ensure user has access to this delivery's webhook
    if delivery.webhook.organization != request.user.organization:
        messages.error(request, 'Access denied.')
        return redirect('webhook_list')

    # Format payload as pretty JSON
    payload_formatted = json.dumps(delivery.payload, indent=2)

    context = {
        'delivery': delivery,
        'payload_formatted': payload_formatted,
        'title': f'Delivery Details: {delivery.event_type}'
    }
    return render(request, 'core/webhook_delivery_detail.html', context)


@login_required
def webhook_toggle(request, webhook_id):
    """Toggle webhook active status via AJAX."""
    if request.method == 'POST':
        webhook = get_object_or_404(
            Webhook,
            id=webhook_id,
            organization=request.user.organization
        )

        webhook.is_active = not webhook.is_active
        webhook.save()

        return JsonResponse({
            'success': True,
            'is_active': webhook.is_active,
            'message': f'Webhook {"enabled" if webhook.is_active else "disabled"}'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request method'})
