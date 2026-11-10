"""
Tag management views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Count
from core.models import Tag
from core.middleware import get_request_organization


def is_superuser(user):
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def tag_list(request):
    """List all tags"""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

    tags = Tag.objects.filter(organization=org).annotate(
        asset_count=Count('assets', distinct=True),
        password_count=Count('passwords', distinct=True)
    ).order_by('name')

    return render(request, 'core/tag_list.html', {
        'tags': tags,
        'current_organization': org,
    })


@login_required
@user_passes_test(is_superuser)
def tag_create(request):
    """Create a new tag"""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '#6c757d')

        if not name:
            messages.error(request, 'Tag name is required.')
            return render(request, 'core/tag_form.html', {
                'current_organization': org,
                'action': 'Create',
            })

        # Create slug from name
        from django.utils.text import slugify
        slug = slugify(name)

        # Check if slug already exists
        if Tag.objects.filter(organization=org, slug=slug).exists():
            messages.error(request, f'A tag with this name already exists.')
            return render(request, 'core/tag_form.html', {
                'current_organization': org,
                'action': 'Create',
                'name': name,
                'color': color,
            })

        Tag.objects.create(
            organization=org,
            name=name,
            slug=slug,
            color=color
        )

        messages.success(request, f'Tag "{name}" created successfully.')
        return redirect('core:tag_list')

    return render(request, 'core/tag_form.html', {
        'current_organization': org,
        'action': 'Create',
    })


@login_required
@user_passes_test(is_superuser)
def tag_edit(request, pk):
    """Edit an existing tag"""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

    tag = get_object_or_404(Tag, pk=pk, organization=org)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '#6c757d')

        if not name:
            messages.error(request, 'Tag name is required.')
            return render(request, 'core/tag_form.html', {
                'tag': tag,
                'current_organization': org,
                'action': 'Edit',
            })

        # Update slug if name changed
        from django.utils.text import slugify
        new_slug = slugify(name)

        # Check if new slug conflicts with another tag
        if new_slug != tag.slug and Tag.objects.filter(organization=org, slug=new_slug).exists():
            messages.error(request, f'A tag with this name already exists.')
            return render(request, 'core/tag_form.html', {
                'tag': tag,
                'current_organization': org,
                'action': 'Edit',
                'name': name,
                'color': color,
            })

        tag.name = name
        tag.slug = new_slug
        tag.color = color
        tag.save()

        messages.success(request, f'Tag "{name}" updated successfully.')
        return redirect('core:tag_list')

    return render(request, 'core/tag_form.html', {
        'tag': tag,
        'current_organization': org,
        'action': 'Edit',
    })


@login_required
@user_passes_test(is_superuser)
def tag_delete(request, pk):
    """Delete a tag"""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')

    tag = get_object_or_404(Tag, pk=pk, organization=org)

    if request.method == 'POST':
        tag_name = tag.name
        tag.delete()
        messages.success(request, f'Tag "{tag_name}" deleted successfully.')
        return redirect('core:tag_list')

    # Count usage
    from assets.models import Asset
    from vault.models import Password

    asset_count = Asset.objects.filter(tags=tag).count()
    from vault.permissions import visible_passwords
    password_count = visible_passwords(request.user, Password.objects.filter(tags=tag)).count()

    return render(request, 'core/tag_confirm_delete.html', {
        'tag': tag,
        'asset_count': asset_count,
        'password_count': password_count,
        'current_organization': org,
    })
