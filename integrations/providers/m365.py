"""
Microsoft 365 / Graph API provider.
Uses Azure AD app registration with client credentials OAuth2 flow.
Required Graph API permissions (application, not delegated):
  User.Read.All, Group.Read.All, Sites.Read.All, TeamSettings.Read.All,
  Directory.Read.All, Organization.Read.All, SecurityAlert.Read.All,
  Reports.Read.All
"""
import logging
import requests

logger = logging.getLogger(__name__)

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
TOKEN_URL = 'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'


class M365Provider:
    """Read-only Microsoft Graph API client using client credentials flow."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.post(
            TOKEN_URL.format(tenant_id=self.tenant_id),
            data={
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'https://graph.microsoft.com/.default',
            },
            timeout=15,
        )
        resp.raise_for_status()
        self._token = resp.json()['access_token']
        return self._token

    def _get(self, path: str, params: dict = None) -> dict:
        headers = {
            'Authorization': f'Bearer {self._get_token()}',
            'Accept': 'application/json',
            # Required for $search and advanced $filter queries (Graph API ignores for others)
            'ConsistencyLevel': 'eventual',
        }
        url = path if path.startswith('http') else f'{GRAPH_BASE}{path}'
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _get_all(self, path: str, params: dict = None) -> list:
        """Follow @odata.nextLink to page through all results."""
        results = []
        data = self._get(path, params)
        results.extend(data.get('value', []))
        while '@odata.nextLink' in data:
            data = self._get(data['@odata.nextLink'])
            results.extend(data.get('value', []))
        return results

    def test_connection(self) -> dict:
        try:
            data = self._get('/organization', params={'$select': 'displayName,id'})
            org_name = data.get('value', [{}])[0].get('displayName', 'Unknown')
            return {'success': True, 'message': f"Connected to tenant: {org_name}"}
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                if e.response.status_code == 401:
                    return {'success': False, 'error': 'Authentication failed — check tenant ID, client ID and secret.'}
                if e.response.status_code == 403:
                    return {'success': False, 'error': 'Forbidden — ensure the app has required Graph API permissions.'}
                try:
                    err = e.response.json().get('error', {})
                    return {'success': False, 'error': f"{err.get('code')}: {err.get('message')}"}
                except Exception:
                    pass
            return {'success': False, 'error': str(e)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_users(self) -> list:
        try:
            return self._get_all('/users', params={
                '$select': 'displayName,userPrincipalName,accountEnabled,assignedLicenses,jobTitle,department,mail',
                '$filter': 'accountEnabled eq true',
                '$top': '999',
            })
        except Exception as e:
            logger.warning(f"M365 get_users failed: {e}")
            return []

    def get_licenses(self) -> list:
        try:
            return self._get_all('/subscribedSkus', params={
                '$select': 'skuPartNumber,consumedUnits,prepaidUnits,skuId',
            })
        except Exception as e:
            logger.warning(f"M365 get_licenses failed: {e}")
            return []

    def get_shared_mailboxes(self) -> list:
        """Get shared mailboxes (users with mailbox but no assigned licenses)."""
        try:
            users = self._get_all('/users', params={
                '$select': 'displayName,mail,userPrincipalName,assignedLicenses',
                '$filter': "mail ne null",
                '$top': '999',
            })
            return [u for u in users if not u.get('assignedLicenses')]
        except Exception as e:
            logger.warning(f"M365 get_shared_mailboxes failed: {e}")
            return []

    def get_mailbox_usage(self) -> list:
        """Get mailbox usage stats — storage used, item count, type.
        Uses /reports/getMailboxUsageDetail which requires Reports.Read.All.

        Graph reporting endpoints redirect (302) to a pre-authenticated Azure Blob
        SAS URL serving a CSV file. We must follow the redirect manually because
        requests strips Authorization on cross-domain redirects (graph→blob), which
        causes a spurious 403. We always parse as CSV — the $format=json parameter
        is unreliable across tenants and causes additional redirect complexity.
        """
        import csv as _csv, io as _io
        try:
            auth_headers = {
                'Authorization': f'Bearer {self._get_token()}',
                'Accept': 'text/csv, application/json, */*',
            }
            url = f'{GRAPH_BASE}/reports/getMailboxUsageDetail(period=\'D7\')'
            resp = requests.get(url, headers=auth_headers, timeout=30, allow_redirects=False)

            # Follow redirect manually — the Location URL is a blob SAS that needs no auth
            if resp.status_code in (301, 302, 303, 307, 308):
                redirect_url = resp.headers.get('Location', '')
                if redirect_url:
                    resp = requests.get(redirect_url, timeout=60)

            if resp.status_code == 403:
                return [{'permission_error': True, 'required': 'Reports.Read.All'}]
            resp.raise_for_status()

            # Try JSON first (some tenants return JSON directly at 200)
            ct = resp.headers.get('Content-Type', '')
            if 'json' in ct:
                try:
                    data = resp.json()
                    if isinstance(data, list):
                        return data
                    return data.get('value', [])
                except ValueError:
                    pass

            # CSV parsing — strip UTF-8 BOM if present, normalise line endings
            text = resp.content.decode('utf-8-sig', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
            reader = _csv.DictReader(_io.StringIO(text))
            rows = []
            for row in reader:
                # Strip BOM from first field key in case csv.DictReader didn't catch it
                row = {k.lstrip('\ufeff').strip(): v for k, v in row.items()}
                storage_raw = (row.get('Storage Used (Byte)') or row.get('Storage Used (Bytes)') or
                               row.get('storageUsedInBytes') or '0')
                item_raw = row.get('Item Count') or row.get('itemCount') or '0'
                try:
                    storage_bytes = int(str(storage_raw).replace(',', '') or '0')
                except (ValueError, TypeError):
                    storage_bytes = 0
                try:
                    item_count = int(str(item_raw).replace(',', '') or '0')
                except (ValueError, TypeError):
                    item_count = 0
                rows.append({
                    'displayName': row.get('Display Name') or row.get('displayName') or '',
                    'userPrincipalName': row.get('User Principal Name') or row.get('userPrincipalName') or '',
                    'recipientType': row.get('Recipient Type') or row.get('recipientType') or '',
                    'storageUsedInBytes': storage_bytes,
                    'itemCount': item_count,
                    'lastActivityDate': row.get('Last Activity Date') or row.get('lastActivityDate') or '',
                })
            if not rows:
                logger.warning(f"M365 get_mailbox_usage: CSV parsed but returned 0 rows. "
                               f"Status={resp.status_code}, CT={ct}, "
                               f"First 200 chars: {text[:200]!r}")
            return rows
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code == 403:
                return [{'permission_error': True, 'required': 'Reports.Read.All'}]
            logger.warning(f"M365 get_mailbox_usage failed (HTTP {code}): {e}")
            return []
        except Exception as e:
            logger.warning(f"M365 get_mailbox_usage failed: {e}")
            return []

    def get_onedrive_usage(self) -> list:
        """Get OneDrive usage per user. Requires Reports.Read.All.
        Uses the same redirect+CSV pattern as getMailboxUsageDetail."""
        import csv as _csv, io as _io
        try:
            auth_headers = {
                'Authorization': f'Bearer {self._get_token()}',
                'Accept': 'text/csv, application/json, */*',
            }
            url = f"{GRAPH_BASE}/reports/getOneDriveUsageAccountDetail(period='D30')"
            resp = requests.get(url, headers=auth_headers, timeout=30, allow_redirects=False)

            if resp.status_code in (301, 302, 303, 307, 308):
                redirect_url = resp.headers.get('Location', '')
                if redirect_url:
                    resp = requests.get(redirect_url, timeout=60)

            if resp.status_code == 403:
                return [{'permission_error': True, 'required': 'Reports.Read.All'}]
            resp.raise_for_status()

            ct = resp.headers.get('Content-Type', '')
            if 'json' in ct:
                try:
                    data = resp.json()
                    return data if isinstance(data, list) else data.get('value', [])
                except ValueError:
                    pass

            text = resp.content.decode('utf-8-sig', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
            reader = _csv.DictReader(_io.StringIO(text))
            rows = []
            for row in reader:
                row = {k.lstrip('\ufeff').strip(): v for k, v in row.items()}
                used_raw = (row.get('Storage Used (Byte)') or row.get('Storage Used (Bytes)') or
                            row.get('storageUsedInBytes') or '0')
                alloc_raw = (row.get('Storage Allocated (Byte)') or row.get('Storage Allocated (Bytes)') or
                             row.get('storageAllocatedInBytes') or '0')
                try:
                    used_bytes = int(str(used_raw).replace(',', '') or '0')
                except (ValueError, TypeError):
                    used_bytes = 0
                try:
                    alloc_bytes = int(str(alloc_raw).replace(',', '') or '0')
                except (ValueError, TypeError):
                    alloc_bytes = 0
                rows.append({
                    # OneDrive report uses "Owner Display Name" / "Owner Principal Name"
                    'displayName': (row.get('Owner Display Name') or row.get('Display Name') or
                                    row.get('displayName') or row.get('ownerDisplayName') or ''),
                    'userPrincipalName': (row.get('Owner Principal Name') or
                                          row.get('User Principal Name') or
                                          row.get('userPrincipalName') or row.get('ownerPrincipalName') or ''),
                    'siteUrl': row.get('Site URL') or row.get('siteUrl') or '',
                    'storageUsedInBytes': used_bytes,
                    'storageAllocatedInBytes': alloc_bytes,
                    'lastActivityDate': row.get('Last Activity Date') or row.get('lastActivityDate') or '',
                    'fileCount': int(str(row.get('File Count') or row.get('fileCount') or '0').replace(',', '') or '0'),
                    'isDeleted': (row.get('Is Deleted') or '').lower() in ('true', '1', 'yes'),
                })
            return [r for r in rows if not r['isDeleted']]
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code == 403:
                return [{'permission_error': True, 'required': 'Reports.Read.All'}]
            logger.warning(f"M365 get_onedrive_usage failed (HTTP {code}): {e}")
            return []
        except Exception as e:
            logger.warning(f"M365 get_onedrive_usage failed: {e}")
            return []

    def get_teams(self) -> list:
        try:
            return self._get_all('/groups', params={
                '$select': 'displayName,description,visibility,createdDateTime,mail',
                '$filter': "groupTypes/any(c:c eq 'Unified') and resourceProvisioningOptions/Any(x:x eq 'Team')",
                '$top': '999',
            })
        except Exception as e:
            logger.warning(f"M365 get_teams failed: {e}")
            return []

    def _get_sites_list(self, select: str = 'id,displayName,webUrl') -> list:
        """Enumerate SharePoint sites. Tries $search=* first; falls back to root + subsites."""
        # Primary: search-based enumeration (requires ConsistencyLevel + $count)
        try:
            results = self._get_all('/sites', params={
                '$search': '*',
                '$select': select,
                '$count': 'true',
            })
            if results:
                return results
        except Exception as e:
            logger.debug(f"M365 sites $search failed: {e}")

        # Fallback: root site + its direct children
        sites = []
        try:
            root = self._get('/sites/root', params={'$select': select})
            if root.get('id'):
                sites.append(root)
        except Exception:
            pass
        try:
            children = self._get_all('/sites/root/sites', params={'$select': select})
            sites.extend(children)
        except Exception:
            pass
        return sites

    def get_sharepoint_sites(self) -> list:
        try:
            return self._get_sites_list(
                select='displayName,webUrl,description,createdDateTime'
            )
        except Exception as e:
            logger.warning(f"M365 get_sharepoint_sites failed: {e}")
            return []

    def get_roles(self) -> list:
        try:
            roles = self._get_all('/directoryRoles', params={'$select': 'id,displayName,description'})
            result = []
            for role in roles:
                try:
                    members = self._get_all(f"/directoryRoles/{role['id']}/members", params={'$select': 'displayName,userPrincipalName'})
                    if members:
                        role['members'] = members
                        result.append(role)
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.warning(f"M365 get_roles failed: {e}")
            return []

    def get_conditional_access_policies(self) -> list:
        """Get Conditional Access policies. Requires Policy.Read.All permission."""
        try:
            return self._get_all('/identity/conditionalAccess/policies', params={
                '$select': 'displayName,state,createdDateTime,modifiedDateTime,conditions,grantControls',
            })
        except Exception as e:
            logger.warning(f"M365 get_conditional_access_policies failed: {e}")
            return []

    def get_secure_score(self) -> dict:
        """Get latest Secure Score. Requires SecurityEvents.Read.All or SecurityActions.Read.All."""
        try:
            data = self._get('/security/secureScores', params={
                '$top': '1',
                '$select': 'currentScore,maxScore,percentageScore,createdDateTime,controlScores',
            })
            scores = data.get('value', [])
            return scores[0] if scores else {}
        except Exception as e:
            logger.warning(f"M365 get_secure_score failed: {e}")
            return {}

    def get_devices(self) -> list:
        """Get Entra ID registered/joined devices. Requires Device.Read.All."""
        try:
            return self._get_all('/devices', params={
                '$select': 'displayName,operatingSystem,operatingSystemVersion,trustType,approximateLastSignInDateTime,isCompliant,isManaged',
                '$top': '999',
            })
        except Exception as e:
            logger.warning(f"M365 get_devices failed: {e}")
            return []

    def get_sharepoint_usage(self) -> list:
        """Get SharePoint site storage via per-site drive quota. Requires Sites.Read.All."""
        results = []
        try:
            sites = self._get_sites_list(select='id,displayName,webUrl')
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code == 403:
                return [{'permission_error': True, 'required': 'Sites.Read.All'}]
            return []
        except Exception as e:
            logger.warning(f"M365 get_sharepoint_usage (sites) failed: {e}")
            return []
        if not sites:
            return [{'permission_error': False, 'no_sites': True}]

        for site in sites[:50]:  # cap to avoid too many requests
            try:
                drive = self._get(f"/sites/{site['id']}/drive",
                                  params={'$select': 'quota'})
                quota = drive.get('quota') or {}
                results.append({
                    'displayName': site.get('displayName') or '',
                    'siteUrl': site.get('webUrl') or '',
                    'storageUsedInBytes': quota.get('used') or 0,
                    'storageAllocatedInBytes': quota.get('total') or 0,
                    'ownerDisplayName': '',
                })
            except Exception:
                continue
        return results

    def get_defender_alerts(self) -> list:
        """Get recent Defender/security alerts. Requires SecurityAlert.Read.All.
        Note: alerts_v2 does not support $orderby — omit it to avoid 400 errors."""
        try:
            return self._get_all('/security/alerts_v2', params={
                '$select': 'id,title,severity,status,createdDateTime,serviceSource,category,description,assignedTo',
                '$top': '100',
            })
        except requests.exceptions.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else 0
            err_code, err_msg = '', ''
            try:
                err = (resp.json() or {}).get('error', {}) if resp is not None else {}
                err_code = err.get('code') or ''
                err_msg = err.get('message') or ''
            except Exception:
                pass
            logger.warning(f"M365 get_defender_alerts failed (HTTP {code}, code={err_code!r}): {e}")
            if code == 403:
                # Issue #143: a 403 from alerts_v2 is ambiguous. It fires both when
                # the app genuinely lacks SecurityAlert.Read.All / admin consent AND
                # when the permission IS granted but the tenant simply isn't
                # onboarded/licensed for Microsoft Defender (Graph returns 403 there
                # too). Only surface the alarming "add the permission" warning when
                # the error is genuinely an authorization/consent denial — otherwise
                # tell the admin the feature is unavailable so they don't chase a
                # permission they already have.
                blob = f'{err_code} {err_msg}'.lower()
                consent_problem = (
                    'authorization_requestdenied' in blob
                    or 'insufficient privileges' in blob
                    or 'consent' in blob
                    or 'token validation' in blob
                )
                if consent_problem:
                    return [{'permission_error': True, 'required': 'SecurityAlert.Read.All'}]
                return [{'unavailable': True, 'reason': err_msg or (
                    'Microsoft Defender alerts are not available for this tenant '
                    '(it may not be licensed or onboarded for Microsoft Defender).')}]
            return []
        except Exception as e:
            logger.warning(f"M365 get_defender_alerts failed: {e}")
            return []

    def sync(self) -> dict:
        """Pull all data and return structured summary.

        v3.17.489 / issue #133 — Graph reporting endpoints
        (getMailboxUsageDetail, getOneDriveUsageAccountDetail,
        getSharePointSiteUsageDetail) anonymize Display Name + UPN by
        default since MS's 2021 privacy update. The names come back as
        32-char hex hashes (e.g. ``5C807787F0A30D1C3CDBB76DC1ED3CAB``)
        OR blank. The /users endpoint is unaffected. After we collect
        everything, we cross-reference the usage rows against the users
        list and substitute real names where the report rows are
        anonymized.

        Tenant admin can also disable anonymization in
        M365 admin center → Settings → Org settings → Reports →
        uncheck "Display anonymous identifiers instead of names". Code
        de-anonymization makes it work without that change.
        """
        users = self.get_users()
        mailbox_usage = self.get_mailbox_usage()
        onedrive_usage = self.get_onedrive_usage()
        sharepoint_usage = self.get_sharepoint_usage()
        _deanonymize_usage_rows(mailbox_usage, users)
        _deanonymize_usage_rows(onedrive_usage, users)
        _deanonymize_usage_rows(sharepoint_usage, users)

        return {
            'users': users,
            'licenses': self.get_licenses(),
            'shared_mailboxes': self.get_shared_mailboxes(),
            'teams': self.get_teams(),
            'sharepoint_sites': self.get_sharepoint_sites(),
            'roles': self.get_roles(),
            'conditional_access_policies': self.get_conditional_access_policies(),
            'secure_score': self.get_secure_score(),
            'devices': self.get_devices(),
            'sharepoint_usage': sharepoint_usage,
            'defender_alerts': self.get_defender_alerts(),
            'mailbox_usage': mailbox_usage,
            'onedrive_usage': onedrive_usage,
        }


# v3.17.489 — module-level helper (no `self`) so it's testable in isolation.
_ANON_HASH_RE = __import__('re').compile(r'^[0-9A-Fa-f]{32,}$')


def _deanonymize_usage_rows(rows, users):
    """Mutate `rows` in place: where displayName / userPrincipalName look
    anonymized (blank, or 32+ hex chars — MS's hash format), substitute
    real values from `users` joining on whichever field IS real. If we
    can't find a match (e.g. user deleted, only the hash survives in
    the report), leave the row alone and mark `_anonymized=True` so the
    UI can show a hint.

    A row's match strategy:
      1. If UPN is real (contains '@' and isn't a hex hash), look up
         displayName by UPN.
      2. Else if displayName is real, look up UPN by displayName.
      3. Else flag as anonymized — nothing to join on.
    """
    if not rows or not users:
        return
    # Skip permission-error sentinel rows.
    if rows and isinstance(rows[0], dict) and rows[0].get('permission_error'):
        return

    upn_to_name = {}
    name_to_upn = {}
    for u in users:
        upn = (u.get('userPrincipalName') or '').strip()
        name = (u.get('displayName') or '').strip()
        if upn and name:
            upn_to_name[upn.lower()] = name
            name_to_upn[name.lower()] = upn

    for r in rows:
        if not isinstance(r, dict):
            continue
        name = (r.get('displayName') or '').strip()
        upn = (r.get('userPrincipalName') or '').strip()
        name_looks_anon = (not name) or bool(_ANON_HASH_RE.match(name))
        upn_looks_anon = (not upn) or ('@' not in upn) or bool(_ANON_HASH_RE.match(upn))

        if not name_looks_anon and not upn_looks_anon:
            continue  # row is already de-anonymized

        # Strategy 1: real UPN → look up name
        if not upn_looks_anon:
            real_name = upn_to_name.get(upn.lower())
            if real_name:
                r['displayName'] = real_name
                continue

        # Strategy 2: real name → look up UPN
        if not name_looks_anon:
            real_upn = name_to_upn.get(name.lower())
            if real_upn:
                r['userPrincipalName'] = real_upn
                continue

        # Strategy 3: both anonymized — flag for UI hint
        r['_anonymized'] = True
