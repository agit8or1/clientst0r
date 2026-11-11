"""Which editor instance serves which organization, and whether a user may
open a given file in it.

    instance_for(org, provider=None) -> EditorInstance | None
    availability(user, target, provider=None) -> Availability

Resolution order for ``instance_for`` (only enabled instances of enabled
providers that are available to the organization — shared, or dedicated to
it — are candidates):

  1. the organization has switched Office editing off -> None;
  2. the organization's preferred instance, when the platform allows
     organization overrides;
  3. an instance dedicated to the organization;
  4. the platform default instance;
  5. the first shared instance by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import formats


def _org_id(org):
    return getattr(org, 'pk', org)


def candidates(org, provider=None):
    from .models import EditorInstance, OfficeSettings
    settings_obj = OfficeSettings.get()
    providers = [p for p in (settings_obj.enabled_providers or [])
                 if provider is None or p == provider]
    if not providers:
        return EditorInstance.objects.none()
    qs = EditorInstance.objects.filter(enabled=True, provider__in=providers)
    org_id = _org_id(org)
    from django.db.models import Q
    if org_id is None:
        return qs.filter(shared=True)
    return qs.filter(Q(shared=True) | Q(organizations__pk=org_id)).distinct()


def org_policy(org):
    from .models import OrganizationOfficePolicy
    org_id = _org_id(org)
    if org_id is None:
        return None
    return OrganizationOfficePolicy.objects.filter(organization_id=org_id).first()


def office_enabled_for(org) -> bool:
    policy = org_policy(org)
    return policy is None or policy.office_enabled


def instance_for(org, provider=None):
    from .models import OfficeSettings
    if not office_enabled_for(org):
        return None
    pool = list(candidates(org, provider).prefetch_related('organizations'))
    if not pool:
        return None
    by_id = {i.pk: i for i in pool}
    settings_obj = OfficeSettings.get()
    policy = org_policy(org)
    if settings_obj.allow_org_override and policy and policy.preferred_instance_id in by_id:
        return by_id[policy.preferred_instance_id]
    org_id = _org_id(org)
    if org_id is not None:
        for inst in pool:
            if not inst.shared and any(o.pk == org_id for o in inst.organizations.all()):
                return inst
    if settings_obj.default_instance_id in by_id:
        return by_id[settings_obj.default_instance_id]
    shared = sorted((i for i in pool if i.shared), key=lambda i: i.name.lower())
    return shared[0] if shared else None


@dataclass
class Availability:
    """What the UI may offer for one file and one user.

    ``can_edit`` / ``can_view_in_editor`` are only True when a configured,
    enabled, healthy instance whose provider connector is installed supports
    the format, and the user holds the permission. Otherwise ``reason``
    explains why, for the disabled button's tooltip.
    """
    can_edit: bool = False
    can_view_in_editor: bool = False
    reason: str = ''
    instance: object = None
    provider: object = None
    capabilities: object = None
    read_only_format: bool = False
    can_convert: bool = False
    can_export_pdf: bool = False
    user_may_edit: bool = False
    notes: list = field(default_factory=list)


def availability(user, target, provider=None) -> Availability:
    from .providers import NotConfigured, get_provider
    av = Availability()
    name = target.filename
    av.read_only_format = formats.is_read_only_format(name)
    av.user_may_edit = target.can_edit(user)
    if not formats.is_office(name):
        av.reason = 'Not an Office file.'
        return av
    instance = instance_for(target.organization_id, provider)
    if instance is None:
        if not office_enabled_for(target.organization_id):
            av.reason = 'Office editing is switched off for this organization.'
        else:
            av.reason = 'No Office editor is configured for this organization.'
        return av
    av.instance = instance
    try:
        impl = get_provider(instance.provider)
        caps = impl.capabilities(instance)
    except NotConfigured as e:
        av.reason = str(e) or f'The {instance.get_provider_display()} connector is not available.'
        return av
    av.provider, av.capabilities = impl, caps
    if not instance.is_healthy:
        av.reason = (f'The editor "{instance.name}" is not healthy '
                     f'({instance.get_health_status_display().lower()}). '
                     f'An administrator can run its health check.')
        return av
    size_limit = min(instance.max_file_mb or 10**6, caps.max_file_mb or 10**6) * 1024 * 1024
    if target.size and target.size > size_limit:
        av.reason = f'The file is larger than the editor\'s {size_limit // (1024 * 1024)} MB limit.'
        return av
    ext = target.extension
    av.can_export_pdf = caps.export_pdf
    if av.read_only_format:
        dest = formats.conversion_target(name)
        av.can_convert = bool(dest and caps.can_convert(ext, dest) and av.user_may_edit)
    av.can_view_in_editor = caps.can_view(ext)
    if not av.can_view_in_editor:
        av.reason = f'{instance.get_provider_display()} cannot open .{ext} files.'
        return av
    if av.read_only_format:
        av.reason = ('Legacy and macro-enabled files open read-only; the original is kept. '
                     'Convert to a new copy to edit.')
        return av
    if not caps.can_edit(ext):
        av.reason = f'{instance.get_provider_display()} cannot edit .{ext} files.'
        return av
    if not av.user_may_edit:
        av.reason = 'You have permission to view this file, not to edit it.'
        return av
    av.can_edit = True
    return av
