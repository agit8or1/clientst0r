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
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='document_categories', null=True, blank=True, help_text='Organization for org-specific categories. NULL for global KB categories.')
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

    def save(self, *args, **kwargs):
        # Auto-generate slug if not provided
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Document(BaseModel):
    """
    Knowledge base document with HTML or Markdown body, or uploaded file.
    """
    CONTENT_TYPES = [
        ('html', 'HTML (WYSIWYG)'),
        ('markdown', 'Markdown'),
        ('file', 'Uploaded File'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='documents', null=True, blank=True, help_text='Organization for org-specific docs. NULL for global KB articles.')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    body = models.TextField(blank=True)  # Now optional for file uploads
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES, default='html')
    is_published = models.BooleanField(default=True)
    is_template = models.BooleanField(default=False, help_text='Is this a reusable template?')
    is_archived = models.BooleanField(default=False)
    is_global = models.BooleanField(default=False, help_text='Global KB - visible to all organizations')

    # File upload fields
    file = models.FileField(
        upload_to='documents/files/%Y/%m/',
        null=True,
        blank=True,
        help_text='Uploaded file (PDF, DOCX, images, etc.)'
    )
    file_size = models.BigIntegerField(null=True, blank=True, help_text='File size in bytes')
    file_type = models.CharField(max_length=100, blank=True, help_text='MIME type of uploaded file')

    # Relations
    category = models.ForeignKey(DocumentCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    tags = models.ManyToManyField(Tag, blank=True, related_name='documents')

    # Preview image for templates
    preview_image = models.ImageField(
        upload_to='documents/previews/',
        null=True,
        blank=True,
        help_text='Preview image for template (300x200)'
    )

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
            # Already HTML from WYSIWYG editor or AI-generated
            html = self.body

        # Sanitize HTML for security
        # Allow Bootstrap 5 styling components and Font Awesome icons
        allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
            'p', 'br', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'strong', 'em', 'ul', 'ol', 'li', 'blockquote', 'hr', 'table',
            'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span', 'img', 'a',
            'i', 'b', 'u', 's', 'small', 'mark', 'del', 'ins', 'sub', 'sup',
            'button', 'kbd', 'samp', 'var', 'abbr', 'address', 'cite', 'q',
            'section', 'article', 'header', 'footer', 'nav', 'aside', 'main',
            'figure', 'figcaption', 'details', 'summary', 'time', 'dl', 'dt', 'dd'
        ]
        allowed_attrs = {
            **bleach.sanitizer.ALLOWED_ATTRIBUTES,
            '*': ['class', 'id', 'style'],  # Allow class/id/style on all tags for Bootstrap
            'img': ['src', 'alt', 'title', 'width', 'height', 'class', 'style', 'loading'],
            'a': ['href', 'title', 'target', 'rel', 'class', 'style'],
            'button': ['type', 'class', 'style', 'disabled', 'data-*'],
            'div': ['class', 'id', 'style', 'role', 'aria-*', 'data-*'],
            'span': ['class', 'id', 'style', 'role', 'aria-*', 'data-*'],
            'i': ['class', 'style', 'aria-*'],  # Font Awesome icons
            'table': ['class', 'style', 'border', 'cellpadding', 'cellspacing'],
            'td': ['colspan', 'rowspan', 'style', 'class'],
            'th': ['colspan', 'rowspan', 'style', 'class', 'scope'],
            'ul': ['class', 'style'],
            'ol': ['class', 'style', 'start', 'type'],
            'li': ['class', 'style'],
            'code': ['class', 'style'],
            'pre': ['class', 'style'],
            'p': ['class', 'style'],
            'h1': ['class', 'id', 'style'],
            'h2': ['class', 'id', 'style'],
            'h3': ['class', 'id', 'style'],
            'h4': ['class', 'id', 'style'],
            'h5': ['class', 'id', 'style'],
            'h6': ['class', 'id', 'style'],
            'section': ['class', 'id', 'style'],
            'article': ['class', 'id', 'style'],
            'blockquote': ['class', 'style', 'cite'],
        }
        return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=False)

    # Backward compatibility
    def render_markdown(self):
        return self.render_content()

    def save(self, *args, **kwargs):
        # Auto-generate slug if not provided
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.title)
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
        ('blue', 'Blue'),
        ('green', 'Green'),
        ('purple', 'Purple'),
        ('red', 'Red'),
        ('yellow', 'Yellow'),
    ])
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'document_flags'
        unique_together = [['user', 'document']]

    def __str__(self):
        return f"{self.user.username} flagged {self.document.title}"


class Diagram(BaseModel):
    """
    Draw.io diagram with versioning support.
    """
    DIAGRAM_TYPES = [
        ('erd', 'Entity Relationship Diagram'),
        ('floorplan', 'Floor Plan'),
        ('flowchart', 'Flowchart'),
        ('network', 'Network Diagram'),
        ('org', 'Organizational Chart'),
        ('other', 'Other'),
        ('process', 'Process Flow'),
        ('rack', 'Rack Layout'),
        ('architecture', 'System Architecture'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='diagrams',
        null=True,
        blank=True,
        help_text='Organization for org-specific diagrams. NULL for global diagram templates.'
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)

    # Diagram data (current version)
    diagram_xml = models.TextField(help_text='.drawio XML format')

    # Export caching
    png_export = models.FileField(
        upload_to='diagrams/png/',
        null=True,
        blank=True,
        help_text='PNG export of diagram'
    )
    svg_export = models.FileField(
        upload_to='diagrams/svg/',
        null=True,
        blank=True,
        help_text='SVG export of diagram'
    )
    thumbnail = models.ImageField(
        upload_to='diagrams/thumbnails/',
        null=True,
        blank=True,
        help_text='Thumbnail preview (300x200)'
    )

    # Categorization
    diagram_type = models.CharField(
        max_length=50,
        choices=DIAGRAM_TYPES,
        default='other'
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='diagrams')

    # Global/template support
    is_global = models.BooleanField(
        default=False,
        help_text='Global diagram - visible to all organizations'
    )
    is_published = models.BooleanField(default=True)
    is_template = models.BooleanField(
        default=False,
        help_text='Diagram template - can be cloned'
    )

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='diagrams_created'
    )
    last_modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='diagrams_modified'
    )
    last_edited_at = models.DateTimeField(auto_now=True)

    # Version tracking
    version_number = models.PositiveIntegerField(default=1)

    objects = OrganizationManager()

    class Meta:
        db_table = 'diagrams'
        unique_together = [['organization', 'slug']]
        ordering = ['-last_edited_at']
        indexes = [
            models.Index(fields=['organization', 'slug']),
            models.Index(fields=['diagram_type']),
            models.Index(fields=['is_global', 'is_published']),
        ]

    def __str__(self):
        prefix = "[GLOBAL] " if self.is_global else ""
        template = "[TEMPLATE] " if self.is_template else ""
        return f"{prefix}{template}{self.title} (v{self.version_number})"

    def save(self, *args, **kwargs):
        from django.utils.text import slugify
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def create_version_snapshot(self, user):
        """Create a version snapshot of current diagram."""
        DiagramVersion.objects.create(
            diagram=self,
            version_number=self.version_number,
            diagram_xml=self.diagram_xml,
            created_by=user
        )


class DiagramVersion(BaseModel):
    """
    Version history for diagrams.
    """
    diagram = models.ForeignKey(
        Diagram,
        on_delete=models.CASCADE,
        related_name='versions'
    )
    version_number = models.PositiveIntegerField()
    diagram_xml = models.TextField(help_text='Snapshot of diagram XML')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    change_notes = models.TextField(blank=True)

    class Meta:
        db_table = 'diagram_versions'
        unique_together = [['diagram', 'version_number']]
        ordering = ['-version_number']
        indexes = [
            models.Index(fields=['diagram', '-version_number']),
        ]

    def __str__(self):
        return f"{self.diagram.title} - v{self.version_number}"


class DiagramAnnotation(BaseModel):
    """
    Annotations on diagrams (comments, notes, highlights).
    """
    diagram = models.ForeignKey(
        Diagram,
        on_delete=models.CASCADE,
        related_name='annotations'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='diagram_annotations'
    )

    # Annotation content
    text = models.TextField()
    annotation_type = models.CharField(
        max_length=20,
        choices=[
            ('comment', 'Comment'),
            ('issue', 'Issue'),
            ('note', 'Note'),
            ('suggestion', 'Suggestion'),
        ],
        default='note'
    )

    # Position (optional - for pinned annotations)
    position_x = models.IntegerField(null=True, blank=True)
    position_y = models.IntegerField(null=True, blank=True)

    is_resolved = models.BooleanField(default=False)

    class Meta:
        db_table = 'diagram_annotations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['diagram', '-created_at']),
        ]

    def __str__(self):
        return f"{self.annotation_type}: {self.text[:50]}"
