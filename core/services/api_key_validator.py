"""
API Key validation service for various integrations.
Tests API keys to ensure they work before saving in settings.
"""

import requests
import anthropic
from typing import Dict, Tuple


class APIKeyValidator:
    """Validate API keys for various services."""

    @staticmethod
    def validate_anthropic(api_key: str) -> Tuple[bool, str, Dict]:
        """
        Validate Anthropic (Claude) API key.

        Args:
            api_key: Anthropic API key

        Returns:
            Tuple of (success: bool, message: str, details: dict)
        """
        if not api_key or not api_key.strip():
            return False, "API key is required", {}

        # v3.17.468 (issue #130) — `claude-3-5-haiku-20241022` was
        # retired by Anthropic and now returns 404. Test with the
        # current Haiku model. If even that's been retired by the time
        # someone hits this, fall through to a generic "model not
        # found" message rather than crashing.
        test_model = "claude-haiku-4-5-20251001"

        try:
            client = anthropic.Anthropic(api_key=api_key.strip())

            # Try a minimal API call to test the key
            response = client.messages.create(
                model=test_model,  # Cheapest current model for validation
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Hello"}
                ]
            )

            return True, "API key is valid", {
                "model_tested": test_model,
                "response_id": response.id
            }

        except anthropic.AuthenticationError:
            return False, "Invalid API key - authentication failed", {}
        except anthropic.PermissionDeniedError:
            return False, "API key lacks required permissions", {}
        except anthropic.RateLimitError:
            # Rate limit means the key is valid but quota exceeded
            return True, "API key is valid (rate limit reached, but key works)", {}
        except anthropic.APIError as e:
            return False, f"Anthropic API error: {str(e)}", {}
        except Exception as e:
            return False, f"Validation error: {str(e)}", {}

    @staticmethod
    def validate_google_maps(api_key: str) -> Tuple[bool, str, Dict]:
        """
        Validate Google Maps API key.

        Args:
            api_key: Google Maps API key

        Returns:
            Tuple of (success: bool, message: str, details: dict)
        """
        if not api_key or not api_key.strip():
            return False, "API key is required", {}

        try:
            # Test with Geocoding API (simple test)
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "address": "1600 Amphitheatre Parkway, Mountain View, CA",
                "key": api_key.strip()
            }

            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get("status") == "OK":
                return True, "API key is valid and has Geocoding API access", {
                    "apis_tested": ["Geocoding API"]
                }
            elif data.get("status") == "REQUEST_DENIED":
                error_message = data.get("error_message", "Request denied")
                if "API key not valid" in error_message or "API key is invalid" in error_message:
                    return False, "Invalid API key", {}
                else:
                    return False, f"API key denied: {error_message}", {}
            elif data.get("status") == "OVER_QUERY_LIMIT":
                # Quota exceeded means the key is valid
                return True, "API key is valid (quota exceeded, but key works)", {}
            else:
                return False, f"Unexpected status: {data.get('status')}", {}

        except requests.exceptions.Timeout:
            return False, "Request timed out", {}
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Validation error: {str(e)}", {}

    @staticmethod
    def validate_twilio(account_sid: str, auth_token: str) -> Tuple[bool, str, Dict]:
        """
        Validate Twilio credentials.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token

        Returns:
            Tuple of (success: bool, message: str, details: dict)
        """
        if not account_sid or not auth_token:
            return False, "Account SID and Auth Token are required", {}

        try:
            # Test by fetching account info
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid.strip()}.json"

            response = requests.get(
                url,
                auth=(account_sid.strip(), auth_token.strip()),
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return True, "Credentials are valid", {
                    "account_status": data.get("status"),
                    "friendly_name": data.get("friendly_name")
                }
            elif response.status_code == 401:
                return False, "Invalid credentials - authentication failed", {}
            else:
                return False, f"API returned status {response.status_code}", {}

        except requests.exceptions.Timeout:
            return False, "Request timed out", {}
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Validation error: {str(e)}", {}

    @staticmethod
    def validate_vonage(api_key: str, api_secret: str) -> Tuple[bool, str, Dict]:
        """
        Validate Vonage (Nexmo) credentials.

        Args:
            api_key: Vonage API key
            api_secret: Vonage API secret

        Returns:
            Tuple of (success: bool, message: str, details: dict)
        """
        if not api_key or not api_secret:
            return False, "API key and secret are required", {}

        try:
            # Test by fetching account balance
            url = "https://rest.nexmo.com/account/get-balance"
            params = {
                "api_key": api_key.strip(),
                "api_secret": api_secret.strip()
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if "value" in data:
                    return True, "Credentials are valid", {
                        "balance": f"{data.get('value')} {data.get('currency', 'EUR')}"
                    }
                else:
                    return False, "Unexpected response format", {}
            elif response.status_code == 401 or response.status_code == 403:
                return False, "Invalid credentials - authentication failed", {}
            else:
                return False, f"API returned status {response.status_code}", {}

        except requests.exceptions.Timeout:
            return False, "Request timed out", {}
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Validation error: {str(e)}", {}
