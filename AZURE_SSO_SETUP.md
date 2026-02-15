# Azure AD SSO Setup Guide

## Overview

Client St0r now supports Azure AD (Microsoft Entra ID) Single Sign-On authentication. Users can log in using their Microsoft work accounts.

## Setup Steps

### 1. Register Application in Azure Portal

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** → **App registrations**
3. Click **New registration**
4. Configure:
   - **Name**: Client St0r
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**:
     - Type: Web
     - URL: `https://your-domain.com/accounts/auth/azure/callback/`
5. Click **Register**

### 2. Configure Application

After registration, note the following values (you'll need them later):

- **Application (client) ID**: Found on the Overview page
- **Directory (tenant) ID**: Found on the Overview page

### 3. Create Client Secret

1. Go to **Certificates & secrets** → **Client secrets**
2. Click **New client secret**
3. Add description: "Client St0r OAuth"
4. Select expiration (recommended: 24 months)
5. Click **Add**
6. **IMPORTANT**: Copy the **Value** immediately (you won't be able to see it again)

### 4. Configure API Permissions

1. Go to **API permissions**
2. Ensure **User.Read** permission is present (should be added automatically)
3. If not present:
   - Click **Add a permission**
   - Select **Microsoft Graph** → **Delegated permissions**
   - Add **User.Read**
4. Click **Grant admin consent** (if you have admin rights)

### 5. Configure Client St0r

#### Option A: Via Admin UI (Recommended)

1. Log in to Client St0r as superuser
2. Go to **Admin** → **Settings** → **Directory Services**
3. Under **Azure AD / Microsoft Entra ID**, configure:
   - **Enable Azure AD**: ✓ (checked)
   - **Tenant ID**: Paste your Directory (tenant) ID
   - **Client ID**: Paste your Application (client) ID
   - **Client Secret**: Paste the secret value you copied
   - **Redirect URI**: `https://your-domain.com/accounts/auth/azure/callback/`
   - **Auto-create users**: ✓ (recommended - creates users on first login)
   - **Sync groups**: Optional (not yet implemented)
4. Click **Save**

#### Option B: Via Database

Run SQL to configure settings:

```sql
-- Enable Azure AD
INSERT INTO core_systemsetting (key, value, value_type, category, description, is_public, created_at, updated_at)
VALUES ('azure_ad_enabled', 'true', 'boolean', 'authentication', 'Enable Azure AD authentication', 0, NOW(), NOW());

-- Tenant ID
INSERT INTO core_systemsetting (key, value, value_type, category, description, is_public, created_at, updated_at)
VALUES ('azure_ad_tenant_id', 'YOUR-TENANT-ID-HERE', 'string', 'authentication', 'Azure AD Tenant ID', 0, NOW(), NOW());

-- Client ID
INSERT INTO core_systemsetting (key, value, value_type, category, description, is_public, created_at, updated_at)
VALUES ('azure_ad_client_id', 'YOUR-CLIENT-ID-HERE', 'string', 'authentication', 'Azure AD Client ID', 0, NOW(), NOW());

-- Client Secret
INSERT INTO core_systemsetting (key, value, value_type, category, description, is_public, created_at, updated_at)
VALUES ('azure_ad_client_secret', 'YOUR-CLIENT-SECRET-HERE', 'string', 'authentication', 'Azure AD Client Secret', 0, NOW(), NOW());

-- Redirect URI
INSERT INTO core_systemsetting (key, value, value_type, category, description, is_public, created_at, updated_at)
VALUES ('azure_ad_redirect_uri', 'https://your-domain.com/accounts/auth/azure/callback/', 'string', 'authentication', 'Azure AD Redirect URI', 0, NOW(), NOW());

-- Auto-create users
INSERT INTO core_systemsetting (key, value, value_type, category, description, is_public, created_at, updated_at)
VALUES ('azure_ad_auto_create_users', 'true', 'boolean', 'authentication', 'Auto-create users on first Azure login', 0, NOW(), NOW());
```

### 6. Run Migrations

Apply database migrations:

```bash
python manage.py migrate accounts
```

### 7. Test Login

1. Go to the login page: `https://your-domain.com/`
2. You should see a **"Sign in with Microsoft"** button
3. Click the button
4. You'll be redirected to Microsoft login
5. After successful authentication, you'll be logged into Client St0r

## Features

### Auto-User Creation

When enabled, users who successfully authenticate via Azure AD will automatically have accounts created in Client St0r:

- **Username**: Derived from email (e.g., `john.doe` from `john.doe@company.com`)
- **Email**: From Azure AD
- **Name**: First and last name from Azure AD
- **Auth Source**: Marked as `azure_ad`

### 2FA Bypass

Users who authenticate via Azure AD **bypass 2FA requirements**. Azure AD authentication is already secure through Microsoft's multi-factor authentication.

### User Sync

User information (name, email) is automatically updated from Azure AD on each login.

## Security Notes

- **Client Secret**: Store securely, never commit to version control
- **Redirect URI**: Must exactly match what's configured in Azure
- **HTTPS Required**: Azure AD requires HTTPS for redirect URIs (except localhost)
- **Session Security**: Azure authentication status is stored in session

## Troubleshooting

### "Azure AD is not configured" Error

- Verify all settings are saved correctly
- Check that `azure_ad_enabled` is set to `true`
- Ensure all required fields (tenant_id, client_id, client_secret, redirect_uri) are populated

### "Failed to obtain access token" Error

- Verify client secret is correct (may have expired)
- Check redirect URI matches exactly between Azure and Client St0r
- Ensure Azure app has User.Read permission

### "Authentication failed" Error

- Check that user's email is valid
- If auto-create is disabled, ensure user already exists in Client St0r
- Review audit logs for more details

### Azure Button Not Showing

- Check browser console for JavaScript errors
- Verify `/accounts/auth/azure/status/` endpoint returns `{"enabled": true}`
- Clear browser cache

## URLs

- **Login Initiation**: `/accounts/auth/azure/login/`
- **OAuth Callback**: `/accounts/auth/azure/callback/`
- **Status Check**: `/accounts/auth/azure/status/`

## Architecture

### Components

1. **AzureADBackend** (`accounts/azure_auth.py`): Django authentication backend
2. **AzureOAuthClient** (`accounts/azure_auth.py`): OAuth helper for MSAL
3. **OAuth Views** (`accounts/oauth_views.py`): Login initiation and callback handling
4. **Login Template** (`templates/two_factor/core/login.html`): UI with Azure button

### Flow

1. User clicks "Sign in with Microsoft"
2. Redirected to `/accounts/auth/azure/login/`
3. MSAL generates authorization URL
4. User redirected to Microsoft login
5. After authentication, Microsoft redirects to `/accounts/auth/azure/callback/`
6. Client St0r exchanges code for access token
7. Fetches user info from Microsoft Graph API
8. Authenticates user in Django
9. Creates user account if needed
10. Sets session flag `azure_ad_authenticated = True`
11. Redirects to dashboard

## Support

For issues or questions, please file an issue on GitHub.
