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
    return render(request, 'core/about.html', {
        'version': get_version(),
        'full_version': get_full_version(),
    })
