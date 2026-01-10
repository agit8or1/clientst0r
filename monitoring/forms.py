"""
Monitoring forms
"""
from django import forms
from .models import WebsiteMonitor, Expiration, Rack, RackDevice, Subnet, IPAddress


class WebsiteMonitorForm(forms.ModelForm):
    """Form for website monitor."""

    class Meta:
        model = WebsiteMonitor
        fields = [
            'name', 'url', 'check_interval_minutes', 'is_enabled',
            'notify_on_down', 'notify_on_ssl_expiry', 'notify_on_domain_expiry',
            'ssl_warning_days', 'domain_warning_days',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://example.com'}),
            'check_interval_minutes': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_on_down': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_on_ssl_expiry': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_on_domain_expiry': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ssl_warning_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'domain_warning_days': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)


class ExpirationForm(forms.ModelForm):
    """Form for expiration tracking."""

    class Meta:
        model = Expiration
        fields = [
            'name', 'expiration_type', 'expires_at', 'warning_days',
            'auto_renew', 'renewal_cost', 'related_url', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'expiration_type': forms.Select(attrs={'class': 'form-select'}),
            'expires_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'warning_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'auto_renew': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'renewal_cost': forms.NumberInput(attrs={'class': 'form-control'}),
            'related_url': forms.URLInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)


class RackForm(forms.ModelForm):
    """Form for rack."""

    class Meta:
        model = Rack
        fields = [
            'name', 'datacenter', 'aisle', 'location', 'units', 'width_inches', 'depth_inches',
            'power_capacity_watts', 'cooling_capacity_btu', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'datacenter': forms.TextInput(attrs={'class': 'form-control'}),
            'aisle': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'units': forms.NumberInput(attrs={'class': 'form-control'}),
            'width_inches': forms.Select(attrs={'class': 'form-control'}),
            'depth_inches': forms.NumberInput(attrs={'class': 'form-control'}),
            'power_capacity_watts': forms.NumberInput(attrs={'class': 'form-control'}),
            'cooling_capacity_btu': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)


class RackDeviceForm(forms.ModelForm):
    """Form for rack device."""

    class Meta:
        model = RackDevice
        fields = [
            'name', 'start_unit', 'units', 'power_draw_watts',
            'color', 'photo', 'notes', 'asset_id',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'start_unit': forms.NumberInput(attrs={'class': 'form-control'}),
            'units': forms.NumberInput(attrs={'class': 'form-control'}),
            'power_draw_watts': forms.NumberInput(attrs={'class': 'form-control'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'photo_url': forms.URLInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'asset_id': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        rack = kwargs.pop('rack', None)
        super().__init__(*args, **kwargs)


class SubnetForm(forms.ModelForm):
    """Form for subnet."""

    class Meta:
        model = Subnet
        fields = [
            'name', 'network', 'description', 'vlan_id', 'vlan_name',
            'gateway', 'dns_servers', 'location',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'network': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.0/24'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'vlan_id': forms.NumberInput(attrs={'class': 'form-control'}),
            'vlan_name': forms.TextInput(attrs={'class': 'form-control'}),
            'gateway': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.1'}),
            'dns_servers': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '["8.8.8.8", "8.8.4.4"]'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)


class IPAddressForm(forms.ModelForm):
    """Form for IP address."""

    class Meta:
        model = IPAddress
        fields = [
            'ip_address', 'hostname', 'mac_address', 'status',
            'description', 'notes', 'asset_id',
        ]
        widgets = {
            'ip_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.100'}),
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'mac_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '00:11:22:33:44:55'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'asset_id': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        subnet = kwargs.pop('subnet', None)
        super().__init__(*args, **kwargs)
