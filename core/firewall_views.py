"""
Firewall management views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from core.models import FirewallSettings, FirewallIPRule, FirewallCountryRule, FirewallLog
import logging

logger = logging.getLogger('core')


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def firewall_settings(request):
    """Firewall settings and rules management."""
    settings = FirewallSettings.get_settings()

    if request.method == 'POST':
        # Update settings
        settings.ip_firewall_enabled = request.POST.get('ip_firewall_enabled') == 'on'
        settings.ip_firewall_mode = request.POST.get('ip_firewall_mode', 'blocklist')
        settings.geoip_firewall_enabled = request.POST.get('geoip_firewall_enabled') == 'on'
        settings.geoip_firewall_mode = request.POST.get('geoip_firewall_mode', 'blocklist')
        settings.bypass_for_staff = request.POST.get('bypass_for_staff') == 'on'
        settings.bypass_for_api = request.POST.get('bypass_for_api') == 'on'
        settings.log_blocked_requests = request.POST.get('log_blocked_requests') == 'on'
        settings.updated_by = request.user
        settings.save()

        messages.success(request, 'Firewall settings updated successfully.')
        return redirect('core:firewall_settings')

    # Get rules and logs
    ip_rules = FirewallIPRule.objects.all()
    country_rules = FirewallCountryRule.objects.all()
    recent_blocks = FirewallLog.objects.all()[:20]

    # Get statistics
    from django.utils import timezone
    from datetime import timedelta

    total_blocks_today = FirewallLog.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=1)
    ).count()

    context = {
        'settings': settings,
        'ip_rules': ip_rules,
        'country_rules': country_rules,
        'recent_blocks': recent_blocks,
        'total_blocks_today': total_blocks_today,
        'ip_rules_count': ip_rules.count(),
        'country_rules_count': country_rules.count(),
    }

    return render(request, 'core/firewall_settings.html', context)


@login_required
@user_passes_test(is_superuser)
def firewall_ip_rules(request):
    """Manage IP firewall rules."""
    if request.method == 'POST':
        # Add new IP rule
        ip_address = request.POST.get('ip_address', '').strip()
        description = request.POST.get('description', '').strip()

        if ip_address:
            try:
                FirewallIPRule.objects.create(
                    ip_address=ip_address,
                    description=description,
                    created_by=request.user
                )
                messages.success(request, f'IP rule added: {ip_address}')
            except Exception as e:
                messages.error(request, f'Error adding IP rule: {str(e)}')
        else:
            messages.error(request, 'IP address is required.')

        return redirect('core:firewall_ip_rules')

    rules = FirewallIPRule.objects.all()

    context = {
        'rules': rules,
    }

    return render(request, 'core/firewall_ip_rules.html', context)


@login_required
@user_passes_test(is_superuser)
@require_POST
def firewall_ip_rule_delete(request, pk):
    """Delete an IP firewall rule."""
    rule = get_object_or_404(FirewallIPRule, pk=pk)
    ip_address = rule.ip_address
    rule.delete()
    messages.success(request, f'IP rule deleted: {ip_address}')
    return redirect('core:firewall_ip_rules')


@login_required
@user_passes_test(is_superuser)
@require_POST
def firewall_ip_rule_toggle(request, pk):
    """Toggle an IP firewall rule active state."""
    rule = get_object_or_404(FirewallIPRule, pk=pk)
    rule.is_active = not rule.is_active
    rule.save()

    status = "enabled" if rule.is_active else "disabled"
    messages.success(request, f'IP rule {status}: {rule.ip_address}')
    return redirect('core:firewall_ip_rules')


@login_required
@user_passes_test(is_superuser)
def firewall_country_rules(request):
    """Manage country firewall rules."""
    if request.method == 'POST' and 'map_codes' in request.POST:
        # v3.17.522 — the world map posts the whole selection; reconcile against
        # it. Names come from our own ISO table, never from the browser: these
        # rows drive a firewall and are shown back to admins.
        from core.geoip_map import name_for, normalise_codes

        selected = normalise_codes(request.POST.get('map_codes', ''))
        existing = {r.country_code.upper(): r for r in FirewallCountryRule.objects.all()}

        added, removed = 0, 0
        for code in selected:
            if code not in existing:
                FirewallCountryRule.objects.create(
                    country_code=code,
                    country_name=name_for(code) or code,
                    created_by=request.user,
                )
                added += 1
        for code, rule in existing.items():
            if code not in selected:
                rule.delete()
                removed += 1

        if added or removed:
            messages.success(
                request,
                f'Country rules updated from map: {added} added, {removed} removed.')
        else:
            messages.info(request, 'No country rule changes to apply.')
        return redirect('core:firewall_country_rules')

    if request.method == 'POST':
        # Add new country rule
        country_code = request.POST.get('country_code', '').strip().upper()
        country_name = request.POST.get('country_name', '').strip()

        if country_code and country_name:
            try:
                FirewallCountryRule.objects.create(
                    country_code=country_code,
                    country_name=country_name,
                    created_by=request.user
                )
                messages.success(request, f'Country rule added: {country_name} ({country_code})')
            except Exception as e:
                messages.error(request, f'Error adding country rule: {str(e)}')
        else:
            messages.error(request, 'Country code and name are required.')

        return redirect('core:firewall_country_rules')

    rules = FirewallCountryRule.objects.all()

    # Common countries for quick add
    common_countries = [
        ('US', 'United States'),
        ('GB', 'United Kingdom'),
        ('CA', 'Canada'),
        ('AU', 'Australia'),
        ('DE', 'Germany'),
        ('FR', 'France'),
        ('CN', 'China'),
        ('RU', 'Russia'),
        ('IN', 'India'),
        ('BR', 'Brazil'),
    ]

    # v3.17.522 — map context. A single list here: a country either has a rule
    # or it does not; whether that means "blocked" or "allowed" is decided by
    # the firewall's own mode setting, not per country.
    from core.geoip_map import COLOR_SINGLE, build_lists, map_background_context
    from core.models import SystemSetting

    # Two different settings models: the backdrop is cosmetic branding
    # (SystemSetting), the allowlist/blocklist mode is firewall behaviour
    # (FirewallSettings). Reading the mode off the wrong one is how this first
    # went wrong — the page 500'd because SystemSetting has no such field.
    settings_obj = SystemSetting.get_settings()
    firewall_settings = FirewallSettings.get_settings()
    active_codes = [r.country_code.upper() for r in rules if r.is_active]

    context = {
        'rules': rules,
        'common_countries': common_countries,
        'lists_json': build_lists(
            ('rules', 'Countries with a rule', COLOR_SINGLE,
             'id_map_codes', active_codes),
        ),
        'firewall_mode': firewall_settings.geoip_firewall_mode,
        'background_modes': SystemSetting.GEOIP_MAP_BACKGROUND_MODES,
        'background_patterns': SystemSetting.GEOIP_MAP_PATTERNS,
        **map_background_context(settings_obj),
    }

    return render(request, 'core/firewall_country_rules.html', context)


@login_required
@user_passes_test(is_superuser)
@require_POST
def geoip_map_background(request):
    """Save the GeoIP map backdrop (v3.17.522).

    Cosmetic only — it never affects which countries are blocked. Kept as its
    own endpoint so saving a backdrop can't accidentally rewrite firewall rules.
    """
    from core.models import SystemSetting

    settings_obj = SystemSetting.get_settings()
    modes = {k for k, _ in SystemSetting.GEOIP_MAP_BACKGROUND_MODES}
    patterns = {k for k, _ in SystemSetting.GEOIP_MAP_PATTERNS}

    mode = (request.POST.get('geoip_map_background_mode') or '').strip()
    pattern = (request.POST.get('geoip_map_background_pattern') or '').strip()

    if mode in modes:
        settings_obj.geoip_map_background_mode = mode
    if pattern in patterns:
        settings_obj.geoip_map_background_pattern = pattern

    upload = request.FILES.get('geoip_map_background_image')
    if upload:
        content_type = getattr(upload, 'content_type', '') or ''
        if not content_type.startswith('image/'):
            messages.error(request, 'Map backdrop must be an image file.')
            return redirect('core:firewall_country_rules')
        if upload.size > 5 * 1024 * 1024:
            messages.error(request, 'Map backdrop image must be 5 MB or smaller.')
            return redirect('core:firewall_country_rules')
        settings_obj.geoip_map_background_image = upload

    if request.POST.get('clear_image') == '1':
        settings_obj.geoip_map_background_image = None

    settings_obj.save()
    messages.success(request, 'Map backdrop updated.')
    return redirect('core:firewall_country_rules')


@login_required
@user_passes_test(is_superuser)
@require_POST
def firewall_country_rule_delete(request, pk):
    """Delete a country firewall rule."""
    rule = get_object_or_404(FirewallCountryRule, pk=pk)
    country_name = rule.country_name
    rule.delete()
    messages.success(request, f'Country rule deleted: {country_name}')
    return redirect('core:firewall_country_rules')


@login_required
@user_passes_test(is_superuser)
@require_POST
def firewall_country_rule_toggle(request, pk):
    """Toggle a country firewall rule active state."""
    rule = get_object_or_404(FirewallCountryRule, pk=pk)
    rule.is_active = not rule.is_active
    rule.save()

    status = "enabled" if rule.is_active else "disabled"
    messages.success(request, f'Country rule {status}: {rule.country_name}')
    return redirect('core:firewall_country_rules')


@login_required
@user_passes_test(is_superuser)
def firewall_logs(request):
    """View firewall logs."""
    logs_list = FirewallLog.objects.select_related('user').all()

    # Pagination
    paginator = Paginator(logs_list, 50)  # 50 logs per page
    page_number = request.GET.get('page')
    logs = paginator.get_page(page_number)

    # Statistics
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Count

    total_blocks = FirewallLog.objects.count()
    blocks_today = FirewallLog.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=1)
    ).count()
    blocks_this_week = FirewallLog.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=7)
    ).count()

    # Top blocked IPs
    top_ips = FirewallLog.objects.values('ip_address').annotate(
        count=Count('id')
    ).order_by('-count')[:10]

    # Top blocked countries
    top_countries = FirewallLog.objects.exclude(country_code='').values(
        'country_code', 'country_name'
    ).annotate(
        count=Count('id')
    ).order_by('-count')[:10]

    context = {
        'logs': logs,
        'total_blocks': total_blocks,
        'blocks_today': blocks_today,
        'blocks_this_week': blocks_this_week,
        'top_ips': top_ips,
        'top_countries': top_countries,
    }

    return render(request, 'core/firewall_logs.html', context)


@login_required
@user_passes_test(is_superuser)
@require_POST
def firewall_logs_clear(request):
    """Clear all firewall logs."""
    count = FirewallLog.objects.count()
    FirewallLog.objects.all().delete()
    messages.success(request, f'Cleared {count} firewall log entries.')
    return redirect('core:firewall_logs')
