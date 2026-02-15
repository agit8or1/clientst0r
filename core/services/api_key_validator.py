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

        try:
            client = anthropic.Anthropic(api_key=api_key.strip())

            # Try a minimal API call to test the key
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",  # Use cheapest model for testing
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Hello"}
                ]
            )

            return True, "API key is valid", {
                "model_tested": "claude-3-5-haiku-20241022",
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

    @staticmethod
    def validate_connectwise_psa(base_url: str, company_id: str, public_key: str, private_key: str) -> Tuple[bool, str, Dict]:
        """
        Validate ConnectWise PSA credentials.

        Args:
            base_url: ConnectWise API base URL
            company_id: Company ID
            public_key: Public API key
            private_key: Private API key

        Returns:
            Tuple of (success: bool, message: str, details: dict)
        """
        if not all([base_url, company_id, public_key, private_key]):
            return False, "All credentials are required", {}

        try:
            # Clean up base URL
            base_url = base_url.strip().rstrip('/')

            # Test by fetching company info
            url = f"{base_url}/v4_6_release/apis/3.0/company/info"

            auth_string = f"{company_id}+{public_key}:{private_key}"
            import base64
            auth_header = base64.b64encode(auth_string.encode()).decode()

            headers = {
                "Authorization": f"Basic {auth_header}",
                "clientId": "clientst0r",
                "Content-Type": "application/json"
            }

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return True, "Credentials are valid", {
                    "company_name": data.get("identifier")
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
    def validate_syncro_rmm(base_url: str, api_key: str) -> Tuple[bool, str, Dict]:
        """
        Validate SyncroMSP RMM credentials.

        Args:
            base_url: Syncro API base URL
            api_key: API key

        Returns:
            Tuple of (success: bool, message: str, details: dict)
        """
        if not base_url or not api_key:
            return False, "Base URL and API key are required", {}

        try:
            # Clean up base URL
            base_url = base_url.strip().rstrip('/')

            # Test by fetching customers (limit to 1)
            url = f"{base_url}/api/v1/customers"
            params = {"page": 1, "per_page": 1}
            headers = {
                "Authorization": api_key.strip(),
                "Accept": "application/json"
            }

            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                return True, "API key is valid", {}
            elif response.status_code == 401:
                return False, "Invalid API key - authentication failed", {}
            else:
                return False, f"API returned status {response.status_code}", {}

        except requests.exceptions.Timeout:
            return False, "Request timed out", {}
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Validation error: {str(e)}", {}

    @staticmethod
    def validate_generic_api_key(url: str, api_key: str, header_name: str = "Authorization") -> Tuple[bool, str, Dict]:
        """
        Generic API key validator for simple bearer token APIs.

        Args:
            url: Test endpoint URL
            api_key: API key or token
            header_name: Header name for the key (default: "Authorization")

        Returns:
            Tuple of (success: bool, message: str, details: dict)
        """
        if not url or not api_key:
            return False, "URL and API key are required", {}

        try:
            headers = {header_name: api_key.strip()}

            response = requests.get(url.strip(), headers=headers, timeout=10)

            if response.status_code in [200, 201]:
                return True, "API key is valid", {"status_code": response.status_code}
            elif response.status_code in [401, 403]:
                return False, "Invalid API key - authentication failed", {}
            else:
                return False, f"API returned status {response.status_code}", {}

        except requests.exceptions.Timeout:
            return False, "Request timed out", {}
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Validation error: {str(e)}", {}
