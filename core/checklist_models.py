"""
Checklist models - Tasks and checklists
"""
from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from core.models import Organization, BaseModel
from core.utils import OrganizationManager


class Checklist(BaseModel):
    """
    Reusable checklist template or attached to specific object.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='checklists')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_template = models.BooleanField(default=False)

    # Optional: Link to specific object
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='checklists_created')

    objects = OrganizationManager()

    class Meta:
        db_table = 'checklists'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def completion_percentage(self):
        """Calculate completion percentage."""
        total = self.items.count()
        if total == 0:
            return 0
        completed = self.items.filter(is_completed=True).count()
        return int((completed / total) * 100)


class ChecklistItem(BaseModel):
    """
    Individual checklist item/task.
    """
    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name='items')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='checklist_items_completed')

    class Meta:
        db_table = 'checklist_items'
        ordering = ['order', 'created_at']

    def __str__(self):
        return self.title
