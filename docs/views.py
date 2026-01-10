"""
Docs views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.text import slugify
from core.middleware import get_request_organization
from core.decorators import require_write
from .models import Document, DocumentVersion, DocumentCategory
from .forms import DocumentForm


@login_required
def document_list(request):
    """
    List all documents in current organization (NOT including global KB) with filtering.
    """
    from django.db.models import Q
    org = get_request_organization(request)

    # Get org-specific docs only
    documents = Document.objects.filter(
        organization=org,
        is_published=True,
        is_archived=False,
        is_global=False  # Exclude global KB articles
    ).prefetch_related('tags', 'category')

    # Filter by category
    category_id = request.GET.get('category')
    if category_id:
        documents = documents.filter(category_id=category_id)

    # Filter by tag
    tag_id = request.GET.get('tag')
    if tag_id:
        documents = documents.filter(tags__id=tag_id)

    # Search query
    query = request.GET.get('q', '').strip()
    if query:
        documents = documents.filter(
            Q(title__icontains=query) | Q(body__icontains=query)
        )

    documents = documents.order_by('-updated_at')

    # Get all categories and tags for filters
    categories = DocumentCategory.objects.filter(organization=org).order_by('order', 'name')
    from core.models import Tag
    tags = Tag.objects.filter(organization=org).order_by('name')

    return render(request, 'docs/document_list.html', {
        'org_docs': documents,
        'org': org,
        'categories': categories,
        'tags': tags,
        'selected_category': category_id,
        'selected_tag': tag_id,
        'query': query,
    })


@login_required
def document_detail(request, slug):
    """
    View document details with rendered markdown.
    """
    org = get_request_organization(request)
    document = get_object_or_404(Document, slug=slug, organization=org)

    # Get versions
    versions = document.versions.all()[:10]  # Last 10 versions

    return render(request, 'docs/document_detail.html', {
        'document': document,
        'rendered_body': document.render_markdown(),
        'versions': versions,
    })


@login_required
@require_write
def document_create(request):
    """
    Create new document, optionally from a template.
    """
    org = get_request_organization(request)

    # Check if creating from template
    template_id = request.GET.get('template')
    initial_data = {}
    selected_template = None

    if template_id:
        try:
            selected_template = Document.objects.get(
                id=template_id,
                organization=org,
                is_template=True
            )
            initial_data = {
                'body': selected_template.body,
                'content_type': selected_template.content_type,
                'category': selected_template.category,
            }
        except Document.DoesNotExist:
            messages.warning(request, 'Template not found.')

    if request.method == 'POST':
        form = DocumentForm(request.POST, organization=org)
        if form.is_valid():
            document = form.save(commit=False)
            document.organization = org
            document.slug = slugify(document.title)
            document.created_by = request.user
            document.last_modified_by = request.user
            document.is_template = False  # Ensure created docs are not templates
            document.save()
            form.save_m2m()
            messages.success(request, f"Document '{document.title}' created successfully.")
            return redirect('docs:document_detail', slug=document.slug)
    else:
        form = DocumentForm(organization=org, initial=initial_data)

    # Get available templates for dropdown
    templates = Document.objects.filter(
        organization=org,
        is_template=True
    ).order_by('title')

    return render(request, 'docs/document_form.html', {
        'form': form,
        'action': 'Create',
        'templates': templates,
        'selected_template': selected_template,
    })


@login_required
@require_write
def document_edit(request, slug):
    """
    Edit document (creates version automatically).
    """
    org = get_request_organization(request)
    document = get_object_or_404(Document, slug=slug, organization=org)

    if request.method == 'POST':
        form = DocumentForm(request.POST, instance=document, organization=org)
        if form.is_valid():
            document = form.save(commit=False)
            document.last_modified_by = request.user
            document.save()
            form.save_m2m()
            messages.success(request, f"Document '{document.title}' updated successfully.")
            return redirect('docs:document_detail', slug=document.slug)
    else:
        form = DocumentForm(instance=document, organization=org)

    return render(request, 'docs/document_form.html', {
        'form': form,
        'document': document,
        'action': 'Edit',
    })


@login_required
@require_write
def document_delete(request, slug):
    """
    Delete document.
    """
    org = get_request_organization(request)
    document = get_object_or_404(Document, slug=slug, organization=org)

    if request.method == 'POST':
        title = document.title
        document.delete()
        messages.success(request, f"Document '{title}' deleted successfully.")
        return redirect('docs:document_list')

    return render(request, 'docs/document_confirm_delete.html', {
        'document': document,
    })


# ============================================================================
# Global KB Views (Staff Only)
# ============================================================================

def require_staff_user(view_func):
    """Decorator to require staff user access."""
    def wrapper(request, *args, **kwargs):
        if not getattr(request, 'is_staff_user', False) and not request.user.is_superuser:
            messages.error(request, 'Access denied. Global KB is only accessible to staff users.')
            return redirect('core:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@require_staff_user
def global_kb_list(request):
    """
    List all global KB articles (staff only) with filtering.
    """
    from django.db.models import Q
    from core.models import Organization

    # Get first org for categories/tags
    org = Organization.objects.first()

    documents = Document.objects.filter(
        is_global=True,
        is_published=True,
        is_archived=False
    ).prefetch_related('tags', 'category')

    # Filter by category
    category_id = request.GET.get('category')
    if category_id:
        documents = documents.filter(category_id=category_id)

    # Filter by tag
    tag_id = request.GET.get('tag')
    if tag_id:
        documents = documents.filter(tags__id=tag_id)

    # Search query
    query = request.GET.get('q', '').strip()
    if query:
        documents = documents.filter(
            Q(title__icontains=query) | Q(body__icontains=query)
        )

    documents = documents.order_by('-updated_at')

    # Get all categories and tags for filters
    categories = DocumentCategory.objects.filter(organization=org).order_by('order', 'name')
    from core.models import Tag
    tags = Tag.objects.filter(organization=org).order_by('name')

    return render(request, 'docs/global_kb_list.html', {
        'documents': documents,
        'categories': categories,
        'tags': tags,
        'selected_category': category_id,
        'selected_tag': tag_id,
        'query': query,
    })


@login_required
@require_staff_user
def global_kb_detail(request, slug):
    """
    View global KB article (staff only).
    """
    document = get_object_or_404(Document, slug=slug, is_global=True)

    return render(request, 'docs/global_kb_detail.html', {
        'document': document,
    })


@login_required
@require_staff_user
def global_kb_create(request):
    """
    Create global KB article (staff only), optionally from a template.
    """
    # Get first organization as placeholder (global docs still need an org reference)
    from core.models import Organization
    org = Organization.objects.first()

    if not org:
        messages.error(request, 'At least one organization must exist.')
        return redirect('docs:global_kb_list')

    # Check if creating from template
    template_id = request.GET.get('template')
    initial_data = {}
    selected_template = None

    if template_id:
        try:
            selected_template = Document.objects.get(
                id=template_id,
                is_template=True
            )
            initial_data = {
                'body': selected_template.body,
                'content_type': selected_template.content_type,
                'category': selected_template.category,
            }
        except Document.DoesNotExist:
            messages.warning(request, 'Template not found.')

    if request.method == 'POST':
        form = DocumentForm(request.POST, organization=org)
        if form.is_valid():
            document = form.save(commit=False)
            document.organization = org
            document.is_global = True  # Mark as global KB
            document.is_template = False  # Ensure created KB articles are not templates
            document.created_by = request.user
            document.last_modified_by = request.user
            document.save()
            form.save_m2m()
            messages.success(request, f"Global KB article '{document.title}' created successfully.")
            return redirect('docs:global_kb_detail', slug=document.slug)
    else:
        form = DocumentForm(organization=org, initial=initial_data)

    # Get available templates for dropdown (from any org for global KB)
    templates = Document.objects.filter(is_template=True).order_by('title')

    return render(request, 'docs/global_kb_form.html', {
        'form': form,
        'action': 'Create',
        'templates': templates,
        'selected_template': selected_template,
    })


@login_required
@require_staff_user
def global_kb_edit(request, slug):
    """
    Edit global KB article (staff only).
    """
    document = get_object_or_404(Document, slug=slug, is_global=True)

    if request.method == 'POST':
        form = DocumentForm(request.POST, instance=document, organization=document.organization)
        if form.is_valid():
            document = form.save(commit=False)
            document.is_global = True  # Ensure it stays global
            document.last_modified_by = request.user
            document.save()
            form.save_m2m()
            messages.success(request, f"Global KB article '{document.title}' updated successfully.")
            return redirect('docs:global_kb_detail', slug=document.slug)
    else:
        form = DocumentForm(instance=document, organization=document.organization)

    return render(request, 'docs/global_kb_form.html', {
        'form': form,
        'document': document,
        'action': 'Edit',
    })


@login_required
@require_staff_user
def global_kb_delete(request, slug):
    """
    Delete global KB article (staff only).
    """
    document = get_object_or_404(Document, slug=slug, is_global=True)

    if request.method == 'POST':
        title = document.title
        document.delete()
        messages.success(request, f"Global KB article '{title}' deleted successfully.")
        return redirect('docs:global_kb_list')

    return render(request, 'docs/global_kb_confirm_delete.html', {
        'document': document,
    })


# ============================================================================
# Template Management Views
# ============================================================================

@login_required
@require_write
def template_list(request):
    """
    List all document templates in current organization.
    """
    org = get_request_organization(request)

    templates = Document.objects.filter(
        organization=org,
        is_template=True
    ).order_by('title')

    return render(request, 'docs/template_list.html', {
        'templates': templates,
    })


@login_required
@require_write
def template_create(request):
    """
    Create new document template.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        form = DocumentForm(request.POST, organization=org)
        if form.is_valid():
            template = form.save(commit=False)
            template.organization = org
            template.slug = slugify(template.title)
            template.created_by = request.user
            template.last_modified_by = request.user
            template.is_template = True  # Force as template
            template.is_published = True
            template.save()
            form.save_m2m()
            messages.success(request, f"Template '{template.title}' created successfully.")
            return redirect('docs:template_list')
    else:
        initial_data = {'is_template': True}
        form = DocumentForm(organization=org, initial=initial_data)

    return render(request, 'docs/template_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def template_edit(request, pk):
    """
    Edit document template.
    """
    org = get_request_organization(request)
    template = get_object_or_404(Document, pk=pk, organization=org, is_template=True)

    if request.method == 'POST':
        form = DocumentForm(request.POST, instance=template, organization=org)
        if form.is_valid():
            template = form.save(commit=False)
            template.is_template = True  # Ensure it stays a template
            template.last_modified_by = request.user
            template.save()
            form.save_m2m()
            messages.success(request, f"Template '{template.title}' updated successfully.")
            return redirect('docs:template_list')
    else:
        form = DocumentForm(instance=template, organization=org)

    return render(request, 'docs/template_form.html', {
        'form': form,
        'template': template,
        'action': 'Edit',
    })


@login_required
@require_write
def template_delete(request, pk):
    """
    Delete document template.
    """
    org = get_request_organization(request)
    template = get_object_or_404(Document, pk=pk, organization=org, is_template=True)

    if request.method == 'POST':
        title = template.title
        template.delete()
        messages.success(request, f"Template '{title}' deleted successfully.")
        return redirect('docs:template_list')

    return render(request, 'docs/template_confirm_delete.html', {
        'template': template,
    })
