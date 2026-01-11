"""
Accounts forms
"""
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm
from core.models import Organization
from .models import Membership, UserProfile, RoleTemplate
import pytz


class OrganizationForm(forms.ModelForm):
    """Form for creating and editing organizations."""

    class Meta:
        model = Organization
        fields = [
            'name', 'legal_name', 'tax_id', 'description',
            'street_address', 'street_address_2', 'city', 'state', 'postal_code', 'country',
            'phone', 'email', 'website',
            'primary_contact_name', 'primary_contact_title', 'primary_contact_email', 'primary_contact_phone',
            'logo', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Organization Name'}),
            'legal_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Legal Business Name'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tax ID / EIN'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description'}),
            'street_address': forms.TextInput(attrs={'class': 'form-control'}),
            'street_address_2': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'primary_contact_name': forms.TextInput(attrs={'class': 'form-control'}),
            'primary_contact_title': forms.TextInput(attrs={'class': 'form-control'}),
            'primary_contact_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'primary_contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'is_active': 'Inactive organizations are hidden from users',
        }


class MembershipForm(forms.ModelForm):
    """Form for managing organization memberships."""

    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'user@example.com'}),
        help_text='Email of user to add (leave blank if selecting existing user)'
    )

    class Meta:
        model = Membership
        fields = ['user', 'role', 'role_template', 'is_active']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'role_template': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'role': 'Basic role (used if no role template is selected)',
            'role_template': 'Optional: Select a role template for granular permissions',
            'is_active': 'Uncheck to suspend this user',
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # Only show users who don't belong to ANY organization yet
        if organization:
            # Get all user IDs who are members of ANY organization
            all_member_ids = Membership.objects.filter(
                is_active=True
            ).values_list('user_id', flat=True).distinct()

            # Show only users who aren't members of any organization
            # This prevents adding users from other organizations
            self.fields['user'].queryset = User.objects.exclude(id__in=all_member_ids).order_by('username')
            self.fields['user'].label = 'Select User (unassigned users only)'
            self.fields['user'].help_text = 'Only shows users not assigned to any organization'

            # Get role templates (system + org custom)
            system_templates = RoleTemplate.objects.filter(is_system_template=True)
            org_templates = RoleTemplate.objects.filter(organization=organization, is_system_template=False)
            all_templates = list(system_templates) + list(org_templates)

            # Build choices with optgroups
            choices = [('', '--- Use Default Role ---')]
            if system_templates:
                choices.append(('System Templates', [(t.id, t.name) for t in system_templates]))
            if org_templates:
                choices.append(('Custom Templates', [(t.id, t.name) for t in org_templates]))

            self.fields['role_template'].choices = choices
            self.fields['role_template'].required = False

        self.fields['user'].required = False
        self.fields['email'].help_text = 'Enter email to add existing user or create invitation'


class UserProfileForm(forms.ModelForm):
    """Form for editing user profile."""
    
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'})
    )
    
    class Meta:
        model = UserProfile
        fields = ['phone', 'title', 'department', 'timezone', 'locale', 'email_notifications', 'notification_frequency']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1 (555) 123-4567'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Job Title'}),
            'department': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Department'}),
            'timezone': forms.Select(attrs={'class': 'form-select'}),
            'locale': forms.Select(attrs={'class': 'form-select'}),
            'email_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notification_frequency': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Add timezone choices
        common_timezones = [
            ('UTC', 'UTC'),
            ('America/New_York', 'Eastern Time (US & Canada)'),
            ('America/Chicago', 'Central Time (US & Canada)'),
            ('America/Denver', 'Mountain Time (US & Canada)'),
            ('America/Los_Angeles', 'Pacific Time (US & Canada)'),
            ('America/Phoenix', 'Arizona'),
            ('America/Anchorage', 'Alaska'),
            ('Pacific/Honolulu', 'Hawaii'),
            ('Europe/London', 'London'),
            ('Europe/Paris', 'Paris'),
            ('Europe/Berlin', 'Berlin'),
            ('Europe/Moscow', 'Moscow'),
            ('Asia/Dubai', 'Dubai'),
            ('Asia/Kolkata', 'Mumbai, Kolkata'),
            ('Asia/Shanghai', 'Beijing, Shanghai'),
            ('Asia/Tokyo', 'Tokyo'),
            ('Asia/Singapore', 'Singapore'),
            ('Australia/Sydney', 'Sydney'),
            ('Pacific/Auckland', 'Auckland'),
        ]
        # Add all other timezones
        all_timezones = [(tz, tz) for tz in pytz.common_timezones if tz not in dict(common_timezones).keys()]
        self.fields['timezone'].choices = common_timezones + [('---', '--- All Timezones ---')] + all_timezones

        if self.user:
            self.fields['first_name'].initial = self.user.first_name
            self.fields['last_name'].initial = self.user.last_name
            self.fields['email'].initial = self.user.email
    
    def save(self, commit=True):
        profile = super().save(commit=False)
        
        if self.user:
            self.user.first_name = self.cleaned_data['first_name']
            self.user.last_name = self.cleaned_data['last_name']
            self.user.email = self.cleaned_data['email']
            if commit:
                self.user.save()
        
        if commit:
            profile.save()
        
        return profile


class PasswordChangeForm(DjangoPasswordChangeForm):
    """Custom password change form with Bootstrap styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class UserCreateForm(forms.ModelForm):
    """Form for creating new users by admins."""
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Enter a strong password'
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Enter the same password again'
    )

    # User type and global role (from profile)
    user_type = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Staff users have global access to all organizations. Org users only see their assigned organizations.'
    )
    global_role_template = forms.ModelChoiceField(
        queryset=None,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='For staff users: role template that applies globally across all organizations'
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import UserType, RoleTemplate
        self.fields['user_type'].choices = UserType.choices
        self.fields['global_role_template'].queryset = RoleTemplate.objects.filter(is_system_template=True)

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
            # Update profile with user type and global role
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.user_type = self.cleaned_data['user_type']
            profile.global_role_template = self.cleaned_data.get('global_role_template')
            profile.save()
        return user


class UserEditForm(forms.ModelForm):
    """Form for editing users by admins."""

    # User type and global role (from profile)
    user_type = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Staff users have global access to all organizations. Org users only see their assigned organizations.'
    )
    global_role_template = forms.ModelChoiceField(
        queryset=None,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='For staff users: role template that applies globally across all organizations'
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'is_active': 'User can log in',
            'is_staff': 'User can access admin site',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import UserType, RoleTemplate
        self.fields['user_type'].choices = UserType.choices
        self.fields['global_role_template'].queryset = RoleTemplate.objects.filter(is_system_template=True)

        # Set initial values from profile
        if self.instance and self.instance.pk:
            profile = getattr(self.instance, 'profile', None)
            if profile:
                self.fields['user_type'].initial = profile.user_type
                self.fields['global_role_template'].initial = profile.global_role_template

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            # Update profile with user type and global role
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.user_type = self.cleaned_data['user_type']
            profile.global_role_template = self.cleaned_data.get('global_role_template')
            profile.save()
        return user


class UserPasswordResetForm(forms.Form):
    """Form for admins to reset user passwords."""
    password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Enter a new password for this user'
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Enter the same password again'
    )

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2
