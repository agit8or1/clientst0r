"""
Domain and SSL tracking models
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta
from core.models import Organization, BaseModel
from core.utils import OrganizationManager


class Domain(BaseModel):
    """
    Domain name with expiration tracking.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='domains')
    domain_name = models.CharField(max_length=255)
    registrar = models.CharField(max_length=255, blank=True)
    registration_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    auto_renew = models.BooleanField(default=False)

    # Nameservers
    nameservers = models.JSONField(default=list, blank=True)

    # Contact info
    registrant_email = models.EmailField(blank=True)
    admin_email = models.EmailField(blank=True)

    # Monitoring
    is_monitored = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'domains'
        unique_together = [['organization', 'domain_name']]
        ordering = ['domain_name']
        indexes = [
            models.Index(fields=['organization', 'expiration_date']),
        ]

    def __str__(self):
        return self.domain_name

    @property
    def days_until_expiration(self):
        """Days until domain expires."""
        if not self.expiration_date:
            return None
        delta = self.expiration_date - timezone.now().date()
        return delta.days

    @property
    def is_expiring_soon(self):
        """Check if domain expires within 30 days."""
        days = self.days_until_expiration
        return days is not None and 0 < days <= 30

    @property
    def is_expired(self):
        """Check if domain is expired."""
        days = self.days_until_expiration
        return days is not None and days < 0


class SSLCertificate(BaseModel):
    """
    SSL/TLS certificate tracking.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='ssl_certificates')
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE, null=True, blank=True, related_name='ssl_certificates')

    common_name = models.CharField(max_length=255)
    issuer = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)

    # Dates
    issued_date = models.DateTimeField(null=True, blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)

    # Certificate details
    certificate_type = models.CharField(max_length=50, choices=[
        ('dv', 'Domain Validated'),
        ('ov', 'Organization Validated'),
        ('ev', 'Extended Validation'),
        ('wildcard', 'Wildcard'),
    ], default='dv')

    # Subject Alternative Names
    san_domains = models.JSONField(default=list, blank=True, help_text='Subject Alternative Names')

    # Monitoring
    is_monitored = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'ssl_certificates'
        ordering = ['-expiration_date']
        indexes = [
            models.Index(fields=['organization', 'expiration_date']),
        ]

    def __str__(self):
        return f"{self.common_name} (expires {self.expiration_date})"

    @property
    def days_until_expiration(self):
        """Days until certificate expires."""
        if not self.expiration_date:
            return None
        delta = self.expiration_date - timezone.now()
        return delta.days

    @property
    def is_expiring_soon(self):
        """Check if certificate expires within 30 days."""
        days = self.days_until_expiration
        return days is not None and 0 < days <= 30

    @property
    def is_expired(self):
        """Check if certificate is expired."""
        days = self.days_until_expiration
        return days is not None and days < 0
