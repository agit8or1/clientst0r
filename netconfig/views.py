"""
Phase 34.1 (v3.17.544) — config backup views.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from assets.models import Asset
from core.middleware import get_request_organization

from .adapters import ADAPTER_CHOICES
from .collector import collect_target
from .models import BackupTarget, ConfigBackup

# Asset types this feature is offered for. A config backup of a laptop is not a
# thing, and offering it everywhere would bury the devices it matters for.
NETWORK_ASSET_TYPES = [
    'switch', 'router', 'firewall', 'load_balancer',
    'wireless_ap', 'wireless_controller', 'modem', 'gateway',
    'bridge', 'console_server',
]


def _accessible_assets(request):
    """Network devices in the caller's current organization scope."""
    org = get_request_organization(request)
    qs = Asset.objects.filter(asset_type__in=NETWORK_ASSET_TYPES)
    if org is not None:
        qs = qs.filter(organization=org)
    return qs.select_related('organization')


@login_required
def device_list(request):
    """Network devices, with how recently each was captured."""
    devices = list(_accessible_assets(request).order_by('name'))
    latest = {}
    for backup in (ConfigBackup.objects
                   .filter(asset__in=devices)
                   .order_by('asset_id', '-captured_at')):
        latest.setdefault(backup.asset_id, backup)

    rows = [{
        'asset': a,
        'latest': latest.get(a.id),
        'count': 0,
    } for a in devices]

    # One grouped count rather than a query per device.
    from django.db.models import Count
    counts = dict(
        ConfigBackup.objects.filter(asset__in=devices)
        .values_list('asset_id')
        .annotate(n=Count('id'))
    )
    for row in rows:
        row['count'] = counts.get(row['asset'].id, 0)

    return render(request, 'netconfig/device_list.html', {'rows': rows})


@login_required
def device_detail(request, asset_id):
    """Snapshot history for one device, newest first."""
    asset = get_object_or_404(_accessible_assets(request), pk=asset_id)
    backups = list(ConfigBackup.objects.filter(asset=asset).order_by('-captured_at'))

    # Latest-vs-prior is what anyone opening this page wants to see, so it is
    # rendered without being asked for.
    head_diff = []
    head_stats = {'added': 0, 'removed': 0}
    if len(backups) >= 2:
        head_diff = backups[0].diff_against(backups[1])
        head_stats = backups[0].diff_stats(backups[1])

    target = BackupTarget.objects.filter(asset=asset).select_related('credential').first()
    return render(request, 'netconfig/device_detail.html', {
        'asset': asset,
        'backups': backups,
        'head_diff': head_diff,
        'head_stats': head_stats,
        'target': target,
        'blocking_reason': target.blocking_reason() if target else None,
        # Phase 34.4 — firmware trail and lifecycle, newest first for reading.
        'firmware_history': list(reversed(ConfigBackup.firmware_history(asset))),
        'current_firmware': ConfigBackup.current_firmware(asset),
    })


@login_required
def capture(request, asset_id):
    """Paste or upload a configuration.

    Sub-phase 34.2 collects over SSH. This exists first and stays afterwards:
    an operator with a config in the clipboard and no device credentials
    configured should still be able to version it.
    """
    asset = get_object_or_404(_accessible_assets(request), pk=asset_id)

    if request.method == 'POST':
        body = request.POST.get('body') or ''
        uploaded = request.FILES.get('config_file')
        if uploaded is not None:
            try:
                body = uploaded.read().decode('utf-8', errors='replace')
            except Exception:
                messages.error(request, 'Could not read that file as text.')
                return redirect('netconfig:capture', asset_id=asset.pk)

        if not body.strip():
            messages.error(request, 'Nothing to store — paste a config or choose a file.')
            return redirect('netconfig:capture', asset_id=asset.pk)

        backup, created = ConfigBackup.record_for_asset(
            asset, body,
            source='manual',
            captured_at=timezone.now(),
            firmware_version=(request.POST.get('firmware_version') or '').strip()[:120],
            captured_by=request.user,
            note=(request.POST.get('note') or '').strip()[:255],
        )
        if created:
            from .drift import classify_and_alert
            state = classify_and_alert(backup)
            if state == 'unauthorized':
                messages.warning(
                    request,
                    'Configuration stored — and it differs from the approved '
                    'baseline with no approved change request covering now. '
                    'An alert has been raised.')
            else:
                messages.success(request, 'Configuration stored.')
        else:
            messages.info(
                request,
                'Identical to the last capture, so nothing new was stored — '
                'the existing snapshot is now marked as seen just now.')
        return redirect('netconfig:device_detail', asset_id=asset.pk)

    return render(request, 'netconfig/capture.html', {'asset': asset})


@login_required
def compare(request, asset_id):
    """Diff any two snapshots of one device."""
    asset = get_object_or_404(_accessible_assets(request), pk=asset_id)
    backups = list(ConfigBackup.objects.filter(asset=asset).order_by('-captured_at'))

    left = right = None
    if backups:
        left_id = request.GET.get('left')
        right_id = request.GET.get('right')
        by_id = {str(b.pk): b for b in backups}
        # Default to the two newest, which is the comparison people want.
        right = by_id.get(right_id) or backups[0]
        left = by_id.get(left_id) or (backups[1] if len(backups) > 1 else None)

    diff = right.diff_against(left) if right else []
    stats = right.diff_stats(left) if right else {'added': 0, 'removed': 0}

    return render(request, 'netconfig/compare.html', {
        'asset': asset,
        'backups': backups,
        'left': left,
        'right': right,
        'diff': diff,
        'stats': stats,
    })


@login_required
def view_backup(request, backup_id):
    """The raw stored configuration."""
    backup = get_object_or_404(
        ConfigBackup.objects.select_related('asset', 'organization'), pk=backup_id)
    # Scope check via the same queryset the rest of the app uses.
    get_object_or_404(_accessible_assets(request), pk=backup.asset_id)
    return render(request, 'netconfig/view.html', {
        'backup': backup,
        'previous': backup.previous(),
    })


# ---------------------------------------------------------------------------
# Phase 34.2 (v3.17.545) — SSH collection
# ---------------------------------------------------------------------------

@login_required
def target_edit(request, asset_id):
    """Configure how to reach a device."""
    from vault.models import Password

    asset = get_object_or_404(_accessible_assets(request), pk=asset_id)
    target = BackupTarget.objects.filter(asset=asset).first()

    if request.method == 'POST':
        if request.POST.get('action') == 'delete' and target:
            target.delete()
            messages.success(request, 'Connection settings removed.')
            return redirect('netconfig:device_detail', asset_id=asset.pk)

        if target is None:
            target = BackupTarget(asset=asset, organization=asset.organization)

        target.host = (request.POST.get('host') or '').strip()[:255]
        target.username = (request.POST.get('username') or '').strip()[:150]
        target.adapter = request.POST.get('adapter') or 'generic'
        target.config_command = (request.POST.get('config_command') or '').strip()[:255]
        target.version_command = (request.POST.get('version_command') or '').strip()[:255]
        target.is_enabled = request.POST.get('is_enabled') == 'on'
        try:
            target.port = int(request.POST.get('port') or 22)
        except (TypeError, ValueError):
            target.port = 22
        try:
            target.cadence_hours = int(request.POST.get('cadence_hours') or 24)
        except (TypeError, ValueError):
            target.cadence_hours = 24

        credential_id = request.POST.get('credential')
        if credential_id:
            # Scoped to the asset's own organization: a switch in one client's
            # rack must not be reachable with another client's credential.
            cred = Password.objects.filter(
                pk=credential_id, organization_id=asset.organization_id).first()
            if cred is None:
                messages.error(
                    request,
                    'That vault entry is not available for this client.')
                return redirect('netconfig:target_edit', asset_id=asset.pk)
            target.credential = cred
        else:
            target.credential = None

        if not target.host:
            messages.error(request, 'A host is required.')
            return redirect('netconfig:target_edit', asset_id=asset.pk)

        target.save()
        messages.success(request, 'Connection settings saved.')
        return redirect('netconfig:device_detail', asset_id=asset.pk)

    credentials = Password.objects.filter(
        organization_id=asset.organization_id).order_by('title')

    return render(request, 'netconfig/target_edit.html', {
        'asset': asset,
        'target': target,
        'credentials': credentials,
        'adapter_choices': ADAPTER_CHOICES,
    })


@login_required
def collect_now(request, asset_id):
    """Run a collection against one device on demand."""
    asset = get_object_or_404(_accessible_assets(request), pk=asset_id)
    target = get_object_or_404(BackupTarget, asset=asset)

    if request.method != 'POST':
        return redirect('netconfig:device_detail', asset_id=asset.pk)

    result = collect_target(target, user=request.user)
    if result['ok']:
        messages.success(request, result['message'])
    else:
        messages.error(request, result['message'])
    return redirect('netconfig:device_detail', asset_id=asset.pk)


@login_required
def approve_baseline(request, backup_id):
    """Phase 34.3 (v3.17.546): mark a snapshot as the known-good config."""
    backup = get_object_or_404(ConfigBackup, pk=backup_id)
    get_object_or_404(_accessible_assets(request), pk=backup.asset_id)

    if request.method != 'POST':
        return redirect('netconfig:device_detail', asset_id=backup.asset_id)

    backup.approve_as_baseline()
    messages.success(
        request,
        'Marked as the approved baseline. Later configs are compared against '
        'this one, and a difference outside an approved change window raises '
        'an alert.')
    return redirect('netconfig:device_detail', asset_id=backup.asset_id)


@login_required
def lifecycle(request):
    """Phase 34.4 (v3.17.547): network gear approaching or past its dates.

    Sorted by urgency rather than name: out-of-support first, because a switch
    that stopped receiving security fixes is a different kind of problem from
    one due for replacement next year.
    """
    from datetime import date, timedelta as _td

    horizon = date.today() + _td(days=365)
    devices = list(_accessible_assets(request))

    rows = []
    for asset in devices:
        eol = asset.get_end_of_life_date()
        eos = asset.vendor_end_of_support
        out_of_support = asset.is_out_of_support()
        eol_soon = bool(eol and eol <= horizon)
        eos_soon = bool(eos and eos <= horizon)
        # Consistent on both dates: a device whose end-of-support is five
        # years out is no more in need of attention than one whose
        # end-of-life is, and listing it would dilute the page into an
        # inventory of everything that happens to have a date on it.
        if not (out_of_support or eol_soon or eos_soon):
            continue
        rows.append({
            'asset': asset,
            'eol': eol,
            'eos': eos,
            'out_of_support': out_of_support,
            'eol_soon': eol_soon,
            'eos_soon': eos_soon,
            'firmware': ConfigBackup.current_firmware(asset),
            # 0 sorts first.
            'rank': 0 if out_of_support else (1 if eol_soon else 2),  # 0 sorts first
        })
    rows.sort(key=lambda r: (r['rank'], r['eos'] or r['eol'] or date.max))

    return render(request, 'netconfig/lifecycle.html', {
        'rows': rows,
        'horizon': horizon,
    })
