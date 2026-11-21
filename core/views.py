"""
Core views - Documentation and About pages
"""
from core.error_responses import public_error
import logging
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.templatetags.static import static
from django.core.cache import cache
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from config.version import get_version, get_full_version
from .updater import UpdateService
from . import root_helper
from .models import ConsultRequest
from audit.models import AuditLog

# Served from static/vendor so a CDN outage can't leave these pages unstyled.
BOOTSTRAP_CSS = 'vendor/bootstrap/5.3.0/css/bootstrap.min.css'

logger = logging.getLogger(__name__)


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser


@login_required
def documentation(request):
    """
    Platform documentation page.
    """
    from core.security_features import grouped
    return render(request, 'core/documentation.html', {
        'version': get_version(),
        'security_groups': grouped(),
    })


@login_required
def roadmap(request):
    """
    Public roadmap page rendered from `docs/ROADMAP.md`. No login required —
    same as /core/about/. Markdown is rendered server-side so the file
    stays the single source of truth (also visible on GitHub at /docs/ROADMAP.md).

    v3.17.319: phase H2 headings get `data-phase-status` attributes
    (`shipped` / `complete` / `in-progress` / `planned`) so the page
    template can visually distinguish them — green badges + muted
    colors for shipped/complete, an in-progress badge, etc. Plus a
    "Hide shipped phases" toggle in the page UI so users can focus on
    what's left.
    """
    import os
    import re as _re
    from pathlib import Path
    from django.conf import settings
    from markdown import markdown
    base = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
    path = Path(base) / 'docs' / 'ROADMAP.md'
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        raw = '# Roadmap\n\nThe roadmap file could not be loaded.'
    html = markdown(raw, extensions=['extra', 'tables', 'sane_lists', 'toc'])

    # Tag each Phase H2 with its status so CSS can style + so the
    # toggle JS can hide shipped ones.
    def _classify(match):
        h2_open, content, h2_close = match.group(1), match.group(2), match.group(3)
        # Look at the whole H2 inner text for status hints
        text = _re.sub(r'<[^>]+>', '', content).lower()
        status = 'planned'
        if '[wont-do]' in text or '[won\'t do]' in text or '[out-of-scope]' in text:
            status = 'wont-do'
        elif '[complete]' in text or '— complete' in text:
            status = 'complete'
        elif 'shipped' in text:  # `[shipped — vN.N.N]` or `**— shipped**`
            status = 'shipped'
        elif '[in progress]' in text or '[in-progress]' in text:
            status = 'in-progress'
        # Only tag if this looks like a Phase heading
        if 'phase ' not in text:
            return match.group(0)
        # Inject the data attribute + a status badge span before the
        # status bracket so screen readers + visual users get the same
        # signal.
        badge_map = {
            'shipped':     '<span class="phase-badge phase-shipped">Shipped</span>',
            'complete':    '<span class="phase-badge phase-complete">Complete</span>',
            'in-progress': '<span class="phase-badge phase-inprogress">In progress</span>',
            'planned':     '<span class="phase-badge phase-planned">Planned</span>',
            'wont-do':     '<span class="phase-badge phase-wontdo">Won’t do</span>',
        }
        badge = badge_map[status]
        new_open = h2_open.replace(
            '<h2',
            f'<h2 data-phase-status="{status}"',
            1,
        )
        return f'{new_open}{badge}{content}{h2_close}'

    html = _re.sub(
        r'(<h2[^>]*>)(.*?)(</h2>)',
        _classify,
        html,
        flags=_re.DOTALL,
    )

    return render(request, 'core/roadmap.html', {
        'roadmap_html': html,
        'roadmap_source_url': 'https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP.md',
    })


def roadmap_status_json(request):
    """
    Polling-friendly JSON view of roadmap phase status, parsed from
    `docs/ROADMAP.md`. Lets external dashboards / status pages /
    customer portals refresh themselves without scraping HTML.

    Convention (CLAUDE.md): each top-level phase header looks like:
        ## Phase N — Title **(SIZE)** [STATUS]
    where STATUS is one of `complete` / `in progress` / `shipped`
    (with optional version e.g. `[shipped — v3.17.NNN]` or
    `**— shipped**`). Sub-bullets carry per-item status via
    `*(shipped vN.N.N)*` or `*(planned)*` annotations.

    Response shape:
      {
        "generated_at": "2026-04-30T...",
        "current_version": "3.17.NNN",
        "phases": [
          {"number": 1, "title": "...", "status": "complete",
           "size": "M · foundation", "version": null},
          ...
        ]
      }
    """
    import re
    from pathlib import Path
    from django.conf import settings
    from django.http import JsonResponse
    from django.views.decorators.cache import cache_page

    base = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
    path = Path(base) / 'docs' / 'ROADMAP.md'
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        return JsonResponse(
            {'error': 'roadmap not found', 'phases': []}, status=503
        )

    # Match `## Phase N — Title  **(SIZE)** [optional status]`
    # Handles `[complete]`, `[in progress]`, `[shipped — v3.17.NNN]`,
    # and inline `**— shipped**` / `**— complete**` markers.
    phase_re = re.compile(
        r'^##\s+Phase\s+(?P<num>\d+(?:\.\d+)?)'
        r'\s*[—\-]\s*(?P<title>.+?)'
        r'(?:\s*\*\*\((?P<size>[^)]+)\)\*\*)?'
        r'(?:\s*\*\*[—\-]\s*(?P<inline_status>shipped|complete)\*\*)?'
        r'(?:\s*\[(?P<bracket_status>[^\]]+)\])?'
        r'\s*$',
        re.MULTILINE,
    )
    version_re = re.compile(r'v(\d+\.\d+\.\d+)')

    phases = []
    for m in phase_re.finditer(raw):
        bracket = (m.group('bracket_status') or '').strip().lower()
        inline = (m.group('inline_status') or '').strip().lower()
        # Normalize status into one of: complete / shipped / in_progress / planned / wont_do
        status = 'planned'
        if 'wont-do' in bracket or "won't do" in bracket or 'out-of-scope' in bracket:
            status = 'wont_do'
        elif 'complete' in bracket or inline == 'complete':
            status = 'complete'
        elif 'shipped' in bracket or inline == 'shipped':
            status = 'shipped'
        elif 'in progress' in bracket or 'in-progress' in bracket:
            status = 'in_progress'

        # Pull a version number out of the bracket if present
        v = version_re.search(bracket) if bracket else None
        version = v.group(1) if v else None

        try:
            phase_num = float(m.group('num')) if '.' in m.group('num') else int(m.group('num'))
        except (ValueError, TypeError):
            phase_num = m.group('num')

        phases.append({
            'number': phase_num,
            'title': m.group('title').strip(),
            'size': (m.group('size') or '').strip() or None,
            'status': status,
            'version': version,
        })

    # Current installed version
    try:
        from config.version import VERSION as current_version
    except Exception:
        current_version = None

    return JsonResponse({
        'generated_at': timezone.now().isoformat(),
        'current_version': current_version,
        'roadmap_source_url': 'https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP.md',
        'phase_count': len(phases),
        'shipped_count': sum(1 for p in phases if p['status'] in ('shipped', 'complete')),
        'phases': phases,
    })


def about(request):
    """
    About page with version and system information.
    Fast-loading with minimal database queries.
    """
    from assets.models import Vendor, EquipmentModel

    # Get equipment catalog statistics (cached for 1 hour - fast DB query)
    stats_cache_key = 'about_page_equipment_stats'
    equipment_stats = cache.get(stats_cache_key)
    if equipment_stats is None:
        equipment_stats = {
            'vendor_count': Vendor.objects.filter(is_active=True).count(),
            'model_count': EquipmentModel.objects.filter(is_active=True).count(),
        }
        cache.set(stats_cache_key, equipment_stats, 3600)  # Cache for 1 hour

    # Security scan and dependencies moved to System Status page for performance
    # These operations are slow (pip-audit takes 1-2 seconds) and not critical for About page

    from core.security_features import grouped
    two_factor_enabled = False
    if request.user.is_authenticated:
        from django_otp import user_has_device
        two_factor_enabled = user_has_device(request.user)
    return render(request, 'core/about.html', {
        'version': get_version(),
        'full_version': get_full_version(),
        'equipment_stats': equipment_stats,
        'security_groups': grouped(),
        'two_factor_enabled': two_factor_enabled,
    })


def free_consult(request):
    """Free consultation request form (public — no login required)."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        company = request.POST.get('company', '').strip()
        phone = request.POST.get('phone', '').strip()
        areas = request.POST.getlist('areas')
        description = request.POST.get('description', '').strip()
        best_time = request.POST.get('best_time', '').strip()
        heard_from = request.POST.get('heard_from', '').strip()

        if not name or not email:
            messages.error(request, 'Name and email are required.')
        else:
            # Validate areas against allowed choices
            valid_keys = {k for k, _ in ConsultRequest.AREA_CHOICES}
            areas = [a for a in areas if a in valid_keys]
            ConsultRequest.objects.create(
                name=name,
                email=email,
                company=company,
                phone=phone,
                areas_of_interest=','.join(areas),
                description=description,
                best_time=best_time,
                heard_from=heard_from,
            )
            return render(request, 'core/consult_thanks.html', {'name': name})

    return render(request, 'core/consult.html', {
        'area_choices': ConsultRequest.AREA_CHOICES,
        # Re-check the boxes the visitor ticked when the form comes back with an error.
        'selected_areas': request.POST.getlist('areas') if request.method == 'POST' else [],
    })


# Used by the emergency restart endpoint below.
from django.views.decorators.csrf import csrf_exempt as _csrf_exempt


def health(request):
    """
    v3.17.490 — minimal health endpoint at GET /health/.

    Returns 200 + JSON {ok: true, version: 'X.Y.Z'} as soon as Django
    can serve a request. Used by the Dockerfile HEALTHCHECK, load
    balancers, and uptime monitors. Anonymous-accessible by design;
    leaks no sensitive data beyond the version string (which is also
    in /core/roadmap.json and About → Settings).

    Why no DB ping: the Django process being up but the DB being down
    is a real failure mode worth distinguishing from "container alive,
    DB unreachable." Add a separate /health/db/ if you need that.
    """
    from django.http import JsonResponse
    from config.version import VERSION
    return JsonResponse({'ok': True, 'version': VERSION}, status=200)


def privacy_policy(request):
    """
    Public privacy policy page rendered from `docs/PRIVACY_POLICY.md`.
    Anonymous-accessible so Play Console reviewers and tester users can
    reach it without an account. Single source of truth is the markdown
    file; this view renders it server-side.
    """
    from pathlib import Path
    from django.conf import settings
    from markdown import markdown
    base = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
    path = Path(base) / 'docs' / 'PRIVACY_POLICY.md'
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        raw = '# Privacy Policy\n\nThe privacy policy file could not be loaded.'
    html = markdown(raw, extensions=['extra', 'tables', 'sane_lists'])
    return render(request, 'core/privacy_policy.html', {'policy_html': html})


def beta_onboarding(request):
    """
    v3.17.481 — Public beta-onboarding page rendered from
    `docs/BETA_ONBOARDING.md`. Anonymous-accessible so Play Store users
    who follow the opt-in URL can read install instructions, known
    limitations, and how to file feedback without logging in.
    """
    from pathlib import Path
    from django.conf import settings
    from markdown import markdown
    base = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
    path = Path(base) / 'docs' / 'BETA_ONBOARDING.md'
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        raw = '# Mobile beta\n\nThe onboarding page could not be loaded.'
    html = markdown(raw, extensions=['extra', 'tables', 'sane_lists'])
    return render(request, 'core/beta_onboarding.html', {'page_html': html})


@login_required
@user_passes_test(is_superuser)
def consult_requests(request):
    """Superuser view — list all consult form submissions."""
    requests_qs = ConsultRequest.objects.all()
    if request.method == 'POST' and 'mark_read' in request.POST:
        req_id = request.POST.get('mark_read')
        ConsultRequest.objects.filter(id=req_id).update(is_read=True)
        return redirect('core:consult_requests')
    return render(request, 'core/consult_requests.html', {
        'consult_requests': requests_qs,
        'unread_count': requests_qs.filter(is_read=False).count(),
    })


def _parse_iso(value):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _update_status_line(state, rows, installed, upgrade_state=None):
    """One honest sentence about updates. Never "up to date" from a failed or
    incomplete check, and never as if no other releases existed. While an
    upgrade runs it is the only status: nothing is "available" then."""
    if upgrade_state and upgrade_state.get('state') == 'running':
        from core.upgrade import journal as upgrade_journal
        j = upgrade_state.get('journal') or {}
        t = j.get('target') or {}
        p = upgrade_journal.progress(j)
        to = _describe_target(state, t)['label'] if t else 'a new version'
        num = f"stage {p['number']} of {p['total']}: " if p['number'] else ''
        return 'running', f"Updating to {to} \u2014 {num}{p['label']}."
    if state.get('error') and not state.get('stale'):
        return 'error', f"Could not check for updates: {state['error']}"
    target = state.get('target')
    from core.upgrade.channels import CHANNEL_LABELS, LEGACY_CHANNELS
    ch = state.get('channel') or 'stable'
    channel_label = CHANNEL_LABELS.get(LEGACY_CHANNELS.get(ch, ch), CHANNEL_LABELS['stable'])
    if target:
        line = (f"Update available on your {channel_label} channel: "
                f"{_describe_target(state, target)['label']}")
        tone = 'update'
    else:
        inst = state.get('installed') or {}
        here = ''
        if inst.get('version') or inst.get('sha'):
            here = _describe_target(state, {'kind': 'preview', 'ref': 'main', 'sha': inst.get('sha'),
                                            'version': inst.get('version')})
            here = (f"v{inst['version']}" if here['is_release'] or not inst.get('sha')
                    else here['short'])
        line = (f"Up to date \u2014 {here}. " if here else '') + \
            'No newer updates on your selected channel.'
        tone = 'ok'
    if state.get('error') and state.get('stale'):
        return 'stale', f"{line} The latest check failed: {state['error']}"

    return tone, line


def _describe_target(state, t):
    """core.upgrade.catalog.describe_build for a {kind, ref, sha, version}."""
    from core.upgrade.catalog import describe_build
    t = t or {}
    return describe_build(state or {}, t.get('kind'), t.get('ref'), t.get('sha'), t.get('version') or '')


@login_required
@user_passes_test(is_superuser)
def system_updates(request):
    """Settings -> Updates: what is installed, every version discovered on
    GitHub (official releases and testing builds), the channel policy, restore
    points and pre-upgrade backups. Superusers only."""
    updater = UpdateService()

    # core.upgrade.channels caches the GitHub answer itself (and keeps the
    # last good one for when GitHub is unreachable).
    update_info = updater.check_for_updates()
    state = update_info.get('channels') or {}

    git_status = updater.get_git_status()
    sudo_configured = updater._check_passwordless_sudo()

    recent_updates = AuditLog.objects.filter(
        action__in=['system_update', 'system_update_failed', 'update_check']
    ).order_by('-timestamp')[:10]

    current_version = get_version()
    current_changelog = updater.get_changelog_for_version(current_version)

    from core.upgrade import catalog as upgrade_catalog
    from core.upgrade import journal as upgrade_journal, retention as upgrade_retention
    upgrade_state = upgrade_journal.assess()
    repair_target = _repair_candidate(state, upgrade_state)
    try:
        backups = upgrade_retention.summary()
    except Exception:
        logger.exception('could not list the upgrade backups')
        backups = {'backups': [], 'total_human': '?', 'free_human': 'unknown', 'policy': None,
                   'env_keep': upgrade_retention.env_keep(), 'would_remove': 0}
    recent_backups = backups['backups']

    # Every discovered version, whatever the channel. None when GitHub has
    # never been reached: the page then says so instead of showing empty
    # categories.
    discovered = state.get('releases') is not None or bool(state.get('preview'))
    try:
        rows = upgrade_catalog.build(state, upgrade_state=upgrade_state) if state else []
    except Exception:
        logger.exception('could not build the version list')
        rows = []
    installed = upgrade_catalog.installed_summary(state, rows) if state else {
        'type': 'unknown', 'type_label': 'Unknown', 'ahead_of_stable': False}
    status_tone, status_line = _update_status_line(update_info.get('channels') or update_info, rows,
                                                   installed, upgrade_state)
    upgrade_running = upgrade_state['state'] == 'running'
    upgrade_progress = None
    upgrade_to = upgrade_from = None
    j = upgrade_state.get('journal') or {}
    if upgrade_state['state'] in ('running', 'interrupted', 'failed') and j:
        from core.upgrade import journal as _j
        upgrade_progress = _j.progress(j) if upgrade_running else None
        if j.get('target'):
            upgrade_to = _describe_target(state, j['target'])
        if j.get('prev_sha') or j.get('prev_version'):
            upgrade_from = _describe_target(state, {'kind': 'preview', 'ref': 'main',
                                                    'sha': j.get('prev_sha'),
                                                    'version': j.get('prev_version')})
    target_desc = _describe_target(state, update_info.get('target')) if update_info.get('target') else None
    try:
        restore_points = upgrade_catalog.restore_points(backups if backups.get('policy') else None)
    except Exception:
        logger.exception('could not list restore points')
        restore_points = []
    latest_dev = next((r for r in rows if r['type'] == 'development'), None)
    latest_testing = next((r for r in rows if r.get('group') == 'testing'), None)
    latest_testing_desc = (_describe_target(state, latest_testing) if latest_testing else None)

    from core.models import SystemPackageScan
    last_package_scan = SystemPackageScan.objects.order_by('-scan_date').first()

    from core.upgrade.channels import CHANNEL_LABELS
    return render(request, 'core/system_updates.html', {
        'version': current_version,
        'update_info': update_info,
        'git_status': git_status,
        'sudo_configured': sudo_configured,
        'recent_updates': recent_updates,
        'current_changelog': current_changelog,
        'last_package_scan': last_package_scan,
        'root_helper_needed': root_helper.needs_bootstrap(),
        'root_helper_command': root_helper.bootstrap_command(),
        'channels': state,
        'channel_label': CHANNEL_LABELS.get(state.get('channel') or 'stable', CHANNEL_LABELS['stable']),
        'official_count': sum(1 for r in rows if r.get('group') == 'official'),
        'testing_count': sum(1 for r in rows if r.get('group') == 'testing'),
        'latest_testing': latest_testing,
        'latest_testing_desc': latest_testing_desc,
        'upgrade_running': upgrade_running,
        'upgrade_progress': upgrade_progress,
        'upgrade_to': upgrade_to,
        'upgrade_from': upgrade_from,
        'target_desc': target_desc,
        'unpublished_tag': (state.get('discovery') or {}).get('unpublished_tag'),
        'last_checked': (state.get('checked_at') or (update_info or {}).get('checked_at') or 'never'),
        'last_checked_dt': _parse_iso(state.get('checked_at') or (update_info or {}).get('checked_at')),
        'newer_count': sum(1 for r in rows if r.get('relation') == 'newer'),
        'check_error': state.get('error') or (update_info or {}).get('error') or '',
        'versions': rows,
        'versions_discovered': discovered,
        'discovery': state.get('discovery') or {},
        'installed_summary': installed,
        'latest_dev': latest_dev,
        'status_line': status_line,
        'status_tone': status_tone,
        'restore_points': restore_points,
        'eligible_restore_points': [r for r in restore_points if r['eligible']],
        'upgrade_state': upgrade_state,
        'repair_target': repair_target,
        'recent_backups': recent_backups,
        'backups': backups,
        'cleanup_blocked': (upgrade_state['state'] in ('running', 'unreadable')
                            or upgrade_state['needs_recovery']),
        'backup_dir': str(upgrade_journal.backup_root()),
    })


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def set_update_channel(request):
    """Choose the release channel: which version is recommended, what the
    badge and the nightly timer act on. Saving it never installs anything and
    never hides a version."""
    from core.models import SystemSetting
    from core.upgrade import channels
    channel = request.POST.get('channel', '')
    if channel not in channels.CHANNELS:
        messages.error(request, 'Unknown release channel.')
        return redirect('core:system_updates')
    s = SystemSetting.get_settings()
    if s.update_channel != channel:
        SystemSetting.objects.filter(pk=1).update(update_channel=channel)
        SystemSetting.forget_request_copy()
        AuditLog.objects.create(
            user=request.user, username=request.user.username, action='update',
            object_type='system_setting', object_repr='Release channel',
            description=f'Release channel set to {channel}')
    messages.success(request, {
        'stable': 'Following Official release: signed published releases are recommended.',
        'preview': 'Following Preview / testing: the newest commit on main (unreleased, '
                   'unsigned, pinned by commit) is recommended.',
    }[channel] + ' Nothing was installed; every version stays listed under Available Versions.')
    return redirect('core:system_updates')


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def upgrade_backup_settings(request):
    """Retention for pre-upgrade backups: how many to keep, and how old."""
    from core.models import SystemSetting
    errors = []

    def number(field, label, minimum, maximum):
        raw = (request.POST.get(field) or '').strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            errors.append(f'{label} must be a whole number.')
            return None
        if not minimum <= value <= maximum:
            errors.append(f'{label} must be between {minimum} and {maximum}.')
            return None
        return value

    keep = number('keep', 'Backups to keep', 1, 100)
    max_age = number('max_age_days', 'Maximum age', 1, 3650)
    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect('core:system_updates')
    s = SystemSetting.get_settings()
    before = (s.upgrade_backups_keep, s.upgrade_backups_max_age_days)
    if before != (keep, max_age):
        SystemSetting.objects.filter(pk=1).update(upgrade_backups_keep=keep,
                                                  upgrade_backups_max_age_days=max_age)
        SystemSetting.forget_request_copy()
        AuditLog.objects.create(
            user=request.user, username=request.user.username, action='update',
            object_type='system_setting', object_repr='Upgrade backup retention',
            description=(f"Upgrade backup retention: keep {keep or 'default'}, "
                         f"max age {f'{max_age} days' if max_age else 'none'}"),
            extra_data={'before': {'keep': before[0], 'max_age_days': before[1]},
                        'after': {'keep': keep, 'max_age_days': max_age}})
    messages.success(request, 'Backup retention saved. It is applied by every upgrade, by the daily '
                     'cleanup, and by "Clean up now".')
    return redirect('core:system_updates')


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
@ratelimit(key='user', rate='30/h', method='POST', block=True)
def upgrade_backups_prune(request):
    """"Clean up now": apply the retention rules immediately."""
    from core.upgrade import retention
    try:
        removed = retention.prune(trigger='web', user=request.user)
    except retention.RetentionRefused as e:
        messages.error(request, str(e))
        return redirect('core:system_updates')
    if removed:
        messages.success(request, f'Removed {len(removed)} old backup(s).')
    else:
        messages.info(request, 'Nothing to remove: every backup is within the retention rules.')
    return redirect('core:system_updates')


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
@ratelimit(key='user', rate='60/h', method='POST', block=True)
def upgrade_backup_delete(request):
    """Remove one pre-upgrade backup, named by its directory name."""
    from core.upgrade import retention
    name = request.POST.get('name', '')
    try:
        path = retention.delete(name, user=request.user, trigger='web')
    except retention.RetentionRefused as e:
        messages.error(request, str(e))
        return redirect('core:system_updates')
    messages.success(request, f'Removed the backup {path.rsplit("/", 1)[-1]}.')
    return redirect('core:system_updates')


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
@ratelimit(key='user', rate='20/h', method='POST', block=True)
def upgrade_preflight_api(request):
    """Run the preflight checks Apply runs first and return them as JSON."""
    from core.upgrade import preflight
    from core.upgrade.revision import RevisionError, Target, fetch, head_sha
    target = None
    t = (UpdateService().check_for_updates().get('target'))
    if t:
        target = Target(t['kind'], t['ref'], t['sha'], t.get('version') or '')
        try:
            fetch(target)   # needed to list the migrations / requirements it brings
        except RevisionError as e:
            return JsonResponse({'checks': [{'name': 'target revision', 'status': 'fail',
                                             'detail': str(e), 'hint': ''}], 'ok': False})
        except Exception as e:
            logger.warning('preflight could not fetch %s: %s', t.get('ref'), e)
    checks = preflight.run(target, installed_sha=head_sha())
    return JsonResponse({'checks': [c.as_dict() for c in checks],
                         'ok': not preflight.failed(checks),
                         'target': t})


def _reviewed_target(request):
    """The (kind, ref, sha) the page sent, validated, or (None, error)."""
    import json as _json
    from core.upgrade.revision import RevisionError, Target
    try:
        body = _json.loads(request.body or b'{}')
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        return Target(str(body.get('kind', '')), str(body.get('ref', '')),
                      str(body.get('sha', ''))).validate(), body, None
    except RevisionError:
        # Input validation: say what is wrong without echoing exception text.
        return None, body, 'the kind, ref or sha sent is not a valid revision'


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
@ratelimit(key='user', rate='40/h', method='POST', block=True)
def upgrade_review_api(request):
    """Review one version before installing it: what it changes (from -> to,
    upgrade / older version / outside the channel), its notes, and every check
    Apply will run first: the revision is fetched and pinned, a release or
    pre-release tag's signature is verified, an older version is checked
    against the database's migrations, and the preflight checks run. Nothing
    is installed and the channel is not changed."""
    from core.upgrade import catalog as upgrade_catalog
    from core.upgrade import journal as upgrade_journal, preflight
    from core.upgrade.revision import RevisionError, fetch, head_sha, verify_release_tag, version_at
    target, body, err = _reviewed_target(request)
    if target is None:
        return JsonResponse({'ok': False, 'message': f'No version was selected ({err}).'}, status=400)
    info = UpdateService().check_for_updates()
    state = info.get('channels') or {}
    assessment = upgrade_journal.assess()
    rows = upgrade_catalog.build(state, upgrade_state=assessment, check_compat=False)
    row = upgrade_catalog.find(rows, target.kind, target.ref, target.sha)
    if row is None:
        return JsonResponse({'ok': False, 'message':
                             f'{target.ref} @ {target.sha[:12]} is not among the versions discovered '
                             'on GitHub (it may have moved). Reload the page.'}, status=404)
    inst = state.get('installed') or {}
    out = {
        'target': {'kind': row['kind'], 'ref': row['ref'], 'sha': row['sha'], 'version': row['version'],
                   'type': row['type'], 'type_label': row['type_label']},
        'from': {'version': inst.get('version') or get_version(), 'sha': inst.get('sha') or ''},
        'relation': row['relation'], 'in_channel': row['in_channel'], 'recommended': row['recommended'],
        'channel': state.get('channel') or 'stable', 'notes': row['notes'], 'url': row['url'],
        'commits': row['commits'], 'signature': row['signature'], 'name': row['name'],
        'date': row['date'], 'date_kind': row['date_kind'], 'checks': [], 'ok': False,
    }
    checks = out['checks']

    def add(name, status, detail, hint=''):
        checks.append({'name': name, 'status': status, 'detail': detail, 'hint': hint})

    if not row['installable']:
        add('eligibility', 'fail', row['reason'])
        return JsonResponse(out)
    try:
        fetch(target)
        add('revision', 'ok', f'fetched {target.ref}; the commit is {target.sha[:12]} as reviewed')
    except RevisionError as e:
        add('revision', 'fail', str(e))
        return JsonResponse(out)
    except Exception as e:
        add('revision', 'fail', f'could not fetch it: {e}')
        return JsonResponse(out)
    if target.kind in ('release', 'prerelease'):
        try:
            add('signature', 'ok', 'tag signed by a trusted release key: ' + verify_release_tag(target))
        except RevisionError as e:
            add('signature', 'fail', str(e))
    else:
        add('signature', 'warn', 'development build: not a release and not signed; pinned to this '
                                 'exact commit')
    try:
        out['target']['version'] = version_at(target.sha) or row['version']
    except RevisionError:
        pass
    if row['relation'] == 'older':
        state_, detail, _ = upgrade_catalog.downgrade_compatibility(target.sha)
        add('compatibility', 'ok' if state_ == 'safe' else 'fail', detail,
            '' if state_ == 'safe' else 'Use a restore point (Rollback) instead.')
    for c in preflight.run(target, installed_sha=head_sha()):
        checks.append(c.as_dict())
    out['ok'] = not any(c['status'] == 'fail' for c in checks)
    return JsonResponse(out)


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
@ratelimit(key='user', rate='5/h', method='POST', block=True)
def root_helper_install(request):
    """One-time install of the root helper, using the operator's sudo password.

    v3.17.597. After this the app runs root actions only through the helper,
    and the helper keeps itself and the root-owned config it manages current
    from signed releases, so this never needs doing again. The password is
    passed to sudo on stdin and not stored or logged.
    """
    if root_helper.is_installed():
        messages.info(request, 'The root helper is already installed.')
        return redirect('core:system_updates')
    password = request.POST.get('sudo_password', '')
    if not password:
        messages.error(request, 'Enter the sudo password for the server account that runs Client St0r.')
        return redirect('core:system_updates')

    ok, output = root_helper.bootstrap_with_password(password)
    AuditLog.objects.create(
        user=request.user, username=request.user.username,
        action='system_update' if ok else 'system_update_failed',
        object_type='root_helper', object_repr='Root helper install',
        description='Installed the root helper' if ok else 'Root helper install failed',
    )
    if ok:
        messages.success(request, 'Root helper installed. Old unsafe sudo rules on this server have been disabled.')
    else:
        logger.error('Root helper install failed: %s', output)
        messages.error(request, f'Root helper install failed. Check the password and try again. {output[-300:]}')
    return redirect('core:system_updates')


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def check_updates_now(request):
    """
    Force check for updates (bypass cache).
    Staff-only access.
    """
    updater = UpdateService()
    update_info = updater.check_for_updates(force_refresh=True)

    # Log the check (best-effort — older DB schemas may not have extra_data column yet)
    try:
        AuditLog.objects.create(
            action='update_check',
            description=f'Manual update check by {request.user.username}',
            user=request.user,
            username=request.user.username,
            extra_data={k: v for k, v in update_info.items() if k != 'channels'}
        )
    except Exception:
        # Likely the legacy schema without `extra_data`. Try the slim row;
        # if THAT fails too, log it — silently swallowing the second failure
        # makes real DB issues invisible during update checks.
        try:
            AuditLog.objects.create(
                action='update_check',
                description=f'Manual update check by {request.user.username}',
                user=request.user,
                username=request.user.username,
            )
        except Exception:
            logger.exception('Failed to write update_check audit log')

    if update_info.get('error'):
        messages.error(request, f"Failed to check for updates: {update_info['error']}"
                       + (' Showing the last successful check.' if update_info.get('stale') else ''))
    elif _upgrade_running():
        messages.info(request, 'An upgrade is in progress. Its progress is shown below; '
                      'nothing else can be installed until it finishes.')
    elif update_info['update_available']:
        d = _describe_target(update_info.get('channels') or {}, update_info['target'])
        messages.success(request, f"Update available: {d['label']}")
    else:
        messages.info(request, 'No newer updates on your selected channel. Every discovered version '
                      'is listed under Available Versions.')

    return redirect('core:system_updates')


def _upgrade_running():
    try:
        from core.upgrade import journal as upgrade_journal
        return upgrade_journal.assess()['state'] == 'running'
    except Exception:
        return False


def _repair_candidate(state, upgrade_state):
    """A newer build that can finish an unfinished upgrade: what the channel
    offers now, else the newest testing build. None when nothing needs
    recovery or nothing newer than the stuck revision is offered. Whether it
    contains the stuck revision is checked here when the commit is already
    local, and always again when the repair runs (core.upgrade.apply)."""
    if not state or not upgrade_state.get('needs_recovery'):
        return None
    stuck = ((upgrade_state.get('journal') or {}).get('target') or {})
    if not stuck.get('sha'):
        return None
    cands = []
    t = state.get('target')
    if t and t.get('sha'):
        cands.append({'kind': t['kind'], 'ref': t['ref'], 'sha': t['sha'],
                      'version': t.get('version') or ''})
    p = state.get('preview')
    if p and p.get('sha'):
        cands.append({'kind': 'preview', 'ref': 'main', 'sha': p['sha'],
                      'version': p.get('version') or ''})
    from core.upgrade.revision import git
    for c in cands:
        if c['sha'] == stuck['sha']:
            continue
        try:
            if git('cat-file', '-e', f"{c['sha']}^{{commit}}", timeout=10).returncode == 0:
                if git('merge-base', '--is-ancestor', stuck['sha'], c['sha'],
                       timeout=10).returncode != 0:
                    continue
                c['contains_checked'] = True
        except Exception:
            logger.exception('could not check the repair candidate')
        return c
    return None


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def repair_update(request):
    """Finish an unfinished upgrade from the browser: "resume" re-runs the
    revision it stopped on; "repair" finishes it with a newer build that
    contains that revision (the fix when the stuck revision itself is
    broken). Both reuse the verified pre-upgrade backup."""
    import json as _json
    import threading
    from core.updater import UpdateService
    from core.update_progress import UpdateProgress
    from core.upgrade import apply as upgrade_apply
    from core.upgrade import journal as upgrade_journal
    try:
        body = _json.loads(request.body or b'{}')
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mode = body.get('mode')
    if mode not in ('resume', 'repair'):
        return JsonResponse({'status': 'error', 'message': 'Unknown repair action.'}, status=400)
    assessment = upgrade_journal.assess()
    if assessment['state'] == 'running':
        return JsonResponse({'status': 'error', 'message': assessment['message']}, status=409)
    if not assessment['needs_recovery']:
        return JsonResponse({'status': 'error', 'message': 'There is no unfinished upgrade to repair.'},
                            status=409)
    stuck = (assessment.get('journal') or {}).get('target') or {}
    if body.get('stuck_sha') != stuck.get('sha'):
        return JsonResponse({'status': 'error', 'message': 'The unfinished upgrade has changed since '
                             'the page was loaded. Reload the page.'}, status=409)
    retarget = None
    if mode == 'repair':
        reviewed, _, err = _reviewed_target(request)
        if reviewed is None:
            return JsonResponse({'status': 'error', 'message':
                                 f'No reviewed revision was sent ({err}). Reload the page.'}, status=400)
        updater = UpdateService()
        info = updater.check_for_updates(force_refresh=True)
        if info.get('error'):
            return JsonResponse({'status': 'error', 'message':
                                 'Could not confirm with GitHub what is offered right now '
                                 f"({info['error']}), so nothing was started."}, status=503)
        cand = _repair_candidate(info.get('channels') or {}, assessment)
        if not cand or (cand['kind'], cand['ref'], cand['sha']) != (reviewed.kind, reviewed.ref, reviewed.sha):
            return JsonResponse({'status': 'error', 'message':
                                 f'{reviewed.ref} @ {reviewed.sha[:12]} is no longer the build offered '
                                 'for the repair. Reload the page.'}, status=409)
        reviewed.version = cand.get('version') or ''
        retarget = reviewed
    else:
        updater = UpdateService()

    progress = UpdateProgress()
    progress.start(total_steps=upgrade_apply.TOTAL_STEPS)
    user = request.user

    def run():
        try:
            updater.perform_update(user=user, progress_tracker=progress, resume=True,
                                   retarget=retarget,
                                   allow_preview=bool(retarget and retarget.kind == 'preview'),
                                   allow_prerelease=bool(retarget and retarget.kind == 'prerelease'))
        except Exception as e:
            logger.error(f'Upgrade repair failed: {e}')
            progress.finish(success=False, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    try:
        AuditLog.objects.create(
            action='system_update', user=user, username=user.username,
            description=(f"Unfinished upgrade to {stuck.get('ref')} @ {(stuck.get('sha') or '')[:12]}: "
                         + (f'repair with {retarget.ref} @ {retarget.sha[:12]}' if retarget else 'resume')
                         + f' triggered by {user.username}'),
            extra_data={'mode': mode, 'stuck': stuck, 'target': retarget.as_dict() if retarget else None})
    except Exception:
        logger.exception('Failed to write the repair audit log')
    return JsonResponse({'status': 'started'})


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def apply_update(request):
    """
    Start system update using UpdateService with proper progress tracking.
    """
    try:
        from core.updater import UpdateService
        from core.update_progress import UpdateProgress
        from core.upgrade import apply as upgrade_apply
        from core.upgrade import journal as upgrade_journal
        import threading

        # The page shows a specific revision; Apply must install exactly that
        # one. The browser sends back what it showed, and it has to be what
        # this server discovers now -- otherwise the admin reviewed something
        # else, and nothing is started.
        reviewed, body, err = _reviewed_target(request)
        if reviewed is None:
            return JsonResponse({'status': 'error', 'message':
                                 f'No reviewed revision was sent ({err}). Reload the page.'}, status=400)
        updater = UpdateService()
        # Ask GitHub now rather than trusting any stored answer: the page may
        # be minutes old. If GitHub cannot be asked, refuse rather than
        # install from a stale answer.
        info = updater.check_for_updates(force_refresh=True)
        if info.get('error'):
            return JsonResponse({'status': 'error', 'message':
                                 'Could not confirm with GitHub what this channel offers right now '
                                 f"({info['error']}), so nothing was started. Try again in a few "
                                 'minutes.'}, status=503)
        assessment = upgrade_journal.assess()
        if assessment['state'] == 'running' or assessment['needs_recovery']:
            return JsonResponse({'status': 'error', 'message': assessment['message']}, status=409)
        current = (info.get('target') or {})
        flags = {}
        selection = 'recommended'
        if (current.get('kind'), current.get('ref'), current.get('sha')) == \
                (reviewed.kind, reviewed.ref, reviewed.sha):
            reviewed.version = current.get('version') or ''
        elif body.get('recommended'):
            # "Update now" on the channel's recommendation, which has moved
            # on since the page loaded: show the new one for review.
            return JsonResponse({'status': 'error', 'reason': 'target_changed',
                                 'target': current or None, 'message':
                                 'What this channel offers has changed since the page was loaded '
                                 f"(now: {current.get('ref') or 'nothing'} "
                                 f"{(current.get('sha') or '')[:12]}). Reload the page and review it "
                                 'again.'}, status=409)
        else:
            # A version the admin picked from Available Versions, inside or
            # outside the channel: it must be one discovery offers now and
            # eligible; out-of-channel and older ones need their own
            # confirmation. The configured channel is not changed.
            from core.upgrade import catalog as upgrade_catalog
            state = info.get('channels') or {}
            rows = upgrade_catalog.build(state, upgrade_state=assessment, check_compat=False)
            row = upgrade_catalog.find(rows, reviewed.kind, reviewed.ref, reviewed.sha)
            if row is None:
                dev = next((r for r in rows if r['type'] == 'development'), None)
                if current:
                    # What was reviewed is gone (re-tagged, or main moved):
                    # show what the channel recommends now, for review.
                    return JsonResponse({'status': 'error', 'reason': 'target_changed',
                                         'target': current, 'message':
                                         f'{reviewed.ref} @ {reviewed.sha[:12]} is no longer offered '
                                         f"(now recommended: {current.get('ref')} "
                                         f"{(current.get('sha') or '')[:12]}). Review it again."},
                                        status=409)
                if reviewed.kind == 'preview' and dev:
                    return JsonResponse({'status': 'error', 'reason': 'target_changed',
                                         'target': {'kind': 'preview', 'ref': 'main', 'sha': dev['sha'],
                                                    'version': dev['version']},
                                         'message': 'main has moved since the page was loaded (now '
                                                    f"{dev['sha'][:12]}). Review the new build."},
                                        status=409)
                return JsonResponse({'status': 'error', 'reason': 'not_offered', 'message':
                                     f'{reviewed.ref} @ {reviewed.sha[:12]} is not among the versions '
                                     'GitHub offers now, so nothing was started. Reload the page.'},
                                    status=409)
            if not row['installable']:
                return JsonResponse({'status': 'error', 'reason': 'not_installable',
                                     'message': f"{row['ref']} cannot be installed: {row['reason']}"},
                                    status=409)
            if not row['in_channel'] and not body.get('confirm_out_of_channel'):
                return JsonResponse({'status': 'error', 'reason': 'confirm_required', 'message':
                                     f"{row['ref']} is outside the {info.get('channel')} channel; "
                                     'confirm installing it.'}, status=400)
            if row['relation'] == 'older' and not body.get('confirm_downgrade'):
                return JsonResponse({'status': 'error', 'reason': 'confirm_required', 'message':
                                     f"{row['ref']} is older than the installed version; confirm "
                                     'installing an older version.'}, status=400)
            reviewed.version = row['version']
            flags = {'allow_preview': reviewed.kind == 'preview' and not row['in_channel'],
                     'allow_prerelease': reviewed.kind == 'prerelease' and not row['in_channel'],
                     'allow_downgrade': row['relation'] == 'older'}
            selection = 'older version' if row['relation'] == 'older' else (
                'outside the channel' if not row['in_channel'] else 'selected')

        # Initialize progress tracker
        progress = UpdateProgress()
        progress.start(total_steps=upgrade_apply.TOTAL_STEPS)

        def run_update():
            try:
                updater.perform_update(user=request.user, progress_tracker=progress,
                                       target=reviewed, **flags)
            except Exception as e:
                logger.error(f"Update failed: {e}")
                progress.finish(success=False, error=str(e))

        update_thread = threading.Thread(target=run_update)
        update_thread.daemon = True
        update_thread.start()

        # Log the action (best-effort)
        try:
            AuditLog.objects.create(
                action='system_update',
                description=(f'Update to {reviewed.ref} @ {reviewed.sha[:12]} ({selection}) '
                             f'triggered by {request.user.username}'),
                user=request.user,
                username=request.user.username,
                extra_data={'target': reviewed.as_dict(), 'selection': selection, **flags},
            )
        except Exception:
            pass

        return JsonResponse({
            'status': 'started',
            'message': 'Update in progress...'
        })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': public_error(e, 'apply_update failed', log=logger)
        }, status=500)


def _json_superuser_required(view):
    """For JSON endpoints a page polls: 401 {"error": "signed_out"} when not
    signed in, 403 {"error": "forbidden"} for a signed-in non-superuser, never
    a redirect to the login page (fetch() would follow it and get HTML)."""
    from functools import wraps

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return JsonResponse({'error': 'signed_out'}, status=401)
        if not is_superuser(user):
            return JsonResponse({'error': 'forbidden'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


@_json_superuser_required
def update_status_api(request):
    """
    API endpoint for checking update status (for AJAX polling).
    Staff-only access.
    """
    update_info = UpdateService().check_for_updates()
    out = {k: v for k, v in update_info.items() if k != 'channels'}
    out['upgrade_running'] = _upgrade_running()
    if update_info.get('target'):
        out['target_label'] = _describe_target(update_info.get('channels') or {},
                                               update_info['target'])['label']
    return JsonResponse(out)


@_json_superuser_required
def update_progress_api(request):
    """
    API endpoint for checking update progress (for AJAX polling).
    Staff-only access.
    """
    import time as _time
    from core.update_progress import UpdateProgress
    progress = UpdateProgress().get_progress()
    # The page measures elapsed time against the server's clock, not the
    # browser's (they need not agree).
    progress['now'] = _time.time()
    return JsonResponse(progress)


@login_required
@user_passes_test(is_superuser)
def version_diagnostic(request):
    """
    Diagnostic endpoint to debug version mismatch issues.
    Shows: file content vs Python import vs worker reports
    """
    import subprocess
    import os
    from django.conf import settings

    diagnostics = {}

    # 1. Read version.py file directly
    version_file = os.path.join(settings.BASE_DIR, 'config', 'version.py')
    try:
        with open(version_file, 'r') as f:
            content = f.read()
            for line in content.split('\n'):
                if line.strip().startswith('VERSION ='):
                    diagnostics['file_content'] = line.strip()
                    break
    except Exception as e:
        diagnostics['file_content'] = public_error(e, 'Error reading file', log=logger)

    # 2. Python import (current process)
    try:
        from config.version import VERSION
        diagnostics['python_import'] = f"VERSION = '{VERSION}'"
    except Exception as e:
        diagnostics['python_import'] = public_error(e, 'Error importing', log=logger)

    # 3. Force reload and check again
    try:
        import importlib
        import config.version
        importlib.reload(config.version)
        diagnostics['python_reload'] = f"VERSION = '{config.version.VERSION}'"
    except Exception as e:
        diagnostics['python_reload'] = public_error(e, 'Error reloading', log=logger)

    # 4. UpdateService reports
    try:
        updater = UpdateService()
        diagnostics['update_service'] = f"VERSION = '{updater.current_version}'"
    except Exception as e:
        diagnostics['update_service'] = public_error(e, 'Error', log=logger)

    # 5. Git info
    try:
        result = subprocess.run(['git', 'log', '-1', '--oneline'],
                               capture_output=True, text=True, cwd=settings.BASE_DIR)
        diagnostics['git_commit'] = result.stdout.strip()
    except Exception as e:
        diagnostics['git_commit'] = public_error(e, 'Error', log=logger)

    # 6. Check for .pyc files
    try:
        pyc_path = os.path.join(settings.BASE_DIR, 'config', '__pycache__', 'version.cpython-312.pyc')
        if os.path.exists(pyc_path):
            import time
            mtime = os.path.getmtime(pyc_path)
            diagnostics['pyc_file'] = f"Exists (modified: {time.ctime(mtime)})"
        else:
            diagnostics['pyc_file'] = "Not found"
    except Exception as e:
        diagnostics['pyc_file'] = public_error(e, 'Error', log=logger)

    return JsonResponse(diagnostics, json_dumps_params={'indent': 2})


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def force_restart_services(request):
    """
    Force restart all services and clear cache.
    Use this when Update Now completes but version doesn't change.
    This is a bootstrap fix for when old buggy UpdateService is running.
    """
    import subprocess
    import logging

    logger = logging.getLogger(__name__)

    try:
        # Clear Django cache first
        cache.delete('system_update_check')
        logger.info("Cleared Django cache")

        # Detect which gunicorn service exists
        service_names = ['clientst0r-gunicorn.service']
        gunicorn_service = None

        for service in service_names:
            result = subprocess.run(
                ['systemctl', 'list-unit-files', service],
                capture_output=True,
                text=True
            )
            if service in result.stdout:
                gunicorn_service = service
                logger.info(f"Found service: {gunicorn_service}")
                break

        if not gunicorn_service:
            return JsonResponse({
                'success': False,
                'error': 'No gunicorn service found'
            }, status=500)

        # Stop service
        subprocess.run(['sudo', 'systemctl', 'stop', gunicorn_service], check=False)
        logger.info(f"Stopped {gunicorn_service}")

        # Kill any lingering processes
        subprocess.run(['sudo', 'pkill', '-9', '-f', 'gunicorn'], check=False)
        logger.info("Killed lingering gunicorn processes")

        # Wait a moment
        import time
        time.sleep(2)

        # Clear Python bytecode cache
        import os
        import shutil
        from django.conf import settings

        for root, dirs, files in os.walk(settings.BASE_DIR):
            if 'venv' in root or 'node_modules' in root:
                continue
            if '__pycache__' in dirs:
                cache_dir = os.path.join(root, '__pycache__')
                shutil.rmtree(cache_dir, ignore_errors=True)

        logger.info("Cleared Python bytecode cache")

        # Start service
        subprocess.run(['sudo', 'systemctl', 'start', gunicorn_service], check=True)
        logger.info(f"Started {gunicorn_service}")

        # Wait for service to start
        time.sleep(3)

        # Check if service is running
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', gunicorn_service],
            capture_output=True,
            text=True
        )

        if result.stdout.strip() == 'active':
            messages.success(request, 'Services restarted successfully! Refresh page to see new version.')
            return JsonResponse({
                'success': True,
                'message': 'Services restarted successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Service failed to start'
            }, status=500)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': public_error(e, 'Force restart failed', log=logger)
        }, status=500)


def _emergency_restart_rate_key(group, request):
    from core.client_ip import get_client_ip
    return get_client_ip(request) or 'unknown'


@_csrf_exempt
@require_http_methods(['POST'])
@ratelimit(key=_emergency_restart_rate_key, rate='10/h', method='POST', block=False)
def emergency_restart_webhook(request):
    """
    Emergency restart webhook - no login, authenticated by a shared secret.
    Lets an operator force-heal a stuck server remotely.

    Disabled (404) unless EMERGENCY_RESTART_SECRET is set in the environment.

    Signed form (v3.17.717, preferred): headers `X-Emergency-Timestamp: <unix
    seconds>` and `X-Emergency-Signature: <hex HMAC-SHA256(secret,
    "<timestamp>.<path>")>`. The secret never travels, the call is valid for
    five minutes and once only. Set EMERGENCY_RESTART_REQUIRE_SIGNED=true to
    refuse the plain form.

    Plain form: header `X-Emergency-Secret: <secret>` (or form field
    `secret`). Never in the query string, which ends up in access logs.
    """
    from django.http import Http404
    from django.utils.crypto import constant_time_compare
    import subprocess

    expected_secret = getattr(settings, 'EMERGENCY_RESTART_SECRET', '')
    if not expected_secret:
        raise Http404()

    if getattr(request, 'limited', False):
        return JsonResponse({'error': 'Too many attempts'}, status=429)

    signature = request.headers.get('X-Emergency-Signature') or ''
    if signature or getattr(settings, 'EMERGENCY_RESTART_REQUIRE_SIGNED', False):
        import hashlib
        import hmac as _hmac
        from api_access import webhook_guard as _wg
        try:
            ts = _wg.parse_timestamp(request.headers.get('X-Emergency-Timestamp'))
        except _wg.Refused:
            ts = None
        material = f'{ts}.{request.path}'.encode()
        expected = _hmac.new(expected_secret.encode(), material, hashlib.sha256).hexdigest()
        if ts is None or not signature or not _hmac.compare_digest(expected, signature.strip().lower()):
            return JsonResponse({'error': 'Invalid or expired signature'}, status=403)
        if not _wg.claim('emergency_restart', material, True):
            return JsonResponse({'error': 'This signed call was already used'}, status=409)
    else:
        provided_secret = (request.headers.get('X-Emergency-Secret')
                           or request.POST.get('secret') or '')
        if not provided_secret or not constant_time_compare(provided_secret, expected_secret):
            return JsonResponse({'error': 'Invalid secret'}, status=403)

    # Run auto-heal command
    try:
        result = subprocess.run(
            ['python', 'manage.py', 'auto_heal_version'],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )
    except Exception as e:
        logger.error(f"Emergency restart failed: {e}")
        return JsonResponse({'success': False}, status=500)

    if result.returncode != 0:
        logger.error(f"Emergency restart: auto_heal_version exited {result.returncode}: {result.stderr[-2000:]}")
    # Command output stays in the server log; the caller only learns the outcome.
    return JsonResponse({'success': result.returncode == 0})


@login_required
@ratelimit(key='user', rate='10/h', method='POST', block=False)
def report_bug(request):
    """
    Bug reporting endpoint - generates pre-filled GitHub issue URL.
    Users submit with their own GitHub account.
    Rate limited to 10 reports per user per hour.
    """
    from django.http import JsonResponse
    from .github_api import format_bug_report_body, generate_github_issue_url
    import sys
    import platform
    from config.version import VERSION

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        }, status=405)

    # Check if rate limited
    if getattr(request, 'limited', False):
        logger.warning(f"Bug report rate limit exceeded for user {request.user.username}")
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_rate_limited',
            object_type='bug_report',
            description=f'User exceeded rate limit (10 reports per hour)'
        )
        return JsonResponse({
            'success': False,
            'message': 'Rate limit exceeded. You can only submit 10 bug reports per hour. Please wait before submitting another report.'
        }, status=429)

    # Get form data
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    steps_to_reproduce = request.POST.get('steps_to_reproduce', '').strip()

    # Validate required fields
    if not title or not description:
        return JsonResponse({
            'success': False,
            'message': 'Title and description are required'
        }, status=400)




    
    # Collect system information
    system_info = {
        'version': VERSION,
        'django_version': f"{'.'.join(map(str, __import__('django').VERSION[:3]))}",
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'browser': request.META.get('HTTP_USER_AGENT', 'Unknown'),
        'os': platform.platform(),
        'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    }

    # Collect reporter information
    reporter_info = {
        'username': request.user.username,
        'email': request.user.email if request.user.email else None,
        'organization': request.current_organization.name if hasattr(request, 'current_organization') and request.current_organization else None
    }

    # Format issue body
    issue_body = format_bug_report_body(
        description=description,
        steps_to_reproduce=steps_to_reproduce,
        system_info=system_info,
        reporter_info=reporter_info
    )

    # Generate pre-filled GitHub issue URL
    try:
        github_url = generate_github_issue_url(
            title=title,
            body=issue_body,
            labels=['bug', 'user-reported']
        )

        # Log bug report initiation
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_initiated',
            object_type='bug_report',
            description=f'Bug report URL generated: {title}'
        )
        logger.info(f"Bug report URL generated for {request.user.username}: {title}")

        return JsonResponse({
            'success': True,
            'message': 'Opening GitHub to submit your bug report...',
            'github_url': github_url
        })

    except Exception as e:
        logger.error(f"Unexpected error in report_bug: {e}")
        import traceback
        logger.error(traceback.format_exc())
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_error',
            object_type='bug_report',
            description=f'Unexpected error: {str(e)}'
        )
        return JsonResponse({
            'success': False,
            'message': public_error(e, 'An unexpected error occurred', log=logger)
        }, status=500)


@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def mobile_app_build_progress(request, app_type):
    """
    JSON progress endpoint for the live build status page (v3.17.431).
    Counts `> Task :` lines in the build log to compute a percentage
    against an empirical total (~588 for this app on first build).
    Polled every ~1.5s by the building page's JS so the user sees
    smooth progress instead of a 5-second-meta-refresh stutter.
    """
    import os
    import json as _json
    import re as _re
    import time as _time
    from django.conf import settings as dj_settings
    from django.http import JsonResponse

    if app_type not in ('android', 'ios'):
        return JsonResponse({'error': 'invalid app_type'}, status=400)

    builds_dir = os.path.join(dj_settings.BASE_DIR, 'mobile-app', 'builds')
    status_path = os.path.join(builds_dir, f'{app_type}_build_status.json')
    log_path = os.path.join(builds_dir, f'{app_type}_build.log')
    apk_path = os.path.join(
        builds_dir, 'clientst0r.apk' if app_type == 'android' else 'clientst0r.ipa'
    )

    state = {'status': 'idle', 'message': '', 'started_at': None}
    if os.path.exists(status_path):
        try:
            with open(status_path) as fh:
                sd = _json.load(fh)
            state['status'] = sd.get('status', 'idle')
            state['message'] = sd.get('message', '')
            state['started_at'] = sd.get('timestamp')
        except (OSError, ValueError):
            pass

    # APK already exists → done.
    if os.path.exists(apk_path):
        state['status'] = 'complete'

    tasks_seen = 0
    last_task = ''
    log_tail_lines = []
    if os.path.exists(log_path):
        try:
            with open(log_path) as fh:
                raw = fh.read()
            lines = [ln for ln in raw.split('\n') if ln.strip()]
            for ln in lines:
                if _re.match(r'^>\s+Task\s+:', ln):
                    tasks_seen += 1
                    last_task = ln
            log_tail_lines = lines[-30:]
        except OSError:
            pass

    # Empirical total task count from the v3.17.427 successful build.
    # If we ever see more, bump expected_total to that.
    expected_total = max(588, tasks_seen)
    pct = 0
    if state['status'] == 'complete':
        pct = 100
    elif tasks_seen > 0:
        pct = min(99, int((tasks_seen / expected_total) * 100))

    elapsed = 0
    if state.get('started_at'):
        try:
            elapsed = max(0, int(_time.time() - float(state['started_at'])))
        except (TypeError, ValueError):
            elapsed = 0

    return JsonResponse({
        'status': state['status'],
        'message': state['message'],
        'tasks_seen': tasks_seen,
        'tasks_total_est': expected_total,
        'percent': pct,
        'current_task': last_task,
        'elapsed_s': elapsed,
        'log_tail': log_tail_lines,
    })


@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def mobile_apps_admin(request):
    """
    Admin landing page for mobile-app sideload distribution.
    Lists Android APK + iOS IPA download status with sideload
    instructions for each platform. Linked from the Admin nav
    dropdown so superusers / staff can hand the apps to techs
    in the field without going through Apple/Google stores.

    POST ?action=rebuild&platform=android — wipes the cached
    binary + status files so the next click on Build/Download
    triggers a fresh compile from the current `mobile/` source
    tree (added v3.17.397 because the cached Feb-2026 APK kept
    being re-served instead of rebuilt).
    """
    import os
    import json
    import datetime as _dt
    from django.conf import settings as dj_settings

    builds_dir = os.path.join(dj_settings.BASE_DIR, 'mobile-app', 'builds')
    os.makedirs(builds_dir, exist_ok=True)

    if request.method == 'POST' and request.POST.get('action') == 'rebuild':
        platform = request.POST.get('platform', '').strip()
        if platform in ('android', 'ios'):
            removed = []
            for fname in (
                f'clientst0r.{"apk" if platform == "android" else "ipa"}',
                f'{platform}_build_status.json',
                f'{platform}_build.log',
            ):
                fpath = os.path.join(builds_dir, fname)
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                        removed.append(fname)
                    except OSError:
                        pass
            AuditLog.objects.create(
                user=request.user,
                action='mobile_app_rebuild_requested',
                object_type='mobile_app',
                description=f'Wiped cached {platform} build artifacts: {", ".join(removed) or "nothing — already clean"}',
            )
            messages.success(
                request,
                f'Cleared cached {platform} build. Click "Build & download {platform.upper()}" to start a fresh build from the latest source.',
            )
        return redirect('core:mobile_apps_admin')

    def _build_state(app_type, filename):
        binary_path = os.path.join(builds_dir, filename)
        status_path = os.path.join(builds_dir, f'{app_type}_build_status.json')
        state = {
            'available': os.path.exists(binary_path),
            'size_mb': None,
            'mtime': None,
            'status': 'idle',
            'message': '',
        }
        if state['available']:
            try:
                st = os.stat(binary_path)
                state['size_mb'] = round(st.st_size / (1024 * 1024), 1)
                state['mtime'] = _dt.datetime.fromtimestamp(
                    st.st_mtime, tz=_dt.timezone.utc,
                )
            except OSError:
                pass
        if os.path.exists(status_path):
            try:
                with open(status_path, 'r') as fh:
                    sd = json.load(fh)
                state['status'] = sd.get('status', 'idle')
                state['message'] = sd.get('message', '')
            except (OSError, ValueError):
                pass
        return state

    return render(request, 'core/mobile_apps_admin.html', {
        'android': _build_state('android', 'clientst0r.apk'),
        'ios': _build_state('ios', 'clientst0r.ipa'),
        'has_new_codebase': os.path.isdir(
            os.path.join(dj_settings.BASE_DIR, 'mobile')
        ),
    })


@login_required
def download_mobile_app(request, app_type):
    """
    Serve mobile app downloads or auto-build if not available.
    Automatically triggers build process when apps don't exist.
    """
    import os
    import json
    import subprocess
    import threading
    import time
    from django.conf import settings
    from django.http import FileResponse, Http404, HttpResponse
    from django.shortcuts import redirect, render

    # CSP nonce for the inline <script> blocks in the hand-built pages below.
    _nonce = getattr(request, '_csp_nonce', None)
    csp_nonce = str(_nonce) if _nonce is not None else ''

    # Define mobile app paths
    MOBILE_APP_DIR = os.path.join(settings.BASE_DIR, 'mobile-app', 'builds')
    os.makedirs(MOBILE_APP_DIR, exist_ok=True)

    if app_type == 'android':
        apk_path = os.path.join(MOBILE_APP_DIR, 'clientst0r.apk')
        status_file = os.path.join(MOBILE_APP_DIR, 'android_build_status.json')

        # v3.17.429 — single-button rebuild. ?rebuild=1 wipes the cached
        # APK + status + log so the rest of this view's flow falls through
        # to a fresh build kickoff. Replaces the separate POST /core/mobile-apps/
        # `action=rebuild` round-trip that the user had to do before.
        if request.GET.get('rebuild') == '1':
            for fpath in (apk_path, status_file,
                          os.path.join(MOBILE_APP_DIR, 'android_build.log')):
                try:
                    os.remove(fpath)
                except OSError:
                    pass
            AuditLog.objects.create(
                user=request.user,
                action='mobile_app_rebuild_requested',
                object_type='mobile_app',
                description='Wiped cached android build artifacts via single-button rebuild',
            )
            # Fall through — APK is gone, no status file, will trigger build.

        # Check if APK exists
        if os.path.exists(apk_path):
            # Serve the APK file
            response = FileResponse(
                open(apk_path, 'rb'),
                content_type='application/vnd.android.package-archive'
            )
            response['Content-Disposition'] = 'attachment; filename="Client St0r.apk"'

            # Log download
            AuditLog.objects.create(
                user=request.user,
                action='mobile_app_download',
                object_type='mobile_app',
                description=f'Downloaded Android APK'
            )

            return response

        # Check if build is in progress
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status_data = json.load(f)

            # v3.17.423 — stale-status detection. If neither status file
            # nor log file has been touched in 5+ minutes while marked
            # as "building", the build process died (gunicorn restart,
            # OOM, etc.) — flip to 'failed' so the user can retry.
            log_file = os.path.join(MOBILE_APP_DIR, f'{app_type}_build.log')
            try:
                last_status = os.path.getmtime(status_file)
                last_log = (
                    os.path.getmtime(log_file)
                    if os.path.exists(log_file) else 0
                )
                quiet_secs = time.time() - max(last_status, last_log)
                if (status_data.get('status') == 'building'
                        and quiet_secs > 300):
                    minutes = int(quiet_secs / 60)
                    status_data['status'] = 'failed'
                    status_data['message'] = (
                        f'Build process appears to have died (no log activity '
                        f'for {minutes} min). Most likely cause: gunicorn was '
                        'restarted while the build was running. Click Retry '
                        'to start a fresh build.'
                    )
                    with open(status_file, 'w') as f:
                        json.dump(status_data, f)
            except OSError:
                pass

            if status_data['status'] == 'building':
                # Read build log for real-time progress
                log_file = os.path.join(MOBILE_APP_DIR, f'{app_type}_build.log')
                build_log = ''
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        build_log = f.read()
                        # v3.17.427 — widened filter. Previously stripped all
                        # `> Task :` lines (Gradle's actual progress) so the
                        # page looked frozen even while Gradle ran for
                        # minutes. Now keep almost everything and drop only
                        # npm-warn noise.
                        log_lines = []
                        for line in build_log.split('\n'):
                            stripped = line.strip()
                            if not stripped:
                                continue
                            low = stripped.lower()
                            if low.startswith('npm warn') or low.startswith('warning:'):
                                continue
                            log_lines.append(line)
                        # Show the last 60 lines so the page conveys ongoing
                        # work — gradle emits many `> Task :` lines.
                        build_log = '\n'.join(log_lines[-60:]) if len(log_lines) > 60 else '\n'.join(log_lines)
                        if not build_log.strip():
                            build_log = 'Build in progress…'

                # Build in progress - show status page with live log
                # v3.17.431 — replaced the 5-second meta-refresh with JS that
                # polls /core/mobile-apps/build-progress/android/ every 1.5s
                # and updates the progress bar + log live. Bar is driven by
                # `> Task :` line count vs an empirical total (~588 for this
                # app), so the percentage is real, not a striped-only animation.
                progress_url = '/core/mobile-apps/build-progress/android/'
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Building Android App - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 1200px; margin: 30px auto; padding: 20px; }}
                            .spinner {{ border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }}
                            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #58a6ff; }}
                            .log-container {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 18px; max-height: 480px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 12.5px; line-height: 1.45; color: #c9d1d9; white-space: pre-wrap; word-break: break-word; }}
                            .progress-bar-container {{ width: 100%; height: 18px; background: #30363d; border-radius: 6px; overflow: hidden; margin: 20px 0 8px; position: relative; }}
                            .progress-bar {{ height: 100%; background: linear-gradient(90deg, #2ea043, #3fb950); transition: width 0.5s ease; }}
                            .progress-bar.indeterminate {{ background: linear-gradient(90deg, #58a6ff, #79c0ff, #58a6ff); background-size: 200% 100%; animation: progressSlide 2s linear infinite; }}
                            @keyframes progressSlide {{ 0% {{ background-position: 100% 0; }} 100% {{ background-position: -100% 0; }} }}
                            .progress-meta {{ display: flex; justify-content: space-between; font-size: 0.9rem; color: #8b949e; }}
                            .current-task {{ font-family: 'Courier New', monospace; font-size: 0.85rem; color: #79c0ff; padding: 8px 12px; background: rgba(88,166,255,0.08); border-left: 3px solid #58a6ff; border-radius: 3px; word-break: break-all; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <div class="status-header" style="display:flex;align-items:center;justify-content:center;">
                                    <div class="spinner"></div>
                                    <h1 style="margin: 0;">Building Android App…</h1>
                                </div>
                                <p class="lead text-center" id="status-msg"><strong>Status:</strong> <span id="status-text">{status_data['message']}</span></p>

                                <div class="progress-bar-container">
                                    <div id="progress-bar" class="progress-bar indeterminate" style="width: 0%;"></div>
                                </div>
                                <div class="progress-meta">
                                    <span><strong id="progress-pct">0%</strong> · <span id="task-count">0</span> tasks</span>
                                    <span>Elapsed: <strong id="elapsed-time" style="color:#58a6ff;">0m 00s</strong></span>
                                </div>

                                <div id="current-task-row" style="margin-top:15px;display:none;">
                                    <p class="text-muted" style="margin-bottom:6px;font-size:.85rem;">Current task:</p>
                                    <div id="current-task" class="current-task">—</div>
                                </div>

                                <p class="text-center text-muted" style="margin-top:15px;"><small>Auto-updates every 1.5s • You can close this tab</small></p>
                            </div>

                            <div class="card">
                                <h3 style="margin-bottom: 15px;">📝 Build Progress Log</h3>
                                <div id="log-container" class="log-container">{build_log if build_log else 'Waiting for build to start…'}</div>
                                <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Live tail · <a href="/core/mobile-apps/" style="color: #58a6ff;">View Mobile Apps page</a></small></p>
                            </div>
                        </div>

                        <script nonce="{csp_nonce}">
                            (function() {{
                                var progressUrl = '{progress_url}';
                                var pollInterval = 1500;
                                var startedAt = null;

                                function fmtElapsed(seconds) {{
                                    var s = Math.max(0, Math.floor(seconds || 0));
                                    var m = Math.floor(s / 60);
                                    var ss = s % 60;
                                    return m + 'm ' + (ss < 10 ? '0' : '') + ss + 's';
                                }}

                                function poll() {{
                                    fetch(progressUrl + '?_=' + Date.now(), {{cache: 'no-store'}})
                                        .then(function(r) {{ return r.ok ? r.json() : null; }})
                                        .then(function(d) {{
                                            if (!d) {{ setTimeout(poll, pollInterval); return; }}
                                            // Status text
                                            var st = document.getElementById('status-text');
                                            if (st) st.textContent = d.message || ('Tasks: ' + d.tasks_seen);
                                            // Bar
                                            var bar = document.getElementById('progress-bar');
                                            var pctEl = document.getElementById('progress-pct');
                                            var taskEl = document.getElementById('task-count');
                                            if (bar) {{
                                                bar.style.width = (d.percent || 0) + '%';
                                                if (d.percent && d.percent > 0) {{
                                                    bar.classList.remove('indeterminate');
                                                }}
                                            }}
                                            if (pctEl) pctEl.textContent = (d.percent || 0) + '%';
                                            if (taskEl) taskEl.textContent = d.tasks_seen + ' / ~' + d.tasks_total_est;
                                            // Elapsed
                                            var el = document.getElementById('elapsed-time');
                                            if (el) el.textContent = fmtElapsed(d.elapsed_s);
                                            // Current task
                                            var ctRow = document.getElementById('current-task-row');
                                            var ct = document.getElementById('current-task');
                                            if (ct && d.current_task) {{
                                                ct.textContent = d.current_task;
                                                if (ctRow) ctRow.style.display = '';
                                            }}
                                            // Log tail
                                            if (d.log_tail && d.log_tail.length) {{
                                                var lc = document.getElementById('log-container');
                                                if (lc) {{
                                                    lc.textContent = d.log_tail.join('\\n');
                                                    lc.scrollTop = lc.scrollHeight;
                                                }}
                                            }}
                                            // State transitions
                                            if (d.status === 'complete') {{
                                                window.location.href = '/core/download-mobile-app/android/';
                                                return;
                                            }} else if (d.status === 'failed') {{
                                                window.location.reload();
                                                return;
                                            }}
                                            setTimeout(poll, pollInterval);
                                        }})
                                        .catch(function() {{ setTimeout(poll, pollInterval); }});
                                }}
                                poll();
                            }})();
                        </script>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'complete':
                # Build complete but file not downloaded yet
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Android App Build Complete - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 800px; margin: 50px auto; padding: 40px; }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #3fb950; }}
                            code {{ background: #30363d; padding: 2px 6px; border-radius: 3px; color: #ffa657; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <h1>&#x2705; Android App Build Complete!</h1>
                                <p class="lead">{status_data['message']}</p>
                                <hr>
                                <h5>Next Steps:</h5>
                                <ol class="text-start">
                                    <li>Download the APK from the URL above</li>
                                    <li>Place it at: <code>~/clientst0r/mobile-app/builds/clientst0r.apk</code></li>
                                    <li>Refresh this page to download</li>
                                </ol>
                                <hr>
                                <a href="#" onclick="history.back(); return false;" class="btn btn-secondary">&larr; Go Back</a>
                                <a href="#" onclick="location.reload(); return false;" class="btn btn-primary">Refresh Page</a>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'failed':
                # v3.17.429 — Show the actual failure with build log so the
                # user can see WHY it failed. Previously we deleted the
                # status file and rendered a generic "Not Created Yet" page,
                # which discarded the error. The page no longer auto-refreshes
                # so the error stays put until the user explicitly retries.
                if request.GET.get('retry') == '1':
                    # Clear status and trigger new build
                    try:
                        os.remove(status_file)
                    except OSError:
                        pass
                    # Fall through to trigger build below
                else:
                    # Read the build log so we can show what actually failed.
                    log_file = os.path.join(MOBILE_APP_DIR, f'{app_type}_build.log')
                    fail_log = ''
                    if os.path.exists(log_file):
                        try:
                            with open(log_file, 'r') as f:
                                raw = f.read()
                            lines = [ln for ln in raw.split('\n') if ln.strip()]
                            fail_log = '\n'.join(lines[-80:])
                        except OSError:
                            fail_log = '(could not read build log)'
                    else:
                        fail_log = '(no build log on disk)'

                    err_msg = status_data.get('message') or 'Build failed.'
                    # Escape HTML in the log so error markers show as text
                    import html as _html
                    safe_log = _html.escape(fail_log)
                    safe_msg = _html.escape(err_msg)
                    return HttpResponse(f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <title>Android Build Failed - Client St0r</title>
                            <meta charset="UTF-8">
                            <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                            <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                            <style>
                                body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                                .container {{ max-width: 1100px; margin: 30px auto; padding: 20px; }}
                                .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 25px; margin-bottom: 20px; }}
                                .card.danger {{ border-color: #da3633; }}
                                h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                                h1 {{ color: #f85149; margin-top: 0; }}
                                p, .lead {{ color: #c9d1d9; }}
                                .text-muted {{ color: #8b949e !important; }}
                                .btn-retry {{ background: #238636; border: 1px solid #2ea043; color: white; padding: 10px 24px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-right: 10px; }}
                                .btn-retry:hover {{ background: #2ea043; color: white; }}
                                .btn-secondary {{ background: #30363d; border: 1px solid #484f58; color: white; padding: 10px 24px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-right: 10px; }}
                                .btn-secondary:hover {{ background: #484f58; color: white; }}
                                .log-container {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 18px; max-height: 520px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 12.5px; line-height: 1.45; color: #c9d1d9; white-space: pre-wrap; word-break: break-word; }}
                                .err-msg {{ background: #2d1010; border-left: 4px solid #f85149; padding: 12px 16px; margin: 15px 0; border-radius: 4px; color: #ffa198; }}
                            </style>
                            <script nonce="{csp_nonce}">
                                // Auto-scroll log to bottom on load
                                window.addEventListener('load', function() {{
                                    var c = document.getElementById('log-container');
                                    if (c) c.scrollTop = c.scrollHeight;
                                }});
                            </script>
                        </head>
                        <body>
                            <div class="container">
                                <div class="card danger">
                                    <h1>❌ Android Build Failed</h1>
                                    <div class="err-msg"><strong>Error:</strong> {safe_msg}</div>
                                    <p class="text-muted" style="margin-bottom: 0;">The build log is below. Read the last lines for the actual cause — usually a Gradle, NDK, or expo-modules error.</p>
                                    <div style="margin-top: 18px;">
                                        <a href="?retry=1" class="btn-retry">🔁 Retry build</a>
                                        <a href="/core/mobile-apps/" class="btn-secondary">← Back to Mobile Apps</a>
                                    </div>
                                </div>

                                <div class="card">
                                    <h3 style="margin-top: 0;">📝 Build Log (last 80 non-blank lines)</h3>
                                    <div id="log-container" class="log-container">{safe_log if safe_log else '(empty)'}</div>
                                </div>
                            </div>
                        </body>
                        </html>
                    """, content_type='text/html; charset=utf-8')

        # v3.17.423 — detach the build into its own process group / session
        # so it survives a gunicorn restart. Previously the daemon-thread +
        # subprocess.run setup made the build a child of the gunicorn worker;
        # any subsequent `systemctl reload clientst0r-gunicorn.service` would
        # SIGTERM the worker's process tree and kill the gradle build mid-
        # flight, leaving the status file stuck on "building" forever.
        #
        # Use start_new_session=True (Python wrapper around setsid()) so the
        # subprocess becomes its own session leader, detached from the gunicorn
        # worker's controlling terminal + process group.
        venv_python = os.path.join(settings.BASE_DIR, 'venv', 'bin', 'python')
        try:
            subprocess.Popen(
                [venv_python, 'manage.py', 'build_mobile_app', 'android'],
                cwd=settings.BASE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except Exception as exc:
            logger.error(f'Failed to launch detached build: {exc}')

        # Log build initiation
        AuditLog.objects.create(
            user=request.user,
            action='mobile_app_build_started',
            object_type='mobile_app',
            description=f'Started Android APK build'
        )

        # Return building status page with log viewer
        current_time = time.time()
        return HttpResponse(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Building Android App - Client St0r</title>
                <meta charset="UTF-8">
                <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                <meta http-equiv="Pragma" content="no-cache">
                <meta http-equiv="Expires" content="0">
                <meta http-equiv="refresh" content="5">
                <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                <style>
                    body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                    .container {{ max-width: 1200px; margin: 30px auto; padding: 20px; }}
                    .spinner {{ border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }}
                    @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }}
                    h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                    p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                    strong {{ color: #ffffff; }}
                    .text-muted {{ color: #8b949e !important; }}
                    h1 {{ color: #58a6ff; }}
                    .log-container {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 20px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5; color: #c9d1d9; }}
                    .log-container::-webkit-scrollbar {{ width: 10px; }}
                    .log-container::-webkit-scrollbar-track {{ background: #161b22; }}
                    .log-container::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 5px; }}
                    .status-header {{ display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }}
                    .progress-bar-container {{ width: 100%; height: 8px; background: #30363d; border-radius: 4px; overflow: hidden; margin: 20px 0; }}
                    .progress-bar {{ height: 100%; background: linear-gradient(90deg, #58a6ff, #79c0ff, #58a6ff); background-size: 200% 100%; animation: progressSlide 2s linear infinite; }}
                    @keyframes progressSlide {{ 0% {{ background-position: 100% 0; }} 100% {{ background-position: -100% 0; }} }}
                </style>
                <script nonce="{csp_nonce}">
                    window.onload = function() {{
                        var logContainer = document.getElementById('log-container');
                        if (logContainer) {{
                            logContainer.scrollTop = logContainer.scrollHeight;
                        }}

                        // Show elapsed time with live updates
                        var startTime = {current_time} * 1000;
                        console.log('Build start time:', new Date(startTime));
                        console.log('Current time:', new Date());

                        function updateElapsedTime() {{
                            var elapsed = Math.floor((Date.now() - startTime) / 1000);
                            if (elapsed < 0) elapsed = 0;
                            var minutes = Math.floor(elapsed / 60);
                            var seconds = elapsed % 60;
                            var elapsedText = minutes + 'm ' + (seconds < 10 ? '0' : '') + seconds + 's';
                            var elapsedElement = document.getElementById('elapsed-time');
                            if (elapsedElement) {{
                                elapsedElement.textContent = elapsedText;
                                elapsedElement.style.color = '#58a6ff';  // Ensure visibility
                            }}
                        }}

                        // Start immediately and update every second
                        updateElapsedTime();
                        setInterval(updateElapsedTime, 1000);

                        // Also show page refresh countdown
                        var refreshIn = 5;
                        setInterval(function() {{
                            refreshIn--;
                            if (refreshIn <= 0) refreshIn = 5;
                            var refreshElement = document.getElementById('refresh-countdown');
                            if (refreshElement) refreshElement.textContent = refreshIn;
                        }}, 1000);
                    }};
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <div class="status-header">
                            <div class="spinner"></div>
                            <h1 style="margin: 0;">Building Android App...</h1>
                        </div>
                        <p class="lead text-center"><strong>Status:</strong> Build started! Initializing...</p>
                        <div class="progress-bar-container">
                            <div class="progress-bar"></div>
                        </div>
                        <p class="text-center"><strong>Elapsed Time:</strong> <span id="elapsed-time" style="color: #58a6ff; font-size: 1.2em;">Calculating...</span></p>
                        <p class="text-center text-muted"><small>Page refreshes in <span id="refresh-countdown">5</span> seconds • You can close this tab</small></p>
                    </div>

                    <div class="card">
                        <h3 style="margin-bottom: 15px;">&#x1F4DD; Build Progress Log</h3>
                        <div id="log-container" class="log-container">
                            <pre style="margin: 0; color: #c9d1d9;">Build initializing... Log will appear shortly.</pre>
                        </div>
                        <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Real-time build output will display here</small></p>
                    </div>
                </div>
            </body>
            </html>
        """, content_type='text/html; charset=utf-8')

    elif app_type == 'ios':
        ipa_path = os.path.join(MOBILE_APP_DIR, 'clientst0r.ipa')
        status_file = os.path.join(MOBILE_APP_DIR, 'ios_build_status.json')

        # Check if IPA exists
        if os.path.exists(ipa_path):
            # Serve the IPA file
            response = FileResponse(
                open(ipa_path, 'rb'),
                content_type='application/octet-stream'
            )
            response['Content-Disposition'] = 'attachment; filename="Client St0r.ipa"'

            # Log download
            AuditLog.objects.create(
                user=request.user,
                action='mobile_app_download',
                object_type='mobile_app',
                description=f'Downloaded iOS IPA'
            )

            return response

        # Check if build is in progress
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status_data = json.load(f)

            if status_data['status'] == 'building':
                # Read build log for real-time progress
                log_file = os.path.join(MOBILE_APP_DIR, f'{app_type}_build.log')
                build_log = ''
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        build_log = f.read()
                        # v3.17.427 — widened filter. Previously stripped all
                        # `> Task :` lines (Gradle's actual progress) so the
                        # page looked frozen even while Gradle ran for
                        # minutes. Now keep almost everything and drop only
                        # npm-warn noise.
                        log_lines = []
                        for line in build_log.split('\n'):
                            stripped = line.strip()
                            if not stripped:
                                continue
                            low = stripped.lower()
                            if low.startswith('npm warn') or low.startswith('warning:'):
                                continue
                            log_lines.append(line)
                        # Show the last 60 lines so the page conveys ongoing
                        # work — gradle emits many `> Task :` lines.
                        build_log = '\n'.join(log_lines[-60:]) if len(log_lines) > 60 else '\n'.join(log_lines)
                        if not build_log.strip():
                            build_log = 'Build in progress…'

                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Building iOS App - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <meta http-equiv="refresh" content="5">
                        <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 1200px; margin: 30px auto; padding: 20px; }}
                            .spinner {{ border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }}
                            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #58a6ff; }}
                            .log-container {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 20px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5; color: #c9d1d9; }}
                            .log-container::-webkit-scrollbar {{ width: 10px; }}
                            .log-container::-webkit-scrollbar-track {{ background: #161b22; }}
                            .log-container::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 5px; }}
                            .status-header {{ display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }}
                            .progress-bar-container {{ width: 100%; height: 8px; background: #30363d; border-radius: 4px; overflow: hidden; margin: 20px 0; }}
                            .progress-bar {{ height: 100%; background: linear-gradient(90deg, #58a6ff, #79c0ff, #58a6ff); background-size: 200% 100%; animation: progressSlide 2s linear infinite; }}
                            @keyframes progressSlide {{ 0% {{ background-position: 100% 0; }} 100% {{ background-position: -100% 0; }} }}
                        </style>
                        <script nonce="{csp_nonce}">
                            // Auto-scroll to bottom of log
                            window.onload = function() {{
                                var logContainer = document.getElementById('log-container');
                                if (logContainer) {{
                                    logContainer.scrollTop = logContainer.scrollHeight;
                                }}
                            }};
                        </script>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <div class="status-header">
                                    <div class="spinner"></div>
                                    <h1 style="margin: 0;">Building iOS App...</h1>
                                </div>
                                <p class="lead text-center"><strong>Status:</strong> {status_data['message']}</p>
                                <div class="progress-bar-container">
                                    <div class="progress-bar"></div>
                                </div>
                                <p class="text-center"><strong>Elapsed Time:</strong> <span id="elapsed-time" style="color: #58a6ff; font-size: 1.2em;">Calculating...</span></p>
                                <p class="text-center text-muted"><small>Page refreshes in <span id="refresh-countdown">5</span> seconds • You can close this tab</small></p>
                            </div>

                            <div class="card">
                                <h3 style="margin-bottom: 15px;">&#x1F4DD; Build Progress Log</h3>
                                <div id="log-container" class="log-container">
                                    <pre style="margin: 0; color: #c9d1d9;">{build_log if build_log else 'Waiting for build to start...'}</pre>
                                </div>
                                <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Showing last 60 lines of build output. <a href="/core/mobile-apps/" style="color: #58a6ff;">View Mobile Apps page</a></small></p>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'complete':
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>iOS App Build Complete - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 800px; margin: 50px auto; padding: 40px; }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #3fb950; }}
                            code {{ background: #30363d; padding: 2px 6px; border-radius: 3px; color: #ffa657; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <h1>&#x2705; iOS App Build Complete!</h1>
                                <p class="lead">{status_data['message']}</p>
                                <hr>
                                <h5>Next Steps:</h5>
                                <ol class="text-start">
                                    <li>Download the IPA from the URL above</li>
                                    <li>Place it at: <code>~/clientst0r/mobile-app/builds/clientst0r.ipa</code></li>
                                    <li>Refresh this page to download</li>
                                </ol>
                                <p class="alert alert-warning">IPA files require TestFlight, enterprise distribution, or App Store for installation.</p>
                                <hr>
                                <a href="#" onclick="history.back(); return false;" class="btn btn-secondary">&larr; Go Back</a>
                                <a href="#" onclick="location.reload(); return false;" class="btn btn-primary">Refresh Page</a>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'failed':
                # Delete failed status file so we show clean state
                try:
                    os.remove(status_file)
                except Exception:
                    pass

                # Show friendly "not created yet" page instead of error
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>iOS App - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 800px; margin: 50px auto; padding: 40px; text-align: center; }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 40px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #58a6ff; margin-bottom: 20px; }}
                            .info-icon {{ font-size: 64px; margin-bottom: 20px; }}
                            .btn-build {{ background: #238636; border: 1px solid #2ea043; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; }}
                            .btn-build:hover {{ background: #2ea043; color: white; }}
                            .btn-secondary {{ background: #30363d; border: 1px solid #484f58; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; margin-left: 10px; }}
                            .btn-secondary:hover {{ background: #484f58; color: white; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <div class="info-icon">📱</div>
                                <h1>iOS App Not Available</h1>
                                <p class="lead">iOS app builds are not currently supported.</p>
                                <p class="text-muted">Building iOS apps requires a macOS system with Xcode. Consider using the Android app or web interface instead.</p>
                                <div class="mt-4">
                                    <a href="#" onclick="history.back(); return false;" class="btn-secondary">Go Back</a>
                                </div>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

        # No IPA and no build in progress - show friendly message
        # iOS builds require macOS with Xcode, so we don't support them
        return HttpResponse(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>iOS App - Client St0r</title>
                <meta charset="UTF-8">
                <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                <meta http-equiv="Pragma" content="no-cache">
                <meta http-equiv="Expires" content="0">
                <link href="{static(BOOTSTRAP_CSS)}" rel="stylesheet">
                <style>
                    body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                    .container {{ max-width: 800px; margin: 50px auto; padding: 40px; text-align: center; }}
                    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 40px; }}
                    h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                    p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                    strong {{ color: #ffffff; }}
                    .text-muted {{ color: #8b949e !important; }}
                    h1 {{ color: #58a6ff; margin-bottom: 20px; }}
                    .info-icon {{ font-size: 64px; margin-bottom: 20px; }}
                    .btn-secondary {{ background: #30363d; border: 1px solid #484f58; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; }}
                    .btn-secondary:hover {{ background: #484f58; color: white; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <div class="info-icon">📱</div>
                        <h1>iOS App Not Available</h1>
                        <p class="lead">iOS app builds are not currently supported.</p>
                        <p class="text-muted">Building iOS apps requires a macOS system with Xcode installed. This Linux server cannot build iOS apps.</p>
                        <p class="text-muted">Consider using the Android app or accessing Client St0r through your web browser instead.</p>
                        <div class="mt-4">
                            <a href="#" onclick="history.back(); return false;" class="btn-secondary">Go Back</a>
                        </div>
                    </div>
                </div>
            </body>
            </html>
        """, content_type='text/html; charset=utf-8')

        AuditLog.objects.create(
            user=request.user,
            action='mobile_app_build_started',
            object_type='mobile_app',
            description=f'Started iOS IPA build'
        )

        return HttpResponse("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Building iOS App - Client St0r</title>
                <meta charset="UTF-8">
                <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                <meta http-equiv="Pragma" content="no-cache">
                <meta http-equiv="Expires" content="0">
                <meta http-equiv="refresh" content="5">
                <link href="__BOOTSTRAP_CSS__" rel="stylesheet">
                <style>
                    body { background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
                    .container { max-width: 1200px; margin: 30px auto; padding: 20px; }
                    .spinner { border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }
                    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                    .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }
                    h1, h2, h3, h4, h5 { color: #ffffff !important; }
                    p, .lead { color: #ffffff !important; font-size: 1.1rem; }
                    strong { color: #ffffff; }
                    .text-muted { color: #8b949e !important; }
                    h1 { color: #58a6ff; }
                    .log-container { background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 20px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5; color: #c9d1d9; }
                    .log-container::-webkit-scrollbar { width: 10px; }
                    .log-container::-webkit-scrollbar-track { background: #161b22; }
                    .log-container::-webkit-scrollbar-thumb { background: #30363d; border-radius: 5px; }
                    .status-header { display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }
                </style>
                <script nonce="__CSP_NONCE__">
                    window.onload = function() {{
                        var logContainer = document.getElementById('log-container');
                        if (logContainer) {{
                            logContainer.scrollTop = logContainer.scrollHeight;
                        }}

                        // Show elapsed time with live updates
                        var startTime = {status_data.get('timestamp', time.time())} * 1000;
                        console.log('Build start time:', new Date(startTime));
                        console.log('Current time:', new Date());

                        function updateElapsedTime() {{
                            var elapsed = Math.floor((Date.now() - startTime) / 1000);
                            if (elapsed < 0) elapsed = 0;
                            var minutes = Math.floor(elapsed / 60);
                            var seconds = elapsed % 60;
                            var elapsedText = minutes + 'm ' + (seconds < 10 ? '0' : '') + seconds + 's';
                            var elapsedElement = document.getElementById('elapsed-time');
                            if (elapsedElement) {{
                                elapsedElement.textContent = elapsedText;
                                elapsedElement.style.color = '#58a6ff';  // Ensure visibility
                            }}
                        }}

                        // Start immediately and update every second
                        updateElapsedTime();
                        setInterval(updateElapsedTime, 1000);

                        // Also show page refresh countdown
                        var refreshIn = 5;
                        setInterval(function() {{
                            refreshIn--;
                            if (refreshIn <= 0) refreshIn = 5;
                            var refreshElement = document.getElementById('refresh-countdown');
                            if (refreshElement) refreshElement.textContent = refreshIn;
                        }}, 1000);
                    }};
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <div class="status-header">
                            <div class="spinner"></div>
                            <h1 style="margin: 0;">Building iOS App...</h1>
                        </div>
                        <p class="lead text-center"><strong>Status:</strong> Build started! Initializing...</p>
                        <p class="text-center text-muted"><small>Page refreshes every 5 seconds. You can close this tab and come back later.</small></p>
                    </div>

                    <div class="card">
                        <h3 style="margin-bottom: 15px;">&#x1F4DD; Build Progress Log</h3>
                        <div id="log-container" class="log-container">
                            <pre style="margin: 0; color: #c9d1d9;">Build initializing... Log will appear shortly.</pre>
                        </div>
                        <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Real-time build output will display here</small></p>
                    </div>
                </div>
            </body>
            </html>
        """.replace('__CSP_NONCE__', csp_nonce).replace('__BOOTSTRAP_CSS__', static(BOOTSTRAP_CSS)), content_type='text/html; charset=utf-8')

    else:
        raise Http404("Invalid app type")


@login_required
def download_browser_extension(request):
    """
    Serve the browser extension as a ZIP download with install instructions.
    """
    import os
    import zipfile
    import io
    from django.http import FileResponse, HttpResponse

    ext_dir = os.path.join(settings.BASE_DIR, 'clientst0r-extension')

    if request.GET.get('download') == '1' and os.path.isdir(ext_dir):
        # Stream a ZIP of the extension directory
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(ext_dir):
                # Skip __pycache__ and hidden dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
                for filename in files:
                    filepath = os.path.join(root, filename)
                    arcname = os.path.relpath(filepath, os.path.dirname(ext_dir))
                    zf.write(filepath, arcname)
        buf.seek(0)
        response = FileResponse(buf, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="clientst0r-extension.zip"'
        return response

    # Show install instructions page
    ext_exists = os.path.isdir(ext_dir)
    return render(request, 'core/browser_extension.html', {
        'ext_exists': ext_exists,
        'version': get_version(),
    })


def install_app(request):
    """
    Public install/add-to-home-screen page. No login required so it can be
    shared with staff via a link or QR code.
    """
    import qrcode, io
    from django.http import HttpResponse

    # Serve the QR code as PNG when ?qr=1
    if request.GET.get('qr') == '1':
        base = f"{request.scheme}://{request.get_host()}"
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
        qr.add_data(base)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    site_url = f"{request.scheme}://{request.get_host()}"
    return render(request, 'core/install_app.html', {
        'site_url': site_url,
        'version': get_version(),
    })
