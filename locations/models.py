"""
Location models - Multi-location support with AI floor plan generation
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, BaseModel
from core.utils import OrganizationManager


class Location(BaseModel):
    """
    Physical location for an organization.
    Supports multiple locations per organization with AI-powered floor plan generation.
    """
    LOCATION_TYPES = [
        ('office', 'Office'),
        ('warehouse', 'Warehouse'),
        ('datacenter', 'Data Center'),
        ('retail', 'Retail Store'),
        ('branch', 'Branch Office'),
        ('manufacturing', 'Manufacturing'),
        ('coworking', 'Co-working Space'),
        ('remote', 'Remote Site'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('planned', 'Planned'),
        ('closed', 'Closed'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='locations',
        null=True,
        blank=True,
        help_text="Owner organization (leave blank for shared/global locations)"
    )

    # Shared location support
    is_shared = models.BooleanField(
        default=False,
        help_text="Shared location (e.g., data center, co-location facility) that multiple organizations can use"
    )
    associated_organizations = models.ManyToManyField(
        Organization,
        related_name='associated_locations',
        blank=True,
        help_text="Organizations that have access to this shared location"
    )

    name = models.CharField(
        max_length=255,
        help_text="Location name (e.g., 'Main Office', 'Warehouse #2')"
    )
    location_type = models.CharField(
        max_length=20,
        choices=LOCATION_TYPES,
        default='office'
    )

    # Address fields
    street_address = models.CharField(max_length=255)
    street_address_2 = models.CharField(max_length=255, blank=True, null=True, default='')
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='United States')

    # Geocoding
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="GPS latitude coordinate"
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="GPS longitude coordinate"
    )

    # Building information
    building_sqft = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total building square footage"
    )
    floors_count = models.IntegerField(
        null=True,
        blank=True,
        help_text="Number of floors in building"
    )
    year_built = models.IntegerField(
        null=True,
        blank=True,
        help_text="Year building was constructed"
    )
    property_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default='',
        help_text="Property classification (e.g., 'Commercial Office')"
    )

    # External data sources
    property_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default='',
        help_text="Tax assessor parcel ID"
    )
    google_place_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default='',
        help_text="Google Places API identifier"
    )
    external_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw data from external APIs (property records, etc.)"
    )

    # Metadata
    is_primary = models.BooleanField(
        default=False,
        help_text="Primary/headquarters location for organization"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    notes = models.TextField(blank=True)

    # Contact information
    phone = models.CharField(max_length=50, blank=True, null=True, default='')
    email = models.EmailField(blank=True, null=True, default='')
    website = models.URLField(blank=True, null=True, default='')

    # Generated assets
    satellite_image = models.ImageField(
        upload_to='locations/satellite/%Y/%m/',
        blank=True,
        help_text="Satellite imagery of building"
    )
    street_view_image = models.ImageField(
        upload_to='locations/street/%Y/%m/',
        blank=True,
        help_text="Street view photo of building"
    )
    area_map_image = models.ImageField(
        upload_to='locations/maps/%Y/%m/',
        blank=True,
        help_text="Area map showing surrounding context"
    )
    property_diagram = models.ImageField(
        upload_to='locations/diagrams/%Y/%m/',
        blank=True,
        help_text="Property diagram/floor plan from tax collector or property appraiser records"
    )

    # Floor plan generation tracking
    floorplan_generated = models.BooleanField(
        default=False,
        help_text="Has floor plan been auto-generated?"
    )
    floorplan_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When floor plan was last generated"
    )
    floorplan_generation_status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        default='',
        help_text="Status of floor plan generation (pending, processing, completed, failed)"
    )
    floorplan_error = models.TextField(
        blank=True,
        null=True,
        default='',
        help_text="Error message if floor plan generation failed"
    )

    # Organization-scoped manager
    objects = OrganizationManager()

    class Meta:
        db_table = 'locations'
        ordering = ['-is_primary', 'name']
        indexes = [
            models.Index(fields=['organization', 'is_primary']),
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['is_shared']),
            models.Index(fields=['latitude', 'longitude']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'name'],
                condition=models.Q(organization__isnull=False),
                name='unique_org_location_name'
            )
        ]

    def __str__(self):
        if self.is_shared:
            return f"{self.name} (Shared)"
        if self.is_primary and self.organization:
            return f"{self.name} (HQ) - {self.organization.name}"
        if self.organization:
            return f"{self.name} - {self.organization.name}"
        return self.name

    def get_all_organizations(self):
        """Get all organizations with access to this location."""
        if self.is_shared:
            return self.associated_organizations.all()
        elif self.organization:
            return [self.organization]
        return []

    def can_organization_access(self, organization):
        """Check if an organization has access to this location."""
        if self.is_shared:
            return self.associated_organizations.filter(id=organization.id).exists()
        return self.organization == organization

    @property
    def full_address(self):
        """Get full formatted address."""
        parts = [self.street_address]
        if self.street_address_2:
            parts.append(self.street_address_2)
        parts.append(f"{self.city}, {self.state} {self.postal_code}")
        if self.country and self.country != 'United States':
            parts.append(self.country)
        return ', '.join(parts)

    @property
    def has_coordinates(self):
        """Check if location has geocoded coordinates."""
        return self.latitude is not None and self.longitude is not None

    @property
    def google_maps_url(self):
        """Get Google Maps URL for this location."""
        if self.has_coordinates:
            return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
        return f"https://www.google.com/maps/search/?api=1&query={self.full_address.replace(' ', '+')}"

    @property
    def apple_maps_url(self):
        """Get Apple Maps URL for this location."""
        if self.has_coordinates:
            return f"https://maps.apple.com/?q={self.name}&ll={self.latitude},{self.longitude}"
        # Apple Maps can also use address
        import urllib.parse
        address = urllib.parse.quote(self.full_address)
        return f"https://maps.apple.com/?address={address}"

    @property
    def waze_url(self):
        """Get Waze URL for this location."""
        if self.has_coordinates:
            return f"https://waze.com/ul?ll={self.latitude},{self.longitude}&navigate=yes"
        return None  # Waze requires coordinates

    @property
    def google_maps_navigate_url(self):
        """Get Google Maps navigation URL (opens directly to navigation mode)."""
        if self.has_coordinates:
            return f"https://www.google.com/maps/dir/?api=1&destination={self.latitude},{self.longitude}&travelmode=driving"
        import urllib.parse
        destination = urllib.parse.quote(self.full_address)
        return f"https://www.google.com/maps/dir/?api=1&destination={destination}&travelmode=driving"

    def get_all_navigation_urls(self):
        """Get all available navigation URLs for this location."""
        urls = {
            'google_maps': self.google_maps_url,
            'google_maps_navigate': self.google_maps_navigate_url,
            'apple_maps': self.apple_maps_url,
        }
        if self.waze_url:
            urls['waze'] = self.waze_url
        return urls

    def get_property_appraiser_info(self):
        """Get property appraiser information based on location's county/state."""
        state = self.state.upper() if self.state else ''
        city = self.city.lower() if self.city else ''

        # Florida counties
        if state in ['FL', 'FLORIDA']:
            florida_counties = {
                'jacksonville': {
                    'county': 'Duval',
                    'name': 'Duval County Property Appraiser',
                    'url': 'https://paopropertysearch.coj.net/',
                    'search_url': 'https://paopropertysearch.coj.net/Basic/Search.aspx'
                },
                'miami': {
                    'county': 'Miami-Dade',
                    'name': 'Miami-Dade County Property Appraiser',
                    'url': 'https://www.miamidade.gov/pa/',
                    'search_url': 'https://www.miamidade.gov/Apps/PA/propertysearch/'
                },
                'fort lauderdale': {
                    'county': 'Broward',
                    'name': 'Broward County Property Appraiser',
                    'url': 'https://bcpa.net/',
                    'search_url': 'https://web.bcpa.net/bcpaclient/PropertySearch.aspx'
                },
                'orlando': {
                    'county': 'Orange',
                    'name': 'Orange County Property Appraiser',
                    'url': 'https://www.ocpafl.org/',
                    'search_url': 'https://www.ocpafl.org/searches/ParcelSearch.aspx'
                },
                'tampa': {
                    'county': 'Hillsborough',
                    'name': 'Hillsborough County Property Appraiser',
                    'url': 'https://www.hcpafl.org/',
                    'search_url': 'https://www.hcpafl.org/Property-Search'
                },
                'st petersburg': {
                    'county': 'Pinellas',
                    'name': 'Pinellas County Property Appraiser',
                    'url': 'https://www.pcpao.gov/',
                    'search_url': 'https://www.pcpao.gov/propertysearch'
                },
                'clearwater': {
                    'county': 'Pinellas',
                    'name': 'Pinellas County Property Appraiser',
                    'url': 'https://www.pcpao.gov/',
                    'search_url': 'https://www.pcpao.gov/propertysearch'
                },
                'tallahassee': {
                    'county': 'Leon',
                    'name': 'Leon County Property Appraiser',
                    'url': 'https://www.leonpa.org/',
                    'search_url': 'https://www.leonpa.org/PropertySearch'
                },
            }

            if city in florida_counties:
                return florida_counties[city]

            # Default Florida message
            return {
                'county': 'Your County',
                'name': 'Florida Property Appraiser',
                'url': f'https://www.google.com/search?q={self.city}+county+property+appraiser+florida',
                'search_url': f'https://www.google.com/search?q={self.city}+county+property+appraiser+florida',
                'is_generic': True
            }

        # California counties
        elif state in ['CA', 'CALIFORNIA']:
            return {
                'county': 'County',
                'name': 'County Assessor',
                'url': f'https://www.google.com/search?q={self.city}+county+assessor+california',
                'search_url': f'https://www.google.com/search?q={self.city}+county+assessor+california',
                'is_generic': True
            }

        # Texas counties
        elif state in ['TX', 'TEXAS']:
            return {
                'county': 'County',
                'name': 'County Appraisal District',
                'url': f'https://www.google.com/search?q={self.city}+county+appraisal+district+texas',
                'search_url': f'https://www.google.com/search?q={self.city}+county+appraisal+district+texas',
                'is_generic': True
            }

        # Default for other states
        return {
            'county': 'Your County',
            'name': 'Property Records',
            'url': f'https://www.google.com/search?q={self.city}+property+records+{state}',
            'search_url': f'https://www.google.com/search?q={self.city}+property+records+{state}',
            'is_generic': True
        }

    def save(self, *args, **kwargs):
        # Shared locations cannot be primary
        if self.is_shared:
            self.is_primary = False

        # Ensure only one primary location per organization
        if self.is_primary and self.organization:
            Location.objects.filter(
                organization=self.organization,
                is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)


class LocationFloorPlan(BaseModel):
    """
    Generated floor plan for a specific floor in a location.
    Created by AI analysis of property records, satellite imagery, and building data.
    """
    SOURCE_CHOICES = [
        ('tax_record', 'Tax/Property Record'),
        ('satellite', 'Satellite Imagery Analysis'),
        ('building_footprint', 'Building Footprint Data'),
        ('user_input', 'User Provided'),
        ('ai_estimate', 'AI Estimation'),
        ('magicplan', 'MagicPlan Import'),
        ('hybrid', 'Multiple Sources'),
    ]

    location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='floor_plans'
    )
    floor_number = models.IntegerField(
        default=1,
        help_text="Floor level (1 = ground floor, 0 = basement, 2 = second floor)"
    )
    floor_name = models.CharField(
        max_length=100,
        help_text="Descriptive name (e.g., 'Ground Floor', '2nd Floor', 'Basement')"
    )

    # Dimensions
    width_feet = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Floor width in feet"
    )
    length_feet = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Floor length in feet"
    )
    ceiling_height_feet = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ceiling height in feet"
    )
    total_sqft = models.IntegerField(
        help_text="Total floor area in square feet"
    )

    # Data sources
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default='ai_estimate',
        help_text="Primary data source for dimensions"
    )
    confidence_score = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="AI confidence score (0.00 to 1.00)"
    )

    # AI analysis metadata
    ai_analysis = models.JSONField(
        default=dict,
        blank=True,
        help_text="Detailed AI analysis results and source data"
    )

    # Generated diagram
    diagram_xml = models.TextField(
        blank=True,
        null=True,
        default='',
        help_text="Draw.io XML for floor plan"
    )
    diagram = models.ForeignKey(
        'docs.Diagram',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='floor_plan_locations',
        help_text="Link to generated diagram in docs module"
    )

    # Generation metadata
    template_used = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default='',
        help_text="Template used for generation (office, warehouse, etc.)"
    )
    include_network = models.BooleanField(
        default=True,
        help_text="Include network equipment (APs, switches, cameras)"
    )
    include_furniture = models.BooleanField(
        default=True,
        help_text="Include furniture and equipment"
    )

    class Meta:
        db_table = 'location_floor_plans'
        ordering = ['location', 'floor_number']
        unique_together = [['location', 'floor_number']]
        indexes = [
            models.Index(fields=['location', 'floor_number']),
        ]

    def __str__(self):
        return f"{self.location.name} - {self.floor_name}"

    @property
    def area_sqft(self):
        """Calculate area from dimensions."""
        if self.width_feet and self.length_feet:
            return float(self.width_feet) * float(self.length_feet)
        return self.total_sqft

    @property
    def dimensions_str(self):
        """Get formatted dimensions string."""
        return f"{self.width_feet}' × {self.length_feet}' ({self.total_sqft:,} sq ft)"

    @property
    def has_diagram(self):
        """Check if diagram has been generated."""
        return bool(self.diagram_xml) or self.diagram is not None
