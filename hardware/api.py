"""Read-only REST endpoints (mounted under /api/ with the existing API auth and org scoping).

Writes go through the validated session endpoints (/hardware/api/...), which
apply the occupancy, tenancy, compatibility and VLAN rules in `services`.
"""
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from api.views import OrganizationScopedViewSet

from .models import Cable, CableTermination, DevicePort, HardwareDevice, HardwareModel


class HardwareModelSerializer(serializers.ModelSerializer):
    manufacturer = serializers.CharField(source='manufacturer.name')

    class Meta:
        model = HardwareModel
        fields = ('id', 'manufacturer', 'model', 'slug', 'kind', 'part_number', 'category', 'category_source',
                  'u_height', 'is_full_depth', 'is_generic', 'spec_provenance', 'spec_source_url',
                  'upstream_path', 'upstream_revision', 'revision')


class HardwareModelViewSet(viewsets.ReadOnlyModelViewSet):
    """The shared catalog. Global by design: it holds no client data."""
    permission_classes = [IsAuthenticated]
    serializer_class = HardwareModelSerializer
    filterset_fields = ('kind', 'category', 'is_generic', 'spec_provenance')
    search_fields = ('model', 'part_number', 'manufacturer__name')

    def get_queryset(self):
        return HardwareModel.objects.select_related('manufacturer').order_by('manufacturer__name', 'model')


class DeviceSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='asset.name')
    hostname = serializers.CharField(source='asset.hostname')
    serial_number = serializers.CharField(source='asset.serial_number')
    asset_tag = serializers.CharField(source='asset.asset_tag')
    management_ip = serializers.CharField(source='asset.ip_address', allow_null=True)
    model = serializers.CharField(source='hardware_model.__str__')

    class Meta:
        model = HardwareDevice
        fields = ('id', 'public_id', 'organization', 'asset', 'name', 'hostname', 'serial_number', 'asset_tag',
                  'management_ip', 'hardware_model', 'model', 'template_revision', 'site', 'room', 'status',
                  'platform', 'install_date')


class PortSerializer(serializers.ModelSerializer):
    tagged_vlans = serializers.SerializerMethodField()
    cable = serializers.SerializerMethodField()

    class Meta:
        model = DevicePort
        fields = ('id', 'public_id', 'organization', 'device', 'module', 'template_key', 'component_class', 'name',
                  'label', 'type', 'connector', 'description', 'tech_label', 'mode', 'untagged_vlan', 'voice_vlan',
                  'tagged_vlans', 'admin_state', 'oper_state', 'oper_source', 'poe_mode', 'poe_setting', 'lag', 'cable')

    def get_tagged_vlans(self, obj):
        return [m.vlan_id for m in obj.tagged_memberships.all()]

    def get_cable(self, obj):
        t = getattr(obj, 'cable_termination', None) if hasattr(obj, 'cable_termination') else None
        return {'id': t.cable_id, 'end': t.end} if t else None


class CableSerializer(serializers.ModelSerializer):
    a = serializers.SerializerMethodField()
    b = serializers.SerializerMethodField()

    class Meta:
        model = Cable
        fields = ('id', 'public_id', 'organization', 'label', 'cable_type', 'status', 'color', 'length',
                  'length_unit', 'label_a', 'label_b', 'a', 'b')

    def _end(self, obj, end):
        return [t.port_id for t in obj.terminations.all() if t.end == end]

    def get_a(self, obj):
        return self._end(obj, 'A')

    def get_b(self, obj):
        return self._end(obj, 'B')


class _ReadOnlyScoped(OrganizationScopedViewSet):
    view_perm = 'assets_view'
    http_method_names = ['get', 'head', 'options']


class DeviceViewSet(_ReadOnlyScoped):
    serializer_class = DeviceSerializer
    queryset = HardwareDevice.objects.select_related('asset', 'hardware_model__manufacturer')


class PortViewSet(_ReadOnlyScoped):
    serializer_class = PortSerializer
    queryset = DevicePort.objects.select_related('cable_termination').prefetch_related('tagged_memberships')
    filterset_fields = ('device', 'component_class')


class CableViewSet(_ReadOnlyScoped):
    serializer_class = CableSerializer
    queryset = Cable.objects.prefetch_related('terminations')
