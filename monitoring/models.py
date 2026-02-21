"""
Monitoring Models - Website/SSL monitoring, Expiration tracking, Rack Management, IPAM
"""
from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from core.models import Organization, BaseModel
from core.utils import OrganizationManager
from assets.models import Asset


class WebsiteMonitor(BaseModel):
    """
    Website and SSL certificate monitoring.
    Tracks domain expiration, SSL expiration, and website status.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('warning', 'Warning'),
        ('down', 'Down'),
        ('unknown', 'Unknown'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='website_monitors')
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=500)

    # Monitoring configuration
    check_interval_minutes = models.PositiveIntegerField(default=60, help_text="How often to check")
    is_enabled = models.BooleanField(default=True)

    # Current status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unknown')
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_status_code = models.PositiveIntegerField(null=True, blank=True)
    last_response_time_ms = models.PositiveIntegerField(null=True, blank=True, help_text="Response time in milliseconds")

    # SSL Certificate info
    ssl_enabled = models.BooleanField(default=False)
    ssl_expires_at = models.DateTimeField(null=True, blank=True)
    ssl_issued_at = models.DateTimeField(null=True, blank=True)
    ssl_issuer = models.CharField(max_length=255, blank=True)
    ssl_subject = models.CharField(max_length=255, blank=True)
    ssl_serial_number = models.CharField(max_length=100, blank=True)
    ssl_version = models.CharField(max_length=20, blank=True)
    ssl_warning_days = models.PositiveIntegerField(default=30, help_text="Warn X days before expiration")

    # Domain WHOIS info
    domain_expires_at = models.DateTimeField(null=True, blank=True)
    domain_registrar = models.CharField(max_length=255, blank=True)
    domain_warning_days = models.PositiveIntegerField(default=60, help_text="Warn X days before expiration")

    # Notifications
    notify_on_down = models.BooleanField(default=True)
    notify_on_ssl_expiry = models.BooleanField(default=True)
    notify_on_domain_expiry = models.BooleanField(default=True)

    # Last error
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'website_monitors'
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization', 'is_enabled']),
            models.Index(fields=['ssl_expires_at']),
            models.Index(fields=['domain_expires_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.url})"

    @property
    def is_ssl_expiring_soon(self):
        """Check if SSL cert expires within warning period."""
        if not self.ssl_expires_at:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return self.ssl_expires_at <= timezone.now() + timedelta(days=self.ssl_warning_days)

    @property
    def is_domain_expiring_soon(self):
        """Check if domain expires within warning period."""
        if not self.domain_expires_at:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return self.domain_expires_at <= timezone.now() + timedelta(days=self.domain_warning_days)

    def check_status(self):
        """
        Perform website health check and SSL certificate check.
        Updates status, response time, and SSL information.
        """
        import requests
        import ssl
        import socket
        from datetime import datetime, timezone as dt_timezone
        from django.utils import timezone
        from urllib.parse import urlparse
        import ipaddress

        # Validate URL to prevent SSRF attacks
        def is_safe_url(url):
            """Validate URL to prevent SSRF attacks."""
            try:
                parsed = urlparse(url)

                # Only allow http/https schemes
                if parsed.scheme not in ['http', 'https']:
                    return False, f"Invalid URL scheme: {parsed.scheme}"

                # Get hostname
                hostname = parsed.hostname
                if not hostname:
                    return False, "Invalid URL: no hostname"

                # Try to resolve hostname to IP
                try:
                    ip_str = socket.gethostbyname(hostname)
                    ip = ipaddress.ip_address(ip_str)

                    # Check if private IP monitoring is allowed via configuration
                    allow_private_ips = getattr(settings, 'ALLOW_PRIVATE_IP_INTEGRATIONS', False)

                    # Block private IP ranges unless explicitly allowed
                    if ip.is_private and not allow_private_ips:
                        return False, f"Cannot monitor private IP addresses: {ip_str}. Set ALLOW_PRIVATE_IP_INTEGRATIONS=True in .env to allow."

                    # Block loopback addresses unless explicitly allowed
                    if ip.is_loopback and not allow_private_ips:
                        return False, f"Cannot monitor loopback addresses: {ip_str}. Set ALLOW_PRIVATE_IP_INTEGRATIONS=True to allow localhost monitoring."

                    # Block link-local addresses unless explicitly allowed
                    if ip.is_link_local and not allow_private_ips:
                        return False, f"Cannot monitor link-local addresses: {ip_str}. Set ALLOW_PRIVATE_IP_INTEGRATIONS=True to allow."

                except socket.gaierror:
                    # Hostname doesn't resolve - allow it (will fail naturally)
                    pass

                return True, None

            except Exception as e:
                return False, f"URL validation error: {str(e)}"

        try:
            # Validate URL before making request
            is_safe, error_msg = is_safe_url(self.url)
            if not is_safe:
                self.last_checked_at = timezone.now()
                self.status = 'error'
                self.last_error = f'Security: {error_msg}'
                self.save()
                return

            # Make HTTP request
            start_time = datetime.now()
            response = requests.get(self.url, timeout=10, verify=True, allow_redirects=False)
            end_time = datetime.now()

            # Calculate response time
            response_time_ms = int((end_time - start_time).total_seconds() * 1000)

            # Update basic status
            self.last_checked_at = timezone.now()
            self.last_status_code = response.status_code
            self.last_response_time_ms = response_time_ms

            # Determine status based on response code
            if 200 <= response.status_code < 300:
                self.status = 'active'
                self.last_error = ''
            elif 300 <= response.status_code < 400:
                self.status = 'warning'
                self.last_error = f'Redirect: {response.status_code}'
            else:
                self.status = 'down'
                self.last_error = f'HTTP {response.status_code}'

            # Check SSL certificate if HTTPS
            parsed_url = urlparse(self.url)
            if parsed_url.scheme == 'https':
                try:
                    hostname = parsed_url.hostname
                    port = parsed_url.port or 443

                    # Create SSL context
                    context = ssl.create_default_context()

                    # Get certificate
                    with socket.create_connection((hostname, port), timeout=5) as sock:
                        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                            cert = ssock.getpeercert()

                            # Parse expiry date
                            expiry_str = cert['notAfter']
                            # Format: 'Jan 15 12:00:00 2026 GMT'
                            expiry_date = datetime.strptime(expiry_str, '%b %d %H:%M:%S %Y %Z')
                            expiry_date = expiry_date.replace(tzinfo=dt_timezone.utc)

                            # Parse issued date
                            issued_str = cert['notBefore']
                            issued_date = datetime.strptime(issued_str, '%b %d %H:%M:%S %Y %Z')
                            issued_date = issued_date.replace(tzinfo=dt_timezone.utc)

                            # Update SSL info
                            self.ssl_enabled = True
                            self.ssl_expires_at = expiry_date
                            self.ssl_issued_at = issued_date

                            # Get issuer
                            issuer = dict(x[0] for x in cert['issuer'])
                            self.ssl_issuer = issuer.get('organizationName', issuer.get('commonName', 'Unknown'))

                            # Get subject
                            subject = dict(x[0] for x in cert['subject'])
                            self.ssl_subject = subject.get('commonName', hostname)

                            # Get serial number
                            self.ssl_serial_number = cert.get('serialNumber', '')

                            # Get SSL version
                            self.ssl_version = ssock.version() or 'Unknown'

                except Exception as ssl_error:
                    self.last_error += f' SSL error: {str(ssl_error)}'

        except requests.exceptions.Timeout:
            self.status = 'down'
            self.last_error = 'Connection timeout'
            self.last_checked_at = timezone.now()

        except requests.exceptions.ConnectionError as e:
            self.status = 'down'
            self.last_error = f'Connection error: {str(e)}'
            self.last_checked_at = timezone.now()

        except Exception as e:
            self.status = 'down'
            self.last_error = f'Error: {str(e)}'
            self.last_checked_at = timezone.now()

        # Save the updated monitor
        self.save()


class Expiration(BaseModel):
    """
    Generic expiration tracking for any item.
    Auto-populated from website monitors and can be manually added.
    """
    EXPIRATION_TYPES = [
        ('ssl_cert', 'SSL Certificate'),
        ('domain', 'Domain Registration'),
        ('license', 'Software License'),
        ('contract', 'Contract/Agreement'),
        ('warranty', 'Warranty'),
        ('insurance', 'Insurance'),
        ('certification', 'Certification'),
        ('other', 'Other'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='expirations')
    name = models.CharField(max_length=255)
    expiration_type = models.CharField(max_length=50, choices=EXPIRATION_TYPES)
    expires_at = models.DateTimeField()
    warning_days = models.PositiveIntegerField(default=30)

    # Optional link to related object
    related_url = models.URLField(max_length=500, blank=True)
    notes = models.TextField(blank=True)

    # Auto-renewal info
    auto_renew = models.BooleanField(default=False)
    renewal_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Notification status
    notification_sent = models.BooleanField(default=False)

    objects = OrganizationManager()

    class Meta:
        db_table = 'expirations'
        ordering = ['expires_at']
        indexes = [
            models.Index(fields=['organization', 'expires_at']),
            models.Index(fields=['expiration_type']),
        ]

    def __str__(self):
        return f"{self.name} (expires {self.expires_at.date()})"

    @property
    def is_expired(self):
        """Check if already expired."""
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def days_until_expiration(self):
        """Days until expiration (negative if expired)."""
        from django.utils import timezone
        delta = self.expires_at - timezone.now()
        return delta.days

    @property
    def is_expiring_soon(self):
        """Check if expiring within warning period."""
        return 0 <= self.days_until_expiration <= self.warning_days


class Rack(BaseModel):
    """
    Physical rack or network closet for equipment.
    Supports full racks, data closets, network closets, and wall-mount configurations.
    """
    WIDTH_CHOICES = [
        (19, '19"'),
        (23, '23"'),
    ]

    RACK_TYPE_CHOICES = [
        ('full_rack', 'Full Rack (42U+)'),
        ('half_rack', 'Half Rack (20U-25U)'),
        ('data_closet', 'Data Closet'),
        ('network_closet', 'Network Closet'),
        ('wall_mount', 'Wall Mount Rack'),
        ('open_frame', 'Open Frame Rack'),
        ('cabinet', 'Server Cabinet'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='racks')
    name = models.CharField(max_length=100)

    # Rack type
    rack_type = models.CharField(max_length=50, choices=RACK_TYPE_CHOICES, default='full_rack', help_text="Type of rack or closet")

    # Location hierarchy
    datacenter = models.CharField(max_length=100, blank=True, help_text="Datacenter/facility name")
    building = models.CharField(max_length=100, blank=True, help_text="Building name/number")
    floor = models.CharField(max_length=50, blank=True, help_text="Floor level")
    room = models.CharField(max_length=50, blank=True, help_text="Room number/name")
    aisle = models.CharField(max_length=50, blank=True, help_text="Aisle/row identifier")
    location = models.CharField(max_length=255, blank=True, help_text="Additional location details")

    # Physical specs
    units = models.PositiveIntegerField(default=42, help_text="Rack units (U)")
    width_inches = models.PositiveIntegerField(choices=WIDTH_CHOICES, default=19)
    depth_inches = models.PositiveIntegerField(null=True, blank=True)

    # Power
    power_capacity_watts = models.PositiveIntegerField(null=True, blank=True)
    power_allocated_watts = models.PositiveIntegerField(default=0)
    pdu_count = models.PositiveIntegerField(default=0, help_text="Number of Power Distribution Units")

    # Cooling
    cooling_capacity_btu = models.PositiveIntegerField(null=True, blank=True)
    ambient_temp_f = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Ambient temperature (°F)")

    # Network closet specific
    patch_panel_count = models.PositiveIntegerField(default=0, help_text="Number of patch panels")
    total_port_count = models.PositiveIntegerField(default=0, help_text="Total network ports")

    # Visual/Layout
    closet_diagram = models.ImageField(upload_to='rack_diagrams/', null=True, blank=True, help_text="Network closet layout diagram or photo")

    # Metadata
    notes = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'racks'
        ordering = ['location', 'name']
        indexes = [
            models.Index(fields=['organization', 'location']),
        ]

    def __str__(self):
        return f"{self.location}: {self.name}"

    @property
    def power_utilization_percent(self):
        """Calculate power utilization percentage."""
        if not self.power_capacity_watts or self.power_capacity_watts == 0:
            return 0
        return round((self.power_allocated_watts / self.power_capacity_watts) * 100, 1)

    @property
    def available_units(self):
        """Calculate available rack units."""
        used = self.rack_devices.aggregate(total=models.Sum('units'))['total'] or 0
        return self.units - used


class RackDevice(BaseModel):
    """
    Device mounted in a rack.
    Tracks position, size, power draw, and links to assets.
    Supports both vertical rack mounting (U positions) and horizontal board mounting (X/Y positions).
    """
    rack = models.ForeignKey(Rack, on_delete=models.CASCADE, related_name='rack_devices')
    name = models.CharField(max_length=255)

    # Position in rack (1U = bottom) - for vertical racks
    start_unit = models.PositiveIntegerField(help_text="Starting U position (1 = bottom)")
    units = models.PositiveIntegerField(default=1, help_text="Height in U")

    # Position on board (X/Y coordinates) - for wall-mounted/board layouts
    board_position_x = models.PositiveIntegerField(null=True, blank=True, help_text="X position on board (pixels)")
    board_position_y = models.PositiveIntegerField(null=True, blank=True, help_text="Y position on board (pixels)")
    board_width = models.PositiveIntegerField(null=True, blank=True, help_text="Width on board (pixels)")
    board_height = models.PositiveIntegerField(null=True, blank=True, help_text="Height on board (pixels)")

    # Power draw
    power_draw_watts = models.PositiveIntegerField(null=True, blank=True)

    # Optional link to asset
    asset = models.ForeignKey(Asset, on_delete=models.SET_NULL, null=True, blank=True, help_text="Link to Asset", related_name='rack_devices')

    # Equipment model from vendor database (alternative to asset link)
    equipment_model = models.ForeignKey(
        'assets.EquipmentModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rack_devices',
        help_text="Equipment model from vendor database"
    )

    # Visual
    color = models.CharField(max_length=7, default='#0d6efd', help_text="Hex color for visualization")
    photo = models.ImageField(upload_to='rack_devices/', null=True, blank=True, help_text="Device photo")

    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'rack_devices'
        ordering = ['rack', 'start_unit']
        unique_together = [['rack', 'start_unit']]

    def __str__(self):
        return f"{self.name} (U{self.start_unit}-U{self.start_unit + self.units - 1})"

    @property
    def end_unit(self):
        """Calculate ending U position."""
        return self.start_unit + self.units - 1

    def save(self, *args, **kwargs):
        """Override save to auto-resize uploaded photos."""
        if self.photo:
            from PIL import Image
            from io import BytesIO
            from django.core.files.uploadedfile import InMemoryUploadedFile
            import sys

            # Open the image
            img = Image.open(self.photo)

            # Convert to RGB if necessary (handles RGBA, P, etc.)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Calculate target dimensions
            # Width based on rack width (19" = 300px, 23" = 350px)
            rack_width_px = 300 if self.rack.width_inches == 19 else 350
            # Height: 40px per U unit
            target_height = self.units * 40

            # Resize image maintaining aspect ratio to fit within target dimensions
            img.thumbnail((rack_width_px, target_height), Image.Resampling.LANCZOS)

            # Create a new image with exact dimensions and paste the resized image centered
            final_img = Image.new('RGB', (rack_width_px, target_height), (255, 255, 255))
            paste_x = (rack_width_px - img.width) // 2
            paste_y = (target_height - img.height) // 2
            final_img.paste(img, (paste_x, paste_y))

            # Save to BytesIO
            output = BytesIO()
            final_img.save(output, format='JPEG', quality=85, optimize=True)
            output.seek(0)

            # Replace the photo field with optimized version
            self.photo = InMemoryUploadedFile(
                output, 'ImageField',
                f"{self.photo.name.split('.')[0]}.jpg",
                'image/jpeg',
                sys.getsizeof(output), None
            )

        super().save(*args, **kwargs)


class RackConnection(BaseModel):
    """
    Represents a cable/connection between two rack devices.
    Supports network, power, and fiber connections for cable visualization.
    """
    CONNECTION_TYPES = [
        ('network', 'Network Cable'),
        ('fiber', 'Fiber Optic'),
        ('power', 'Power Cable'),
        ('console', 'Console Cable'),
        ('storage', 'Storage (SAN/NAS)'),
    ]

    from_device = models.ForeignKey(RackDevice, on_delete=models.CASCADE, related_name='connections_from')
    to_device = models.ForeignKey(RackDevice, on_delete=models.CASCADE, related_name='connections_to')

    connection_type = models.CharField(max_length=50, choices=CONNECTION_TYPES)
    from_port = models.CharField(max_length=50, blank=True, help_text="Source port (e.g., eth0, port 24)")
    to_port = models.CharField(max_length=50, blank=True, help_text="Destination port")

    cable_color = models.CharField(max_length=7, default='#0d6efd', help_text="Cable color for visualization")
    speed = models.CharField(max_length=50, blank=True, help_text="Connection speed (e.g., 1Gbps, 10Gbps)")

    class Meta:
        db_table = 'rack_connections'

    def __str__(self):
        return f"{self.from_device.name} → {self.to_device.name} ({self.connection_type})"


class VLAN(BaseModel):
    """
    Virtual LAN configuration.
    Can be assigned to subnets, devices, and switch ports.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='vlans')
    vlan_id = models.PositiveIntegerField(help_text="VLAN number (1-4094)")
    name = models.CharField(max_length=100, help_text="VLAN name (e.g., Production, Guest, DMZ)")
    description = models.TextField(blank=True)

    # Optional color for visual identification
    color = models.CharField(max_length=7, blank=True, help_text="Hex color code (e.g., #FF5733)")

    objects = OrganizationManager()

    class Meta:
        db_table = 'vlans'
        ordering = ['vlan_id']
        unique_together = [['organization', 'vlan_id']]
        indexes = [
            models.Index(fields=['organization', 'vlan_id']),
        ]

    def __str__(self):
        return f"VLAN {self.vlan_id} - {self.name}"


class Subnet(BaseModel):
    """
    IP subnet for IP address management (IPAM).
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='subnets')
    name = models.CharField(max_length=100)
    network = models.CharField(max_length=50, help_text="e.g., 192.168.1.0/24")
    description = models.TextField(blank=True)

    # VLAN association (new ForeignKey)
    vlan = models.ForeignKey('VLAN', on_delete=models.SET_NULL, null=True, blank=True, related_name='subnets', help_text="Associated VLAN")

    # Gateway
    gateway = models.GenericIPAddressField(null=True, blank=True)

    # DNS servers
    dns_servers = models.JSONField(default=list, help_text="List of DNS server IPs")

    # Location
    location = models.CharField(max_length=255, blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'subnets'
        ordering = ['network']
        indexes = [
            models.Index(fields=['organization', 'network']),
        ]

    def __str__(self):
        return f"{self.name} ({self.network})"


class IPAddress(BaseModel):
    """
    Individual IP address assignment.
    """
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('reserved', 'Reserved'),
        ('dhcp', 'DHCP Pool'),
    ]

    subnet = models.ForeignKey(Subnet, on_delete=models.CASCADE, related_name='ip_addresses')
    ip_address = models.GenericIPAddressField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')

    # Assignment details
    hostname = models.CharField(max_length=255, blank=True)
    mac_address = models.CharField(max_length=17, blank=True, help_text="MAC address in XX:XX:XX:XX:XX:XX format")
    description = models.TextField(blank=True)

    # Optional link to asset
    asset = models.ForeignKey(Asset, on_delete=models.SET_NULL, null=True, blank=True, help_text="Link to Asset", related_name='ip_addresses')

    # Last seen
    last_seen_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'ip_addresses'
        unique_together = [['subnet', 'ip_address']]
        ordering = ['subnet', 'ip_address']
        indexes = [
            models.Index(fields=['subnet', 'status']),
            models.Index(fields=['ip_address']),
            models.Index(fields=['mac_address']),
        ]

    def __str__(self):
        if self.hostname:
            return f"{self.ip_address} ({self.hostname})"
        return self.ip_address


class RackResource(BaseModel):
    """
    Resources and equipment in racks/closets (non-rackable items).
    Tracks patch panels, cable management, PDUs, UPS units, switches, etc.
    """
    RESOURCE_TYPE_CHOICES = [
        ('patch_panel', 'Patch Panel'),
        ('switch', 'Network Switch'),
        ('router', 'Router'),
        ('firewall', 'Firewall'),
        ('ups', 'UPS/Battery Backup'),
        ('pdu', 'Power Distribution Unit'),
        ('cable_mgmt', 'Cable Management'),
        ('shelf', 'Shelf/Tray'),
        ('kvm', 'KVM Switch'),
        ('monitor', 'Monitor/Display'),
        ('keystone', 'Keystone Jacks'),
        ('fiber_panel', 'Fiber Patch Panel'),
        ('other', 'Other Equipment'),
    ]

    rack = models.ForeignKey(Rack, on_delete=models.CASCADE, related_name='resources')
    name = models.CharField(max_length=255)
    resource_type = models.CharField(max_length=50, choices=RESOURCE_TYPE_CHOICES)

    # Specifications
    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)

    # Network equipment specifics
    port_count = models.PositiveIntegerField(null=True, blank=True, help_text="Number of ports (for switches/patch panels)")
    port_speed = models.CharField(max_length=50, blank=True, help_text="e.g., 1Gbps, 10Gbps")
    port_configuration = models.JSONField(default=dict, blank=True, help_text="Port configuration and connections for patch panels/switches")

    # Power specs
    power_draw_watts = models.PositiveIntegerField(null=True, blank=True)
    input_voltage = models.CharField(max_length=50, blank=True, help_text="e.g., 120V, 240V")

    # UPS specifics
    battery_runtime_minutes = models.PositiveIntegerField(null=True, blank=True, help_text="Runtime at full load")
    capacity_va = models.PositiveIntegerField(null=True, blank=True, help_text="VA capacity for UPS")

    # Optional rack mount position
    rack_position = models.PositiveIntegerField(null=True, blank=True, help_text="U position if rack-mounted")

    # Position on board (X/Y coordinates) - for wall-mounted/board layouts
    board_position_x = models.PositiveIntegerField(null=True, blank=True, help_text="X position on board (pixels)")
    board_position_y = models.PositiveIntegerField(null=True, blank=True, help_text="Y position on board (pixels)")
    board_width = models.PositiveIntegerField(null=True, blank=True, help_text="Width on board (pixels)")
    board_height = models.PositiveIntegerField(null=True, blank=True, help_text="Height on board (pixels)")

    # Management
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="Management IP")
    mac_address = models.CharField(max_length=17, blank=True)
    management_url = models.URLField(max_length=500, blank=True)

    # Warranty/Support
    purchase_date = models.DateField(null=True, blank=True)
    warranty_expires = models.DateField(null=True, blank=True)
    support_contract = models.CharField(max_length=100, blank=True)

    # Optional link to asset
    asset = models.ForeignKey(Asset, on_delete=models.SET_NULL, null=True, blank=True, related_name='rack_resources')

    # Documentation
    photo = models.ImageField(upload_to='rack_resources/', null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'rack_resources'
        ordering = ['rack', 'resource_type', 'name']
        indexes = [
            models.Index(fields=['rack', 'resource_type']),
            models.Index(fields=['ip_address']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_resource_type_display()})"
