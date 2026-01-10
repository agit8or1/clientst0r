"""
Global search views - Search across all content
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from core.middleware import get_request_organization
from assets.models import Asset, Contact
from vault.models import Password
from docs.models import Document
from integrations.models import PSACompany, PSAContact


@login_required
def global_search(request):
    """
    Global search across all content types.
    """
    org = get_request_organization(request)
    query = request.GET.get('q', '').strip()

    results = {
        'query': query,
        'assets': [],
        'contacts': [],
        'documents': [],
        'global_kb': [],
        'passwords': [],
        'psa_companies': [],
        'psa_contacts': [],
        'total_count': 0,
    }

    if query and len(query) >= 2:
        # Search Assets
        results['assets'] = Asset.objects.filter(
            organization=org
        ).filter(
            Q(name__icontains=query) |
            Q(asset_tag__icontains=query) |
            Q(serial_number__icontains=query) |
            Q(manufacturer__icontains=query) |
            Q(model__icontains=query) |
            Q(notes__icontains=query)
        )[:10]

        # Search Contacts
        results['contacts'] = Contact.objects.filter(
            organization=org
        ).filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query) |
            Q(title__icontains=query)
        )[:10]

        # Search Documents (org-specific only)
        results['documents'] = Document.objects.filter(
            organization=org,
            is_published=True,
            is_archived=False,
            is_global=False
        ).filter(
            Q(title__icontains=query) |
            Q(body__icontains=query)
        )[:10]

        # Search Global KB (staff users and superusers only)
        is_staff = getattr(request, 'is_staff_user', False)
        if is_staff or request.user.is_superuser:
            results['global_kb'] = Document.objects.filter(
                is_global=True,
                is_published=True,
                is_archived=False
            ).filter(
                Q(title__icontains=query) |
                Q(body__icontains=query)
            )[:10]

        # Search Passwords (title and username only, not actual passwords)
        results['passwords'] = Password.objects.filter(
            organization=org,
            is_personal=False
        ).filter(
            Q(title__icontains=query) |
            Q(username__icontains=query) |
            Q(url__icontains=query) |
            Q(notes__icontains=query)
        )[:10]

        # Search PSA Companies
        try:
            results['psa_companies'] = PSACompany.objects.filter(
                Q(name__icontains=query)
            ).filter(
                connection__organization=org
            )[:10]
        except:
            pass

        # Search PSA Contacts
        try:
            results['psa_contacts'] = PSAContact.objects.filter(
                Q(name__icontains=query) |
                Q(email__icontains=query)
            ).filter(
                connection__organization=org
            )[:10]
        except:
            pass

        # Calculate total
        results['total_count'] = (
            len(results['assets']) +
            len(results['contacts']) +
            len(results['documents']) +
            len(results['global_kb']) +
            len(results['passwords']) +
            len(results['psa_companies']) +
            len(results['psa_contacts'])
        )

    return render(request, 'core/search_results.html', results)
