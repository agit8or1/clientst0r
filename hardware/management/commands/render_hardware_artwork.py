"""Pre-generate catalog layouts and cached artwork.

    python manage.py render_hardware_artwork              # every device/module model
    python manage.py render_hardware_artwork --manufacturer Dell

Optional: pages generate artwork on first view anyway. Running this after an
import means catalog pages never write while they are being browsed.
"""
from django.core.management.base import BaseCommand

from hardware.layout import get_layout
from hardware.models import HardwareModel
from hardware.renderer import cached_face_svg


class Command(BaseCommand):
    help = 'Pre-generate hardware catalog layouts and cached SVG artwork.'

    def add_arguments(self, parser):
        parser.add_argument('--manufacturer', action='append')
        parser.add_argument('--no-thumbs', action='store_true')

    def handle(self, *args, **o):
        qs = HardwareModel.objects.exclude(kind=HardwareModel.KIND_RACK).select_related('manufacturer')
        if o['manufacturer']:
            qs = qs.filter(manufacturer__name__in=o['manufacturer'])
        n = 0
        for hm in qs.iterator(chunk_size=200):
            lay = get_layout(hm)
            for face in lay.faces:
                cached_face_svg(hm, lay, face)
                if not o['no_thumbs'] and face == 'front':
                    cached_face_svg(hm, lay, face, variant='thumb')
            n += 1
            if n % 1000 == 0:
                self.stdout.write(f'  {n} models')
        self.stdout.write(self.style.SUCCESS(f'Rendered artwork for {n} models.'))
