"""
Vault forms
"""
from django import forms
from django.conf import settings
from .models import Password, PasswordBreachCheck
from .breach_checker import PasswordBreachChecker


class PasswordForm(forms.ModelForm):
    # Separate field for plaintext password input
    plaintext_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Password will be encrypted before storage"
    )

    # TOTP secret input
    plaintext_otp_secret = forms.CharField(
        label='TOTP Secret',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Base32 encoded secret'}),
        required=False,
        help_text="TOTP/2FA secret key (will be encrypted). Leave blank to generate new secret."
    )

    generate_new_secret = forms.BooleanField(
        label='Generate New TOTP Secret',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Check to automatically generate a new TOTP secret"
    )

    # Breach scanning frequency
    hibp_scan_frequency = forms.ChoiceField(
        label='Breach Scan Frequency',
        choices=[],  # Will be set in __init__
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="How often to check this password for data breaches"
    )

    class Meta:
        model = Password
        fields = [
            'title', 'password_type', 'username', 'url', 'otp_issuer', 'notes', 'expires_at', 'tags',
            'email_server', 'email_port', 'domain', 'database_type', 'database_host', 'database_port',
            'database_name', 'ssh_host', 'ssh_port', 'license_key'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'password_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_password_type'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'url': forms.URLInput(attrs={'class': 'form-control'}),
            'otp_issuer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Google, GitHub'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'expires_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
            # Email fields
            'email_server': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'mail.example.com'}),
            'email_port': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '993/587'}),
            # Windows/AD fields
            'domain': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'DOMAIN or domain.local'}),
            # Database fields
            'database_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'MySQL, PostgreSQL, etc.'}),
            'database_host': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'localhost or IP'}),
            'database_port': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '3306, 5432, etc.'}),
            'database_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Database name'}),
            # SSH fields
            'ssh_host': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'hostname or IP'}),
            'ssh_port': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '22'}),
            # License key
            'license_key': forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        self.breach_warning = None  # Will hold breach warning message
        super().__init__(*args, **kwargs)

        # Set scan frequency choices
        frequencies = getattr(settings, 'HIBP_SCAN_FREQUENCIES', [2, 4, 8, 16, 24])
        self.fields['hibp_scan_frequency'].choices = [(h, f'Every {h} hours') for h in frequencies]

        # Set default or current value for scan frequency
        default_freq = getattr(settings, 'HIBP_DEFAULT_SCAN_FREQUENCY', 24)
        if self.instance and self.instance.pk and self.instance.custom_fields:
            current_freq = self.instance.custom_fields.get('hibp_scan_frequency', default_freq)
            self.fields['hibp_scan_frequency'].initial = current_freq
        else:
            self.fields['hibp_scan_frequency'].initial = default_freq

        # Filter tags by organization
        if self.organization:
            self.fields['tags'].queryset = self.organization.tags.all()

        # If editing existing password, populate OTP secret if it exists
        if self.instance and self.instance.pk:
            self.fields['plaintext_password'].help_text = "Leave blank to keep existing password"
            if self.instance.otp_secret:
                # Don't show the actual secret for security
                self.fields['plaintext_otp_secret'].widget.attrs['placeholder'] = '(Secret configured)'

    def clean(self):
        cleaned_data = super().clean()
        password_type = cleaned_data.get('password_type')
        plaintext_password = cleaned_data.get('plaintext_password')
        plaintext_otp_secret = cleaned_data.get('plaintext_otp_secret')
        generate_new_secret = cleaned_data.get('generate_new_secret')

        # Validate based on password type
        if password_type == 'otp':
            # OTP type must have either a secret or generate new one
            if not self.instance.pk:  # Creating new OTP entry
                if not plaintext_otp_secret and not generate_new_secret:
                    self.add_error('plaintext_otp_secret', 'TOTP secret is required for OTP entries, or check "Generate New TOTP Secret"')
        else:
            # Non-OTP types need a password
            if not self.instance.pk:  # Creating new entry
                if not plaintext_password:
                    self.add_error('plaintext_password', 'Password is required')

        # Validate TOTP secret format if provided (for any password type)
        if plaintext_otp_secret:
            # Verify it's valid base32
            import re
            if not re.match(r'^[A-Z2-7]+=*$', plaintext_otp_secret.replace(' ', '')):
                self.add_error('plaintext_otp_secret', 'TOTP secret must be valid base32 format (A-Z, 2-7)')

        # Check password against breach database
        if plaintext_password and getattr(settings, 'HIBP_CHECK_ON_SAVE', True):
            try:
                checker = PasswordBreachChecker()
                is_breached, count = checker.check_password(plaintext_password)

                if is_breached:
                    block_breached = getattr(settings, 'HIBP_BLOCK_BREACHED', False)
                    if block_breached:
                        # Block breached passwords
                        self.add_error(
                            'plaintext_password',
                            f"This password has been found in {count:,} data breaches. "
                            f"Please choose a different password."
                        )
                    else:
                        # Just warn, don't block
                        self.breach_warning = (
                            f"⚠️ WARNING: This password has been found in {count:,} "
                            f"data breaches. Consider using a different password."
                        )
            except Exception as e:
                # Log error but don't block on breach check failure
                import logging
                logger = logging.getLogger('vault')
                logger.warning(f"Breach check failed: {e}")

        return cleaned_data

    def save(self, commit=True):
        password_obj = super().save(commit=False)

        # Store scan frequency in custom_fields
        freq = self.cleaned_data.get('hibp_scan_frequency')
        if freq:
            if not password_obj.custom_fields:
                password_obj.custom_fields = {}
            password_obj.custom_fields['hibp_scan_frequency'] = int(freq)

        # Set encrypted password if plaintext provided
        plaintext = self.cleaned_data.get('plaintext_password')
        if plaintext:
            password_obj.set_password(plaintext)
        elif not self.instance.pk:
            # New entry with no password - set empty password for OTP type
            if password_obj.password_type == 'otp':
                password_obj.set_password('')

        # Handle TOTP secret (for ANY password type, not just 'otp')
        generate_new = self.cleaned_data.get('generate_new_secret')
        plaintext_secret = self.cleaned_data.get('plaintext_otp_secret')

        if generate_new:
            # Generate new TOTP secret
            import pyotp
            new_secret = pyotp.random_base32()
            password_obj.set_otp_secret(new_secret)
        elif plaintext_secret:
            # Use provided secret (remove spaces for user convenience)
            clean_secret = plaintext_secret.replace(' ', '').upper()
            password_obj.set_otp_secret(clean_secret)

        if commit:
            password_obj.save()
            self.save_m2m()

            # Create initial breach check record if password was provided
            if plaintext and getattr(settings, 'HIBP_CHECK_ON_SAVE', True):
                try:
                    checker = PasswordBreachChecker()
                    is_breached, count = checker.check_password(plaintext)
                    PasswordBreachCheck.objects.create(
                        password=password_obj,
                        is_breached=is_breached,
                        breach_count=count
                    )
                except Exception as e:
                    # Log error but don't fail save
                    import logging
                    logger = logging.getLogger('vault')
                    logger.warning(f"Could not create breach check record: {e}")

        return password_obj
