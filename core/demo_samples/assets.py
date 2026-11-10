"""Sample data group: assets (v3.17.657). See core/demo_samples/__init__.py.

A few new assets on the first two demo customers whose picture is the
generated artwork of a hardware-catalog model, so the asset header and list
thumbnails have something to show. Models are looked up in the installed
catalog by category (preferring well-known manufacturers); when the catalog
is empty nothing is created. Keyed by (customer, name); existing assets are
never touched.
"""

# (asset name, asset type, catalog category, preferred manufacturers, notes)
SPECS = [
    ('Edge firewall (sample artwork)', 'firewall', 'firewall', ('Fortinet', 'Palo Alto', 'SonicWall'),
     'Sample asset showing catalog artwork as its picture.'),
    ('Core switch (sample artwork)', 'switch', 'switch', ('Aruba', 'Cisco', 'Ubiquiti', 'Juniper'),
     'Sample asset showing catalog artwork as its picture.'),
    ('File server (sample artwork)', 'server', 'server', ('Dell', 'HPE', 'Supermicro', 'Lenovo'),
     'Sample asset showing catalog artwork as its picture.'),
]


def _pick_model(category, manufacturers):
    from hardware.models import HardwareModel
    qs = (HardwareModel.objects.filter(is_active=True, kind=HardwareModel.KIND_DEVICE, category=category)
          .select_related('manufacturer').order_by('is_generic', 'manufacturer__name', 'model'))
    for name in manufacturers:
        hm = qs.filter(manufacturer__name__icontains=name, is_generic=False).first()
        if hm is not None:
            return hm
    return qs.first()


def seed(ctx):
    from assets.models import Asset
    from . import has_webhook
    picks = [(spec, _pick_model(spec[2], spec[3])) for spec in SPECS]
    picks = [(spec, hm) for spec, hm in picks if hm is not None]
    if not picks:
        ctx.out.write('  assets: hardware catalog is empty; no artwork samples')
        return
    for org in ctx.customers[:2]:
        if has_webhook(org, 'asset.created'):
            ctx.out.write(f'  assets: skipped {org.slug} (asset.created webhook)')
            continue
        for (name, asset_type, _category, _mfrs, notes), hm in picks:
            if Asset.objects.filter(organization=org, name=name).exists():
                continue
            Asset.objects.create(
                organization=org, name=name, asset_type=asset_type,
                manufacturer=hm.manufacturer.name, model=hm.model, notes=notes,
                image_source=Asset.IMAGE_ARTWORK, artwork_model=hm, artwork_face='front',
                created_by=ctx.admin,
            )
            ctx.created('assets.Asset (artwork)')
