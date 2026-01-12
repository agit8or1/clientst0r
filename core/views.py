"""
Core views - Documentation and About pages
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from config.version import get_version, get_full_version


@login_required
def documentation(request):
    """
    Platform documentation page.
    """
    return render(request, 'core/documentation.html', {
        'version': get_version(),
    })


@login_required
def about(request):
    """
    About page with version and system information.
    """
    from .security_scan import run_vulnerability_scan, get_dependency_versions
    from assets.models import Vendor, EquipmentModel

    # Run security scan
    scan_results = run_vulnerability_scan()

    # Get dependency versions
    dependencies = get_dependency_versions()

    # Get equipment catalog statistics
    equipment_stats = {
        'vendor_count': Vendor.objects.filter(is_active=True).count(),
        'model_count': EquipmentModel.objects.filter(is_active=True).count(),
    }

    return render(request, 'core/about.html', {
        'version': get_version(),
        'full_version': get_full_version(),
        'scan_results': scan_results,
        'dependencies': dependencies,
        'equipment_stats': equipment_stats,
    })
