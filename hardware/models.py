"""
Hardware catalog and visual inventory.

Two layers, deliberately separate:

* **Catalog** (global): ``Manufacturer`` → ``HardwareModel`` with its
  ``ComponentTemplate`` rows, ``PortMappingTemplate`` rows and a versioned
  ``LayoutTemplate`` (artwork geometry). Shared by every client. Populated from
  the community devicetype-library (CC0) by ``import_hardware_catalog`` and by
  staff through "Add model".

* **Client inventory** (organization-scoped): ``HardwareDevice`` extends an
  existing ``assets.Asset`` with the model it is an instance of. Its
  ``DevicePort`` rows are copies of the model's component templates, linked
  back by the template's stable ``key`` so a later catalog change can be
  previewed and applied without remapping ports or breaking cables.
  Connectivity is normalized: ``Cable`` + ``CableTermination``, passive
  ``PortMapping``, ``PortVLAN`` membership, ``LinkAggregationGroup``.

Racks, rack placement and VLANs are the existing ``monitoring.Rack`` /
``monitoring.RackDevice`` / ``monitoring.VLAN`` rows — this module adds
behaviour to them rather than a second copy.
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.models import BaseModel, Organization
from core.utils import OrganizationManager

from . import connectors as C


# =============================================================================
# Catalog
# =============================================================================

class CatalogSource(BaseModel):
    """An external data source and the revision we last imported from it."""
    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    url = models.URLField()
    license_name = models.CharField(max_length=100)
    license_url = models.URLField(blank=True)
    revision = models.CharField(max_length=64, blank=True, help_text='Pinned commit the catalog was last imported from')
    revision_date = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'hw_catalog_sources'

    def __str__(self):
        return self.name

    def file_url(self, path, revision=None):
        rev = revision or self.revision or 'master'
        return f'{self.url.rstrip("/")}/blob/{rev}/{path}'


class Manufacturer(BaseModel):
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True)
    vendor = models.ForeignKey(
        'assets.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hardware_manufacturers',
        help_text='Matching procurement vendor, when one exists')
    source = models.ForeignKey(CatalogSource, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'hw_manufacturers'
        ordering = ['name']

    def __str__(self):
        return self.name


class HardwareModel(BaseModel):
    """A reusable definition of a manufacturer's model (device, module or rack)."""

    KIND_DEVICE = 'device'
    KIND_MODULE = 'module'
    KIND_RACK = 'rack'
    KIND_CHOICES = [(KIND_DEVICE, 'Device'), (KIND_MODULE, 'Module'), (KIND_RACK, 'Rack')]

    CATEGORY_CHOICES = [
        ('switch', 'Switch'),
        ('router', 'Router'),
        ('firewall', 'Firewall'),
        ('wireless_controller', 'Wireless controller'),
        ('access_point', 'Wireless access point'),
        ('server', 'Server'),
        ('blade_chassis', 'Blade chassis'),
        ('blade_server', 'Blade server'),
        ('storage', 'NAS / SAN storage'),
        ('storage_shelf', 'Storage shelf / JBOD'),
        ('patch_panel', 'Copper patch panel'),
        ('fiber_panel', 'Fiber panel / enclosure'),
        ('wall_jack', 'Wall jack / faceplate'),
        ('outlet', 'Power outlet / receptacle'),
        ('ups', 'UPS'),
        ('pdu', 'PDU'),
        ('console_server', 'Console server'),
        ('workstation', 'Workstation / endpoint'),
        ('phone', 'IP phone'),
        ('camera', 'Camera'),
        ('kvm', 'KVM'),
        ('nic', 'NIC / expansion card'),
        ('line_card', 'Line card / network module'),
        ('transceiver', 'Transceiver'),
        ('psu', 'Power supply'),
        ('fan', 'Fan module'),
        ('drive', 'Drive / drive carrier'),
        ('module_other', 'Other module'),
        ('rack', 'Rack / cabinet'),
        ('other', 'Other equipment'),
    ]
    CATEGORY_KEYS = {k for k, _ in CATEGORY_CHOICES}

    CATEGORY_SOURCE_CHOICES = [
        ('inferred', 'Inferred from components and name'),
        ('manual', 'Set by staff'),
    ]

    PROVENANCE_CHOICES = [
        ('upstream', 'Community library (devicetype-library)'),
        ('manufacturer', 'Manufacturer documentation'),
        ('local', 'Entered locally'),
        ('generic', 'Generic template'),
    ]

    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.PROTECT, related_name='models')
    model = models.CharField(max_length=200)
    slug = models.SlugField(max_length=250)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_DEVICE)
    part_number = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='other')
    category_source = models.CharField(max_length=10, choices=CATEGORY_SOURCE_CHOICES, default='inferred')
    description = models.TextField(blank=True)
    comments = models.TextField(blank=True)

    # Physical
    u_height = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    is_full_depth = models.BooleanField(default=True)
    airflow = models.CharField(max_length=30, blank=True)
    weight = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    weight_unit = models.CharField(max_length=5, blank=True)
    subdevice_role = models.CharField(max_length=10, blank=True, help_text='parent / child for blade chassis')
    is_powered = models.BooleanField(default=True)
    # Rack types only
    rack_spec = models.JSONField(default=dict, blank=True, help_text='Rack dimensions/form factor (rack kind only)')

    is_generic = models.BooleanField(default=False, help_text='A user-configurable generic template, not a real model')
    is_active = models.BooleanField(default=True)

    # Specification provenance — what the component list rests on.
    spec_provenance = models.CharField(max_length=15, choices=PROVENANCE_CHOICES, default='upstream')
    spec_source_url = models.URLField(max_length=500, blank=True)
    spec_notes = models.TextField(blank=True)

    # Upstream record (kept verbatim so nothing is silently discarded)
    source = models.ForeignKey(CatalogSource, on_delete=models.SET_NULL, null=True, blank=True, related_name='models')
    upstream_path = models.CharField(max_length=400, blank=True, db_index=True,
                                     help_text='Path of the definition inside the source repository')
    upstream_revision = models.CharField(max_length=64, blank=True)
    upstream_sha = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the imported file')
    upstream_data = models.JSONField(default=dict, blank=True, help_text='The definition exactly as imported')
    unsupported_fields = models.JSONField(default=list, blank=True,
                                          help_text='Upstream keys this application does not model (kept in upstream_data)')
    imported_at = models.DateTimeField(null=True, blank=True)

    # Local customization lives beside upstream data, never inside it.
    locally_modified = models.BooleanField(default=False)
    local_fields = models.JSONField(default=list, blank=True, help_text='Field names staff changed locally')

    equipment_model = models.OneToOneField(
        'assets.EquipmentModel', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hardware_model', help_text='Matching entry in the procurement equipment catalog')

    revision = models.PositiveIntegerField(default=1, help_text='Bumped whenever components or layout change')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'hw_models'
        ordering = ['manufacturer__name', 'model']
        constraints = [
            models.UniqueConstraint(fields=['manufacturer', 'kind', 'slug'], name='hw_model_unique_slug'),
        ]
        indexes = [
            models.Index(fields=['kind', 'category']),
            models.Index(fields=['model']),
            models.Index(fields=['part_number']),
        ]

    def __str__(self):
        return f'{self.manufacturer.name} {self.model}'

    @property
    def is_rackmount(self):
        return self.u_height and self.u_height > 0

    @property
    def current_layout(self):
        return self.layouts.filter(is_current=True).first()

    def upstream_url(self):
        if self.source and self.upstream_path:
            return self.source.file_url(self.upstream_path, self.upstream_revision)
        return ''


class ComponentTemplate(BaseModel):
    """One component of a catalog model.

    ``key`` is the stable identifier: device ports keep it after they are
    created, artwork geometry refers to it, and template updates match on it.
    It never changes, even when the component is renamed.
    """
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.CASCADE, related_name='components')
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    component_class = models.CharField(max_length=20, choices=C.TEMPLATE_CLASSES)
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=100, blank=True, help_text='Printed number or label')
    type = models.CharField(max_length=50, blank=True, help_text='Upstream type, e.g. 1000base-t, sfp, 8p8c, iec-60320-c14')
    connector = models.CharField(max_length=20, blank=True, choices=C.CONNECTOR_CHOICES)
    description = models.CharField(max_length=250, blank=True)
    mgmt_only = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    poe_mode = models.CharField(max_length=10, blank=True)
    poe_type = models.CharField(max_length=30, blank=True)
    rf_role = models.CharField(max_length=10, blank=True)
    positions = models.PositiveIntegerField(default=1)
    color = models.CharField(max_length=6, blank=True)
    maximum_draw = models.PositiveIntegerField(null=True, blank=True)
    allocated_draw = models.PositiveIntegerField(null=True, blank=True)
    feed_leg = models.CharField(max_length=1, blank=True)
    power_port_name = models.CharField(max_length=100, blank=True)
    bay_position = models.CharField(max_length=30, blank=True, help_text='Module bay position token')
    part_id = models.CharField(max_length=60, blank=True)
    item_manufacturer = models.CharField(max_length=100, blank=True)
    # Ports in the same combo group are alternative physical sockets for one
    # logical port (e.g. an RJ45/SFP combo): only one may be in use.
    combo_group = models.CharField(max_length=40, blank=True)
    origin = models.CharField(max_length=10, default='upstream',
                              choices=[('upstream', 'Upstream'), ('local', 'Local')])
    sort_order = models.PositiveIntegerField(default=0)
    extra = models.JSONField(default=dict, blank=True, help_text='Upstream attributes without a column (e.g. bridge)')

    class Meta:
        db_table = 'hw_component_templates'
        ordering = ['hardware_model', 'sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['hardware_model', 'component_class', 'name'],
                                    name='hw_component_unique_name'),
        ]
        indexes = [models.Index(fields=['hardware_model', 'component_class'])]

    def __str__(self):
        return f'{self.hardware_model} · {self.name}'

    @property
    def is_socket(self):
        return self.component_class in dict(C.PHYSICAL_PORT_CLASSES)


class PortMappingTemplate(models.Model):
    """Internal front→rear mapping of a passive model (patch panel, wall jack)."""
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.CASCADE, related_name='port_mappings')
    front_port = models.ForeignKey(ComponentTemplate, on_delete=models.CASCADE, related_name='+')
    front_position = models.PositiveIntegerField(default=1)
    rear_port = models.ForeignKey(ComponentTemplate, on_delete=models.CASCADE, related_name='+')
    rear_position = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'hw_port_mapping_templates'
        constraints = [
            models.UniqueConstraint(fields=['front_port', 'front_position'], name='hw_pmt_front_unique'),
            models.UniqueConstraint(fields=['rear_port', 'rear_position'], name='hw_pmt_rear_unique'),
        ]


class LayoutTemplate(BaseModel):
    """Artwork geometry for one model, versioned.

    ``faces`` holds, per face, the panel size and the position of every
    element in millimetres from the top-left corner of that face. Elements
    that are components carry the component template ``key``; the renderer
    draws them and emits a hit target at exactly the same rectangle, so the
    artwork, the click target, printed labels and exports share one geometry.

    Accuracy is about *placement*, separate from the model's specification
    provenance: a correct port count does not make an arrangement right.
    """
    ACCURACY_VERIFIED = 'verified'
    ACCURACY_APPROXIMATE = 'approximate'
    ACCURACY_GENERIC = 'generic'
    ACCURACY_CHOICES = [
        (ACCURACY_VERIFIED, 'Verified layout'),
        (ACCURACY_APPROXIMATE, 'Approximate layout'),
        (ACCURACY_GENERIC, 'Generic layout'),
    ]

    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.CASCADE, related_name='layouts')
    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    accuracy = models.CharField(max_length=12, choices=ACCURACY_CHOICES, default=ACCURACY_APPROXIMATE)
    faces = models.JSONField(default=dict)
    auto_generated = models.BooleanField(default=True, help_text='Produced by the auto-layout, not placed by a person')
    generator_version = models.PositiveIntegerField(default=0, help_text='Auto-layout rules version that produced it')
    source_url = models.URLField(max_length=500, blank=True, help_text='Document the placement was checked against')
    source_notes = models.TextField(blank=True, help_text='What was verified and what remains uncertain')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'hw_layout_templates'
        ordering = ['hardware_model', '-version']
        constraints = [
            models.UniqueConstraint(fields=['hardware_model', 'version'], name='hw_layout_unique_version'),
            models.UniqueConstraint(fields=['hardware_model'], condition=Q(is_current=True),
                                    name='hw_layout_one_current'),
        ]

    def __str__(self):
        return f'{self.hardware_model} layout v{self.version}'

    def face_accuracy(self, face):
        return (self.faces.get(face) or {}).get('accuracy') or self.accuracy


class ModelRevision(models.Model):
    """Snapshot of a model's components + layout at a revision number.

    Devices remember the revision they were built from; the diff between that
    snapshot and the current one is what "preview template update" shows.
    """
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.CASCADE, related_name='revisions')
    number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reason = models.CharField(max_length=200, blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = 'hw_model_revisions'
        ordering = ['hardware_model', '-number']
        constraints = [
            models.UniqueConstraint(fields=['hardware_model', 'number'], name='hw_revision_unique'),
        ]


class RenderedArtwork(models.Model):
    """Cache of generated SVG artwork, keyed by model + layout version + face.

    Catalog artwork contains no client data, so one cached copy serves every
    client that owns the model. Client overlays are applied in the browser.
    """
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.CASCADE, related_name='artwork')
    layout_version = models.PositiveIntegerField()
    face = models.CharField(max_length=10)
    variant = models.CharField(max_length=20, default='full')
    renderer_version = models.PositiveIntegerField()
    svg = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hw_rendered_artwork'
        constraints = [
            models.UniqueConstraint(fields=['hardware_model', 'layout_version', 'face', 'variant', 'renderer_version'],
                                    name='hw_artwork_unique'),
        ]


class CatalogImportJob(BaseModel):
    """One run of the catalog importer. Resumable: records are per file."""
    STATUS_CHOICES = [
        ('preview', 'Preview (no writes)'),
        ('running', 'Running'),
        ('paused', 'Paused / interrupted'),
        ('completed', 'Completed'),
        ('completed_with_errors', 'Completed with errors'),
        ('failed', 'Failed'),
    ]
    source = models.ForeignKey(CatalogSource, on_delete=models.PROTECT, related_name='jobs')
    revision = models.CharField(max_length=64)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='running')
    is_preview = models.BooleanField(default=False)
    overwrite_local = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total_files = models.PositiveIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    counts = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True)
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'hw_import_jobs'
        ordering = ['-started_at']

    def __str__(self):
        return f'Import {self.pk} @ {self.revision[:10]} ({self.status})'


class CatalogImportRecord(models.Model):
    """Outcome for one upstream file within one job."""
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('unchanged', 'Unchanged'),
        ('conflict', 'Skipped — local changes'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
        ('would_create', 'Would create'),
        ('would_update', 'Would update'),
    ]
    job = models.ForeignKey(CatalogImportJob, on_delete=models.CASCADE, related_name='records')
    path = models.CharField(max_length=400)
    kind = models.CharField(max_length=10)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES)
    sha = models.CharField(max_length=64, blank=True)
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    manufacturer = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=30, blank=True)
    message = models.TextField(blank=True)
    unsupported_fields = models.JSONField(default=list, blank=True)
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'hw_import_records'
        constraints = [
            models.UniqueConstraint(fields=['job', 'path'], name='hw_import_record_unique'),
        ]
        indexes = [models.Index(fields=['job', 'status'])]


class ModelRequest(BaseModel):
    """A technician asking for a model the catalog does not have."""
    STATUS_CHOICES = [('open', 'Open'), ('created', 'Model created'), ('declined', 'Declined')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='hardware_model_requests')
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    manufacturer = models.CharField(max_length=200)
    model = models.CharField(max_length=200)
    part_number = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=30, choices=HardwareModel.CATEGORY_CHOICES, default='other')
    datasheet_url = models.URLField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    created_model = models.ForeignKey(HardwareModel, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    objects = OrganizationManager()

    class Meta:
        db_table = 'hw_model_requests'
        ordering = ['-created_at']


# =============================================================================
# Client inventory
# =============================================================================

class HardwareDevice(BaseModel):
    """A physical device a client owns, built from a catalog model.

    Extends ``assets.Asset`` (name, hostname, serial, asset tag, management
    IP, firmware, warranty expiry, notes, tags live there and keep working in
    the rest of the application) with what the catalog-backed inventory
    needs.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('planned', 'Planned'),
        ('staged', 'Staged'),
        ('spare', 'Spare'),
        ('offline', 'Offline'),
        ('failed', 'Failed'),
        ('decommissioning', 'Decommissioning'),
        ('retired', 'Retired'),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False,
                                 help_text='Opaque identifier used in QR codes')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='hardware_devices')
    asset = models.OneToOneField('assets.Asset', on_delete=models.CASCADE, related_name='hardware')
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.PROTECT, related_name='devices',
                                       limit_choices_to={'kind': HardwareModel.KIND_DEVICE})
    template_revision = models.PositiveIntegerField(default=1, help_text='Model revision the ports were built from')
    site = models.ForeignKey('locations.Location', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='hardware_devices')
    room = models.CharField(max_length=100, blank=True)
    location_detail = models.CharField(max_length=200, blank=True, help_text='e.g. "under desk", "IDF closet shelf 2"')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    platform = models.CharField(max_length=100, blank=True,
                                help_text='Software platform, e.g. OPNsense, Proxmox VE. Does not imply a chassis.')
    install_date = models.DateField(null=True, blank=True)
    warranty_start = models.DateField(null=True, blank=True)
    parent_device = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='child_devices', help_text='Blade chassis this device sits in')
    parent_bay = models.OneToOneField('ModuleBay', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='installed_device')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    objects = OrganizationManager()

    class Meta:
        db_table = 'hw_devices'
        ordering = ['asset__name']
        indexes = [models.Index(fields=['organization', 'status'])]

    def __str__(self):
        return self.asset.name

    def clean(self):
        if self.asset_id and self.asset.organization_id != self.organization_id:
            raise ValidationError('The asset belongs to a different client.')
        if self.site_id and self.site.organization_id not in (None, self.organization_id):
            raise ValidationError({'site': 'That site belongs to a different client.'})

    @property
    def name(self):
        return self.asset.name

    @property
    def rack_placement(self):
        return self.asset.rack_devices.select_related('rack').first()

    @property
    def template_outdated(self):
        return self.template_revision < self.hardware_model.revision


class ModuleBay(BaseModel):
    """A slot in a device (module bay, drive bay, PSU bay, blade bay)."""
    BAY_KIND_CHOICES = [('module', 'Module bay'), ('device', 'Device (blade) bay')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='module_bays')
    parent_module = models.ForeignKey('InstalledModule', on_delete=models.CASCADE, null=True, blank=True,
                                      related_name='child_bays')
    template_key = models.UUIDField(null=True, blank=True)
    bay_kind = models.CharField(max_length=10, choices=BAY_KIND_CHOICES, default='module')
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=100, blank=True)
    position = models.CharField(max_length=30, blank=True)
    description = models.CharField(max_length=250, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'hw_module_bays'
        ordering = ['device', 'sort_order', 'id']
        constraints = [models.UniqueConstraint(fields=['device', 'name'], name='hw_bay_unique_name')]

    def __str__(self):
        return f'{self.device} · {self.name}'


class InstalledModule(BaseModel):
    """A module fitted in a bay. Its ports become DevicePort rows on the device."""
    STATUS_CHOICES = [('active', 'Active'), ('planned', 'Planned'), ('failed', 'Failed'), ('spare', 'Spare')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='modules')
    bay = models.OneToOneField(ModuleBay, on_delete=models.PROTECT, related_name='installed_module')
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.PROTECT, related_name='installed_modules',
                                       limit_choices_to={'kind': HardwareModel.KIND_MODULE})
    template_revision = models.PositiveIntegerField(default=1)
    serial_number = models.CharField(max_length=120, blank=True)
    asset_tag = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'hw_installed_modules'

    def __str__(self):
        return f'{self.hardware_model} in {self.bay}'


class LinkAggregationGroup(BaseModel):
    MODE_CHOICES = [('lacp_active', 'LACP (active)'), ('lacp_passive', 'LACP (passive)'), ('static', 'Static')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='lags')
    name = models.CharField(max_length=64)
    mode = models.CharField(max_length=15, choices=MODE_CHOICES, default='lacp_active')
    description = models.CharField(max_length=250, blank=True)

    class Meta:
        db_table = 'hw_lags'
        ordering = ['device', 'name']
        constraints = [models.UniqueConstraint(fields=['device', 'name'], name='hw_lag_unique_name')]

    def __str__(self):
        return self.name


class DevicePort(BaseModel):
    """A physical connector on a device (or on a module in it).

    Documented configuration and observed state are separate fields. Nothing
    in the UI derives ``oper_state`` from a documented cable: a cable drawn by
    a technician is not evidence of link.
    """
    ADMIN_CHOICES = [('', 'Not documented'), ('enabled', 'Enabled'), ('disabled', 'Disabled')]
    OPER_CHOICES = [('unknown', 'Not observed'), ('up', 'Up'), ('down', 'Down'), ('not_present', 'Not present')]
    MODE_CHOICES = [
        ('', 'Not documented'),
        ('access', 'Access'),
        ('trunk', 'Trunk (tagged)'),
        ('hybrid', 'Hybrid / general'),
        ('routed', 'Routed (L3)'),
        ('none', 'Unused / shut'),
    ]
    POE_SETTING_CHOICES = [('', 'Not documented'), ('auto', 'Auto / enabled'), ('disabled', 'Disabled'),
                           ('static', 'Static allocation'), ('pd', 'Powered device (draws PoE)')]
    SPEED_CHOICES = [('', 'Not documented'), ('auto', 'Auto'), ('10m', '10 Mb/s'), ('100m', '100 Mb/s'),
                     ('1g', '1 Gb/s'), ('2.5g', '2.5 Gb/s'), ('5g', '5 Gb/s'), ('10g', '10 Gb/s'),
                     ('25g', '25 Gb/s'), ('40g', '40 Gb/s'), ('50g', '50 Gb/s'), ('100g', '100 Gb/s'),
                     ('200g', '200 Gb/s'), ('400g', '400 Gb/s')]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='hardware_ports')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='ports')
    module = models.ForeignKey(InstalledModule, on_delete=models.CASCADE, null=True, blank=True, related_name='ports')
    template_key = models.UUIDField(null=True, blank=True, db_index=True,
                                    help_text='Stable key of the component template this port came from')
    component_class = models.CharField(max_length=20, choices=C.PHYSICAL_PORT_CLASSES)
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=100, blank=True, help_text='Number printed on the chassis')
    type = models.CharField(max_length=50, blank=True)
    connector = models.CharField(max_length=20, blank=True, choices=C.CONNECTOR_CHOICES)
    description = models.CharField(max_length=250, blank=True)
    tech_label = models.CharField(max_length=100, blank=True, help_text='Label the technician applied')
    is_custom = models.BooleanField(default=False, help_text='Added on this device, not from the catalog')
    is_populated = models.BooleanField(default=True, help_text='False when this configuration lacks the part')
    mgmt_only = models.BooleanField(default=False)
    positions = models.PositiveIntegerField(default=1)
    combo_group = models.CharField(max_length=40, blank=True)
    breakout_parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='breakout_lanes')
    breakout_mode = models.CharField(max_length=20, blank=True, help_text='e.g. 4x10G when the cage runs split')

    speed_capability = models.CharField(max_length=60, blank=True)
    configured_speed = models.CharField(max_length=6, choices=SPEED_CHOICES, blank=True)
    admin_state = models.CharField(max_length=10, choices=ADMIN_CHOICES, blank=True)
    oper_state = models.CharField(max_length=12, choices=OPER_CHOICES, default='unknown')
    oper_observed_at = models.DateTimeField(null=True, blank=True)
    oper_source = models.CharField(max_length=60, blank=True, help_text='Where the observation came from')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, blank=True)
    untagged_vlan = models.ForeignKey('monitoring.VLAN', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='untagged_ports')
    voice_vlan = models.ForeignKey('monitoring.VLAN', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='voice_ports')
    lag = models.ForeignKey(LinkAggregationGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')

    poe_mode = models.CharField(max_length=10, blank=True, help_text='pse (supplies) / pd (draws), from the catalog')
    poe_type = models.CharField(max_length=30, blank=True)
    poe_setting = models.CharField(max_length=10, choices=POE_SETTING_CHOICES, blank=True)
    poe_notes = models.CharField(max_length=200, blank=True)

    maximum_draw = models.PositiveIntegerField(null=True, blank=True)
    allocated_draw = models.PositiveIntegerField(null=True, blank=True)
    feed_leg = models.CharField(max_length=1, blank=True)
    power_port = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='fed_outlets')
    color = models.CharField(max_length=6, blank=True)
    mac_address = models.CharField(max_length=17, blank=True)
    notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    objects = OrganizationManager()

    class Meta:
        db_table = 'hw_device_ports'
        ordering = ['device', 'sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['device', 'component_class', 'name'], name='hw_port_unique_name'),
            models.UniqueConstraint(fields=['device', 'template_key', 'module'],
                                    condition=Q(template_key__isnull=False, module__isnull=True),
                                    name='hw_port_unique_template_key'),
        ]
        indexes = [
            models.Index(fields=['device', 'component_class']),
            models.Index(fields=['organization', 'description']),
        ]

    def __str__(self):
        return f'{self.device} / {self.display_name}'

    @property
    def display_name(self):
        return self.name

    @property
    def is_passive(self):
        return self.component_class in (C.CLASS_FRONT_PORT, C.CLASS_REAR_PORT)

    @property
    def is_breakout_lane(self):
        return self.breakout_parent_id is not None

    def clean(self):
        errors = {}
        for f in ('untagged_vlan', 'voice_vlan'):
            v = getattr(self, f)
            if v is not None and v.organization_id != self.organization_id:
                errors[f] = 'That VLAN belongs to a different client.'
        if self.lag_id and self.lag.device_id != self.device_id:
            errors['lag'] = 'The LAG is on a different device.'
        if self.device_id and self.device.organization_id != self.organization_id:
            errors['organization'] = 'Port and device belong to different clients.'
        if self.oper_state != 'unknown' and not self.oper_source:
            errors['oper_state'] = 'Operational state needs a source (an observation or import).'
        if errors:
            raise ValidationError(errors)


class PortVLAN(models.Model):
    """Tagged VLAN membership of a port (the untagged/native VLAN is on the port)."""
    port = models.ForeignKey(DevicePort, on_delete=models.CASCADE, related_name='tagged_memberships')
    vlan = models.ForeignKey('monitoring.VLAN', on_delete=models.CASCADE, related_name='tagged_ports')

    class Meta:
        db_table = 'hw_port_vlans'
        constraints = [models.UniqueConstraint(fields=['port', 'vlan'], name='hw_port_vlan_unique')]

    def clean(self):
        if self.vlan.organization_id != self.port.organization_id:
            raise ValidationError('That VLAN belongs to a different client.')


class LogicalInterface(BaseModel):
    """A non-physical interface: SVI, loopback, LAG interface, bridge, tunnel."""
    KIND_CHOICES = [('svi', 'VLAN interface (SVI)'), ('loopback', 'Loopback'), ('lag', 'LAG interface'),
                    ('bridge', 'Bridge'), ('tunnel', 'Tunnel'), ('virtual', 'Other virtual')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='logical_interfaces')
    template_key = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='virtual')
    vlan = models.ForeignKey('monitoring.VLAN', on_delete=models.SET_NULL, null=True, blank=True, related_name='svis')
    lag = models.OneToOneField(LinkAggregationGroup, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='interface')
    ip_addresses = models.CharField(max_length=300, blank=True, help_text='Documented addresses, CIDR, comma-separated')
    description = models.CharField(max_length=250, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'hw_logical_interfaces'
        ordering = ['device', 'name']
        constraints = [models.UniqueConstraint(fields=['device', 'name'], name='hw_logical_unique_name')]


class WirelessRadio(BaseModel):
    """A radio. Never drawn as a socket and never cabled."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='radios')
    template_key = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=100)
    standard = models.CharField(max_length=30, blank=True, help_text='e.g. ieee802.11ax')
    rf_role = models.CharField(max_length=10, blank=True)
    band = models.CharField(max_length=20, blank=True, help_text='Documented band, e.g. 2.4 GHz / 5 GHz / 6 GHz')
    channel = models.CharField(max_length=20, blank=True)
    tx_power = models.CharField(max_length=20, blank=True)
    description = models.CharField(max_length=250, blank=True)

    class Meta:
        db_table = 'hw_wireless_radios'
        ordering = ['device', 'name']
        constraints = [models.UniqueConstraint(fields=['device', 'name'], name='hw_radio_unique_name')]


class WirelessSSID(BaseModel):
    """A broadcast network. Holds no keys or passphrases."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='hardware_ssids')
    ssid = models.CharField(max_length=32)
    vlan = models.ForeignKey('monitoring.VLAN', on_delete=models.SET_NULL, null=True, blank=True, related_name='ssids')
    security = models.CharField(max_length=40, blank=True, help_text='e.g. WPA2-Enterprise, WPA3-Personal')
    hidden = models.BooleanField(default=False)
    radios = models.ManyToManyField(WirelessRadio, blank=True, related_name='ssids')
    description = models.CharField(max_length=250, blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'hw_wireless_ssids'
        ordering = ['ssid']

    def __str__(self):
        return self.ssid


class DeviceInventoryItem(BaseModel):
    """A non-port part recorded by the catalog (e.g. a fixed PSU, CPU, drive)."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='inventory_items')
    template_key = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=100, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    part_id = models.CharField(max_length=60, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=250, blank=True)

    class Meta:
        db_table = 'hw_inventory_items'
        ordering = ['device', 'name']


class PortMapping(models.Model):
    """Internal passive path inside a device: front port (position) ↔ rear port (position)."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE, related_name='port_mappings')
    front_port = models.ForeignKey(DevicePort, on_delete=models.CASCADE, related_name='front_mappings')
    front_position = models.PositiveIntegerField(default=1)
    rear_port = models.ForeignKey(DevicePort, on_delete=models.CASCADE, related_name='rear_mappings')
    rear_position = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'hw_port_mappings'
        constraints = [
            models.UniqueConstraint(fields=['front_port', 'front_position'], name='hw_pm_front_unique'),
            models.UniqueConstraint(fields=['rear_port', 'rear_position'], name='hw_pm_rear_unique'),
        ]

    def clean(self):
        if self.front_port.component_class != C.CLASS_FRONT_PORT:
            raise ValidationError('The front side of a mapping must be a front port.')
        if self.rear_port.component_class != C.CLASS_REAR_PORT:
            raise ValidationError('The rear side of a mapping must be a rear port.')
        if self.front_port.device_id != self.device_id or self.rear_port.device_id != self.device_id:
            raise ValidationError('Both ports of a mapping must be on the same device.')
        if not 1 <= self.rear_position <= self.rear_port.positions:
            raise ValidationError(f'{self.rear_port.name} has {self.rear_port.positions} position(s).')
        if not 1 <= self.front_position <= self.front_port.positions:
            raise ValidationError(f'{self.front_port.name} has {self.front_port.positions} position(s).')


class Cable(BaseModel):
    """A physical cable. Endpoints are CableTermination rows (A and B ends)."""
    STATUS_CHOICES = [('connected', 'Installed'), ('planned', 'Planned'), ('decommissioning', 'To be removed')]
    LENGTH_UNITS = [('m', 'm'), ('cm', 'cm'), ('ft', 'ft'), ('in', 'in')]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='hardware_cables')
    label = models.CharField(max_length=60, blank=True, help_text='Cable ID printed on the cable')
    cable_type = models.CharField(max_length=10, choices=C.CABLE_TYPES, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='connected')
    color = models.CharField(max_length=7, blank=True, help_text='Hex colour, e.g. #1f77b4')
    color_name = models.CharField(max_length=30, blank=True)
    length = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    length_unit = models.CharField(max_length=2, choices=LENGTH_UNITS, blank=True)
    label_a = models.CharField(max_length=100, blank=True, help_text='Text printed on the A-end label')
    label_b = models.CharField(max_length=100, blank=True, help_text='Text printed on the B-end label')
    description = models.CharField(max_length=250, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    objects = OrganizationManager()

    class Meta:
        db_table = 'hw_cables'
        ordering = ['label', 'id']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'label'], condition=~Q(label=''),
                                    name='hw_cable_unique_label'),
        ]
        indexes = [models.Index(fields=['organization', 'label'])]

    def __str__(self):
        return self.label or f'Cable #{self.pk}'

    def ends(self):
        out = {'A': [], 'B': []}
        for t in self.terminations.all():
            out[t.end].append(t)
        return out


class CableTermination(models.Model):
    END_CHOICES = [('A', 'A'), ('B', 'B')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    cable = models.ForeignKey(Cable, on_delete=models.CASCADE, related_name='terminations')
    end = models.CharField(max_length=1, choices=END_CHOICES)
    # One cable per socket: the unique constraint is the occupancy rule.
    port = models.OneToOneField(DevicePort, on_delete=models.PROTECT, related_name='cable_termination')

    class Meta:
        db_table = 'hw_cable_terminations'
        indexes = [models.Index(fields=['cable', 'end'])]

    def clean(self):
        if self.port.organization_id != self.organization_id or self.cable.organization_id != self.organization_id:
            raise ValidationError('A cable cannot connect ports of different clients.')


class LabelTemplate(BaseModel):
    """Physical label stock + text layout. Global when organization is null."""
    KIND_CHOICES = [
        ('device', 'Device asset label'),
        ('rack', 'Rack identifier'),
        ('port', 'Port label'),
        ('patch_strip', 'Patch-panel strip'),
        ('wall_jack', 'Wall jack'),
        ('cable', 'Cable label (both ends)'),
    ]
    PAGE_CHOICES = [('letter', 'US Letter'), ('a4', 'A4'), ('label', 'One label per page (roll / label printer)')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='hardware_label_templates')
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=15, choices=KIND_CHOICES)
    width_mm = models.DecimalField(max_digits=6, decimal_places=2)
    height_mm = models.DecimalField(max_digits=6, decimal_places=2)
    margin_mm = models.DecimalField(max_digits=5, decimal_places=2, default=1.5, help_text='Inner margin on each label')
    font_size_pt = models.DecimalField(max_digits=4, decimal_places=1, default=8)
    include_qr = models.BooleanField(default=False)
    page_size = models.CharField(max_length=10, choices=PAGE_CHOICES, default='letter')
    columns = models.PositiveIntegerField(default=1)
    rows = models.PositiveIntegerField(default=1)
    page_margin_left_mm = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    page_margin_top_mm = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    gap_x_mm = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    gap_y_mm = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    offset_x_mm = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Printer calibration offset')
    offset_y_mm = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Printer calibration offset')
    strip_cells = models.PositiveIntegerField(default=0, help_text='Patch strip: ports per strip (0 = per label)')
    text_format = models.CharField(max_length=200, blank=True,
                                   help_text='Optional override, e.g. "{device} / {port}". See label help.')
    show_border = models.BooleanField(default=True, help_text='Print a thin cut guide around each label')

    class Meta:
        db_table = 'hw_label_templates'
        ordering = ['kind', 'name']

    def __str__(self):
        return self.name


class LabelPrintLog(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    template = models.ForeignKey(LabelTemplate, on_delete=models.SET_NULL, null=True, related_name='+')
    kind = models.CharField(max_length=15)
    label_count = models.PositiveIntegerField()
    items = models.JSONField(default=list, help_text='[{type, id}] of what was printed')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hw_label_print_log'
        ordering = ['-created_at']


class DiagramLayout(BaseModel):
    """Saved node positions for a generated diagram.

    Positions are keyed by stable node keys (``device:<public_id>``); a node
    that appears later gets an automatic position, a node that disappears is
    simply not drawn, and every position the user placed is kept.
    """
    KIND_CHOICES = [('connectivity', 'Physical connectivity'), ('vlan', 'VLAN view')]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='hardware_diagrams')
    kind = models.CharField(max_length=15, choices=KIND_CHOICES)
    scope = models.CharField(max_length=60, default='all', help_text='"all", "site:<id>" or "vlan:<id>"')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    positions = models.JSONField(default=dict)

    class Meta:
        db_table = 'hw_diagram_layouts'
        constraints = [
            models.UniqueConstraint(fields=['organization', 'kind', 'scope', 'user'], name='hw_diagram_unique'),
        ]


class HardwareChange(models.Model):
    """Change history for inventory records (who changed what, field by field)."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    device = models.ForeignKey(HardwareDevice, on_delete=models.SET_NULL, null=True, blank=True, related_name='changes')
    hardware_model = models.ForeignKey(HardwareModel, on_delete=models.SET_NULL, null=True, blank=True, related_name='changes')
    object_type = models.CharField(max_length=40)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=20)
    changes = models.JSONField(default=dict, blank=True, help_text='{field: [old, new]}')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'hw_changes'
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['organization', '-created_at']),
            models.Index(fields=['object_type', 'object_id']),
        ]
