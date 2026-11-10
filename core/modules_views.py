"""Settings → System → Optional modules (core/modules.py)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render

from . import modules
from .models import SystemSetting


def _is_superuser(user):
    return user.is_superuser


@login_required
@user_passes_test(_is_superuser)
def settings_modules(request):
    settings = SystemSetting.get_settings()

    if request.method == 'POST':
        module = modules.MODULES_BY_KEY.get(request.POST.get('module') or '')
        enabled = request.POST.get('enabled')
        if module is None or not module.field or enabled not in ('on', 'off'):
            messages.error(request, 'Nothing was changed: unknown module or action.')
            return redirect('core:settings_modules')
        want = enabled == 'on'
        before = bool(getattr(settings, module.field))
        try:
            stopped, soft_missing = modules.set_enabled(module, settings, want, user=request.user)
        except modules.DependencyError as exc:
            messages.error(request, f'Not turned on. {exc}')
            return redirect('core:settings_modules')

        if before != want:
            from audit.models import AuditLog
            from .client_ip import get_client_ip
            AuditLog.log(
                user=request.user, action='update',
                object_type='core.SystemSetting', object_id=settings.pk,
                object_repr=f'Optional module: {module.label}',
                description=f'{"Turned on" if want else "Turned off"} {module.label}',
                ip_address=get_client_ip(request), path=request.path,
                extra_data={'changed_fields': {module.field: {'from': before, 'to': want}}},
            )
        messages.success(request, f'{module.label} is now {"on" if want else "off"}.')
        if stopped:
            messages.warning(
                request,
                f'These modules are still switched on but stop working until '
                f'{module.label} is on again: {", ".join(m.label for m in stopped)}.')
        if soft_missing:
            messages.warning(
                request,
                f'{module.label} is on, but it does little until '
                f'{", ".join(m.label for m in soft_missing)} is on as well.')
        return redirect(f"{request.path}#module-{module.key}")

    return render(request, 'core/settings_modules.html', {
        'groups': modules.describe(settings),
        'unenforced': modules.UNENFORCED_SWITCHES,
        'current_tab': 'modules',
    })
