"""
Monitoring forms
"""
from django import forms
from .models import WebsiteMonitor, Expiration, Rack, RackDevice, RackConnection, Subnet, IPAddress, VLAN


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
            'organization', 'name', 'rack_type', 'datacenter', 'building', 'floor', 'room', 'aisle', 'location',
            'units', 'width_inches', 'depth_inches', 'power_capacity_watts', 'cooling_capacity_btu',
            'pdu_count', 'patch_panel_count', 'total_port_count', 'ambient_temp_f', 'notes',
        ]
        widgets = {
            'organization': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'rack_type': forms.Select(attrs={'class': 'form-control'}),
            'datacenter': forms.TextInput(attrs={'class': 'form-control'}),
            'building': forms.TextInput(attrs={'class': 'form-control'}),
            'floor': forms.TextInput(attrs={'class': 'form-control'}),
            'room': forms.TextInput(attrs={'class': 'form-control'}),
            'aisle': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'units': forms.NumberInput(attrs={'class': 'form-control'}),
            'width_inches': forms.Select(attrs={'class': 'form-control'}),
            'depth_inches': forms.NumberInput(attrs={'class': 'form-control'}),
            'power_capacity_watts': forms.NumberInput(attrs={'class': 'form-control'}),
            'cooling_capacity_btu': forms.NumberInput(attrs={'class': 'form-control'}),
            'pdu_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'patch_panel_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'total_port_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'ambient_temp_f': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # If organization context exists, pre-select it and hide the field
        if organization:
            self.fields['organization'].initial = organization
            self.fields['organization'].widget = forms.HiddenInput()
        else:
            # Filter organizations by user permissions
            from core.models import Organization
            if user:
                if user.is_superuser or (hasattr(user, 'is_staff_user') and user.is_staff_user):
                    # Staff can see all organizations
                    self.fields['organization'].queryset = Organization.objects.all()
                else:
                    # Regular users only see their organizations
                    self.fields['organization'].queryset = user.organizations.all()


class RackDeviceForm(forms.ModelForm):
    """Form for rack device."""

    class Meta:
        model = RackDevice
        fields = [
            'name', 'start_unit', 'units', 'power_draw_watts',
            'color', 'photo', 'notes', 'asset',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'start_unit': forms.NumberInput(attrs={'class': 'form-control'}),
            'units': forms.NumberInput(attrs={'class': 'form-control'}),
            'power_draw_watts': forms.NumberInput(attrs={'class': 'form-control'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'photo_url': forms.URLInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'asset': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        rack = kwargs.pop('rack', None)
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # Filter assets by organization
        if organization:
            from assets.models import Asset
            # Show all assets, prioritizing rackmount ones
            self.fields['asset'].queryset = Asset.objects.filter(
                organization=organization
            ).order_by('-is_rackmount', 'name')
            self.fields['asset'].required = False
            self.fields['asset'].help_text = 'Optional: Link to an existing asset. Leave blank to create a label-only entry.'
            self.fields['asset'].empty_label = '-- No Asset (Label Only) --'


class SubnetForm(forms.ModelForm):
    """Form for subnet."""

    # Override dns_servers to accept comma-separated input
    dns_servers = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '8.8.8.8, 8.8.4.4'
        }),
        help_text='Enter DNS server IPs separated by commas',
        label='DNS Servers'
    )

    class Meta:
        model = Subnet
        fields = [
            'name', 'network', 'description', 'vlan',
            'gateway', 'dns_servers', 'location',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'network': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.0/24'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'vlan': forms.Select(attrs={'class': 'form-select'}),
            'gateway': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.1'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # Filter VLANs by organization
        if organization:
            self.fields['vlan'].queryset = VLAN.objects.filter(organization=organization).order_by('vlan_id')
            self.fields['vlan'].required = False
            self.fields['vlan'].empty_label = '-- No VLAN --'

        # Convert existing dns_servers list to comma-separated string for display
        if self.instance and self.instance.pk and self.instance.dns_servers:
            if isinstance(self.instance.dns_servers, list):
                self.initial['dns_servers'] = ', '.join(self.instance.dns_servers)

    def clean_dns_servers(self):
        """Convert comma-separated DNS servers to list."""
        dns_input = self.cleaned_data.get('dns_servers', '')

        if not dns_input or not dns_input.strip():
            return []

        # Split by comma and clean up whitespace
        dns_list = [ip.strip() for ip in dns_input.split(',') if ip.strip()]

        return dns_list


class VLANForm(forms.ModelForm):
    """Form for VLAN."""

    class Meta:
        model = VLAN
        fields = ['vlan_id', 'name', 'description', 'color']
        widgets = {
            'vlan_id': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '4094', 'placeholder': 'e.g., 10, 100'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Production, Guest, DMZ'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Purpose of this VLAN...'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        self.fields['color'].required = False
        self.fields['color'].initial = '#3498db'  # Default blue color


class IPAddressForm(forms.ModelForm):
    """Form for IP address."""

    class Meta:
        model = IPAddress
        fields = [
            'ip_address', 'hostname', 'mac_address', 'status',
            'description', 'notes', 'asset',
        ]
        widgets = {
            'ip_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.100'}),
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'mac_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '00:11:22:33:44:55'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'asset': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        subnet = kwargs.pop('subnet', None)
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # Filter assets by organization
        if organization:
            from assets.models import Asset
            self.fields['asset'].queryset = Asset.objects.filter(organization=organization)
            self.fields['asset'].required = False  # IP addresses can be unassigned


class RackConnectionForm(forms.ModelForm):
    """Form for rack device connections (cables/wiring)."""

    class Meta:
        model = RackConnection
        fields = [
            'from_device', 'to_device', 'connection_type',
            'from_port', 'to_port', 'cable_color', 'speed',
        ]
        widgets = {
            'from_device': forms.Select(attrs={'class': 'form-select'}),
            'to_device': forms.Select(attrs={'class': 'form-select'}),
            'connection_type': forms.Select(attrs={'class': 'form-select'}),
            'from_port': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., eth0, port 24, Gi1/0/1'}),
            'to_port': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., eth1, port 12, Gi1/0/2'}),
            'cable_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'speed': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 1Gbps, 10Gbps, 40Gbps'}),
        }

    def __init__(self, *args, **kwargs):
        rack = kwargs.pop('rack', None)
        from_device = kwargs.pop('from_device', None)
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # Filter devices to only show devices in the same rack
        if rack:
            self.fields['from_device'].queryset = RackDevice.objects.filter(rack=rack).order_by('start_unit')
            self.fields['to_device'].queryset = RackDevice.objects.filter(rack=rack).order_by('start_unit')
        elif organization:
            self.fields['from_device'].queryset = RackDevice.objects.filter(rack__organization=organization).select_related('rack').order_by('rack__name', 'start_unit')
            self.fields['to_device'].queryset = RackDevice.objects.filter(rack__organization=organization).select_related('rack').order_by('rack__name', 'start_unit')

        # Pre-select from_device if provided
        if from_device:
            self.fields['from_device'].initial = from_device
            # Exclude from_device from to_device choices (can't connect to itself)
            self.fields['to_device'].queryset = self.fields['to_device'].queryset.exclude(id=from_device.id)
