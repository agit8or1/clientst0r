# Azure AD SSO Setup Guide

## Overview

Clientst0r now supports Azure AD (Microsoft Entra ID) Single Sign-On authentication. Users can log in using their Microsoft work accounts.

## Setup Steps

### 1. Register Application in Azure Portal

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** → **App registrations**
3. Click **New registration**
4. Configure:
   - **Name**: Clientst0r
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
3. Add description: "Clientst0r OAuth"
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
   - From v3.17.764 sign-in also asks for the OpenID **email** permission
     (Microsoft Graph → Delegated → *email*) so the sign-in carries the
     mailbox address. Add it and grant consent if your tenant requires admin
     consent for new permissions.
4. Click **Grant admin consent** (if you have admin rights)

### 5. Configure Clientst0r

#### Option A: Via Admin UI (Recommended)

1. Log in to Clientst0r as superuser
2. Go to **Settings** → **Users & Access** → **Directory Services**
3. Under **Azure AD / Microsoft Entra ID**, configure:
   - **Enable Azure AD**: ✓ (checked)
   - **Tenant ID**: Paste your Directory (tenant) ID
   - **Client ID**: Paste your Application (client) ID
   - **Client Secret**: Paste the secret value you copied
   - **Redirect URI**: `https://your-domain.com/accounts/auth/azure/callback/`
   - **Additional allowed tenant IDs**: leave empty for a single-tenant app. Only the configured tenant's tokens are accepted; with a multi-tenant app (`common` / `organizations`) list every tenant to accept, or none is.
   - **Auto-create users**: off by default. When on, a Microsoft account no account here is linked to gets a new account with **no client access and no staff rights**.
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
5. After successful authentication, you'll be logged into Clientst0r

## Features

### How a Microsoft sign-in finds an account (v3.17.688)

A sign-in is matched **only** on the Microsoft identity stored on the account:
the tenant ID (`tid`) and object ID (`oid`) from the verified ID token. An
e-mail address or UPN never selects an account.

Before v3.17.688 an existing account was matched by e-mail address, so anyone
who could sign in to Microsoft with that address (in an accepted tenant)
signed in as that account, administrators included.

### Linking an existing account

An existing account is linked to Microsoft sign-in in one of two ways:

1. **By the user**: sign in with the password, open **My Profile**, enter the
   password (and authenticator code) under *Microsoft sign-in* and choose
   **Link Microsoft sign-in**, then sign in to Microsoft.
2. **By an administrator**: when someone signs in with Microsoft using the
   e-mail address of an account that isn't linked, the sign-in is refused, a
   security event is logged, and a *link request* appears on that user's page
   (Settings → Users). A superuser may approve it after confirming with the
   person, by entering their own password (and code). Nobody can approve a
   request for their own account. The account matches if its e-mail address
   is the person's Microsoft mailbox address *or* their Microsoft sign-in name
   (UPN); these are often different.

Users and administrators can unlink from the same places.

### Superusers and staff

Superuser and staff accounts are never created or linked automatically.
A superuser may use Microsoft sign-in once it has been linked explicitly (by
either method above).

### Auto-User Creation

Off by default. When enabled, a Microsoft identity that no account is linked
to, and whose e-mail address no account uses, gets a new account:

- **Username**: Derived from the e-mail address
- **Rights**: no organization membership, not staff, not superuser, no password
- **Linked identity**: the token's tenant and object IDs

An administrator grants access afterwards as for any new user.

### 2FA

A Microsoft sign-in counts as 2FA only when Microsoft confirms MFA (`amr`
contains `mfa`), or the server sets `AZURE_SSO_TRUSTED_AS_2FA`. Otherwise the
user enters their Clientst0r authenticator code (v3.17.660).

### Upgrading to v3.17.688

- Accounts that already signed in with Microsoft have its object ID stored.
  They keep working; the tenant ID is recorded on their next sign-in and
  checked from then on.
- **Superusers** whose link was made automatically before v3.17.688 must link
  once more (method 1 or 2 above).
- Accounts with no stored object ID must be linked once.
- Auto-create is switched **off** by the upgrade. Turn it back on in
  Settings → Directory services if you want it.
- Because the old matching trusted e-mail addresses, review the linked
  identity (tenant and object ID) shown on each administrator's user page,
  and the audit log for Microsoft sign-ins you don't recognise. Unlink
  anything unexpected.

## Security Notes

- **Client Secret**: Store securely, never commit to version control
- **Redirect URI**: Must exactly match what's configured in Azure
- **HTTPS Required**: Azure AD requires HTTPS for redirect URIs (except localhost)
- **Session Security**: Azure authentication status is stored in session
- **PKCE, nonce and state**: the sign-in uses MSAL's auth code flow (PKCE S256, nonce, state); the flow is kept in the server session
- **ID token checks**: RS256 signature against Microsoft's published keys, audience (client ID), expiry, nonce, and issuer of an accepted tenant

## Troubleshooting

### "Azure AD is not configured" Error

- Verify all settings are saved correctly
- Check that `azure_ad_enabled` is set to `true`
- Ensure all required fields (tenant_id, client_id, client_secret, redirect_uri) are populated

### "Failed to obtain access token" Error

- Verify client secret is correct (may have expired)
- Check redirect URI matches exactly between Azure and Clientst0r
- Ensure Azure app has User.Read permission

### "Authentication failed" Error

- "already uses this e-mail address, but it is not linked": link the account (see *Linking an existing account*)
- "No account here is linked … You signed in as *address*": no account here is linked to that
  Microsoft identity and no account uses that address. In **Settings → Users**, set the person's
  e-mail address to the one shown (or create the account with it), have them sign in with
  Microsoft once more, then approve the link request on their user page. The audit log entry
  `azure_sso_no_account` lists every address Microsoft sent. Upgrading to v3.17.688 or later
  also turned *Auto-create users* off; turn it back on only if you want unknown Microsoft
  accounts to get new, access-less accounts.
- A superuser locked out of every sign-in method can reset their password on the server:
  `python manage.py changepassword <username>`, then link from My Profile
- "Sign-in from this Microsoft organization is not allowed": the token's tenant is not the configured one or in the allowlist
- Review audit logs (`azure_sso_*` events) for more details

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
6. Clientst0r exchanges the code (MSAL checks state and PKCE)
7. Verifies the ID token (signature, audience, expiry, nonce, tenant)
8. Finds the account linked to the token's tenant and object ID
9. Creates an account only if auto-create is on and nothing matches
10. Sets session flag `azure_ad_authenticated = True`
11. Redirects to dashboard

## Support

For issues or questions, please file an issue on GitHub.
