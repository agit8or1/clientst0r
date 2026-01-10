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


class Diagram(BaseModel):
    """
    Draw.io diagram with versioning support.
    """
    DIAGRAM_TYPES = [
        ('network', 'Network Diagram'),
        ('process', 'Process Flow'),
        ('architecture', 'System Architecture'),
        ('rack', 'Rack Layout'),
        ('floorplan', 'Floor Plan'),
        ('org', 'Organizational Chart'),
        ('erd', 'Entity Relationship Diagram'),
        ('flowchart', 'Flowchart'),
        ('other', 'Other'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='diagrams'
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
            ('note', 'Note'),
            ('comment', 'Comment'),
            ('issue', 'Issue'),
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
