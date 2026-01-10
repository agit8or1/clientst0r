"""
Files views - Private file serving with X-Accel-Redirect
"""
import os
import mimetypes
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, FileResponse, Http404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.conf import settings
from core.middleware import get_request_organization
from .models import Attachment


@login_required
@require_http_methods(["GET"])
def serve_attachment(request, pk):
    """
    Serve attachment via X-Accel-Redirect for Nginx.
    Falls back to direct file serving in development.
    """
    from pathlib import Path

    org = get_request_organization(request)
    attachment = get_object_or_404(Attachment, pk=pk, organization=org)

    # Security: Validate file path to prevent path traversal attacks
    try:
        # Get absolute paths
        upload_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = Path(attachment.file.path).resolve()

        # Ensure file is within upload directory
        file_path.relative_to(upload_root)
    except (ValueError, AttributeError):
        # ValueError: file is not relative to upload_root (path traversal attempt)
        # AttributeError: attachment.file.path doesn't exist
        raise Http404("Invalid file path")

    # Verify file exists
    if not file_path.exists():
        raise Http404("File not found")

    # Use X-Accel-Redirect if not in debug mode
    if not settings.DEBUG:
        # Nginx internal location: /internal_uploads/
        internal_path = f"/internal_uploads/{attachment.file.name}"
        response = HttpResponse()
        response['X-Accel-Redirect'] = internal_path
        response['Content-Type'] = attachment.content_type or 'application/octet-stream'
        response['Content-Disposition'] = f'inline; filename="{attachment.original_filename}"'
        return response
    else:
        # Development: serve directly using validated file_path
        return FileResponse(
            open(file_path, 'rb'),
            content_type=attachment.content_type,
            as_attachment=False,
            filename=attachment.original_filename
        )


@login_required
@require_http_methods(["POST"])
def upload_attachment(request):
    """
    Upload attachment. Expects multipart form with:
    - file
    - entity_type
    - entity_id
    - description (optional)
    """
    org = get_request_organization(request)

    if 'file' not in request.FILES:
        return HttpResponse("No file provided", status=400)

    uploaded_file = request.FILES['file']
    entity_type = request.POST.get('entity_type')
    entity_id = request.POST.get('entity_id')

    if not entity_type or not entity_id:
        return HttpResponse("Missing entity_type or entity_id", status=400)

    # Security: Validate entity_type against whitelist
    VALID_ENTITY_TYPES = ['password', 'asset', 'document', 'contact', 'integration']
    if entity_type not in VALID_ENTITY_TYPES:
        return HttpResponse(f"Invalid entity_type: {entity_type}", status=400)

    # Security: Validate entity_id is a valid integer
    try:
        entity_id = int(entity_id)
    except ValueError:
        return HttpResponse("Invalid entity_id: must be an integer", status=400)

    # Security: Validate file size (max 25MB)
    MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
    if uploaded_file.size > MAX_FILE_SIZE:
        return HttpResponse(f"File too large: maximum size is {MAX_FILE_SIZE // (1024*1024)}MB", status=400)

    # Security: Validate file extension against whitelist
    ALLOWED_EXTENSIONS = {
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',  # Documents
        'txt', 'csv', 'md', 'log',  # Text files
        'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp',  # Images
        'zip', '7z', 'tar', 'gz', 'rar',  # Archives
        'json', 'xml', 'yaml', 'yml',  # Data files
    }

    filename = uploaded_file.name.lower()
    file_ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''

    if not file_ext or file_ext not in ALLOWED_EXTENSIONS:
        return HttpResponse(f"File type not allowed: .{file_ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}", status=400)

    # Security: Block dangerous filenames
    DANGEROUS_PATTERNS = ['.exe', '.bat', '.cmd', '.sh', '.php', '.jsp', '.asp', '.aspx', '.js', '.vbs', '.scr']
    for pattern in DANGEROUS_PATTERNS:
        if pattern in filename:
            return HttpResponse(f"Dangerous file type detected: {pattern}", status=400)

    # Create attachment
    attachment = Attachment(
        organization=org,
        entity_type=entity_type,
        entity_id=entity_id,
        file=uploaded_file,
        original_filename=uploaded_file.name,
        file_size=uploaded_file.size,
        content_type=uploaded_file.content_type or mimetypes.guess_type(uploaded_file.name)[0] or 'application/octet-stream',
        uploaded_by=request.user,
        description=request.POST.get('description', '')
    )
    attachment.save()

    return HttpResponse(f"File uploaded: {attachment.id}", status=201)
