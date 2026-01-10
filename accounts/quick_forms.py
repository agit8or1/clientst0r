"""
Quick add forms for organization admins to rapidly create common items.
"""
from django import forms
from django.contrib.auth.models import User
from .models import Membership, Role


class QuickUserForm(forms.Form):
    """
    Quick form for creating a new user and adding them to an organization.
    """
    # User fields
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'username'}),
        help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.'
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'user@example.com'}),
        help_text='User will receive login instructions at this email'
    )
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
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Temporary password for the user (they should change it after first login)'
    )
    password_confirm = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Re-enter the password'
    )

    # Membership fields
    role = forms.ChoiceField(
        choices=Role.choices,
        initial=Role.READONLY,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='User role in the organization'
    )

    send_welcome_email = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text='Send welcome email with login instructions'
    )

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('A user with this username already exists.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user with this email already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('Passwords do not match.')

        return cleaned_data

    def save(self, organization, created_by):
        """
        Create the user and add them to the organization.
        Returns the created User instance.
        """
        # Create user
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            first_name=self.cleaned_data.get('first_name', ''),
            last_name=self.cleaned_data.get('last_name', '')
        )

        # Create membership
        Membership.objects.create(
            user=user,
            organization=organization,
            role=self.cleaned_data['role'],
            is_active=True
        )

        return user
