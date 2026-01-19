"""
Docs views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.text import slugify
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from core.middleware import get_request_organization
from core.decorators import require_write, require_admin
from .models import Document, DocumentVersion, DocumentCategory
from .forms import DocumentForm
import os


@login_required
def document_list(request):
    """
    List all documents in current organization (NOT including global KB) with filtering.
    """
    from django.db.models import Q
    org = get_request_organization(request)

    # Get org-specific docs only (exclude templates)
    documents = Document.objects.filter(
        organization=org,
        is_published=True,
        is_archived=False,
        is_global=False,  # Exclude global KB articles
        is_template=False  # Exclude templates
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
        from django.db.models import Q
        try:
            # Allow both org-specific templates and global templates
            selected_template = Document.objects.get(
                Q(organization=org) | Q(organization=None, is_global=True),
                id=template_id,
                is_template=True
            )
            initial_data = {
                'title': '',  # Leave title empty for new document
                'body': selected_template.body,
                'content_type': selected_template.content_type,
                'category': selected_template.category,
                'tags': selected_template.tags.all(),  # Include tags from template
            }
        except Document.DoesNotExist:
            messages.warning(request, 'Template not found.')

    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES, organization=org)
        if form.is_valid():
            document = form.save(commit=False)
            document.organization = org
            document.slug = slugify(document.title)
            document.created_by = request.user
            document.last_modified_by = request.user
            document.is_template = False  # Ensure created docs are not templates

            # Handle file upload
            if document.content_type == 'file' and document.file:
                document.file_size = document.file.size
                document.file_type = document.file.content_type
                # Auto-generate title from filename if not provided
                if not document.title or document.title == '':
                    import os
                    document.title = os.path.splitext(document.file.name)[0]
                    document.slug = slugify(document.title)

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
        form = DocumentForm(request.POST, request.FILES, instance=document, organization=org)
        if form.is_valid():
            document = form.save(commit=False)
            document.last_modified_by = request.user

            # Handle file upload
            if document.content_type == 'file' and document.file:
                document.file_size = document.file.size
                document.file_type = document.file.content_type

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
    Delete document. Requires write permission.
    """
    org = get_request_organization(request)
    document = get_object_or_404(Document, slug=slug, organization=org)

    if request.method == 'POST':
        title = document.title
        document.delete()
        messages.success(request, f"Document '{title}' deleted successfully.")

        # Handle AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': f"Document '{title}' deleted successfully."})

        return redirect('docs:document_list')

    return render(request, 'docs/document_confirm_delete.html', {
        'document': document,
    })


@login_required
@require_write
@require_http_methods(["POST"])
def document_upload(request):
    """
    Bulk upload multiple files as documents.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Document upload request received from {request.user.username}")
    logger.info(f"Files in request: {request.FILES}")
    logger.info(f"POST data: {request.POST}")

    org = get_request_organization(request)
    files = request.FILES.getlist('files')
    logger.info(f"Files list: {files}")
    category_id = request.POST.get('category')

    category = None
    if category_id:
        try:
            category = DocumentCategory.objects.get(id=category_id, organization=org)
        except DocumentCategory.DoesNotExist:
            pass

    uploaded_count = 0
    failed = []

    for file in files:
        try:
            # Generate title from filename
            title = os.path.splitext(file.name)[0]
            slug = slugify(title)

            # Make slug unique
            base_slug = slug
            counter = 1
            while Document.objects.filter(organization=org, slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            # Create document
            document = Document.objects.create(
                organization=org,
                title=title,
                slug=slug,
                content_type='file',
                file=file,
                file_size=file.size,
                file_type=file.content_type,
                category=category,
                created_by=request.user,
                last_modified_by=request.user,
                is_published=True
            )
            uploaded_count += 1

        except Exception as e:
            failed.append(f"{file.name}: {str(e)}")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'uploaded': uploaded_count,
            'failed': failed
        })
    else:
        if uploaded_count > 0:
            messages.success(request, f"Successfully uploaded {uploaded_count} file(s).")
        if failed:
            messages.warning(request, f"Failed to upload: {', '.join(failed)}")
        return redirect('docs:document_list')


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

    # Global KB articles (exclude templates - templates have their own list)
    documents = Document.objects.filter(
        is_global=True,
        is_published=True,
        is_archived=False,
        is_template=False  # Exclude templates
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

    # Get global categories (organization=None) for filters - sorted alphabetically
    categories = DocumentCategory.objects.filter(organization__isnull=True).order_by('name')
    from core.models import Tag
    # Global KB doesn't use tags, but keep for template compatibility
    tags = Tag.objects.none()

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
                'title': '',  # Leave title empty for new document
                'body': selected_template.body,
                'content_type': selected_template.content_type,
                'category': selected_template.category,
                'tags': selected_template.tags.all(),  # Include tags from template
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
    List all document templates (organization-specific + global templates).
    """
    from django.db.models import Q

    org = get_request_organization(request)

    # Show org-specific templates AND global templates
    templates = Document.objects.filter(
        Q(organization=org) | Q(organization=None, is_global=True),
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

# ===== Diagram Views =====

@login_required
def diagram_list(request):
    """
    List all diagrams in current organization with filtering.
    """
    from django.db.models import Q
    from .models import Diagram
    
    org = get_request_organization(request)

    # Get org-specific and global diagrams (exclude templates)
    diagrams = Diagram.objects.filter(
        Q(organization=org) | Q(is_global=True),
        is_published=True,
        is_template=False  # Exclude templates
    ).prefetch_related('tags')

    # Filter by diagram type
    diagram_type = request.GET.get('type')
    if diagram_type:
        diagrams = diagrams.filter(diagram_type=diagram_type)

    # Filter by tag
    tag_id = request.GET.get('tag')
    if tag_id:
        diagrams = diagrams.filter(tags__id=tag_id)

    # Search query
    query = request.GET.get('q', '').strip()
    if query:
        diagrams = diagrams.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )

    diagrams = diagrams.order_by('-last_edited_at')

    # Get tags for filters
    from core.models import Tag
    tags = Tag.objects.filter(organization=org).order_by('name')

    # Get diagram type choices
    from .models import Diagram as DiagramModel
    diagram_types = DiagramModel.DIAGRAM_TYPES

    return render(request, 'docs/diagram_list.html', {
        'diagrams': diagrams,
        'current_organization': org,
        'tags': tags,
        'diagram_types': diagram_types,
        'selected_type': diagram_type,
        'selected_tag': tag_id,
        'query': query,
    })


@login_required
def diagram_detail(request, slug):
    """
    View diagram details with PNG/SVG export.
    """
    from django.db.models import Q
    from .models import Diagram
    
    org = get_request_organization(request)
    diagram = get_object_or_404(
        Diagram.objects.filter(Q(organization=org) | Q(is_global=True)),
        slug=slug
    )

    # Get versions
    versions = diagram.versions.all()[:10]  # Last 10 versions

    return render(request, 'docs/diagram_detail.html', {
        'diagram': diagram,
        'versions': versions,
        'current_organization': org,
    })


@login_required
@require_write
def diagram_create(request):
    """
    Create new diagram, optionally from a template - redirects to editor.
    """
    from django.db.models import Q
    from .models import Diagram

    org = get_request_organization(request)

    # Check if creating from template
    template_id = request.GET.get('template')
    initial_data = {}
    selected_template = None
    template_xml = ''

    if template_id:
        try:
            # Allow both org-specific templates and global templates
            selected_template = Diagram.objects.get(
                Q(organization=org) | Q(organization=None, is_global=True),
                id=template_id,
                is_template=True
            )
            template_xml = selected_template.diagram_xml
            initial_data = {
                'diagram_type': selected_template.diagram_type,
                'description': selected_template.description,
            }
        except Diagram.DoesNotExist:
            messages.warning(request, 'Template not found.')

    if request.method == 'POST':
        from .forms import DiagramForm
        form = DiagramForm(request.POST, organization=org)
        if form.is_valid():
            diagram = form.save(commit=False)
            diagram.organization = org
            diagram.created_by = request.user
            diagram.last_modified_by = request.user
            # If from template, use template's XML; otherwise empty
            diagram.diagram_xml = template_xml if template_xml else ''
            diagram.is_template = False  # Ensure created diagrams are not templates
            diagram.save()
            form.save_m2m()
            messages.success(request, f"Diagram '{diagram.title}' created. You can now edit it.")
            return redirect('docs:diagram_edit', slug=diagram.slug)
    else:
        from .forms import DiagramForm
        form = DiagramForm(organization=org, initial=initial_data)

    return render(request, 'docs/diagram_form.html', {
        'form': form,
        'action': 'Create',
        'current_organization': org,
        'selected_template': selected_template,
    })


@login_required
@require_write
def diagram_edit(request, slug):
    """
    Edit diagram with draw.io editor.
    """
    from .models import Diagram
    from django.db.models import Q
    
    org = get_request_organization(request)
    diagram = get_object_or_404(Diagram, slug=slug, organization=org)

    return render(request, 'docs/diagram_editor.html', {
        'diagram': diagram,
        'current_organization': org,
    })


@login_required
@require_write
def diagram_save(request, pk):
    """
    AJAX endpoint to save diagram XML, PNG export, and metadata.
    """
    from django.http import JsonResponse
    from .models import Diagram, DiagramVersion
    from django.core.files.base import ContentFile
    import json
    import base64
    import logging

    logger = logging.getLogger('docs')

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    org = get_request_organization(request)
    diagram = get_object_or_404(Diagram, pk=pk, organization=org)

    try:
        data = json.loads(request.body)
        diagram_xml = data.get('diagram_xml', '')
        png_export_b64 = data.get('png_export', '')

        if not diagram_xml:
            return JsonResponse({'error': 'No diagram data provided'}, status=400)

        # Create version snapshot before saving
        DiagramVersion.objects.create(
            diagram=diagram,
            version_number=diagram.version_number,
            diagram_xml=diagram.diagram_xml if diagram.diagram_xml else '',
            created_by=request.user,
            change_notes=data.get('change_notes', 'Auto-saved')
        )

        # Update diagram XML
        diagram.diagram_xml = diagram_xml
        diagram.last_modified_by = request.user
        diagram.version_number += 1

        # Process PNG export if provided
        if png_export_b64:
            try:
                logger.info(f'Processing PNG export for diagram {diagram.id}')
                # PNG data comes as base64 data URL: data:image/png;base64,iVBORw0KG...
                if png_export_b64.startswith('data:image/png;base64,'):
                    png_export_b64 = png_export_b64.split(',')[1]

                # Decode base64 to bytes
                png_bytes = base64.b64decode(png_export_b64)

                # Save PNG export
                filename = f"{diagram.slug}_v{diagram.version_number}.png"
                diagram.png_export.save(filename, ContentFile(png_bytes), save=False)
                logger.info(f'Saved PNG export: {filename} ({len(png_bytes)} bytes)')
            except Exception as e:
                logger.error(f'Error saving PNG export for diagram {diagram.id}: {e}')
                # Don't fail the whole save if PNG export fails

        diagram.save()

        return JsonResponse({
            'success': True,
            'version': diagram.version_number,
            'has_preview': bool(diagram.png_export)
        })

    except Exception as e:
        logger.error(f'Error saving diagram {pk}: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_write
def diagram_delete(request, slug):
    """
    Delete diagram.
    """
    from .models import Diagram
    
    org = get_request_organization(request)
    diagram = get_object_or_404(Diagram, slug=slug, organization=org)

    if request.method == 'POST':
        title = diagram.title
        diagram.delete()
        messages.success(request, f"Diagram '{title}' deleted successfully.")
        return redirect('docs:diagram_list')

    # Get usage count (how many processes link to this diagram)
    from processes.models import Process
    linked_processes = Process.objects.filter(linked_diagram=diagram).count()

    return render(request, 'docs/diagram_confirm_delete.html', {
        'diagram': diagram,
        'linked_processes': linked_processes,
        'current_organization': org,
    })


# Diagram Template Views

@login_required
def diagram_template_list(request):
    """
    List all diagram templates (organization-specific + global templates).
    """
    from django.db.models import Q
    from .models import Diagram

    org = get_request_organization(request)

    # Show org-specific templates AND global templates
    templates = Diagram.objects.filter(
        Q(organization=org) | Q(organization=None, is_global=True),
        is_template=True
    ).order_by('title')

    return render(request, 'docs/diagram_template_list.html', {
        'templates': templates,
    })


@login_required
@require_write
def diagram_template_create(request):
    """
    Create new diagram template.
    """
    from .models import Diagram
    from .forms import DiagramForm

    org = get_request_organization(request)

    if request.method == 'POST':
        form = DiagramForm(request.POST, organization=org)
        if form.is_valid():
            template = form.save(commit=False)
            template.organization = org
            template.slug = slugify(template.title)
            template.created_by = request.user
            template.last_modified_by = request.user
            template.is_template = True  # Force as template
            template.is_published = True
            template.version = 1
            template.diagram_xml = ''  # Start with empty diagram
            template.save()
            form.save_m2m()
            messages.success(request, f"Template '{template.title}' created successfully.")
            # Redirect to editor to create the template diagram
            return redirect('docs:diagram_edit', slug=template.slug)
    else:
        initial_data = {'is_template': True}
        form = DiagramForm(organization=org, initial=initial_data)

    return render(request, 'docs/diagram_template_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def diagram_template_edit(request, pk):
    """
    Edit diagram template metadata (not the diagram itself).
    """
    from .models import Diagram
    from .forms import DiagramForm

    org = get_request_organization(request)
    template = get_object_or_404(Diagram, pk=pk, organization=org, is_template=True)

    if request.method == 'POST':
        form = DiagramForm(request.POST, instance=template, organization=org)
        if form.is_valid():
            template = form.save(commit=False)
            template.is_template = True  # Ensure it stays a template
            template.last_modified_by = request.user
            template.save()
            form.save_m2m()
            messages.success(request, f"Template '{template.title}' updated successfully.")
            return redirect('docs:diagram_template_list')
    else:
        form = DiagramForm(instance=template, organization=org)

    return render(request, 'docs/diagram_template_form.html', {
        'form': form,
        'template': template,
        'action': 'Edit',
    })


@login_required
@require_write
def diagram_template_delete(request, pk):
    """
    Delete diagram template.
    """
    from .models import Diagram

    org = get_request_organization(request)
    template = get_object_or_404(Diagram, pk=pk, organization=org, is_template=True)

    if request.method == 'POST':
        title = template.title
        template.delete()
        messages.success(request, f"Template '{title}' deleted successfully.")
        return redirect('docs:diagram_template_list')

    return render(request, 'docs/diagram_template_confirm_delete.html', {
        'template': template,
    })


# ============================================================================
# Document Category Management
# ============================================================================

@login_required
@require_admin
def category_list(request):
    """
    List all document categories for current organization.
    """
    from .models import DocumentCategory

    org = get_request_organization(request)
    categories = DocumentCategory.objects.filter(organization=org).order_by('order', 'name')

    return render(request, 'docs/category_list.html', {
        'categories': categories,
    })


@login_required
@require_admin
def category_create(request):
    """
    Create new document category.
    """
    from .models import DocumentCategory
    from .forms import DocumentCategoryForm

    org = get_request_organization(request)

    if request.method == 'POST':
        form = DocumentCategoryForm(request.POST, organization=org)
        if form.is_valid():
            category = form.save(commit=False)
            category.organization = org
            category.save()
            messages.success(request, f"Category '{category.name}' created successfully.")
            return redirect('docs:category_list')
    else:
        form = DocumentCategoryForm(organization=org)

    return render(request, 'docs/category_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_admin
def category_edit(request, pk):
    """
    Edit existing document category.
    """
    from .models import DocumentCategory
    from .forms import DocumentCategoryForm

    org = get_request_organization(request)
    category = get_object_or_404(DocumentCategory, pk=pk, organization=org)

    if request.method == 'POST':
        form = DocumentCategoryForm(request.POST, instance=category, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f"Category '{category.name}' updated successfully.")
            return redirect('docs:category_list')
    else:
        form = DocumentCategoryForm(instance=category, organization=org)

    return render(request, 'docs/category_form.html', {
        'form': form,
        'category': category,
        'action': 'Edit',
    })


@login_required
@require_admin
def category_delete(request, pk):
    """
    Delete document category.
    """
    from .models import DocumentCategory

    org = get_request_organization(request)
    category = get_object_or_404(DocumentCategory, pk=pk, organization=org)

    # Check if category is in use
    doc_count = category.documents.count()

    if request.method == 'POST':
        name = category.name
        category.delete()
        messages.success(request, f"Category '{name}' deleted successfully.")
        return redirect('docs:category_list')

    return render(request, 'docs/category_confirm_delete.html', {
        'category': category,
        'doc_count': doc_count,
    })
