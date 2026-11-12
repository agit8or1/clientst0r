"""
Service Vehicles Models - Fleet management system
"""
from django.db import models
from django.contrib.auth import get_user_model
from core.models import BaseModel
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal

User = get_user_model()


class ServiceVehicle(BaseModel):
    """
    Service vehicle for technician fleet.
    Tracks mileage, condition, insurance, GPS location.
    """
    VEHICLE_TYPES = [
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('truck', 'Truck'),
        ('van', 'Van'),
        ('cargo_van', 'Cargo Van'),
        ('pickup', 'Pickup Truck'),
        ('other', 'Other'),
    ]

    DIAGRAM_TYPES = [
        ('cargo_van', 'Cargo Van (Transit / Sprinter style)'),
        ('pickup_truck', 'Pickup Truck (F-150 / Ram style)'),
    ]

    CONDITION_CHOICES = [
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
        ('needs_repair', 'Needs Repair'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('maintenance', 'In Maintenance'),
        ('retired', 'Retired'),
    ]

    # Basic Information
    name = models.CharField(max_length=200, help_text="Vehicle nickname or identifier")
    vehicle_type = models.CharField(max_length=50, choices=VEHICLE_TYPES, default='van')
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.IntegerField(validators=[MinValueValidator(1900), MaxValueValidator(2100)])
    color = models.CharField(max_length=50, blank=True)

    # Identification
    vin = models.CharField(max_length=17, blank=True, verbose_name="VIN",
                          help_text="Vehicle Identification Number")
    license_plate = models.CharField(max_length=20)
    qr_code = models.CharField(
        max_length=200,
        blank=True,
        help_text="QR code for quick vehicle identification (auto-generated or manual entry)"
    )

    # Status & Condition
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='active')
    condition = models.CharField(max_length=50, choices=CONDITION_CHOICES, default='good')

    # Mileage Tracking
    current_mileage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Current odometer reading"
    )

    # Insurance
    insurance_provider = models.CharField(max_length=200, blank=True)
    insurance_policy_number = models.CharField(max_length=100, blank=True)
    insurance_expires_at = models.DateField(null=True, blank=True)
    insurance_premium = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monthly/annual premium amount"
    )

    # Registration
    registration_expires_at = models.DateField(null=True, blank=True)

    # GPS Location (6 decimal places = ~0.1m accuracy)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Current latitude"
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Current longitude"
    )
    last_location_update = models.DateTimeField(null=True, blank=True)

    # Purchase Information
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    # Current Assignment
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_vehicles',
        help_text="Currently assigned user/technician"
    )

    # Damage diagram style
    diagram_type = models.CharField(
        max_length=30,
        choices=DIAGRAM_TYPES,
        default='cargo_van',
        help_text="Vehicle silhouette used for damage diagrams"
    )

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'service_vehicles'
        ordering = ['name']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['license_plate']),
            models.Index(fields=['assigned_to']),
        ]

    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.license_plate})"

    @property
    def display_name(self):
        """Formatted display name"""
        return self.name or f"{self.year} {self.make} {self.model}"

    @property
    def is_insurance_expiring_soon(self):
        """Check if insurance expires within 30 days"""
        if not self.insurance_expires_at:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return self.insurance_expires_at <= timezone.localdate() + timedelta(days=30)

    @property
    def is_registration_expiring_soon(self):
        """Check if registration expires within 30 days"""
        if not self.registration_expires_at:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return self.registration_expires_at <= timezone.localdate() + timedelta(days=30)

    @property
    def has_location(self):
        """Check if GPS coordinates are set"""
        return self.latitude is not None and self.longitude is not None

    def update_location(self, latitude, longitude):
        """Update GPS location with timestamp"""
        from django.utils import timezone
        self.latitude = Decimal(str(latitude))
        self.longitude = Decimal(str(longitude))
        self.last_location_update = timezone.now()
        self.save(update_fields=['latitude', 'longitude', 'last_location_update'])

    def get_current_assignment(self):
        """Get active assignment record"""
        return self.assignments.filter(end_date__isnull=True).first()

    def get_recent_fuel_mpg(self, limit=5):
        """Calculate average MPG from recent fuel logs"""
        logs = self.fuel_logs.order_by('-date')[:limit]
        if not logs:
            return None
        mpg_values = [log.mpg for log in logs if log.mpg]
        if not mpg_values:
            return None
        return sum(mpg_values) / len(mpg_values)


class VehicleInventoryItem(BaseModel):
    """
    Inventory item stored in vehicle (cables, tools, supplies).
    Separate from Asset model - simple item tracking.
    """
    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='inventory_items'
    )

    # Item Details
    name = models.CharField(max_length=200, help_text="Item name (e.g., 'CAT6 Cable', 'RJ45 Connectors')")
    category = models.CharField(
        max_length=100,
        blank=True,
        help_text="Category (Cables, Tools, Hardware, Supplies, etc.)"
    )
    quantity = models.IntegerField(
        default=1,
        validators=[MinValueValidator(0)]
    )
    unit = models.CharField(
        max_length=50,
        blank=True,
        help_text="Unit of measurement (ea, ft, box, etc.)"
    )

    # Stock Management
    min_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Minimum quantity alert threshold"
    )
    reorder_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="How many to order when restocking"
    )

    # Value
    unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Cost per unit"
    )

    # Notes
    description = models.TextField(blank=True)
    location_in_vehicle = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where stored in vehicle (e.g., 'Toolbox', 'Rear compartment')"
    )

    # QR Code & Reordering
    qr_code = models.CharField(
        max_length=200,
        blank=True,
        help_text="QR code for quick scanning (auto-generated or manual entry)"
    )
    reorder_link = models.URLField(
        max_length=500,
        blank=True,
        help_text="Link to reorder (Amazon, eBay, supplier website, etc.)"
    )

    # Phase 4.3 — auto-replenish hints
    preferred_vendor = models.ForeignKey(
        'assets.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='preferred_vehicle_inventory_items',
        help_text='Vendor to suggest in auto-replenish.',
    )
    last_replenished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'vehicle_inventory_items'
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['vehicle', 'category']),
        ]

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.unit})"

    @property
    def is_low_stock(self):
        """Check if quantity is below minimum threshold"""
        return self.quantity <= self.min_quantity

    @property
    def needs_restock(self):
        """Check if item needs to be reordered"""
        return self.is_low_stock and self.reorder_quantity > 0

    @property
    def total_value(self):
        """Calculate total value of this item"""
        if self.unit_cost:
            return self.quantity * self.unit_cost
        return None

    def generate_qr_code(self):
        """Generate unique QR code for this inventory item"""
        if not self.qr_code:
            import uuid
            self.qr_code = f"VEH-INV-{uuid.uuid4().hex[:12].upper()}"
        return self.qr_code

    def get_qr_code_url(self):
        """Get URL to scan this item"""
        from django.urls import reverse
        if self.qr_code:
            return reverse('vehicles:inventory_scan', kwargs={'qr_code': self.qr_code})
        return None

    def get_qr_code_image_url(self):
        """Get URL for QR code image"""
        from django.urls import reverse
        if self.qr_code:
            return reverse('vehicles:inventory_qr_image', kwargs={'pk': self.pk})
        return None

    def save(self, *args, **kwargs):
        """Auto-generate QR code on save"""
        if not self.qr_code:
            self.generate_qr_code()
        super().save(*args, **kwargs)


class VehicleDamageReport(BaseModel):
    """
    Damage incident report with photos and repair tracking.
    Uses Attachment model for photos.
    """
    SEVERITY_CHOICES = [
        ('minor', 'Minor'),
        ('moderate', 'Moderate'),
        ('major', 'Major'),
        ('total_loss', 'Total Loss'),
    ]

    REPAIR_STATUS_CHOICES = [
        ('reported', 'Reported'),
        ('assessed', 'Assessed'),
        ('in_repair', 'In Repair'),
        ('completed', 'Completed'),
        ('deferred', 'Deferred'),
    ]

    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='damage_reports'
    )

    # Incident Details
    incident_date = models.DateField()
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='reported_damages')
    description = models.TextField(help_text="Describe the damage")

    # Severity & Status
    severity = models.CharField(max_length=50, choices=SEVERITY_CHOICES, default='minor')
    repair_status = models.CharField(max_length=50, choices=REPAIR_STATUS_CHOICES, default='reported')

    # Location
    damage_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Part of vehicle (e.g., 'Front bumper', 'Driver door')"
    )

    # Financial
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Insurance Claim
    insurance_claim_number = models.CharField(max_length=100, blank=True)
    insurance_payout = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Repair Details
    repair_date = models.DateField(null=True, blank=True)
    repair_shop = models.CharField(max_length=200, blank=True)
    repair_notes = models.TextField(blank=True)

    # Condition Change
    condition_before = models.CharField(max_length=50, blank=True)
    condition_after = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = 'vehicle_damage_reports'
        ordering = ['-incident_date']
        indexes = [
            models.Index(fields=['vehicle', 'repair_status']),
            models.Index(fields=['incident_date']),
        ]

    def __str__(self):
        return f"{self.vehicle.display_name} - {self.incident_date} ({self.severity})"

    @property
    def is_pending_repair(self):
        """Check if repair is pending"""
        return self.repair_status in ['reported', 'assessed', 'in_repair']

    def get_photos(self):
        """Get damage photos via Attachment model"""
        from files.models import Attachment
        return Attachment.objects.filter(
            entity_type='vehicle_damage',
            entity_id=self.id
        ).order_by('created_at')


class VehicleMaintenanceRecord(BaseModel):
    """
    Maintenance and service record with recurring schedule support.
    """
    MAINTENANCE_TYPES = [
        ('oil_change', 'Oil Change'),
        ('tire_rotation', 'Tire Rotation'),
        ('brake_service', 'Brake Service'),
        ('inspection', 'Inspection'),
        ('tune_up', 'Tune-up'),
        ('transmission', 'Transmission Service'),
        ('coolant', 'Coolant Service'),
        ('battery', 'Battery Replacement'),
        ('repair', 'Repair'),
        ('other', 'Other'),
    ]

    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='maintenance_records'
    )

    # Maintenance Details
    maintenance_type = models.CharField(max_length=50, choices=MAINTENANCE_TYPES)
    description = models.TextField()
    service_date = models.DateField()

    # Mileage at Service
    mileage_at_service = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Odometer reading at service"
    )

    # Service Provider
    performed_by = models.CharField(max_length=200, blank=True, help_text="Mechanic or service center")

    # Cost
    labor_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parts_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Recurring Schedule
    is_scheduled = models.BooleanField(default=False, help_text="Part of recurring maintenance schedule")
    next_due_mileage = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Next service due at this mileage"
    )
    next_due_date = models.DateField(null=True, blank=True, help_text="Next service due on this date")

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'vehicle_maintenance_records'
        ordering = ['-service_date']
        indexes = [
            models.Index(fields=['vehicle', 'maintenance_type']),
            models.Index(fields=['service_date']),
            models.Index(fields=['next_due_date']),
        ]

    def __str__(self):
        return f"{self.vehicle.display_name} - {self.get_maintenance_type_display()} ({self.service_date})"

    @property
    def is_overdue(self):
        """Check if next service is overdue"""
        from django.utils import timezone
        if self.next_due_date and self.next_due_date < timezone.localdate():
            return True
        if self.next_due_mileage and self.vehicle.current_mileage >= self.next_due_mileage:
            return True
        return False

    def save(self, *args, **kwargs):
        """Auto-calculate total cost"""
        if self.labor_cost and self.parts_cost:
            self.total_cost = self.labor_cost + self.parts_cost
        elif self.labor_cost:
            self.total_cost = self.labor_cost
        elif self.parts_cost:
            self.total_cost = self.parts_cost
        super().save(*args, **kwargs)


class VehicleFuelLog(BaseModel):
    """
    Fuel purchase tracking with automatic MPG calculation.
    """
    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='fuel_logs'
    )

    # Purchase Details
    date = models.DateField()
    mileage = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Odometer reading at fill-up"
    )

    # Fuel Details
    gallons = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    cost_per_gallon = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))]
    )
    total_cost = models.DecimalField(max_digits=10, decimal_places=2)

    # Location
    station = models.CharField(max_length=200, blank=True, help_text="Gas station name/location")

    # Calculated Fields (auto-populated)
    miles_driven = models.IntegerField(
        null=True,
        blank=True,
        help_text="Miles since last fill-up"
    )
    mpg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="MPG",
        help_text="Miles per gallon (auto-calculated)"
    )

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'vehicle_fuel_logs'
        ordering = ['-date', '-mileage']
        indexes = [
            models.Index(fields=['vehicle', 'date']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.vehicle.display_name} - {self.date} ({self.gallons} gal)"

    def save(self, *args, **kwargs):
        """Auto-calculate MPG based on previous fill-up"""
        # Calculate total cost if not set
        if not self.total_cost:
            self.total_cost = self.gallons * self.cost_per_gallon

        # Calculate MPG
        if not self.mpg or not self.miles_driven:
            previous_log = VehicleFuelLog.objects.filter(
                vehicle=self.vehicle,
                mileage__lt=self.mileage
            ).order_by('-mileage').first()

            if previous_log:
                self.miles_driven = self.mileage - previous_log.mileage
                if self.miles_driven > 0 and self.gallons > 0:
                    self.mpg = Decimal(str(self.miles_driven)) / self.gallons

        # Update vehicle current mileage if this is the most recent entry
        if self.vehicle.current_mileage < self.mileage:
            self.vehicle.current_mileage = self.mileage
            self.vehicle.save(update_fields=['current_mileage'])

        super().save(*args, **kwargs)


class VehicleAssignment(BaseModel):
    """
    Track user assignments to vehicles with mileage history.
    """
    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='assignments'
    )

    # Assignment
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vehicle_assignments')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    # Mileage Tracking
    starting_mileage = models.IntegerField(validators=[MinValueValidator(0)])
    ending_mileage = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'vehicle_assignments'
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['vehicle', 'user']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f"{self.vehicle.display_name} → {self.user.get_full_name()} ({self.start_date})"

    @property
    def is_active(self):
        """Check if assignment is currently active"""
        return self.end_date is None

    @property
    def miles_driven(self):
        """Calculate miles driven during assignment"""
        if self.ending_mileage:
            return self.ending_mileage - self.starting_mileage
        return None

    @property
    def duration_days(self):
        """Calculate assignment duration"""
        from django.utils import timezone
        end = self.end_date or timezone.localdate()
        return (end - self.start_date).days


class VehicleServiceProvider(BaseModel):
    """
    Shop or mechanic that services this vehicle, with contact info.
    """
    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='service_providers'
    )
    name = models.CharField(max_length=200, help_text="Shop or service center name")
    contact_name = models.CharField(max_length=200, blank=True, help_text="Primary contact person")
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)
    service_types = models.TextField(blank=True, help_text="Types of service this provider offers (e.g., Oil change, Tires, Brakes)")
    is_preferred = models.BooleanField(default=False, help_text="Mark as preferred/primary shop for this vehicle")
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'vehicle_service_providers'
        ordering = ['-is_preferred', 'name']

    def __str__(self):
        return f"{self.name} ({self.vehicle.display_name})"


class VehicleServiceSchedule(BaseModel):
    """
    Recurring maintenance schedule for a vehicle.
    Triggers service alerts based on mileage or time intervals.
    """
    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='service_schedules'
    )
    name = models.CharField(max_length=200, help_text="e.g., Oil Change, Tire Rotation")
    service_type = models.CharField(
        max_length=50,
        choices=VehicleMaintenanceRecord.MAINTENANCE_TYPES,
        default='other'
    )

    # Recurrence intervals (at least one required)
    interval_miles = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1)],
        help_text="Trigger alert every X miles (e.g., 5000 for oil change)"
    )
    interval_days = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1)],
        help_text="Trigger alert every X days (e.g., 90 for 3-month service)"
    )

    # Early warning thresholds
    warning_miles = models.IntegerField(
        default=500,
        validators=[MinValueValidator(0)],
        help_text="Alert this many miles before the service is due"
    )
    warning_days = models.IntegerField(
        default=7,
        validators=[MinValueValidator(0)],
        help_text="Alert this many days before the service is due"
    )

    # Last performed
    last_service_mileage = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Odometer reading at last service"
    )
    last_service_date = models.DateField(null=True, blank=True, help_text="Date of last service")

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'vehicle_service_schedules'
        ordering = ['name']

    def __str__(self):
        return f"{self.vehicle.display_name} — {self.name}"

    @property
    def next_due_mileage(self):
        if self.interval_miles and self.last_service_mileage is not None:
            return self.last_service_mileage + self.interval_miles
        return None

    @property
    def next_due_date(self):
        from datetime import timedelta
        if self.interval_days and self.last_service_date:
            return self.last_service_date + timedelta(days=self.interval_days)
        return None

    @property
    def miles_until_due(self):
        nd = self.next_due_mileage
        if nd is not None:
            return nd - self.vehicle.current_mileage
        return None

    @property
    def days_until_due(self):
        from django.utils import timezone
        nd = self.next_due_date
        if nd:
            return (nd - timezone.localdate()).days
        return None

    @property
    def is_due(self):
        """True if service should be alerted now (within warning threshold)."""
        from django.utils import timezone
        today = timezone.localdate()
        if self.miles_until_due is not None and self.miles_until_due <= self.warning_miles:
            return True
        if self.days_until_due is not None and self.days_until_due <= self.warning_days:
            return True
        return False

    @property
    def is_overdue(self):
        from django.utils import timezone
        today = timezone.localdate()
        if self.next_due_mileage is not None and self.vehicle.current_mileage >= self.next_due_mileage:
            return True
        if self.next_due_date and today > self.next_due_date:
            return True
        return False


class VehicleServiceAlert(BaseModel):
    """
    Alert generated when a service schedule is due or overdue.
    Can be acknowledged and linked to a maintenance record when service is done.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('acknowledged', 'Acknowledged'),
        ('completed', 'Completed — Service Done'),
    ]

    vehicle = models.ForeignKey(
        ServiceVehicle,
        on_delete=models.CASCADE,
        related_name='service_alerts'
    )
    schedule = models.ForeignKey(
        VehicleServiceSchedule,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='alerts'
    )
    title = models.CharField(max_length=300)
    due_date = models.DateField(null=True, blank=True)
    due_mileage = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Acknowledgement
    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='acknowledged_service_alerts'
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledgement_notes = models.TextField(blank=True)

    # Optional link to the service record when completed
    service_record = models.OneToOneField(
        VehicleMaintenanceRecord,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='service_alert'
    )

    class Meta:
        db_table = 'vehicle_service_alerts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vehicle', 'status']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.vehicle.display_name} — {self.title} ({self.status})"

    @property
    def is_overdue(self):
        from django.utils import timezone
        today = timezone.localdate()
        if self.due_date and today > self.due_date:
            return True
        if self.due_mileage and self.vehicle.current_mileage >= self.due_mileage:
            return True
        return False


class ShopInventoryItem(BaseModel):
    """
    Inventory item stored in the shop/warehouse (not vehicle-specific).
    Tracks tools, parts, and supplies held at the base location.
    """
    # Item Details
    name = models.CharField(max_length=200, help_text="Item name (e.g., 'CAT6 Cable', 'RJ45 Connectors')")
    category = models.CharField(
        max_length=100,
        blank=True,
        help_text="Category (Cables, Tools, Hardware, Supplies, etc.)"
    )
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    unit = models.CharField(max_length=50, blank=True, help_text="Unit of measurement (ea, ft, box, etc.)")

    # Stock Management
    min_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Minimum quantity alert threshold"
    )
    reorder_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="How many to order when restocking"
    )

    # Value
    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Cost per unit"
    )

    # Location & notes
    description = models.TextField(blank=True)
    location_in_shop = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where stored in shop (e.g., 'Shelf A-3', 'Cabinet 2')"
    )

    # Reordering
    qr_code = models.CharField(max_length=200, blank=True)
    reorder_link = models.URLField(max_length=500, blank=True)

    # Phase 4.3 — auto-replenish hints
    preferred_vendor = models.ForeignKey(
        'assets.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='preferred_shop_inventory_items',
        help_text='Vendor to suggest in auto-replenish.',
    )
    last_replenished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'vehicle_shop_inventory'
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.unit or 'ea'})"

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_quantity

    @property
    def needs_restock(self):
        return self.is_low_stock and self.reorder_quantity > 0

    @property
    def total_value(self):
        if self.unit_cost is not None:
            return self.quantity * self.unit_cost
        return None

    def generate_qr_code(self):
        if not self.qr_code:
            import uuid
            self.qr_code = f"SHOP-INV-{uuid.uuid4().hex[:12].upper()}"
        return self.qr_code

    def get_qr_code_url(self):
        from django.urls import reverse
        if self.qr_code:
            return reverse('vehicles:shop_item_scan', kwargs={'qr_code': self.qr_code})
        return None

    def get_qr_code_image_url(self):
        from django.urls import reverse
        if self.pk:
            return reverse('vehicles:shop_inventory_qr_image', kwargs={'pk': self.pk})
        return None

    def save(self, *args, **kwargs):
        if not self.qr_code:
            self.generate_qr_code()
        super().save(*args, **kwargs)


class VehicleReceipt(BaseModel):
    """Scanned receipt for vehicle expenses — fuel, repairs, maintenance, etc."""

    CATEGORY_CHOICES = [
        ('fuel', 'Fuel'),
        ('maintenance', 'Maintenance'),
        ('repair', 'Repair / Parts'),
        ('insurance', 'Insurance'),
        ('registration', 'Registration / Licensing'),
        ('toll', 'Tolls / Parking'),
        ('cleaning', 'Cleaning / Detailing'),
        ('inspection', 'Inspection'),
        ('other', 'Other'),
    ]

    vehicle = models.ForeignKey(
        ServiceVehicle, on_delete=models.CASCADE, related_name='receipts'
    )
    receipt_date = models.DateField()
    vendor = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='other')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    odometer = models.IntegerField(
        null=True, blank=True,
        help_text='Odometer / mileage reading shown on receipt (optional)'
    )
    description = models.TextField(blank=True, help_text='Line items or description from receipt')
    notes = models.TextField(blank=True)

    # AI extraction metadata
    ai_processed = models.BooleanField(default=False)
    ai_confidence = models.CharField(
        max_length=10, blank=True,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]
    )

    # SHA-256 hash of the receipt image — used to prevent duplicate OCR imports
    image_hash = models.CharField(max_length=64, blank=True, db_index=True)

    # Receipt image stored via Attachment (entity_type='vehicle_receipt')
    # Attachment.entity_id = self.pk after save

    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vehicle_receipts_created'
    )

    class Meta:
        db_table = 'vehicle_receipts'
        ordering = ['-receipt_date']

    def __str__(self):
        return f"{self.vehicle} — {self.get_category_display()} ${self.amount} ({self.receipt_date})"

    def get_receipt_image(self):
        """Return the Attachment for this receipt image, if any."""
        from files.models import Attachment
        return Attachment.objects.filter(
            entity_type='vehicle_receipt',
            entity_id=self.pk
        ).order_by('-created_at').first()
