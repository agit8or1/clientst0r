# GitHub Issue #3: Azure SSO Button Not Showing - Resolution

## Problem
User configured Azure SSO but the "Sign in with Microsoft" button isn't appearing on the login page.

## Root Cause
The Azure SSO button visibility is controlled by JavaScript that calls `/accounts/auth/azure/status/` endpoint. The button only appears when ALL 5 required settings are configured:
1. Azure AD Enabled checkbox
2. Tenant ID
3. Client ID
4. Client Secret
5. Redirect URI

If any single field is empty, `is_enabled()` returns `false` and the button stays hidden.

## Changes Made (v2.22.1)

### 1. Enhanced Azure Status Endpoint
**File:** `accounts/oauth_views.py`

Added diagnostic information to the `/accounts/auth/azure/status/` endpoint. When an admin/superuser visits this endpoint while authenticated, they now see:

```json
{
  "enabled": false,
  "debug": {
    "azure_ad_enabled": true,
    "has_tenant_id": true,
    "has_client_id": true,
    "has_client_secret": false,
    "has_redirect_uri": true
  }
}
```

This makes it easy to identify which field is missing.

### 2. Fixed Dark Mode CSS Conflicts
**File:** `static/css/custom.css`

- Removed entire `[data-bs-theme="dark"]` section (245 lines)
- Fixed table backgrounds to use theme-specific variables
- All theme styling now comes from `themes.css`

This fixes the "white backgrounds everywhere" issue in dark mode.

## User Instructions

### Step 1: Diagnose the Issue

1. Log in as superuser/admin
2. Visit: `https://your-domain.com/accounts/auth/azure/status/`
3. Check the `debug` object to see which fields are missing

### Step 2: Fix Configuration

1. Navigate to **Settings → Directory Integration** (`/core/settings/directory/`)
2. Ensure ALL fields are filled:
   - ☑️ Enable Azure AD / Microsoft Entra ID (checkbox)
   - **Tenant ID**: Azure AD Tenant GUID
   - **Client ID**: Application (Client) ID from Azure
   - **Client Secret**: Secret VALUE (not ID) from Azure
   - **Redirect URI**: `https://your-domain.com/accounts/auth/azure/callback/`
3. Click **Save**
4. Hard refresh login page (`Ctrl + Shift + R`)

### Step 3: Verify Azure Portal Configuration

Ensure the Azure App Registration has:
- **Redirect URI** in Authentication settings that EXACTLY matches HuduGlue:
  - Must be: `https://your-domain.com/accounts/auth/azure/callback/`
  - Case sensitive, trailing slash required
  - HTTP vs HTTPS must match
- **API Permissions**: `User.Read` (Microsoft Graph)
- **Client Secret** is not expired

### Common Issues

1. **Client Secret copied with extra characters** - Regenerate and copy carefully
2. **Redirect URI mismatch** - Must match byte-for-byte between HuduGlue and Azure
3. **Settings not saving** - Clear cache and restart Gunicorn

## Testing

After configuration:
1. Log out
2. Go to login page
3. Hard refresh (`Ctrl + Shift + R`)
4. Look for blue "Sign in with Microsoft" button
5. Click button to test OAuth flow

## Response Posted to GitHub

The full troubleshooting guide has been prepared in `/tmp/github_issue_3_response.md` and should be posted as a comment to https://github.com/agit8or1/huduglue/issues/3

**Note:** GitHub API token with issue write permissions is required to post comments programmatically.

## Related Files

- `accounts/oauth_views.py` - Enhanced azure_status view
- `accounts/azure_auth.py` - AzureOAuthClient.is_enabled() method
- `templates/two_factor/core/login.html` - Login page with Azure button
- `static/css/custom.css` - Fixed dark mode conflicts
- `static/css/themes.css` - Theme definitions

## Version
Fixed in: v2.22.1 (unreleased commit)
