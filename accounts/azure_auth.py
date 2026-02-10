"""
Azure AD / Microsoft Entra ID OAuth authentication backend
"""
import msal
import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from core.models import SystemSetting
from accounts.models import UserProfile, Membership
from audit.models import AuditLog
import logging

logger = logging.getLogger('accounts')
User = get_user_model()


class AzureADBackend(ModelBackend):
    """
    Azure AD OAuth authentication backend.
    Authenticates users via Microsoft Entra ID (formerly Azure AD).
    """

    def authenticate(self, request, azure_token=None, **kwargs):
        """
        Authenticate user with Azure AD token.

        Args:
            azure_token: dict with 'access_token' and optional user info
        """
        if azure_token is None:
            return None

        try:
            # Get Azure configuration
            config = self.get_azure_config()
            if not config or not config.get('enabled'):
                logger.error("Azure AD is not enabled or not configured")
                return None

            # Get user info from Microsoft Graph API
            user_info = self.get_user_info(azure_token['access_token'])
            if not user_info:
                logger.error("Failed to get user info from Microsoft Graph")
                return None

            email = user_info.get('mail') or user_info.get('userPrincipalName')
            if not email:
                logger.error("No email found in Azure AD user info")
                return None

            # Find or create user
            user = self.get_or_create_user(email, user_info, config)

            if user:
                # Log successful Azure AD login
                AuditLog.objects.create(
                    action='login',
                    user=user,
                    username=user.username,
                    description=f'User {email} logged in via Azure AD',
                    extra_data={'email': email, 'upn': user_info.get('userPrincipalName'), 'auth_source': 'azure_ad'}
                )

            return user

        except Exception as e:
            logger.exception(f"Azure AD authentication error: {e}")
            return None

    def get_azure_config(self):
        """Get Azure AD configuration from SystemSetting."""
        try:
            settings = SystemSetting.get_settings()
            enabled = getattr(settings, 'azure_ad_enabled', False)
            if not enabled:
                return None

            config = {
                'enabled': enabled,
                'tenant_id': getattr(settings, 'azure_ad_tenant_id', ''),
                'client_id': getattr(settings, 'azure_ad_client_id', ''),
                'client_secret': settings.get_azure_ad_client_secret_decrypted(),
                'redirect_uri': getattr(settings, 'azure_ad_redirect_uri', ''),
                'auto_create': getattr(settings, 'azure_ad_auto_create_users', True),
                'sync_groups': getattr(settings, 'azure_ad_sync_groups', False),
            }

            # FIX: Validate all required fields are present
            required_fields = ['tenant_id', 'client_id', 'client_secret', 'redirect_uri']
            missing_fields = [field for field in required_fields if not config.get(field)]
            if missing_fields:
                logger.error(f"Incomplete Azure AD configuration. Missing fields: {', '.join(missing_fields)}")
                return None

            return config
        except Exception as e:
            logger.error(f"Error getting Azure config: {e}")
            return None

    def get_user_info(self, access_token):
        """
        Get user information from Microsoft Graph API.

        Args:
            access_token: OAuth access token

        Returns:
            dict: User information from Graph API
        """
        try:
            headers = {'Authorization': f'Bearer {access_token}'}
            response = requests.get(
                'https://graph.microsoft.com/v1.0/me',
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching user info from Graph API: {e}")
            return None

    def get_or_create_user(self, email, user_info, config):
        """
        Get existing user or create new one.

        Args:
            email: User email address
            user_info: User info from Graph API
            config: Azure configuration

        Returns:
            User object or None
        """
        # Try to find existing user
        try:
            user = User.objects.get(email__iexact=email)

            # Update user info from Azure
            self.update_user_from_azure(user, user_info)

            return user

        except User.DoesNotExist:
            # Create new user if auto-create is enabled
            if not config.get('auto_create', True):
                logger.warning(f"Azure AD user {email} not found and auto-create is disabled")
                return None

            # Create new user
            given_name = user_info.get('givenName', '')
            surname = user_info.get('surname', '')
            username = email.split('@')[0]  # Use email prefix as username

            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=given_name,
                last_name=surname,
            )

            # Create profile
            UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'auth_source': 'azure_ad',
                    'azure_ad_oid': user_info.get('id', ''),
                }
            )

            logger.info(f"Created new user from Azure AD: {email}")

            # FIX: Auto-assign user to default organization
            from core.models import Organization, Membership
            try:
                # Get first active organization as default
                default_org = Organization.objects.filter(is_active=True).first()
                if default_org:
                    Membership.objects.create(
                        user=user,
                        organization=default_org,
                        role='viewer',  # Default to read-only access
                        is_active=True
                    )
                    logger.info(f"Auto-assigned user {email} to organization {default_org.name} as viewer")
            except Exception as e:
                logger.warning(f"Failed to auto-assign user {email} to organization: {e}")

            # Log user creation
            AuditLog.objects.create(
                action='create',
                user=user,
                username=user.username,
                object_type='User',
                object_id=user.id,
                object_repr=str(user),
                description=f'New user created from Azure AD: {email}',
                extra_data={'email': email, 'source': 'azure_ad'}
            )

            return user

    def update_user_from_azure(self, user, user_info):
        """Update user information from Azure AD."""
        try:
            # Update basic info
            user.first_name = user_info.get('givenName', user.first_name)
            user.last_name = user_info.get('surname', user.last_name)
            user.save()

            # Update profile
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.auth_source = 'azure_ad'
            profile.azure_ad_oid = user_info.get('id', '')
            profile.save()

        except Exception as e:
            logger.error(f"Error updating user from Azure: {e}")


class AzureOAuthClient:
    """Helper class for Azure AD OAuth flow."""

    def __init__(self):
        """Initialize Azure OAuth client with settings from database."""
        self.config = self.load_config()

    def load_config(self):
        """Load Azure configuration from SystemSetting."""
        settings = SystemSetting.get_settings()

        return {
            'enabled': getattr(settings, 'azure_ad_enabled', False),
            'tenant_id': getattr(settings, 'azure_ad_tenant_id', ''),
            'client_id': getattr(settings, 'azure_ad_client_id', ''),
            'client_secret': settings.get_azure_ad_client_secret_decrypted(),
            'redirect_uri': getattr(settings, 'azure_ad_redirect_uri', ''),
        }

    def is_enabled(self):
        """Check if Azure AD is enabled and configured."""
        return (
            self.config.get('enabled', False) and
            self.config.get('tenant_id') and
            self.config.get('client_id') and
            self.config.get('client_secret') and
            self.config.get('redirect_uri')
        )

    def get_authorization_url(self, state=None):
        """
        Get the authorization URL to redirect user to Azure login.

        Args:
            state: Optional CSRF state token (generated by caller)

        Returns:
            str: Authorization URL with state parameter
        """
        if not self.is_enabled():
            return None

        try:
            # Create MSAL confidential client
            authority = f"https://login.microsoftonline.com/{self.config['tenant_id']}"
            app = msal.ConfidentialClientApplication(
                self.config['client_id'],
                authority=authority,
                client_credential=self.config['client_secret']
            )

            # Generate authorization URL with state parameter for CSRF protection
            scopes = ['User.Read']  # Basic profile read permission
            auth_url = app.get_authorization_request_url(
                scopes,
                redirect_uri=self.config['redirect_uri'],
                state=state  # FIX: Include state parameter for CSRF protection
            )

            return auth_url

        except Exception as e:
            logger.error(f"Error generating Azure authorization URL: {e}")
            return None

    def get_token_from_code(self, code):
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from Azure callback

        Returns:
            dict: Token response with access_token
        """
        if not self.is_enabled():
            logger.error("Azure AD is not enabled or not fully configured")
            return None

        try:
            # Create MSAL confidential client
            authority = f"https://login.microsoftonline.com/{self.config['tenant_id']}"
            app = msal.ConfidentialClientApplication(
                self.config['client_id'],
                authority=authority,
                client_credential=self.config['client_secret']
            )

            # Acquire token
            scopes = ['User.Read']
            result = app.acquire_token_by_authorization_code(
                code,
                scopes=scopes,
                redirect_uri=self.config['redirect_uri']
            )

            if 'access_token' in result:
                logger.info("Successfully obtained access token from Azure AD")
                return result
            else:
                # Enhanced error logging with full error details
                error = result.get('error', 'unknown_error')
                error_description = result.get('error_description', 'No description provided')
                error_codes = result.get('error_codes', [])
                correlation_id = result.get('correlation_id', 'N/A')

                logger.error(
                    f"Azure AD token acquisition failed:\n"
                    f"  Error: {error}\n"
                    f"  Description: {error_description}\n"
                    f"  Error Codes: {error_codes}\n"
                    f"  Correlation ID: {correlation_id}\n"
                    f"  Redirect URI: {self.config['redirect_uri']}"
                )

                # Common error messages for troubleshooting
                if 'AADSTS' in error_description:
                    if 'AADSTS54005' in error_description:
                        logger.error("OAuth2 authorization code was already used. User may have clicked the login button multiple times.")
                    elif 'AADSTS50011' in error_description:
                        logger.error("Redirect URI mismatch. Check that Azure app registration redirect URI matches the configured value.")
                    elif 'AADSTS700016' in error_description:
                        logger.error("Application not found. Check that Client ID is correct.")

                return None

        except Exception as e:
            logger.exception(f"Exception while exchanging code for token: {e}")
            return None
