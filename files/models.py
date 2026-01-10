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
