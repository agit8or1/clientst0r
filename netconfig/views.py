"""
Phase 34.1 (v3.17.544) — config backup views.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from assets.models import Asset
from core.middleware import get_request_organization

from .models import ConfigBackup

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

    return render(request, 'netconfig/device_detail.html', {
        'asset': asset,
        'backups': backups,
        'head_diff': head_diff,
        'head_stats': head_stats,
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
