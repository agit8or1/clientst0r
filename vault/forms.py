"""
Vault forms
"""
from django import forms
from .models import Password


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
            'tags': forms.CheckboxSelectMultiple(),
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
        super().__init__(*args, **kwargs)

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

        return cleaned_data

    def save(self, commit=True):
        password_obj = super().save(commit=False)

        # Set encrypted password if plaintext provided
        plaintext = self.cleaned_data.get('plaintext_password')
        if plaintext:
            password_obj.set_password(plaintext)
        elif not self.instance.pk:
            # New entry with no password - set empty password for OTP type
            if password_obj.password_type == 'otp':
                password_obj.set_password('')

        # Handle TOTP secret
        password_type = self.cleaned_data.get('password_type')
        if password_type == 'otp':
            generate_new = self.cleaned_data.get('generate_new_secret')
            plaintext_secret = self.cleaned_data.get('plaintext_otp_secret')

            if generate_new:
                # Generate new TOTP secret
                import pyotp
                new_secret = pyotp.random_base32()
                password_obj.set_otp_secret(new_secret)
            elif plaintext_secret:
                # Use provided secret
                password_obj.set_otp_secret(plaintext_secret)

        if commit:
            password_obj.save()
            self.save_m2m()

        return password_obj
