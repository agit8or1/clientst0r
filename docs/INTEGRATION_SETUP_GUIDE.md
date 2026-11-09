# Client St0r Integration Setup Guide

Complete guide for connecting PSA and RMM platforms to Client St0r with exact connection parameters and setup instructions.

---

## PSA Integrations

### ConnectWise Manage

**Base URL Format:**
```
https://na.myconnectwise.net
https://eu.myconnectwise.net
https://au.myconnectwise.net
https://your-custom-url.connectwise.com
```

**Required Credentials:**
1. **Company ID**: Your ConnectWise company identifier (e.g., `yourcompany`)
2. **Public Key**: API member public key
3. **Private Key**: API member private key
4. **Client ID**: Integration application ID (from Developer Network)

**Setup Instructions:**
1. Log in to ConnectWise Manage
2. Go to **System → Members** → Select API member
3. Navigate to **API Keys** tab
4. Click **New** to generate new API keys
5. Copy the **Public Key** and **Private Key** (save immediately - shown only once)
6. Get your **Company ID** from System → Company settings
7. Register at ConnectWise Developer Network to get **Client ID**
8. In Client St0r, use full URL including region (na/eu/au)

**API Documentation:** https://developer.connectwise.com/

---

### Autotask PSA

**Base URL Format:**
```
https://webservices1.autotask.net/atservicesrest
https://webservices2.autotask.net/atservicesrest
https://webservices3.autotask.net/atservicesrest
...up to webservices20
```

**Required Credentials:**
1. **Username**: API user email address
2. **API Secret**: Generated API tracking identifier
3. **Integration Code**: Your integration vendor code

**Setup Instructions:**
1. Log in to Autotask PSA
2. Go to **Admin → Resources (Users)** → Select API user
3. Navigate to **Security** tab
4. Generate **API Tracking Identifier** (Secret)
5. Get your **webservices zone number** from API documentation
6. Request **Integration Code** from Autotask (required for production)
7. Base URL must match your assigned zone (webservices1-20)

**API Documentation:** https://www.autotask.net/help/DeveloperHelp/

---

### HaloPSA

**Base URL Format:**
```
https://yourtenant.halopsa.com
https://yourtenant.haloitsm.com
```

**Required Credentials:**
1. **Client ID**: OAuth2 application client ID
2. **Client Secret**: OAuth2 application secret
3. **Tenant**: (Optional) Multi-tenant identifier

**Setup Instructions:**
1. Log in to HaloPSA
2. Go to **Configuration → Integrations → HaloPSA API**
3. Click **View Applications**
4. Create **New Application**
5. Set **Authentication Method** to **Client ID and Secret (Services/Daemons)**
6. Select appropriate **Permissions** (read tickets, contacts, companies)
7. Copy **Client ID** and **Client Secret**
8. Base URL is your HaloPSA tenant URL

**API Documentation:** https://haloservicedesk.com/apidoc/

---

### Kaseya BMS

**Base URL Format:**
```
https://your-instance.kaseya.net
https://bms.kaseya.com
```

**Required Credentials:**
1. **API Key**: Generated API authentication key
2. **API Secret**: API secret token

**Setup Instructions:**
1. Log in to Kaseya BMS
2. Go to **System → Security → API Users**
3. Create **New API User**
4. Generate **API Key** and **Secret**
5. Assign appropriate **Role** (minimum: read companies, tickets, contacts)
6. Copy credentials immediately
7. Use your Kaseya instance URL as base URL

**API Documentation:** https://helpdesk.kaseya.com/hc/en-gb/categories/202373247

---

### Syncro

**Base URL Format:**
```
https://yourdomain.syncromsp.com
```

**Required Credentials:**
1. **API Key**: Generated API token
2. **Subdomain**: Your Syncro subdomain (e.g., `yourcompany` from `yourcompany.syncromsp.com`)

**Setup Instructions:**
1. Log in to Syncro
2. Go to **Admin → API Tokens**
3. Click **New API Token**
4. Enter **Name** (e.g., "Client St0r Integration")
5. Copy the **API Key** (shown only once)
6. Extract subdomain from your Syncro URL
7. Base URL: `https://[subdomain].syncromsp.com`

**API Documentation:** https://api-docs.syncromsp.com/

---

### Freshservice

**Base URL Format:**
```
https://yourdomain.freshservice.com
```

**Required Credentials:**
1. **API Key**: Generated API key from profile
2. **Domain**: Your Freshservice domain (e.g., `yourcompany` from `yourcompany.freshservice.com`)

**Setup Instructions:**
1. Log in to Freshservice
2. Click your **Profile Picture** → **Profile Settings**
3. Scroll to **Your API Key** section
4. Copy or regenerate **API Key**
5. Extract domain from your Freshservice URL
6. Base URL: `https://[domain].freshservice.com`

**API Documentation:** https://api.freshservice.com/

---

### Zendesk

**Base URL Format:**
```
https://yoursubdomain.zendesk.com
```

**Required Credentials:**
1. **Email**: Admin email address
2. **API Token**: Generated API token
3. **Subdomain**: Your Zendesk subdomain (e.g., `yourcompany` from `yourcompany.zendesk.com`)

**Setup Instructions:**
1. Log in to Zendesk
2. Go to **Admin Center** → **Apps and integrations** → **APIs**
3. Navigate to **Zendesk API** tab
4. Enable **Token Access**
5. Click **Add API Token**
6. Enter **Description** (e.g., "Client St0r")
7. Copy the **API Token** (shown only once)
8. Use admin email as username
9. Base URL: `https://[subdomain].zendesk.com`

**API Documentation:** https://developer.zendesk.com/api-reference/

---

### ITFlow

**Base URL Format:**
```
https://your-itflow-instance.com
https://yourdomain.com/itflow
```

**Required Credentials:**
1. **API Key**: Generated API key from ITFlow

**Setup Instructions:**
1. Log in to ITFlow
2. Go to **Settings → API Keys**
3. Click **Create API Key**
4. Enter **Name** (e.g., "Client St0r Integration")
5. Copy the **API Key**
6. Use your ITFlow installation URL as base URL

**API Documentation:** https://docs.itflow.org/api_getting_started

---

### RangerMSP (CommitCRM)

**Base URL Format:**
```
https://api.commitcrm.com/api/v1 (Cloud)
https://your-server.com:8443/api/v1 (Self-Hosted)
```

**Required Credentials:**
1. **API Key**: Generated from RangerMSP admin panel
2. **Account ID**: (Optional) For cloud-hosted multi-account setups

**Setup Instructions:**
1. Log in to RangerMSP Admin Panel
2. Go to **Setup → Security → API Access**
3. Click **Generate New API Key**
4. Enter **Application Name** (e.g., "Client St0r")
5. Select **Permissions** (Companies, Contacts, Tickets, Contracts)
6. Copy the **API Key**
7. **Cloud URL:** Use `https://api.commitcrm.com/api/v1`
8. **Self-Hosted:** Use `https://[your-server]:8443/api/v1`

**API Documentation:** https://api.commitcrm.com/docs

---

## RMM Integrations

### Customers, sites and device links

Each RMM connection is either **single customer** (every device belongs to the
organization that owns the connection) or **multiple customers** (each device is
filed under the customer the RMM reports for it). Set this under **Customers** on
the connection form.

On a multiple-customer connection a device is only shown on a customer's assets,
tickets, alerts and reports once its customer is settled: by an imported or mapped
RMM customer ID, or by a technician in **Integrations → (connection) → Review**.
A device the RMM moves to another customer is hidden until a technician confirms
the move. Devices are never filed under the connection owner as a fallback.

| RMM | Customer | Site | Alerts tied to a device by | Open the device in the RMM | How verified |
|---|---|---|---|---|---|
| NinjaOne | Organization ID | Location ID (kept separate from the organization) | `deviceId` | Yes: a short-lived link from the documented dashboard-URL endpoint, fetched by the server when you click | Fixture tests against the v2 API spec. Not yet checked against a live account |
| Datto RMM | Site UID (Datto's site is the customer, so one site is one customer) | Same site | `alertSourceInfo.deviceUid` | Yes: the device's `portalUrl`, shown only on the platform's web host (for example `pinotage.centrastage.net`) | Fixture tests against the API v2 spec. Not yet checked against a live account |
| Atera | `CustomerID` | None (Atera has no site level) | `DeviceGuid`, matched to an agent of the same customer | Yes: the agent's `AppViewUrl`, only on `app.atera.com` | Fixture tests against a published copy of the v3 API spec. Not yet checked against a live account |
| ConnectWise Automate | Client ID | Location ID | `Computer.Id` | No documented URL. The page shows a copyable name and ID | Fixture tests against a published copy of the REST v1 spec. Not yet checked against a live server |
| Tactical RMM | Client ID from one `/clients/` read per sync. If that read fails, the client name (needs a one-time mapping) | Site ID (site names may repeat across customers) | `agent_id` | Yes, when **Web console URL** is set on the connection: `<console>/agents/<agent id>` | Fixture tests against the Tactical RMM source. Not yet checked against a live server |

Device asset links follow the same rules for every RMM. They never cross customers:

- A unique serial matches. Placeholder serials ("To Be Filled By O.E.M.", "0", etc.) are ignored.
- A unique hostname matches only when the serial and site don't conflict.
- IP addresses are never used to identify a device.
- Duplicates and conflicts go to the review queue with the candidates and a plain explanation.
- A technician's link, "create new" or "leave unlinked" decision is kept across syncs.
- An RMM fills empty asset fields. It updates a field only while that field still holds the value the RMM last wrote, so technician edits are kept.

**After upgrading**, run one sync on each connection, then preview and apply reconciliation:

```bash
python manage.py rmm_reconcile                 # dry run: counts only, nothing saved
python manage.py rmm_reconcile --apply         # make the changes
python manage.py rmm_reconcile --connection 3  # one connection only
```

It is safe to run again. Links to another customer's assets stop showing as soon as the update is applied, before reconciliation runs.

### NinjaOne (NinjaRMM)

**Base URL Format:**
```
https://app.ninjarmm.com
https://eu.ninjarmm.com
https://oc.ninjarmm.com
```

**Required Credentials:**
1. **Client ID**: OAuth2 application client ID
2. **Client Secret**: OAuth2 application secret
3. **Refresh Token**: OAuth2 refresh token

**Setup Instructions:**
1. Log in to NinjaOne
2. Go to **Administration → Apps → API**
3. Click **Add** to create new application
4. Select **OAuth** authentication
5. Set **Redirect URI** (use `https://your-clientst0r.com/integrations/callback`)
6. Copy **Client ID** and **Client Secret**
7. Complete OAuth flow to get **Refresh Token**
8. Use region-specific URL (app/eu/oc based on your instance)

**API Documentation:** https://ninjarmm.zendesk.com/hc/en-us/sections/360001438632-API

---

### Datto RMM

**Base URL Format:**
```
https://pinotage-api.centrastage.net
```

**Required Credentials:**
1. **API Key**: Platform API key
2. **API Secret**: Platform API secret

**Setup Instructions:**
1. Log in to Datto RMM
2. Go to **Setup → Account Settings → API Credentials**
3. Click **New**
4. Enter **Name** (e.g., "Client St0r")
5. Copy **API URL**, **API Key**, and **Secret Key**
6. Use the provided API URL as base URL

**API Documentation:** https://help.aem.autotask.net/en/Content/2SETUP/APIv2.htm

---

### ConnectWise Automate (LabTech)

**Base URL Format:**
```
https://your-automate.server.com
https://automate.yourcompany.com
```

**Required Credentials:**
1. **Server URL**: Your Automate server URL
2. **Username**: API user account
3. **Password**: API user password

**Setup Instructions:**
1. Log in to ConnectWise Automate
2. Go to **Tools → User Accounts**
3. Create new user or use existing
4. Set **Security Class** with API permissions
5. Enable **API Only** account (recommended)
6. Use credentials for authentication
7. Base URL is your Automate server address

**API Documentation:** https://docs.connectwise.com/ConnectWise_Automate/ConnectWise_Automate_Documentation

---

### Atera

**Base URL Format:**
```
https://app.atera.com
```

**Required Credentials:**
1. **API Key**: X-API-KEY header value

**Setup Instructions:**
1. Log in to Atera
2. Go to **Admin → API**
3. View your **API Key** (shown as **X-API-KEY**)
4. Copy the API key
5. Base URL is always `https://app.atera.com`

**API Documentation:** https://app.atera.com/api/

---

### Tactical RMM

**Base URL Format:**
```
https://rmm.yourdomain.com
https://your-tactical-instance.com
```

**Required Credentials:**
1. **API Key**: Generated API token

**Setup Instructions:**
1. Log in to Tactical RMM
2. Go to **Settings → API Keys**
3. Click **New**
4. Enter **Name** (e.g., "Client St0r")
5. Select **Permissions** (read agents, alerts, software)
6. Copy the **API Key** (shown only once)
7. Use your Tactical RMM API URL as the base URL (for example `https://api.yourdomain.com`)
8. Optional: set **Web console URL** to the address you open Tactical RMM at (for example `https://rmm.yourdomain.com`) to get "Open in Tactical RMM" links

**API Documentation:** https://docs.tacticalrmm.com/api/

---

## Troubleshooting

### Common Issues

**401 Unauthorized:**
- Verify credentials are correct
- Check if API user has proper permissions
- Ensure API access is enabled in source system
- Check if API keys have expired

**403 Forbidden:**
- User/API key lacks required permissions
- IP whitelist restrictions (if configured)
- Resource access limitations

**404 Not Found:**
- Base URL is incorrect
- Wrong API version in URL
- Endpoint doesn't exist (check provider API docs)

**429 Rate Limited:**
- Too many requests in time window
- Increase sync_interval_minutes
- Contact provider to increase rate limits

**SSL/TLS Errors:**
- Self-signed certificates not trusted
- Certificate expired
- Wrong hostname in certificate

### Testing Connections

1. Save connection with all required credentials
2. Click **Test Connection** button
3. Review error messages for specific issues
4. Check application logs: `/var/log/itdocs/django.log`
5. Verify base URL is accessible: `curl -I [base_url]`
6. Test API credentials with provider's API explorer

### Getting Help

- Check provider's API documentation
- Review error logs for specific error messages
- Contact provider support for API access issues
- Open GitHub issue: https://github.com/agit8or1/clientst0r/issues

---

## Security Best Practices

1. **API Keys:**
   - Use dedicated API-only accounts
   - Grant minimum required permissions
   - Rotate keys regularly (quarterly recommended)
   - Never commit keys to version control

2. **Network Security:**
   - Use HTTPS for all connections
   - Implement IP whitelisting when available
   - Use firewall rules to restrict API access

3. **Monitoring:**
   - Enable audit logging in source systems
   - Monitor API usage and patterns
   - Set up alerts for failed authentications
   - Review sync logs regularly

4. **Access Control:**
   - Limit who can create/edit integrations
   - Use role-based access control
   - Require superadmin for integration management
   - Document integration ownership

---

**Last Updated:** 2026-01-16
**Version:** 2.24.89
