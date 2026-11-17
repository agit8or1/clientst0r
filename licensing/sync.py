"""Pull license subscriptions into the licensing app.

Microsoft 365 (per customer connection) and Pax8 (a distributor connection
whose vendor-side companies are mapped to customers). Both are idempotent:
a subscription is keyed (customer, source, vendor_subscription_id) and
assignments (subscription, external_id), so a re-sync updates rows and never
duplicates them. Fields an administrator owns (cost, price, notes, renewal
date for Microsoft, product name) are never overwritten by a sync.

Google Workspace is not implemented: the platform has no Google service
account credential structure to build the License Manager call on.
"""
import logging
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone

from core.models import Organization

from .models import ExternalCustomerMap, LicenseAssignment, LicenseSubscription, SoftwareProduct

logger = logging.getLogger('licensing.sync')

M365_STATUS = {
    'Enabled': 'active', 'Warning': 'suspended', 'Suspended': 'suspended',
    'LockedOut': 'suspended', 'Deleted': 'expired',
}
PAX8_STATUS = {
    'Active': 'active', 'Trial': 'trial', 'Cancelled': 'cancelled', 'Converted': 'cancelled',
    'Expired': 'expired', 'PendingCancel': 'active', 'PendingManual': 'pending',
    'PendingAutomated': 'pending', 'PendingActivation': 'pending', 'WaitingForDetails': 'pending',
}
PAX8_BILLING = {
    'monthly': 'monthly', 'annual': 'annual', '2-year': 'biennial', '3-year': 'triennial',
    'one-time': 'one_time', 'trial': 'monthly', 'activation': 'one_time',
}


@dataclass
class SyncResult:
    source: str
    connection: str = ''
    created: int = 0
    updated: int = 0
    assignments_created: int = 0
    assignments_removed: int = 0
    skipped: str = ''
    unmapped: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors

    def __str__(self):
        bits = [f'{self.source} {self.connection}'.strip()]
        if self.skipped:
            bits.append(f'skipped ({self.skipped})')
        else:
            bits.append(f'{self.created} created, {self.updated} updated, '
                        f'{self.assignments_created} assignments added, {self.assignments_removed} removed')
        if self.unmapped:
            bits.append(f'{len(self.unmapped)} unmapped vendor customer(s)')
        if self.errors:
            bits.append('errors: ' + '; '.join(self.errors))
        return ' - '.join(bits)


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _product(vendor, sku, name, license_type='subscription'):
    product, _ = SoftwareProduct.objects.get_or_create(
        vendor=vendor, vendor_sku=sku,
        defaults={'name': name or sku, 'license_type': license_type})
    return product


# --------------------------------------------------------------------------
# Microsoft 365
# --------------------------------------------------------------------------

def _m365_provider(conn):
    from integrations.providers.m365 import M365Provider
    creds = conn.get_credentials()
    return M365Provider(conn.tenant_id, creds.get('client_id', ''), creds.get('client_secret', ''))


def sync_m365_connection(conn, *, with_assignments=True, provider=None) -> SyncResult:
    """subscribedSkus -> LicenseSubscription(source=m365); optionally the
    per-user assignedLicenses -> LicenseAssignment."""
    result = SyncResult('m365', conn.name)
    if conn.organization_id is None:
        result.skipped = "platform-owned connection: it is the MSP's own tenant, not a customer's"
        return result
    org = conn.organization
    now = timezone.now()
    provider = provider or _m365_provider(conn)
    try:
        skus = provider._get_all('/subscribedSkus', params={
            '$select': 'skuId,skuPartNumber,consumedUnits,prepaidUnits,capabilityStatus'})
        users = provider.get_licensed_users() if with_assignments else None
    except Exception as exc:
        msg = f'{type(exc).__name__}: {exc}'[:500]
        result.errors.append(msg)
        LicenseSubscription.objects.filter(organization=org, source='m365').update(sync_error=msg)
        return result

    by_sku = {}
    for u in users or []:
        for lic in u.get('assignedLicenses') or []:
            by_sku.setdefault(str(lic.get('skuId', '')).lower(), []).append(u)

    seen = set()
    with transaction.atomic():
        for sku in skus:
            sku_id = str(sku.get('skuId') or '')
            if not sku_id:
                continue
            seen.add(sku_id)
            part = sku.get('skuPartNumber') or sku_id
            product = _product('Microsoft', part, part)
            sub, created = LicenseSubscription.objects.get_or_create(
                organization=org, source='m365', vendor_subscription_id=sku_id,
                defaults={'product': product, 'quantity_purchased': 0})
            sub.quantity_purchased = int((sku.get('prepaidUnits') or {}).get('enabled') or 0)
            sub.vendor_consumed = int(sku.get('consumedUnits') or 0)
            sub.status = M365_STATUS.get(sku.get('capabilityStatus'), 'active')
            sub.last_synced_at = now
            sub.sync_error = ''
            sub.save()
            result.created += created
            result.updated += not created
            if with_assignments:
                _reconcile_m365_assignments(sub, by_sku.get(sku_id.lower(), []), result)
        # SKUs the tenant no longer has are no longer live.
        LicenseSubscription.objects.filter(organization=org, source='m365').exclude(
            vendor_subscription_id__in=seen).exclude(status='expired').update(
            status='expired', last_synced_at=now, sync_error='')
    return result


def _reconcile_m365_assignments(sub, users, result):
    from assets.models import Contact
    existing = {a.external_id: a for a in sub.assignments.exclude(external_id='')}
    wanted = {}
    for u in users:
        uid = str(u.get('id') or '')
        if uid:
            wanted[uid] = u
    for uid, user in wanted.items():
        label = user.get('userPrincipalName') or user.get('mail') or user.get('displayName') or uid
        row = existing.get(uid)
        if row is None:
            email = user.get('mail') or user.get('userPrincipalName') or ''
            contact = (Contact.objects.filter(organization=sub.organization, email__iexact=email).first()
                       if email else None)
            LicenseAssignment.objects.create(subscription=sub, assigned_to=label, external_id=uid,
                                             contact=contact)
            result.assignments_created += 1
        elif row.assigned_to != label:
            row.assigned_to = label
            row.save(update_fields=['assigned_to', 'updated_at'])
    gone = [a.pk for uid, a in existing.items() if uid not in wanted]
    if gone:
        LicenseAssignment.objects.filter(pk__in=gone).delete()
        result.assignments_removed += len(gone)


# --------------------------------------------------------------------------
# Pax8
# --------------------------------------------------------------------------

def _pax8_map(provider, rows, result):
    """{companyId: Organization} for the companies in `rows`; unmapped ids
    are matched to a customer of exactly the same name (when unambiguous)
    and recorded, otherwise reported in `result.unmapped`."""
    ids = {str(r.get('companyId')) for r in rows if r.get('companyId')}
    mapped = {m.external_id: m.organization for m in
              ExternalCustomerMap.objects.filter(source='pax8', external_id__in=ids).select_related('organization')}
    missing = ids - set(mapped)
    if missing:
        try:
            names = {str(c.get('id')): c.get('name') or '' for c in provider.list_companies()}
        except Exception as exc:
            names = {}
            result.errors.append(f'company list failed: {exc}')
        for cid in sorted(missing):
            name = names.get(cid, '')
            matches = list(Organization.objects.filter(name__iexact=name, is_active=True)[:2]) if name else []
            if len(matches) == 1:
                ExternalCustomerMap.objects.get_or_create(
                    source='pax8', external_id=cid,
                    defaults={'organization': matches[0], 'external_name': name})
                mapped[cid] = matches[0]
            else:
                result.unmapped.append(f'{name or "?"} ({cid})')
    return mapped


def sync_pax8_connection(conn, *, provider=None) -> SyncResult:
    result = SyncResult('pax8', conn.name)
    if provider is None:
        from integrations.providers.distributors import get_distributor_provider
        provider = get_distributor_provider(conn)
    if provider is None:
        result.skipped = 'no adapter'
        return result
    now = timezone.now()
    try:
        rows = provider.list_subscriptions()
    except Exception as exc:
        result.errors.append(f'{type(exc).__name__}: {exc}'[:500])
        return result
    orgs = _pax8_map(provider, rows, result)
    product_cache = {}
    with transaction.atomic():
        for row in rows:
            org = orgs.get(str(row.get('companyId')))
            sub_id = str(row.get('id') or '')
            if org is None or not sub_id:
                continue
            pid = str(row.get('productId') or '')
            if pid not in product_cache:
                product = SoftwareProduct.objects.filter(vendor_sku=pid).first() if pid else None
                if product is None and pid:
                    info = provider.get_product(pid) if hasattr(provider, 'get_product') else {}
                    product = _product(info.get('vendorName') or 'Pax8', pid,
                                       info.get('name') or f'Pax8 product {pid[:8]}')
                product_cache[pid] = product
            product = product_cache[pid]
            if product is None:
                continue
            sub, created = LicenseSubscription.objects.get_or_create(
                organization=org, source='pax8', vendor_subscription_id=sub_id,
                defaults={'product': product})
            sub.quantity_purchased = int(row.get('quantity') or 0)
            sub.status = PAX8_STATUS.get(row.get('status'), 'active')
            term = str(row.get('billingTerm') or '').lower()
            sub.billing_frequency = PAX8_BILLING.get(term, sub.billing_frequency)
            sub.term_start = _parse_date(row.get('startDate')) or sub.term_start
            sub.renewal_date = _parse_date(row.get('endDate')) or sub.renewal_date
            cost = row.get('partnerCost', row.get('price'))
            if cost not in (None, ''):
                sub.unit_cost = cost
            sub.last_synced_at = now
            sub.sync_error = ''
            sub.save()
            result.created += created
            result.updated += not created
    return result


# --------------------------------------------------------------------------

def sync_all(organization=None, *, with_assignments=True):
    """Every active Microsoft 365 and Pax8 connection (optionally only
    `organization`'s Microsoft 365 connection). Returns [SyncResult]."""
    from integrations.models import DistributorConnection, M365Connection
    results = []
    m365 = M365Connection.objects.filter(is_active=True)
    if organization is not None:
        m365 = m365.filter(organization=organization)
    for conn in m365:
        try:
            results.append(sync_m365_connection(conn, with_assignments=with_assignments))
        except Exception as exc:  # one broken connection never stops the rest
            logger.exception('m365 license sync failed for connection %s', conn.pk)
            r = SyncResult('m365', conn.name)
            r.errors.append(str(exc)[:500])
            results.append(r)
    if organization is None:
        for conn in DistributorConnection.objects.filter(is_active=True, sync_enabled=True,
                                                         provider_type='pax8'):
            try:
                results.append(sync_pax8_connection(conn))
            except Exception as exc:
                logger.exception('pax8 license sync failed for connection %s', conn.pk)
                r = SyncResult('pax8', conn.name)
                r.errors.append(str(exc)[:500])
                results.append(r)
    return results
