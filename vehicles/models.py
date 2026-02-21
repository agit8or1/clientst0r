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
        return self.insurance_expires_at <= timezone.now().date() + timedelta(days=30)

    @property
    def is_registration_expiring_soon(self):
        """Check if registration expires within 30 days"""
        if not self.registration_expires_at:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return self.registration_expires_at <= timezone.now().date() + timedelta(days=30)

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
        if self.next_due_date and self.next_due_date < timezone.now().date():
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
        end = self.end_date or timezone.now().date()
        return (end - self.start_date).days
