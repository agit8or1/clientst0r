"""Fill the demo's Documents, Diagrams and Office Templates pages for the
Documents and Diagrams guide: categories (one nested), a document with a few
saved versions, a document template, three diagrams with preview images, a
diagram template and two Office templates.

Isolated demo database only. Idempotent; every name is invented.
"""
import io, os, sys

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile

from core.models import Organization, Tag
from docs.models import Diagram, Document, DocumentCategory

User = get_user_model()
tech = User.objects.get(username='demo.tech')
org = Organization.objects.get(name='Northwind Logistics')


def category(name, parent=None, order=0, icon='fa-folder'):
    obj, _ = DocumentCategory.objects.get_or_create(
        organization=org, slug=name.lower().replace(' ', '-'),
        defaults={'name': name, 'parent': parent, 'order': order, 'icon': icon})
    DocumentCategory.objects.filter(pk=obj.pk).update(icon=icon)
    return obj


runbooks = category('Runbooks', order=1, icon='fa-book')
network = category('Network', order=2, icon='fa-network-wired')
warehouse = category('Warehouse systems', parent=runbooks, order=3)

# Documents of this customer still on a global category (the form offers only the
# customer's own) move to the customer's category of the same name.
for d in Document.objects.filter(organization=org, is_global=False, category__isnull=False, category__organization__isnull=True):
    own = {'Network': network, 'Runbooks': runbooks}.get(d.category.name)
    if own:
        Document.objects.filter(pk=d.pk).update(category=own)

# A document that has been edited a few times, so History has rows.
doc = Document.objects.get(organization=org, slug='northwind-network-overview')
if not doc.versions.exists():
    doc.category = network
    doc.last_modified_by = tech
    doc.save()
    for extra in ('<p>Added the Dayton depot uplink: 300 Mbps fibre, static addressing.</p>',
                  '<p>Corrected the core switch model after the March refresh.</p>'):
        doc.body = (doc.body or '') + extra
        doc.last_modified_by = tech
        doc.save()
scanner = Document.objects.filter(organization=org, slug='runbook-warehouse-scanner-onboarding').first()
if scanner and scanner.category_id != warehouse.pk:
    scanner.category = warehouse
    scanner.save()

# A document template.
if not Document.objects.filter(organization=org, slug='new-site-checklist-template').exists():
    Document.objects.create(
        organization=org, title='New site checklist (template)', slug='new-site-checklist-template',
        content_type='markdown', is_template=True, is_published=True, category=runbooks,
        body='# New site checklist\n\n- [ ] Circuit installed and tested\n- [ ] Switch and Wi-Fi configured\n'
             '- [ ] Backup agent enrolled\n- [ ] Handover document written\n',
        created_by=tech, last_modified_by=tech)


# ---- diagrams -------------------------------------------------------------
def preview(label, boxes):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (800, 480), 'white')
    d = ImageDraw.Draw(im)
    for (x, y, w, h, text) in boxes:
        d.rounded_rectangle((x, y, x + w, y + h), 10, outline='#2f5d8a', fill='#e8f1fa', width=3)
        d.text((x + 12, y + h // 2 - 6), text, fill='#1c2b3a')
    d.text((16, 12), label, fill='#555555')
    buf = io.BytesIO(); im.save(buf, 'PNG')
    return buf.getvalue()


XML = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
       '<mxCell id="2" value="{a}" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="120" height="50" as="geometry"/></mxCell>'
       '<mxCell id="3" value="{b}" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="240" y="40" width="120" height="50" as="geometry"/></mxCell>'
       '<mxCell id="4" edge="1" source="2" target="3" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>'
       '</root></mxGraphModel>')

DIAGRAMS = [
    ('Dayton depot network', 'network', 'Core switch, firewall and the depot uplink, with the VLAN each port serves.',
     [(60, 60, 180, 70, 'Internet (fibre)'), (60, 200, 180, 70, 'Firewall'), (330, 200, 180, 70, 'Core switch'),
      (580, 120, 180, 70, 'Scanner VLAN'), (580, 300, 180, 70, 'Office VLAN')], 'Dayton depot', 'Core'),
    ('Warehouse floor plan', 'floorplan', 'Racking aisles, dock doors and access point positions.',
     [(40, 60, 340, 160, 'Aisles A-D'), (420, 60, 340, 160, 'Aisles E-H'), (40, 260, 720, 160, 'Dock doors 1-6')], 'Warehouse floor', 'Floor'),
    ('Scanner onboarding flow', 'process', 'The steps from unboxing a scanner to a first successful scan.',
     [(40, 180, 160, 70, 'Unbox'), (240, 180, 160, 70, 'Enrol'), (440, 180, 160, 70, 'Assign to user'), (640, 180, 120, 70, 'Test scan')], 'Onboarding', 'Flow'),
]
for title, dtype, desc, boxes, a, b in DIAGRAMS:
    slug = title.lower().replace(' ', '-')
    if Diagram.objects.filter(organization=org, slug=slug).exists():
        continue
    dg = Diagram(organization=org, title=title, slug=slug, description=desc, diagram_type=dtype,
                 diagram_xml=XML.format(a=a, b=b), is_published=True, created_by=tech, last_modified_by=tech)
    dg.save()
    dg.png_export.save(f'{slug}_v1.png', ContentFile(preview(title, boxes)), save=True)
    tag = Tag.objects.filter(organization=org, name='Network').first()
    if tag and dtype == 'network':
        dg.tags.add(tag)

if not Diagram.objects.filter(organization=org, slug='branch-office-template').exists():
    Diagram.objects.create(organization=org, title='Branch office template', slug='branch-office-template',
                           description='Starting point for a small branch: firewall, one switch, two VLANs.',
                           diagram_type='network', is_template=True, is_published=True,
                           diagram_xml=XML.format(a='Firewall', b='Switch'), created_by=tech, last_modified_by=tech)

# ---- Office templates -----------------------------------------------------
from office import formats, storage, targets
from office.creation import blank_bytes
from office.models import OfficeFile

for name, desc, owner_org, fmt in (
        ('Change request form.docx', 'Standard change request, one page.', org, 'docx'),
        ('Monthly service report.xlsx', 'Hours and tickets per customer.', org, 'xlsx'),
        ('Onboarding welcome pack.pptx', 'Slides for a new customer kick-off.', None, 'pptx')):
    if OfficeFile.objects.filter(purpose='template', name=name).exists():
        continue
    f = OfficeFile.objects.create(purpose='template', organization=owner_org, name=name,
                                  description=desc, created_by=tech, mime=formats.mime_for(name))
    storage.store_initial(targets.OfficeFileTarget(f), blank_bytes(fmt), user=tech, source='upload')
print('kdoc seed done')
