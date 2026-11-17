"""Sales tax settings, rates, categories, customer exemptions and the
per-document actions (preview, manual override, line categories)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from audit.models import AuditLog
from core.middleware import get_request_organization
from core.models import Organization

from . import services
from .models import (
    CustomerTaxExemption, LineTaxCategory, ManualTaxRate, TaxCalculation, TaxCategory, TaxSettings,
)

PERM = 'manage_tax_settings'


# --- scope + permission -----------------------------------------------------------------

def _may_platform(user) -> bool:
    if user.is_superuser:
        return True
    from accounts.permission_utils import is_msp_staff, user_has_perm
    return bool(is_msp_staff(user) and user_has_perm(user, PERM))


def _scope(request):
    """Tax configuration is MSP-wide (one MSP per install): always the
    install-wide rows, whichever customer is selected. 403 without
    manage_tax_settings (MSP staff / superusers only)."""
    if not _may_platform(request.user):
        raise PermissionDenied("Tax settings need the 'manage_tax_settings' permission.")
    return None, 'MSP-wide (every customer)'


def _scoped(qs, org=None):
    return qs.filter(organization__isnull=True)


def _audit(request, org, obj_type, obj, description, action='update'):
    AuditLog.log(user=request.user, action=action, organization=org, object_type=obj_type,
                 object_id=getattr(obj, 'pk', None), object_repr=str(obj)[:200], description=description[:1000],
                 ip_address=request.META.get('REMOTE_ADDR'), path=request.path)


def _decimal(value, default=None):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return default


def _date(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return 'bad'


def _form_values(item, post, fields):
    """Field values for re-rendering a form: the POST (after an error), else
    the saved row, else blank."""
    out = {}
    for f in fields:
        if post is not None and f in post:
            out[f] = post.get(f)
        else:
            v = getattr(item, f, '') if item is not None else ''
            out[f] = '' if v is None else v
    return out


RATE_FIELDS = ('name', 'rate', 'country', 'state', 'county', 'city', 'zip_pattern')
CATEGORY_FIELDS = ('code', 'name')


def _regions(value):
    return sorted({r.strip().upper() for r in (value or '').replace(';', ',').split(',') if r.strip()})


# --- settings ------------------------------------------------------------------------

CRED_FIELDS = {
    'avalara': ('account_id', 'license_key', 'company_code'),
    'taxjar': ('api_key',),
}
SECRET_FIELDS = {'license_key', 'api_key'}


@login_required
@require_http_methods(['GET', 'POST'])
def settings_view(request):
    from integrations.models import TaxConnection
    org, scope_label = _scope(request)
    row = _scoped(TaxSettings.objects.select_related('connection'), org).order_by('pk').first()
    inherited = None

    if request.method == 'POST':
        creating = row is None
        if row is None:
            row = TaxSettings(organization=org)
        mode = request.POST.get('mode', row.mode)
        if mode not in dict(TaxSettings.MODES):
            messages.error(request, 'Unknown tax mode.')
            return redirect('tax:settings')
        before = row.mode
        row.mode = mode
        auth = request.POST.get('authoritative_system', row.authoritative_system)
        if auth in dict(TaxSettings.AUTHORITY_CHOICES):
            row.authoritative_system = auth
        row.authority_note = (request.POST.get('authority_note') or '').strip()
        row.sandbox = request.POST.get('sandbox') == 'on'
        row.labor_taxable = request.POST.get('labor_taxable') == 'on'
        row.shipping_taxable = request.POST.get('shipping_taxable') == 'on'
        row.nexus_regions = _regions(request.POST.get('nexus_regions'))
        for f in ('origin_line1', 'origin_city', 'origin_region', 'origin_postal_code'):
            setattr(row, f, (request.POST.get(f) or '').strip()[:row._meta.get_field(f).max_length])
        row.origin_region = row.origin_region.upper()
        row.origin_country = ((request.POST.get('origin_country') or 'US').strip().upper() or 'US')[:2]

        if mode in TaxSettings.PROVIDER_MODES:
            conn = row.connection if (row.connection and row.connection.provider_type == mode) else None
            if conn is None:
                conn = _scoped(TaxConnection.objects.filter(provider_type=mode), org).first()
            if conn is None:
                conn = TaxConnection(organization=org, provider_type=mode,
                                     name=f'Sales tax ({dict(TaxSettings.MODES)[mode]})')
            creds = conn.get_credentials() if conn.pk else {}
            for key in CRED_FIELDS[mode]:
                val = (request.POST.get(f'{mode}_{key}') or '').strip()
                if val:  # blank keeps the stored value (secrets are never echoed back)
                    creds[key] = val
            conn.set_credentials(creds)
            conn.is_active = True
            conn.save()
            row.connection = conn
        row.save()
        _audit(request, org, 'tax.TaxSettings', row,
               f'{"Created" if creating else "Updated"} tax settings ({scope_label}): mode {before} -> {mode}',
               action='create' if creating else 'update')
        messages.success(request, 'Tax settings saved.')
        return redirect('tax:settings')

    conn = row.connection if row else None
    creds = conn.get_credentials() if conn else {}
    return render(request, 'tax/settings.html', {
        'row': row, 'inherited': inherited, 'scope_org': org, 'scope_label': scope_label,
        'modes': TaxSettings.MODES, 'authority_choices': TaxSettings.AUTHORITY_CHOICES,
        'current_mode': row.mode if row else (inherited.mode if inherited else TaxSettings.MODE_FLAT),
        'connection': conn,
        'cred_display': {k: ('********' if k in SECRET_FIELDS and v else v) for k, v in creds.items()},
        'rates': _scoped(ManualTaxRate.objects.prefetch_related('applies_to'), org),
        'categories': _scoped(TaxCategory.objects.all(), org),
        'recent': _scoped(TaxCalculation.objects.select_related('created_by'), org)[:15],
    })


@login_required
@require_POST
def test_connection(request):
    from integrations.providers.tax import get_tax_provider
    org, _label = _scope(request)
    row = _scoped(TaxSettings.objects.select_related('connection'), org).first()
    if row is None or row.connection is None or not row.is_provider_mode:
        messages.error(request, 'Choose Avalara or TaxJar and save credentials first.')
        return redirect('tax:settings')
    try:
        ok, msg = get_tax_provider(row.connection, sandbox=row.sandbox).test_connection()
    except Exception as exc:
        ok, msg = False, exc.__class__.__name__
    row.connection.last_error = '' if ok else msg[:1000]
    row.connection.save(update_fields=['last_error'])
    (messages.success if ok else messages.error)(request, f'Connection test: {msg}')
    return redirect('tax:settings')


# --- manual rates ---------------------------------------------------------------------

@login_required
@require_http_methods(['GET', 'POST'])
def rate_form(request, pk=None):
    org, scope_label = _scope(request)
    item = get_object_or_404(_scoped(ManualTaxRate.objects.all(), org), pk=pk) if pk else None
    cats = TaxCategory.objects.filter(organization__isnull=True)
    if request.method == 'POST':
        errors = []
        name = (request.POST.get('name') or '').strip()
        rate = _decimal(request.POST.get('rate'))
        if not name:
            errors.append('A name is required.')
        if rate is None or rate < 0 or rate > 1:
            errors.append('The rate is a fraction between 0 and 1 (0.0875 for 8.75%).')
        eff_from, eff_to = _date(request.POST.get('effective_from')), _date(request.POST.get('effective_to'))
        if 'bad' in (eff_from, eff_to):
            errors.append('Dates are YYYY-MM-DD.')
        elif eff_from and eff_to and eff_to < eff_from:
            errors.append('The end date is before the start date.')
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'tax/rate_form.html', {
                'item': item, 'categories': cats, 'scope_label': scope_label,
                'v': _form_values(item, request.POST, RATE_FIELDS)})
        creating = item is None
        item = item or ManualTaxRate(organization=org)
        item.name = name[:120]
        item.rate = rate
        item.country = ((request.POST.get('country') or 'US').strip().upper() or 'US')[:2]
        item.state = (request.POST.get('state') or '').strip().upper()[:50]
        item.county = (request.POST.get('county') or '').strip()[:100]
        item.city = (request.POST.get('city') or '').strip()[:100]
        item.zip_pattern = (request.POST.get('zip_pattern') or '').strip()[:20]
        item.effective_from, item.effective_to = eff_from, eff_to
        labor = request.POST.get('labor_taxable', '')
        item.labor_taxable = {'yes': True, 'no': False}.get(labor)
        item.is_active = request.POST.get('is_active', 'on') == 'on'
        item.save()
        allowed = {c.pk for c in cats}
        item.applies_to.set([int(c) for c in request.POST.getlist('applies_to')
                             if c.isdigit() and int(c) in allowed])
        _audit(request, org, 'tax.ManualTaxRate', item,
               f'{"Created" if creating else "Updated"} manual tax rate {item.name} = {item.rate} ({scope_label})',
               action='create' if creating else 'update')
        messages.success(request, f'Saved rate "{item.name}".')
        return redirect('tax:settings')
    return render(request, 'tax/rate_form.html', {'item': item, 'categories': cats, 'scope_label': scope_label,
                                                  'v': _form_values(item, None, RATE_FIELDS)})


@login_required
@require_POST
def rate_delete(request, pk):
    org, scope_label = _scope(request)
    item = get_object_or_404(_scoped(ManualTaxRate.objects.all(), org), pk=pk)
    _audit(request, org, 'tax.ManualTaxRate', item, f'Deleted manual tax rate {item.name} ({scope_label})',
           action='delete')
    item.delete()
    messages.success(request, 'Rate deleted.')
    return redirect('tax:settings')


# --- categories -------------------------------------------------------------------------

@login_required
@require_http_methods(['GET', 'POST'])
def category_form(request, pk=None):
    org, scope_label = _scope(request)
    item = get_object_or_404(_scoped(TaxCategory.objects.all(), org), pk=pk) if pk else None
    if request.method == 'POST':
        from django.utils.text import slugify
        code = slugify(request.POST.get('code') or '')[:50]
        name = (request.POST.get('name') or '').strip()[:120]
        kind = request.POST.get('kind', 'goods')
        if not code or not name or kind not in dict(TaxCategory.KIND_CHOICES):
            messages.error(request, 'Code, name and a valid kind are required.')
            return render(request, 'tax/category_form.html', {'item': item, 'kinds': TaxCategory.KIND_CHOICES,
                                                              'scope_label': scope_label,
                                                              'v': _form_values(item, request.POST, CATEGORY_FIELDS)})
        clash = _scoped(TaxCategory.objects.filter(code=code), org)
        if item is not None:
            clash = clash.exclude(pk=item.pk)
        if clash.exists():
            messages.error(request, f'A category with code "{code}" already exists here.')
            return render(request, 'tax/category_form.html', {'item': item, 'kinds': TaxCategory.KIND_CHOICES,
                                                              'scope_label': scope_label,
                                                              'v': _form_values(item, request.POST, CATEGORY_FIELDS)})
        creating = item is None
        item = item or TaxCategory(organization=org)
        item.code, item.name, item.kind = code, name, kind
        item.taxable = request.POST.get('taxable') == 'on'
        item.is_default = request.POST.get('is_default') == 'on'
        for f in ('avalara_tax_code', 'taxjar_product_tax_code', 'qbo_tax_code_id', 'xero_tax_type'):
            setattr(item, f, (request.POST.get(f) or '').strip()[:50])
        item.save()
        if item.is_default:
            _scoped(TaxCategory.objects.exclude(pk=item.pk), org).update(is_default=False)
        _audit(request, org, 'tax.TaxCategory', item,
               f'{"Created" if creating else "Updated"} tax category {item.code} ({scope_label})',
               action='create' if creating else 'update')
        messages.success(request, f'Saved category "{item.name}".')
        return redirect('tax:settings')
    return render(request, 'tax/category_form.html', {'item': item, 'kinds': TaxCategory.KIND_CHOICES,
                                                      'scope_label': scope_label,
                                                      'v': _form_values(item, None, CATEGORY_FIELDS)})


@login_required
@require_POST
def category_delete(request, pk):
    org, scope_label = _scope(request)
    item = get_object_or_404(_scoped(TaxCategory.objects.all(), org), pk=pk)
    _audit(request, org, 'tax.TaxCategory', item, f'Deleted tax category {item.code} ({scope_label})',
           action='delete')
    item.delete()
    messages.success(request, 'Category deleted.')
    return redirect('tax:settings')


# --- customer exemptions -------------------------------------------------------------------

def _client_for_exemptions(request, org_id):
    from core.tenancy import accessible_org_ids
    client = get_object_or_404(Organization, pk=org_id)
    allowed = accessible_org_ids(request)
    if allowed is not None and client.pk not in allowed:
        raise Http404
    if not services.may_manage_tax(request.user, client):
        raise PermissionDenied("Managing tax exemptions needs the 'manage_tax_settings' permission.")
    return client


def _store_certificate(request, client, upload):
    """files.Attachment (entity_type 'tax_exemption'); same checks as the
    attachment upload (size, extension, magic bytes)."""
    import mimetypes
    from files import upload_rules
    from files.models import Attachment
    content = upload.read()
    upload.seek(0)
    problem = upload_rules.check_file(upload.name, content, getattr(upload, 'content_type', '') or '')
    if problem:
        return None, problem
    att = Attachment(organization=client, entity_type='tax_exemption', entity_id=0, file=upload,
                     original_filename=upload.name[:255], file_size=upload.size,
                     content_type=mimetypes.guess_type(upload.name)[0] or 'application/octet-stream',
                     uploaded_by=request.user, description='Sales tax exemption certificate')
    att.save()
    return att, ''


@login_required
@require_http_methods(['GET', 'POST'])
def client_exemptions(request, org_id):
    client = _client_for_exemptions(request, org_id)
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        number = (request.POST.get('certificate_number') or '').strip()[:100]
        valid_from, valid_to = _date(request.POST.get('valid_from')), _date(request.POST.get('valid_to'))
        errors = []
        if reason not in dict(CustomerTaxExemption.REASONS):
            errors.append('Pick a reason.')
        if not number:
            errors.append('A certificate number is required.')
        if 'bad' in (valid_from, valid_to):
            errors.append('Dates are YYYY-MM-DD.')
        elif valid_from and valid_to and valid_to < valid_from:
            errors.append('The end date is before the start date.')
        att = None
        if not errors and request.FILES.get('certificate'):
            att, problem = _store_certificate(request, client, request.FILES['certificate'])
            if problem:
                errors.append(f'Certificate file refused: {problem}')
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            ex = CustomerTaxExemption.objects.create(
                client=client, reason=reason, certificate_number=number, certificate=att,
                jurisdictions=_regions(request.POST.get('jurisdictions')), valid_from=valid_from,
                valid_to=valid_to, notes=(request.POST.get('notes') or '').strip(), created_by=request.user)
            if att is not None:
                att.entity_id = ex.pk
                att.save(update_fields=['entity_id'])
            _audit(request, client, 'tax.CustomerTaxExemption', ex,
                   f'Added tax exemption {ex.get_reason_display()} #{number} for {client.name} (unverified)',
                   action='create')
            messages.success(request, 'Exemption added. Verify the certificate to make it apply.')
        return redirect('tax:client_exemptions', org_id=client.pk)
    return render(request, 'tax/client_exemptions.html', {
        'client': client, 'reasons': CustomerTaxExemption.REASONS,
        'exemptions': CustomerTaxExemption.objects.filter(client=client).select_related('verified_by',
                                                                                       'certificate'),
    })


@login_required
@require_POST
def exemption_action(request, org_id, pk, action):
    client = _client_for_exemptions(request, org_id)
    ex = get_object_or_404(CustomerTaxExemption, pk=pk, client=client)
    if action == 'verify':
        ex.verified_by, ex.verified_at = request.user, timezone.now()
        ex.save(update_fields=['verified_by', 'verified_at', 'updated_at'])
        desc = f'Verified tax exemption #{ex.certificate_number} for {client.name}'
    elif action == 'deactivate':
        ex.is_active = False
        ex.save(update_fields=['is_active', 'updated_at'])
        desc = f'Deactivated tax exemption #{ex.certificate_number} for {client.name}'
    elif action == 'activate':
        ex.is_active = True
        ex.save(update_fields=['is_active', 'updated_at'])
        desc = f'Reactivated tax exemption #{ex.certificate_number} for {client.name}'
    else:
        raise Http404
    _audit(request, client, 'tax.CustomerTaxExemption', ex, desc)
    messages.success(request, desc + '.')
    return redirect('tax:client_exemptions', org_id=client.pk)


@login_required
def exemption_certificate(request, org_id, pk):
    from core.media_views import resolve_under_media_root, stream_file
    client = _client_for_exemptions(request, org_id)
    ex = get_object_or_404(CustomerTaxExemption, pk=pk, client=client)
    att = ex.certificate
    if att is None or not att.file or att.organization_id != client.pk:
        raise Http404
    return stream_file(request, resolve_under_media_root(att.file.name), att.file.name, att.original_filename)


# --- document actions -----------------------------------------------------------------------

def _document(request, doc_type, pk):
    from accounts.permission_utils import user_has_org_perm
    from psa.models import Invoice, Quote
    model, flag = {'quote': (Quote, 'crm_manage_pipeline'),
                   'invoice': (Invoice, 'billing_send_invoices')}.get(doc_type, (None, None))
    if model is None:
        raise Http404
    doc = get_object_or_404(model.objects.select_related('organization', 'client_org'), pk=pk)
    org = get_request_organization(request)
    if org is not None and doc.organization_id != org.pk:
        raise Http404
    if not (user_has_org_perm(request.user, doc.organization_id, flag)
            or user_has_org_perm(request.user, doc.client_org_id, flag)):
        raise PermissionDenied(f"Your role does not include '{flag}' for this customer.")
    return doc


def _detail(doc_type, doc):
    return redirect(f'psa:{doc_type}_detail', pk=doc.pk)


@login_required
@require_POST
def preview(request, doc_type, pk):
    doc = _document(request, doc_type, pk)
    outcome = services.calculate_tax(doc, user=request.user, purpose='preview')
    if outcome.blocked:
        messages.error(request, f'Tax preview failed: {outcome.message} Nothing was changed.')
    else:
        applied = services._document_applies(doc)
        messages.success(request, f'Tax preview: {outcome.total_tax} ({outcome.message})'
                                  + ('' if applied else ' Recorded only: this document is no longer a draft.'))
    return _detail(doc_type, doc)


@login_required
@require_POST
def override(request, doc_type, pk):
    doc = _document(request, doc_type, pk)
    try:
        calc = services.apply_manual_override(doc, request.user, request.POST.get('amount'),
                                              request.POST.get('reason'), request=request)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Manual tax override recorded: {calc.total_tax}. It is in the audit log.')
    return _detail(doc_type, doc)


@login_required
@require_POST
def set_line_categories(request, doc_type, pk):
    doc = _document(request, doc_type, pk)
    if not services._document_applies(doc):
        messages.error(request, 'Line tax categories can only change on a draft.')
        return _detail(doc_type, doc)
    cats = {str(c.pk): c for c in services.categories_for(doc.organization_id).values()}
    line_type = services.line_type_for(doc)
    changed = 0
    for li in doc.line_items.all():
        val = request.POST.get(f'cat_{li.pk}')
        if val is None:
            continue
        if val == '':
            changed += LineTaxCategory.objects.filter(line_type=line_type, line_id=li.pk).delete()[0]
        elif val in cats:
            LineTaxCategory.objects.update_or_create(line_type=line_type, line_id=li.pk,
                                                     defaults={'category': cats[val]})
            changed += 1
    messages.success(request, f'Line tax categories saved ({changed}). Preview tax to recalculate.')
    return _detail(doc_type, doc)
