"""
Webhook delivery system for sending HTTP notifications on events.
"""
import requests
import json
import hmac
import hashlib
import time
import logging
from django.conf import settings
from core.models import Webhook, WebhookDelivery, SystemSetting

logger = logging.getLogger('core')


def send_webhook(event_type, payload_data, organization=None):
    """
    Send webhook notifications for a specific event.

    Args:
        event_type: Event type constant (e.g., Webhook.EVENT_ASSET_CREATED)
        payload_data: Dictionary of data to send in webhook payload
        organization: Organization instance (optional, for org-specific webhooks)

    Returns:
        int: Number of webhooks successfully delivered
    """
    # Check if webhooks are enabled globally
    try:
        settings_obj = SystemSetting.objects.first()
        if not settings_obj or not settings_obj.webhooks_enabled:
            logger.debug(f"Webhooks disabled globally, skipping {event_type}")
            return 0
    except Exception as e:
        logger.error(f"Error checking webhook settings: {e}")
        return 0

    # Find active webhooks for this event
    webhooks = Webhook.objects.filter(is_active=True)

    # Filter by organization if provided
    if organization:
        webhooks = webhooks.filter(organization=organization)

    # Filter by event type
    webhooks = [w for w in webhooks if event_type in w.events]

    if not webhooks:
        logger.debug(f"No active webhooks found for event {event_type}")
        return 0

    success_count = 0

    for webhook in webhooks:
        try:
            success = deliver_webhook(webhook, event_type, payload_data)
            if success:
                success_count += 1
        except Exception as e:
            logger.error(f"Error delivering webhook {webhook.id}: {e}")

    return success_count


def deliver_webhook(webhook, event_type, payload_data):
    """
    Deliver a single webhook notification.

    Args:
        webhook: Webhook instance
        event_type: Event type string
        payload_data: Dictionary of payload data

    Returns:
        bool: True if delivery was successful
    """
    # Build payload
    payload = {
        'event': event_type,
        'timestamp': int(time.time()),
        'data': payload_data,
        'webhook_id': webhook.id,
        'organization': webhook.organization.slug if webhook.organization else None,
    }

    # Convert to JSON
    payload_json = json.dumps(payload)

    # Prepare headers
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'HuduGlue-Webhooks/1.0',
    }

    # Add signature if secret is configured
    if webhook.secret:
        signature = generate_signature(payload_json, webhook.secret)
        headers['X-Webhook-Signature'] = signature

    # Add custom headers
    if webhook.custom_headers:
        headers.update(webhook.custom_headers)

    # Create delivery log
    delivery = WebhookDelivery.objects.create(
        webhook=webhook,
        event_type=event_type,
        payload=payload,
        status=WebhookDelivery.STATUS_PENDING
    )

    try:
        # Send request
        start_time = time.time()
        response = requests.post(
            webhook.url,
            data=payload_json,
            headers=headers,
            timeout=30
        )
        duration_ms = int((time.time() - start_time) * 1000)

        # Update delivery log
        delivery.response_code = response.status_code
        delivery.response_body = response.text[:1000]  # Truncate to 1000 chars
        delivery.duration_ms = duration_ms

        if 200 <= response.status_code < 300:
            delivery.status = WebhookDelivery.STATUS_SUCCESS
            delivery.save()
            logger.info(f"Webhook {webhook.id} delivered successfully: {event_type}")
            return True
        else:
            delivery.status = WebhookDelivery.STATUS_FAILED
            delivery.error_message = f"HTTP {response.status_code}: {response.text[:200]}"
            delivery.save()
            logger.warning(f"Webhook {webhook.id} failed with status {response.status_code}")
            return False

    except requests.Timeout:
        delivery.status = WebhookDelivery.STATUS_FAILED
        delivery.error_message = "Request timeout after 30 seconds"
        delivery.save()
        logger.error(f"Webhook {webhook.id} timed out")
        return False

    except requests.RequestException as e:
        delivery.status = WebhookDelivery.STATUS_FAILED
        delivery.error_message = str(e)[:500]
        delivery.save()
        logger.error(f"Webhook {webhook.id} request failed: {e}")
        return False

    except Exception as e:
        delivery.status = WebhookDelivery.STATUS_FAILED
        delivery.error_message = f"Unexpected error: {str(e)[:500]}"
        delivery.save()
        logger.error(f"Webhook {webhook.id} unexpected error: {e}")
        return False


def generate_signature(payload, secret):
    """
    Generate HMAC-SHA256 signature for webhook payload.

    Args:
        payload: JSON string payload
        secret: Secret key for signing

    Returns:
        str: Hex-encoded signature with sha256= prefix
    """
    signature = hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"


def verify_signature(payload, signature, secret):
    """
    Verify webhook signature (useful for receiving webhooks).

    Args:
        payload: JSON string payload
        signature: Signature from X-Webhook-Signature header
        secret: Secret key

    Returns:
        bool: True if signature is valid
    """
    expected_signature = generate_signature(payload, secret)
    return hmac.compare_digest(expected_signature, signature)
