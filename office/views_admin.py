"""Settings → Integrations → Office Documents (superusers), the organization
policy page (organization admins), templates and quarantine."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.middleware import get_request_organization

from . import audit, diagnostics, formats, install_guidance, policy, storage, targets
from .forms import (EditorInstanceForm, OfficeSettingsForm, OrganizationPolicyForm,
                    TemplateUploadForm)
from .models import (EditorInstance, EditSession, ManagedOfficeService, OfficeFile, OfficeSettings,
                     QuarantinedSave)
from .providers import all_providers


def is_superuser(user):
    return user.is_authenticated and user.is_superuser


superuser_required = user_passes_test(is_superuser)

_SETTINGS_FIELDS = ('enabled_providers', 'default_instance_id', 'allow_org_override',
                    'quarantine_retention_days', 'session_ttl_minutes', 'session_max_hours',
                    'token_ttl_minutes')
_INSTANCE_AUDIT_FIELDS = ('provider', 'name', 'mode', 'browser_url', 'internal_url',
                          'callback_base_url', 'max_file_mb', 'connect_timeout_s',
                          'request_timeout_s', 'conversion_timeout_s', 'enabled', 'shared')


@login_required
@superuser_required
@require_http_methods(['GET', 'POST'])
def settings_index(request):
    obj = OfficeSettings.get()
    before = {f: getattr(obj, f) for f in _SETTINGS_FIELDS}
    form = OfficeSettingsForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.updated_by = request.user
        obj.save()
        after = {f: getattr(obj, f) for f in _SETTINGS_FIELDS}
        changed = {f: [str(before[f]), str(after[f])] for f in _SETTINGS_FIELDS if before[f] != after[f]}
        audit.log('settings_change', user=request.user, request=request,
                  object_type='office.settings', object_id=1, object_repr='Office settings',
                  description='Changed Office settings: ' + (', '.join(changed) or 'no changes'),
                  extra={'changed': changed})
        messages.success(request, 'Office settings saved.')
        return redirect('office:settings')
    instances = EditorInstance.objects.annotate(
        live_sessions=Count('sessions', filter=Q(sessions__state__in=EditSession.LIVE_STATES)))
    return render(request, 'office/settings/index.html', {
        'form': form, 'instances': instances, 'providers': all_providers(),
        'quarantine_count': QuarantinedSave.objects.count(),
        'managed_service': ManagedOfficeService.get(),
        'active_page': 'office_documents',
    })


@login_required
@superuser_required
@require_http_methods(['GET', 'POST'])
def instance_edit(request, pk=None):
    instance = get_object_or_404(EditorInstance, pk=pk) if pk else None
    if instance is not None and instance.mode == 'managed_local':
        messages.info(request, 'This editor is managed by clientst0r: its addresses and secret come '
                               'from the server configuration.')
        return redirect('office:managed')
    before = {f: getattr(instance, f) for f in _INSTANCE_AUDIT_FIELDS} if instance else {}
    old_secret = instance.shared_secret if instance else ''
    old_ca = instance.ca_bundle if instance else ''
    form = EditorInstanceForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.created_by = request.user
        connection_changed = any(before.get(f) != getattr(obj, f) for f in
                                 ('provider', 'browser_url', 'internal_url', 'callback_base_url')) \
            or obj.shared_secret != old_secret or obj.ca_bundle != old_ca
        if connection_changed:
            # A changed endpoint or secret has not been checked yet.
            obj.health_status, obj.health_detail, obj.last_check_at = 'unknown', '', None
        obj.save()
        form.save_m2m()
        changed = [f for f in _INSTANCE_AUDIT_FIELDS if before.get(f) != getattr(obj, f)]
        if obj.shared_secret != old_secret:
            changed.append('shared_secret (value not logged)')
        if obj.ca_bundle != old_ca:
            changed.append('ca_bundle')
        audit.log('settings_change', user=request.user, request=request,
                  object_type='office.instance', object_id=obj.pk, object_repr=obj.name,
                  description=f'{"Updated" if instance else "Added"} Office editor instance '
                              f'{obj.name}: {", ".join(changed) or "no changes"}',
                  extra={'changed': changed})
        messages.success(request, f'Saved {obj.name}. Run its health check before enabling it.'
                         if connection_changed else f'Saved {obj.name}.')
        return redirect('office:instance_diagnostics', pk=obj.pk)
    return render(request, 'office/settings/instance_form.html', {
        'form': form, 'instance': instance, 'active_page': 'office_documents',
    })


@login_required
@superuser_required
@require_http_methods(['GET', 'POST'])
def instance_delete(request, pk):
    instance = get_object_or_404(EditorInstance, pk=pk)
    if instance.mode == 'managed_local':
        messages.info(request, 'Use Uninstall on the Managed Local ONLYOFFICE page; it drains '
                               'sessions first and keeps documents and editor data.')
        return redirect('office:managed')
    live = instance.sessions.filter(state__in=EditSession.LIVE_STATES).count()
    if request.method == 'POST':
        from . import sessions as session_api
        for s in instance.sessions.filter(state__in=EditSession.LIVE_STATES):
            session_api.revoke(s, 'editor instance removed')
        name = instance.name
        instance.delete()
        audit.log('settings_change', user=request.user, request=request,
                  object_type='office.instance', object_id=pk, object_repr=name,
                  description=f'Removed Office editor instance {name} '
                              f'({live} open session(s) ended)')
        messages.success(request, f'Removed {name}. Documents and their revisions are kept.')
        return redirect('office:settings')
    return render(request, 'office/settings/instance_confirm_delete.html', {
        'instance': instance, 'live_sessions': live, 'active_page': 'office_documents',
    })


@login_required
@superuser_required
@require_POST
def instance_health(request, pk):
    instance = get_object_or_404(EditorInstance, pk=pk)
    result = diagnostics.run_health_check(instance, user=request.user, request=request)
    (messages.success if result.status == 'ok' else messages.warning)(
        request, f'Health check: {instance.get_health_status_display()}. {result.detail}'[:500])
    return redirect('office:instance_diagnostics', pk=pk)


@login_required
@superuser_required
@require_http_methods(['GET', 'POST'])
def instance_diagnostics(request, pk):
    instance = get_object_or_404(EditorInstance, pk=pk)
    checks = None
    round_trip = None
    if request.method == 'POST':
        if request.POST.get('action') == 'round_trip':
            round_trip = diagnostics.run_round_trip(instance, request.user, request=request)
        else:
            checks = diagnostics.run_diagnostics(instance, user=request.user, request=request)
    from .providers import Capabilities
    return render(request, 'office/settings/diagnostics.html', {
        'instance': instance, 'checks': checks, 'round_trip': round_trip,
        'caps': Capabilities.from_json(instance.capabilities).to_json(),
        'caps_export_pdf': Capabilities.from_json(instance.capabilities).export_pdf,
        'active_page': 'office_documents',
    })


@login_required
@superuser_required
def install_page(request):
    instance = None
    if request.GET.get('instance', '').isdigit():
        instance = EditorInstance.objects.filter(pk=int(request.GET['instance'])).first()
    guidance = install_guidance.build(
        request.GET.get('provider') or (instance.provider if instance else 'onlyoffice'),
        request.GET.get('mode') or (instance.mode if instance else 'separate_server'),
        instance=instance, editor_host=request.GET.get('editor_host', ''),
        app_url=request.build_absolute_uri('/'), edition=request.GET.get('edition', ''),
        tls=request.GET.get('tls', ''), private_ca=request.GET.get('private_ca') == '1')
    return render(request, 'office/settings/install.html', {
        'guidance': guidance, 'instance': instance, 'instances': EditorInstance.objects.all(),
        'providers': install_guidance.PROVIDERS, 'modes': install_guidance.MODES,
        'editions': install_guidance.EDITIONS, 'tls_modes': install_guidance.TLS_MODES,
        'active_page': 'office_documents',
    })


@login_required
@superuser_required
def quarantine_list(request):
    return render(request, 'office/settings/quarantine.html', {
        'items': QuarantinedSave.objects.select_related('organization', 'user')[:500],
        'retention_days': OfficeSettings.get().quarantine_retention_days,
        'active_page': 'office_documents',
    })


@login_required
@superuser_required
def quarantine_admin_download(request, qid):
    q = get_object_or_404(QuarantinedSave, pk=qid)
    audit.log('quarantine_download', user=request.user, request=request,
              organization_id=q.organization_id, object_type='office.quarantine',
              object_id=q.pk, object_repr=q.original_name,
              description=f'Downloaded quarantined save #{q.pk} ({q.target_label})')
    from .views import _stream
    return _stream(request, q.file.name, storage.safe_filename(q.original_name or 'unsaved'))


# ---------------------------------------------------------------------------
# Organization policy (organization admins)
# ---------------------------------------------------------------------------

def _can_manage_org(user, org):
    if org is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    from accounts.permission_utils import has_perm_for_org
    return has_perm_for_org(user, org.pk, 'org_manage_settings')


@login_required
@require_http_methods(['GET', 'POST'])
def org_policy(request):
    org = get_request_organization(request)
    if org is None:
        messages.info(request, 'Select an organization to manage its Office settings.')
        return redirect('core:dashboard')
    if not _can_manage_org(request.user, org):
        raise PermissionDenied('Organization settings permission required.')
    from .models import OrganizationOfficePolicy
    obj, _ = OrganizationOfficePolicy.objects.get_or_create(organization=org)
    settings_obj = OfficeSettings.get()
    allowed = policy.candidates(org)
    before = (obj.office_enabled, obj.preferred_instance_id)
    form = OrganizationPolicyForm(request.POST or None, instance=obj, allowed_instances=allowed,
                                  allow_override=settings_obj.allow_org_override)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if not settings_obj.allow_org_override:
            obj.preferred_instance_id = before[1]
        obj.updated_by = request.user
        obj.save()
        audit.log('policy_change', user=request.user, request=request, organization_id=org.pk,
                  object_type='office.org_policy', object_id=obj.pk, object_repr=org.name,
                  description=f'Office policy for {org.name}: editing '
                              f'{"on" if obj.office_enabled else "off"}, instance '
                              f'{obj.preferred_instance.name if obj.preferred_instance else "platform default"}')
        if before[0] and not obj.office_enabled:
            from . import sessions as session_api
            for s in EditSession.objects.filter(organization=org, state__in=EditSession.LIVE_STATES):
                session_api.revoke(s, 'Office editing switched off for the organization')
        messages.success(request, 'Saved.')
        return redirect('office:org_policy')
    # Only names and providers: secrets, URLs and CA bundles stay with superusers.
    return render(request, 'office/org_policy.html', {
        'form': form, 'org': org, 'allow_override': settings_obj.allow_org_override,
        'available': [(i.name, i.get_provider_display(), i.is_healthy) for i in allowed],
        'effective': policy.instance_for(org), 'active_page': 'office_org_policy',
    })


# ---------------------------------------------------------------------------
# Templates (org admins for their organization, superusers for all)
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(['GET', 'POST'])
def template_list(request):
    org = get_request_organization(request)
    can_org = _can_manage_org(request.user, org)
    if not (can_org or request.user.is_superuser):
        raise PermissionDenied('Organization settings permission required.')
    form = TemplateUploadForm(request.POST or None, request.FILES or None)
    if not request.user.is_superuser:
        form.fields['scope'].choices = [('org', 'This organization')]
    if request.method == 'POST' and form.is_valid():
        upload = form.cleaned_data['file']
        name = storage.safe_filename(upload.name)
        ext = formats.extension(name)
        scope = form.cleaned_data['scope']
        if ext not in formats.EDITABLE and ext not in formats.TEMPLATE:
            messages.error(request, 'Upload a .docx, .xlsx, .pptx, .dotx, .xltx or .potx file.')
        elif scope == 'org' and not can_org:
            messages.error(request, 'Select an organization you manage first.')
        else:
            f = OfficeFile.objects.create(
                purpose='template', organization=org if scope == 'org' else None, name=name,
                description=form.cleaned_data['description'], created_by=request.user,
                mime=formats.mime_for(name))
            target = targets.OfficeFileTarget(f)
            try:
                storage.store_initial(target, upload, user=request.user, source='upload')
            except storage.StorageError as e:
                f.delete()
                messages.error(request, f'Template refused: {e.message}')
            else:
                audit.log('template_upload', user=request.user, target=target, request=request,
                          description=f'Uploaded Office template {name} '
                                      f'({"global" if f.organization_id is None else org.name})')
                messages.success(request, f'Template {name} added.')
                return redirect('office:template_list')
    qs = OfficeFile.objects.filter(purpose='template')
    if request.user.is_superuser:
        qs = qs.filter(Q(organization__isnull=True) | Q(organization=org)) if org else qs
    else:
        qs = qs.filter(organization=org)
    return render(request, 'office/templates_manage.html', {
        'form': form, 'templates': qs.select_related('organization').order_by('organization_id', 'name'),
        'org': org,
    })


@login_required
@require_POST
def template_delete(request, pk):
    f = OfficeFile.objects.filter(pk=pk, purpose='template').first()
    if f is None:
        raise Http404('Not found')
    target = targets.OfficeFileTarget(f)
    if not target.can_edit(request.user):
        raise Http404('Not found')
    # Retire, don't delete: documents created from it keep their own copies,
    # and the template's revisions stay for the record.
    OfficeFile.objects.filter(pk=f.pk).update(is_active=False)
    audit.log('template_delete', user=request.user, target=target, request=request,
              description=f'Retired Office template {f.name}')
    messages.success(request, f'Template {f.name} retired.')
    return redirect('office:template_list')
