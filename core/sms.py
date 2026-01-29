"""
SMS Helper Module - Send SMS messages via various providers
"""
import logging
from django.conf import settings

logger = logging.getLogger('core')


class SMSProvider:
    """Base SMS provider class."""

    def __init__(self, account_sid, auth_token, from_number):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

    def send_sms(self, to_number, message):
        """Send SMS message. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement send_sms()")


class TwilioProvider(SMSProvider):
    """Twilio SMS provider."""

    def send_sms(self, to_number, message):
        """Send SMS via Twilio."""
        try:
            from twilio.rest import Client

            client = Client(self.account_sid, self.auth_token)

            message_result = client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number
            )

            logger.info(f"SMS sent via Twilio to {to_number}: {message_result.sid}")
            return {
                'success': True,
                'message_sid': message_result.sid,
                'status': message_result.status
            }
        except Exception as e:
            logger.error(f"Failed to send SMS via Twilio: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }


class PlivoProvider(SMSProvider):
    """Plivo SMS provider."""

    def send_sms(self, to_number, message):
        """Send SMS via Plivo."""
        try:
            import plivo

            client = plivo.RestClient(auth_id=self.account_sid, auth_token=self.auth_token)

            response = client.messages.create(
                src=self.from_number,
                dst=to_number,
                text=message
            )

            logger.info(f"SMS sent via Plivo to {to_number}: {response['message_uuid'][0]}")
            return {
                'success': True,
                'message_uuid': response['message_uuid'][0],
                'status': 'queued'
            }
        except Exception as e:
            logger.error(f"Failed to send SMS via Plivo: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }


class VonageProvider(SMSProvider):
    """Vonage (Nexmo) SMS provider."""

    def send_sms(self, to_number, message):
        """Send SMS via Vonage."""
        try:
            import vonage

            client = vonage.Client(key=self.account_sid, secret=self.auth_token)
            sms = vonage.Sms(client)

            response = sms.send_message({
                "from": self.from_number,
                "to": to_number,
                "text": message
            })

            if response["messages"][0]["status"] == "0":
                logger.info(f"SMS sent via Vonage to {to_number}: {response['messages'][0]['message-id']}")
                return {
                    'success': True,
                    'message_id': response['messages'][0]['message-id'],
                    'status': 'delivered'
                }
            else:
                error_text = response["messages"][0]["error-text"]
                logger.error(f"Failed to send SMS via Vonage: {error_text}")
                return {
                    'success': False,
                    'error': error_text
                }
        except Exception as e:
            logger.error(f"Failed to send SMS via Vonage: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }


class TelnyxProvider(SMSProvider):
    """Telnyx SMS provider."""

    def send_sms(self, to_number, message):
        """Send SMS via Telnyx."""
        try:
            import telnyx

            telnyx.api_key = self.auth_token

            response = telnyx.Message.create(
                from_=self.from_number,
                to=to_number,
                text=message
            )

            logger.info(f"SMS sent via Telnyx to {to_number}: {response.id}")
            return {
                'success': True,
                'message_id': response.id,
                'status': 'queued'
            }
        except Exception as e:
            logger.error(f"Failed to send SMS via Telnyx: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }


def get_sms_client():
    """Get configured SMS client based on system settings."""
    from core.models import SystemSetting

    settings = SystemSetting.get_settings()

    if not settings.sms_enabled:
        return None

    # Decrypt auth token
    try:
        from vault.encryption import decrypt
        auth_token = decrypt(settings.sms_auth_token) if settings.sms_auth_token else ''
    except Exception:
        auth_token = settings.sms_auth_token

    provider_map = {
        'twilio': TwilioProvider,
        'plivo': PlivoProvider,
        'vonage': VonageProvider,
        'telnyx': TelnyxProvider,
    }

    provider_class = provider_map.get(settings.sms_provider)

    if not provider_class:
        logger.error(f"Unknown SMS provider: {settings.sms_provider}")
        return None

    return provider_class(
        account_sid=settings.sms_account_sid,
        auth_token=auth_token,
        from_number=settings.sms_from_number
    )


def send_sms(to_number, message):
    """
    Send SMS message using configured provider.

    Args:
        to_number (str): Recipient phone number in E.164 format
        message (str): SMS message body

    Returns:
        dict: Result with success status and details
    """
    client = get_sms_client()

    if not client:
        return {
            'success': False,
            'error': 'SMS is not configured or enabled'
        }

    # Validate phone number format (basic check for E.164)
    if not to_number.startswith('+'):
        return {
            'success': False,
            'error': 'Phone number must be in E.164 format (e.g., +15551234567)'
        }

    return client.send_sms(to_number, message)
