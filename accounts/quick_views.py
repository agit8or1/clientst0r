"""
Quick add views for organization admins to rapidly create common items.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.models import Organization
from .quick_forms import QuickUserForm
from core.decorators import require_admin
from core.middleware import get_request_organization


@login_required
@require_admin
def quick_add_menu(request):
    """
    Quick add menu for organization admins.
    Shows available quick add options.
    """
    org = get_request_organization(request)

    return render(request, 'accounts/quick_add_menu.html', {
        'current_organization': org,
    })


@login_required
@require_admin
def quick_user_add(request):
    """
    Quick form for creating a new user and adding them to the organization.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        form = QuickUserForm(request.POST)
        if form.is_valid():
            try:
                user = form.save(organization=org, created_by=request.user)

                # TODO: Send welcome email if requested
                if form.cleaned_data.get('send_welcome_email'):
                    # This would be implemented with email functionality
                    pass

                messages.success(
                    request,
                    f"User '{user.username}' created successfully and added to {org.name}."
                )
                return redirect('accounts:organization_detail', org_id=org.id)
            except Exception as e:
                messages.error(request, f"Error creating user: {str(e)}")
    else:
        form = QuickUserForm()

    return render(request, 'accounts/quick_user_form.html', {
        'form': form,
        'current_organization': org,
    })
