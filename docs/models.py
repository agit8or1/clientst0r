"""
Docs models - Knowledge base documents with versions
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager
import markdown
import bleach


class DocumentCategory(BaseModel):
    """
    Categories for organizing documents in Knowledge Base.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='document_categories')
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subcategories')
    icon = models.CharField(max_length=50, default='folder', help_text='Font Awesome icon name')
    order = models.IntegerField(default=0)

    objects = OrganizationManager()

    class Meta:
        db_table = 'document_categories'
        unique_together = [['organization', 'slug']]
        ordering = ['order', 'name']
        verbose_name_plural = 'Document categories'

    def __str__(self):
        return self.name


class Document(BaseModel):
    """
    Knowledge base document with HTML or Markdown body.
    """
    CONTENT_TYPES = [
        ('html', 'HTML (WYSIWYG)'),
        ('markdown', 'Markdown'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    body = models.TextField()
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES, default='html')
    is_published = models.BooleanField(default=True)
    is_template = models.BooleanField(default=False, help_text='Is this a reusable template?')
    is_archived = models.BooleanField(default=False)
    is_global = models.BooleanField(default=False, help_text='Global KB - visible to all organizations')

    # Relations
    category = models.ForeignKey(DocumentCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    tags = models.ManyToManyField(Tag, blank=True, related_name='documents')

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='documents_created')
    last_modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='documents_modified')

    objects = OrganizationManager()

    class Meta:
        db_table = 'documents'
        unique_together = [['organization', 'slug']]
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['organization', 'slug']),
            models.Index(fields=['is_published']),
        ]

    def __str__(self):
        return self.title

    def render_content(self):
        """
        Render content based on content_type.
        """
        if self.content_type == 'markdown':
            # Render markdown to HTML
            html = markdown.markdown(
                self.body,
                extensions=['extra', 'codehilite', 'toc']
            )
        else:
            # Already HTML from WYSIWYG editor
            html = self.body

        # Sanitize HTML for security
        allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
            'p', 'br', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'strong', 'em', 'ul', 'ol', 'li', 'blockquote', 'hr', 'table',
            'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span', 'img', 'a'
        ]
        allowed_attrs = {
            **bleach.sanitizer.ALLOWED_ATTRIBUTES,
            'img': ['src', 'alt', 'title', 'width', 'height', 'class', 'style'],
            'a': ['href', 'title', 'target', 'rel'],
            'code': ['class'],
            'div': ['class', 'style'],
            'span': ['class', 'style'],
            'p': ['class', 'style'],
            'table': ['class', 'style'],
            'td': ['colspan', 'rowspan', 'style'],
            'th': ['colspan', 'rowspan', 'style'],
        }
        return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)

    # Backward compatibility
    def render_markdown(self):
        return self.render_content()

    def save(self, *args, **kwargs):
        # Create version on save if document already exists
        if self.pk:
            self._create_version()
        super().save(*args, **kwargs)

    def _create_version(self):
        """
        Create a version snapshot before saving changes.
        """
        try:
            old_doc = Document.objects.get(pk=self.pk)
            DocumentVersion.objects.create(
                document=self,
                title=old_doc.title,
                body=old_doc.body,
                version_number=self.versions.count() + 1,
                created_by=self.last_modified_by
            )
        except Document.DoesNotExist:
            pass


class DocumentVersion(BaseModel):
    """
    Document version history.
    """
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    body = models.TextField()
    content_type = models.CharField(max_length=20, default='markdown')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'document_versions'
        unique_together = [['document', 'version_number']]
        ordering = ['-version_number']

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"


class DocumentFlag(BaseModel):
    """
    User bookmarks/flags on documents.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='document_flags')
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='flags')
    color = models.CharField(max_length=20, default='yellow', choices=[
        ('yellow', 'Yellow'),
        ('red', 'Red'),
        ('blue', 'Blue'),
        ('green', 'Green'),
        ('purple', 'Purple'),
    ])
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'document_flags'
        unique_together = [['user', 'document']]

    def __str__(self):
        return f"{self.user.username} flagged {self.document.title}"
