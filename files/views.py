"""
Files views - private attachment upload / serving
"""
import os
import mimetypes
from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, Http404, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from core.middleware import get_request_organization
from .models import Attachment


# Types a browser may render in place. Everything else is sent as a download,
# so an uploaded HTML/SVG/XML file (or a forged upload Content-Type) can never
# run script on this origin.
INLINE_TYPES = {
    'image/png', 'image/jpeg', 'image/gif', 'image/bmp', 'image/webp',
    'application/pdf', 'text/plain',
}


def _delivery_type(filename):
    """(Content-Type, inline?) from the stored file name, never the upload's own header."""
    guessed = mimetypes.guess_type(filename or '')[0] or 'application/octet-stream'
    if guessed in INLINE_TYPES:
        return guessed, True
    return 'application/octet-stream', False


@login_required
@require_http_methods(["GET", "HEAD"])
def serve_attachment(request, pk):
    """
    Stream an attachment of the selected organization.

    Shares core.media_views with /media/: same permission rule, same
    MEDIA_ROOT containment check, same safe headers. (This used to hand off to
    an nginx X-Accel location aliased to a directory files are never stored
    in, so it 404'd on every production install.)
    """
    from core.media_views import (
        MEDIA_REGISTRY, resolve_under_media_root, stream_file,
    )

    org = get_request_organization(request)
    attachment = get_object_or_404(Attachment, pk=pk, organization=org)
    rule = next(r for r in MEDIA_REGISTRY
                if r.model == 'files.Attachment' and r.field == 'file')
    if not attachment.file or not rule.authorize(request.user, attachment):
        raise Http404("File not found")
    full_path = resolve_under_media_root(attachment.file.name)
    return stream_file(request, full_path, attachment.file.name,
                       attachment.original_filename)


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
    VALID_ENTITY_TYPES = ['password', 'asset', 'document', 'contact', 'integration', 'rack', 'vehicle']
    if entity_type not in VALID_ENTITY_TYPES:
        return HttpResponse(f"Invalid entity_type: {entity_type}", status=400)

    # Security: Validate entity_id is a valid integer
    try:
        entity_id = int(entity_id)
    except ValueError:
        return HttpResponse("Invalid entity_id: must be an integer", status=400)

    # Check image limit (max 20 images per entity for assets and racks)
    if entity_type in ['asset', 'rack']:
        existing_count = Attachment.objects.filter(
            organization=org,
            entity_type=entity_type,
            entity_id=entity_id,
            content_type__startswith='image/'
        ).count()

        if existing_count >= 20:
            return JsonResponse({'error': 'Maximum of 20 images allowed per item'}, status=400)

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
        return HttpResponse("File type not allowed", status=400)

    # Security: Block dangerous filenames
    DANGEROUS_PATTERNS = ['.exe', '.bat', '.cmd', '.sh', '.php', '.jsp', '.asp', '.aspx', '.js', '.vbs', '.scr']
    for pattern in DANGEROUS_PATTERNS:
        if pattern in filename:
            return HttpResponse("File type not allowed", status=400)

    # Security: Validate file content matches extension (magic bytes verification)
    uploaded_file.seek(0)  # Reset file pointer
    file_header = uploaded_file.read(512)  # Read first 512 bytes for magic byte checking
    uploaded_file.seek(0)  # Reset again for later processing

    # Magic bytes signatures for common file types
    MAGIC_BYTES = {
        'pdf': [b'%PDF'],
        'png': [b'\x89PNG\r\n\x1a\n'],
        'jpg': [b'\xff\xd8\xff'],
        'jpeg': [b'\xff\xd8\xff'],
        'gif': [b'GIF87a', b'GIF89a'],
        'zip': [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'],
        'docx': [b'PK\x03\x04'],  # DOCX is a ZIP archive
        'xlsx': [b'PK\x03\x04'],  # XLSX is a ZIP archive
        'pptx': [b'PK\x03\x04'],  # PPTX is a ZIP archive
        '7z': [b'7z\xbc\xaf\x27\x1c'],
        'gz': [b'\x1f\x8b'],
        'bmp': [b'BM'],
    }

    # Verify magic bytes if we have a signature for this file type
    if file_ext in MAGIC_BYTES:
        valid_magic = False
        for magic in MAGIC_BYTES[file_ext]:
            if file_header.startswith(magic):
                valid_magic = True
                break

        if not valid_magic:
            return HttpResponse("Invalid file", status=400)

    # Optimize images
    IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}
    if file_ext in IMAGE_EXTENSIONS and file_ext != 'svg':  # Don't optimize SVG (vector format)
        try:
            img = Image.open(uploaded_file)

            # Convert RGBA to RGB if saving as JPEG
            if img.mode in ('RGBA', 'LA', 'P') and file_ext in ('jpg', 'jpeg'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img

            # Resize if too large (max 2000px on longest side)
            max_dimension = 2000
            if max(img.size) > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            # Save optimized image to BytesIO
            output = BytesIO()
            save_format = 'JPEG' if file_ext in ('jpg', 'jpeg') else file_ext.upper()

            if save_format == 'JPEG':
                img.save(output, format=save_format, quality=85, optimize=True)
            elif save_format == 'PNG':
                img.save(output, format=save_format, optimize=True)
            else:
                img.save(output, format=save_format)

            output.seek(0)

            # Replace uploaded_file with optimized version
            uploaded_file = InMemoryUploadedFile(
                output,
                'ImageField',
                uploaded_file.name,
                uploaded_file.content_type,
                output.getbuffer().nbytes,
                None
            )
        except Exception as e:
            # If optimization fails, use original file
            pass

    # Create attachment
    attachment = Attachment(
        organization=org,
        entity_type=entity_type,
        entity_id=entity_id,
        file=uploaded_file,
        original_filename=uploaded_file.name,
        file_size=uploaded_file.size,
        content_type=mimetypes.guess_type(uploaded_file.name)[0] or 'application/octet-stream',
        uploaded_by=request.user,
        description=request.POST.get('description', '')
    )
    attachment.save()

    return JsonResponse({
        'id': attachment.id,
        'url': attachment.file.url,
        'filename': attachment.original_filename,
        'file_size_human': f"{attachment.file_size // 1024} KB" if attachment.file_size >= 1024 else f"{attachment.file_size} B",
    }, status=201)


@login_required
@require_http_methods(["POST"])
def delete_attachment(request, pk):
    """Delete an attachment owned by this organisation."""
    org = get_request_organization(request)
    attachment = get_object_or_404(Attachment, pk=pk, organization=org)
    attachment.file.delete(save=False)
    attachment.delete()
    return JsonResponse({'success': True})
