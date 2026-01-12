"""
Files models - Private attachments
"""
import os
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from core.models import Organization, BaseModel
from core.utils import OrganizationManager


def attachment_upload_path(instance, filename):
    """
    Generate upload path: org_id/entity_type/entity_id/uuid_filename
    """
    ext = os.path.splitext(filename)[1]
    unique_filename = f"{uuid.uuid4()}{ext}"
    return os.path.join(
        str(instance.organization.id),
        instance.entity_type,
        str(instance.entity_id),
        unique_filename
    )


class Attachment(BaseModel):
    """
    File attachment linked to any entity.
    Files are stored privately and served via X-Accel-Redirect.
    """
    ENTITY_TYPES = [
        ('asset', 'Asset'),
        ('document', 'Document'),
        ('password', 'Password'),
        ('contact', 'Contact'),
        ('vendor', 'Vendor'),
        ('equipment_model', 'Equipment Model'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='attachments')

    # Generic relation to any entity
    entity_type = models.CharField(max_length=50, choices=ENTITY_TYPES)
    entity_id = models.PositiveIntegerField()

    # File info
    file = models.FileField(upload_to=attachment_upload_path, max_length=500)
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()  # bytes
    content_type = models.CharField(max_length=100)

    # Metadata
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='attachments_uploaded')
    description = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'attachments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'entity_type', 'entity_id']),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.entity_type}:{self.entity_id})"

    @property
    def file_path(self):
        """
        Get absolute file path for X-Accel-Redirect.
        """
        return os.path.join(settings.UPLOAD_ROOT, self.file.name)

    @property
    def size_kb(self):
        """
        File size in KB.
        """
        return round(self.file_size / 1024, 2)

    def save(self, *args, **kwargs):
        """Override save to optimize images before saving."""
        # Check if this is an image and needs optimization
        if self.content_type and self.content_type.startswith('image/') and self.file:
            # Skip SVG as it's XML-based
            if 'svg' not in self.content_type.lower():
                self._optimize_image()

        super().save(*args, **kwargs)

    def _optimize_image(self):
        """Optimize image file to reduce size while maintaining quality."""
        from PIL import Image
        from io import BytesIO
        from django.core.files.uploadedfile import InMemoryUploadedFile

        try:
            # Open the image
            img = Image.open(self.file)

            # Convert RGBA/P to RGB for JPEG compatibility
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            # Determine max dimensions (optimize large images)
            MAX_WIDTH = 2048
            MAX_HEIGHT = 2048

            # Resize if too large
            if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
                img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.Resampling.LANCZOS)

            # Save optimized image to BytesIO
            output = BytesIO()
            img_format = img.format or 'JPEG'

            # Optimize based on format
            if img_format in ('JPEG', 'JPG'):
                img.save(output, format='JPEG', quality=85, optimize=True)
                content_type = 'image/jpeg'
            elif img_format == 'PNG':
                img.save(output, format='PNG', optimize=True)
                content_type = 'image/png'
            elif img_format == 'WEBP':
                img.save(output, format='WEBP', quality=85, method=6)
                content_type = 'image/webp'
            else:
                # For other formats, save as JPEG
                img.save(output, format='JPEG', quality=85, optimize=True)
                content_type = 'image/jpeg'

            output.seek(0)

            # Create new InMemoryUploadedFile
            self.file = InMemoryUploadedFile(
                output,
                'ImageField',
                self.file.name,
                content_type,
                output.tell(),
                None
            )
            self.content_type = content_type
            self.file_size = output.tell()

        except Exception as e:
            # If optimization fails, log and continue with original file
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to optimize image {self.original_filename}: {str(e)}")
