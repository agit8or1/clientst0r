"""
CSV import service - imports rows from a CSV file using field_mappings.
"""
import csv
import io
import logging

logger = logging.getLogger('imports')

# Target fields available per model, with human labels
ASSET_TARGET_FIELDS = {
    'name': 'Name (required)',
    'asset_type': 'Asset Type',
    'asset_tag': 'Asset Tag',
    'serial_number': 'Serial Number',
    'manufacturer': 'Manufacturer',
    'model': 'Model',
    'hostname': 'Hostname',
    'ip_address': 'IP Address',
    'mac_address': 'MAC Address',
    'os_version': 'OS / Firmware Version',
    'notes': 'Notes',
    '__skip__': '— Skip this column —',
}

PASSWORD_TARGET_FIELDS = {
    'name': 'Name (required)',
    'username': 'Username',
    'password': 'Password',
    'url': 'URL',
    'notes': 'Notes',
    '__skip__': '— Skip this column —',
}

CONTACT_TARGET_FIELDS = {
    'name': 'Full Name (required)',
    'first_name': 'First Name',
    'last_name': 'Last Name',
    'email': 'Email',
    'phone': 'Phone',
    'title': 'Title / Role',
    'notes': 'Notes',
    '__skip__': '— Skip this column —',
}

DOCUMENT_TARGET_FIELDS = {
    'title': 'Title (required)',
    'body': 'Body / Content',
    '__skip__': '— Skip this column —',
}

# v3.17.523 — Shop + VAN inventory. The two models are near-identical siblings
# (vehicles.ShopInventoryItem / vehicles.VehicleInventoryItem); the vehicle one
# additionally needs to resolve which van a row belongs to.
SHOP_INVENTORY_TARGET_FIELDS = {
    'name': 'Name (required)',
    'category': 'Category',
    'quantity': 'Quantity',
    'unit': 'Unit (ea, ft, box)',
    'min_quantity': 'Minimum Quantity',
    'reorder_quantity': 'Reorder Quantity',
    'unit_cost': 'Unit Cost',
    'location_in_shop': 'Location in Shop',
    'qr_code': 'QR Code',
    'reorder_link': 'Reorder Link',
    'description': 'Description',
    '__skip__': '— Skip this column —',
}

VEHICLE_INVENTORY_TARGET_FIELDS = {
    'vehicle': 'Vehicle (name, licence plate or VIN — required)',
    'name': 'Name (required)',
    'category': 'Category',
    'quantity': 'Quantity',
    'unit': 'Unit (ea, ft, box)',
    'min_quantity': 'Minimum Quantity',
    'reorder_quantity': 'Reorder Quantity',
    'unit_cost': 'Unit Cost',
    'location_in_vehicle': 'Location in Vehicle',
    'qr_code': 'QR Code',
    'reorder_link': 'Reorder Link',
    'description': 'Description',
    '__skip__': '— Skip this column —',
}

TARGET_FIELDS = {
    'asset': ASSET_TARGET_FIELDS,
    'password': PASSWORD_TARGET_FIELDS,
    'contact': CONTACT_TARGET_FIELDS,
    'document': DOCUMENT_TARGET_FIELDS,
    'shop_inventory': SHOP_INVENTORY_TARGET_FIELDS,
    'vehicle_inventory': VEHICLE_INVENTORY_TARGET_FIELDS,
}


def read_csv_preview(file_obj, max_rows=5, filename=''):
    """
    Read headers and up to max_rows of sample data from a CSV or .xlsx upload.
    Returns (headers, rows) where rows is a list of dicts.

    v3.17.523: delegates to `read_tabular` so spreadsheets and CSVs are
    indistinguishable to every caller downstream.
    """
    from .tabular import read_tabular
    return read_tabular(file_obj, filename=filename or getattr(file_obj, 'name', ''),
                        max_rows=max_rows)


def _norm(value):
    """Normalise a natural-key component: trimmed, case-folded, single spaces."""
    return ' '.join(str(value or '').split()).casefold()


def _norm_url(value):
    text = _norm(value)
    for prefix in ('https://', 'http://'):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.rstrip('/')


def _source_id(key):
    """ImportMapping.source_id holds 100 chars; long keys keep a readable
    prefix plus a hash of the whole key."""
    import hashlib
    if len(key) <= 100:
        return key
    return key[:59] + '~' + hashlib.sha1(key.encode('utf-8')).hexdigest()


class CSVImportService:
    """Import CSV rows into Assets, Passwords, Contacts, Documents or inventory.

    Duplicate detection uses a natural key per row (stored as the
    ImportMapping.source_id), so re-running the same file - or a later export
    of the same data - skips rows that were already imported:

    * password:          title + username + URL (case/space-insensitive,
                         scheme and trailing slash ignored on the URL)
    * asset:             serial number, else asset tag, else name + hostname
    * contact:           email, else full name + phone
    * document:          title
    * shop_inventory:    QR code, else name + location in shop
    * vehicle_inventory: vehicle + (QR code, else name + location in vehicle)

    Org-scoped types are de-duplicated within the job's target organization;
    inventory is not org-scoped, so its keys are global. A previously imported
    row whose record has since been deleted is imported again.

    Rows with the same key later in the same file are skipped as duplicates.
    Rows missing a required field (or whose vehicle cannot be matched) are
    counted as failed, with the reason in the log.
    """

    SOURCE_TYPES = {
        'asset': 'csv_asset',
        'password': 'csv_password',
        'contact': 'csv_contact',
        'document': 'csv_document',
        'shop_inventory': 'csv_shop_inventory',
        'vehicle_inventory': 'csv_vehicle_inventory',
    }
    # Inventory is not organization-scoped, so its duplicates are global.
    GLOBAL_TARGETS = ('shop_inventory', 'vehicle_inventory')

    def __init__(self, import_job):
        self.job = import_job
        self.org = import_job.target_organization
        self._seen_keys = set()

    # ------------------------------------------------------------------
    # Natural keys / duplicate detection
    # ------------------------------------------------------------------

    @staticmethod
    def _contact_name_parts(fields):
        first = (fields.get('first_name') or '').strip()
        last = (fields.get('last_name') or '').strip()
        name = (fields.get('name') or '').strip()
        if name and not (first or last):
            parts = name.split(None, 1)
            first = parts[0]
            last = parts[1] if len(parts) > 1 else ''
        return first, last

    def natural_key(self, target_model, fields):
        """Return (key, None), or (None, why-the-row-is-invalid)."""
        def g(f):
            return fields.get(f, '')

        if target_model == 'password':
            if not _norm(g('name')):
                return None, "missing required field 'name'"
            return 'pw:' + '|'.join([_norm(g('name')), _norm(g('username')),
                                     _norm_url(g('url'))]), None
        if target_model == 'asset':
            if not _norm(g('name')):
                return None, "missing required field 'name'"
            if _norm(g('serial_number')):
                return 'serial:' + _norm(g('serial_number')), None
            if _norm(g('asset_tag')):
                return 'tag:' + _norm(g('asset_tag')), None
            return 'name:' + _norm(g('name')) + '|' + _norm(g('hostname')), None
        if target_model == 'contact':
            first, last = self._contact_name_parts(fields)
            if not (first or last):
                return None, "missing required field 'name' (or first/last name)"
            if _norm(g('email')):
                return 'email:' + _norm(g('email')), None
            return 'name:' + _norm(f'{first} {last}') + '|' + _norm(g('phone')), None
        if target_model == 'document':
            if not _norm(g('title')):
                return None, "missing required field 'title'"
            return 'title:' + _norm(g('title')), None
        if target_model == 'shop_inventory':
            if not _norm(g('name')):
                return None, "missing required field 'name'"
            if _norm(g('qr_code')):
                return 'qr:' + _norm(g('qr_code')), None
            return 'name:' + _norm(g('name')) + '|' + _norm(g('location_in_shop')), None
        if target_model == 'vehicle_inventory':
            if not _norm(g('name')):
                return None, "missing required field 'name'"
            vehicle = self._resolve_vehicle(g('vehicle'))
            if vehicle is None:
                return None, (f"no vehicle matches {str(g('vehicle') or '').strip()!r} "
                              f"- row not imported")
            if _norm(g('qr_code')):
                return f'van:{vehicle.pk}|qr:' + _norm(g('qr_code')), None
            return (f'van:{vehicle.pk}|name:' + _norm(g('name')) + '|'
                    + _norm(g('location_in_vehicle'))), None
        return None, f"unknown target type {target_model!r}"

    def _already_imported(self, target_model, source_id):
        """True if a row with this key was imported before and still exists."""
        from django.db.models import Q
        from imports.models import ImportJob, ImportMapping

        source_type = self.SOURCE_TYPES[target_model]
        cond = Q(import_job=self.job)
        if getattr(self.job, 'skip_duplicates', True):
            cond |= Q(import_job__status__in=ImportJob.DEDUPE_STATUSES,
                      import_job__dry_run=False)
        qs = ImportMapping.objects.filter(
            cond, source_type=source_type, source_id=source_id,
            import_job__source_type='csv',
        )
        if target_model not in self.GLOBAL_TARGETS:
            qs = qs.filter(target_organization=self.org)
        return any(m.target_exists() for m in qs.order_by('-created_at')[:5])

    def _map(self, target_model, fields, row_num, obj):
        from imports.models import ImportMapping
        key, _reason = self.natural_key(target_model, fields)
        source_id = _source_id(key) if key else f'row:{row_num}'
        ImportMapping.objects.create(
            import_job=self.job,
            source_type=self.SOURCE_TYPES[target_model],
            source_id=source_id,
            target_model=obj.__class__.__name__,
            target_id=obj.pk,
            target_organization=self.org,
            target_updated_at=getattr(obj, 'updated_at', None),
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run_import(self):
        """Execute the CSV import. Returns stats dict."""
        from django.db import transaction

        job = self.job
        mappings = job.field_mappings or {}
        target_model = job.csv_target_model

        if not job.source_file:
            raise ValueError("No CSV file attached to this import job.")
        if not target_model:
            raise ValueError("No target model selected for CSV import.")
        if target_model not in self.SOURCE_TYPES:
            raise ValueError(f"Unknown CSV target type: {target_model}")
        if not self.org:
            raise ValueError("Target organization is required for CSV imports.")

        job.mark_running()
        job.reset_counters()

        job.source_file.seek(0)
        from .tabular import read_tabular, TabularError
        try:
            _headers, rows = read_tabular(
                job.source_file, filename=getattr(job.source_file, 'name', ''))
        except TabularError as exc:
            job.add_log(f'Import aborted: {exc}')
            job.mark_failed(str(exc))
            raise

        job.add_log(f"Starting CSV import: {len(rows)} rows → {target_model}"
                    + (" (DRY RUN - nothing will be saved)" if job.dry_run else ""))

        imported = skipped = failed = 0
        self._seen_keys = set()

        for i, row in enumerate(rows, 1):
            try:
                # Apply field mappings: build target_fields dict from source columns
                target_fields = {}
                for src_col, tgt_field in mappings.items():
                    if tgt_field and tgt_field != '__skip__':
                        value = (row.get(src_col) or '').strip()
                        if value:
                            target_fields[tgt_field] = value

                if not target_fields:
                    # Nothing mapped has a value: a blank row, not an error.
                    skipped += 1
                    continue

                key, reason = self.natural_key(target_model, target_fields)
                if key is None:
                    job.add_log(f"Row {i}: not imported - {reason}")
                    failed += 1
                    continue
                source_id = _source_id(key)

                if source_id in self._seen_keys:
                    job.add_log(f"Row {i}: skipped - duplicate of an earlier row in this file")
                    skipped += 1
                    continue
                self._seen_keys.add(source_id)

                if self._already_imported(target_model, source_id):
                    skipped += 1
                    continue

                if job.dry_run:
                    imported += 1
                    continue

                # Record + mapping in one savepoint: never an unmapped record.
                with transaction.atomic():
                    ok = self._create_record(target_model, target_fields, i)
                if ok:
                    imported += 1
                else:
                    failed += 1

            except Exception as e:
                logger.warning(f"CSV row {i} failed: {e}")
                job.add_log(f"Row {i}: ERROR — {e}")
                failed += 1

        job.items_imported = imported
        job.items_skipped = skipped
        job.items_failed = failed
        status = job.finish()
        job.add_log(f"Done ({job.get_status_display()}): {imported} imported, "
                    f"{skipped} skipped, {failed} failed (of {len(rows)} rows)")
        return {'imported': imported, 'skipped': skipped, 'failed': failed, 'status': status}

    def _create_record(self, target_model, fields, row_num):
        if target_model == 'asset':
            return self._create_asset(fields, row_num)
        elif target_model == 'password':
            return self._create_password(fields, row_num)
        elif target_model == 'contact':
            return self._create_contact(fields, row_num)
        elif target_model == 'shop_inventory':
            return self._create_shop_inventory(fields, row_num)
        elif target_model == 'vehicle_inventory':
            return self._create_vehicle_inventory(fields, row_num)
        elif target_model == 'document':
            return self._create_document(fields, row_num)
        return False

    def _create_asset(self, fields, row_num):
        from assets.models import Asset
        from django.core.validators import validate_ipv46_address

        name = fields.get('name', '').strip()
        if not name:
            return False

        asset_fields = {
            'organization': self.org,
            'name': name,
            'asset_type': fields.get('asset_type', 'other'),
            'asset_tag': fields.get('asset_tag', ''),
            'serial_number': fields.get('serial_number', ''),
            'manufacturer': fields.get('manufacturer', ''),
            'model': fields.get('model', ''),
            'hostname': fields.get('hostname', ''),
            'mac_address': fields.get('mac_address', ''),
            'os_version': fields.get('os_version', ''),
            'notes': fields.get('notes', ''),
        }

        # Validate IP address
        raw_ip = fields.get('ip_address', '')
        if raw_ip:
            try:
                validate_ipv46_address(raw_ip)
                asset_fields['ip_address'] = raw_ip
            except Exception:
                pass

        # Validate asset_type against known choices
        from assets.custom_types import is_valid_asset_type
        if not is_valid_asset_type(asset_fields['asset_type']):
            asset_fields['asset_type'] = 'other'

        asset = Asset.objects.create(**{k: v for k, v in asset_fields.items() if v or k in ('organization', 'name', 'asset_type')})
        self._map('asset', fields, row_num, asset)
        return True

    def _create_password(self, fields, row_num):
        """Vault entry: ``title`` + ``encrypted_password`` (via
        Password.set_password, org-bound encryption) - plaintext is never
        stored."""
        from vault.models import Password

        name = fields.get('name', '').strip()
        if not name:
            return False

        pwd = Password(
            organization=self.org,
            title=name,
            username=fields.get('username', ''),
            url=fields.get('url', ''),
            notes=fields.get('notes', ''),
            created_by=self.job.started_by,
        )
        plaintext = fields.get('password', '')
        if plaintext:
            pwd.set_password(plaintext)
        pwd.save()
        self._map('password', fields, row_num, pwd)
        return True

    def _create_contact(self, fields, row_num):
        from assets.models import Contact

        # Contact has first_name / last_name; a single "name" column is split
        # on the first space.
        first, last = self._contact_name_parts(fields)
        if not (first or last):
            return False

        contact = Contact.objects.create(
            organization=self.org,
            first_name=first[:100],
            last_name=last[:100],
            email=fields.get('email', ''),
            phone=fields.get('phone', ''),
            title=fields.get('title', ''),
            notes=fields.get('notes', ''),
        )
        self._map('contact', fields, row_num, contact)
        return True

    def _create_document(self, fields, row_num):
        from docs.models import Document
        from .base import BaseImportService

        title = fields.get('title', '').strip()
        if not title:
            return False

        doc = Document.objects.create(
            organization=self.org,
            title=title,
            slug=BaseImportService.unique_document_slug(self.org, title),
            body=fields.get('body', ''),
            content_type='html',
            created_by=self.job.started_by,
        )
        self._map('document', fields, row_num, doc)
        return True

    # ------------------------------------------------------------------
    # Inventory (v3.17.523) — Shop + VAN stock from a spreadsheet
    # ------------------------------------------------------------------

    @staticmethod
    def _to_int(value, default=0):
        """Spreadsheets hand us '12', '12.0', '' or junk. None of that should
        abort a whole import — fall back to the field default."""
        text = str(value or '').strip()
        if not text:
            return default
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_decimal(value, default=None):
        from decimal import Decimal, InvalidOperation
        text = str(value or '').strip().replace('$', '').replace(',', '')
        if not text:
            return default
        try:
            return Decimal(text)
        except (InvalidOperation, TypeError, ValueError):
            return default

    def _inventory_common(self, fields):
        """Fields shared by both inventory models."""
        data = {
            'name': fields.get('name', '').strip(),
            'category': fields.get('category', '').strip(),
            'quantity': self._to_int(fields.get('quantity'), 0),
            'unit': fields.get('unit', '').strip(),
            'min_quantity': self._to_int(fields.get('min_quantity'), 0),
            'reorder_quantity': self._to_int(fields.get('reorder_quantity'), 0),
            'description': fields.get('description', '').strip(),
            'qr_code': fields.get('qr_code', '').strip(),
            'reorder_link': fields.get('reorder_link', '').strip(),
        }
        cost = self._to_decimal(fields.get('unit_cost'))
        if cost is not None:
            data['unit_cost'] = cost
        return data

    def _create_shop_inventory(self, fields, row_num):
        from vehicles.models import ShopInventoryItem

        data = self._inventory_common(fields)
        if not data['name']:
            return False
        data['location_in_shop'] = fields.get('location_in_shop', '').strip()

        # Note: shop/vehicle inventory and the fleet are deliberately NOT
        # org-scoped in this codebase — there is no `organization` field to set.
        item = ShopInventoryItem.objects.create(**data)
        self._map('shop_inventory', fields, row_num, item)
        return True

    def _resolve_vehicle(self, value):
        """Match a spreadsheet cell to a ServiceVehicle.

        Accepts whatever a dispatcher is likely to type — unit number, name, or
        licence plate — because requiring a database id in a spreadsheet is how
        an import feature goes unused.
        """
        from django.db.models import Q
        from vehicles.models import ServiceVehicle

        text = str(value or '').strip()
        if not text:
            return None
        # The fleet is not org-scoped, so there is no organization filter here.
        # Matched on the three things actually printed on a van.
        lookup = (Q(name__iexact=text) | Q(license_plate__iexact=text)
                  | Q(vin__iexact=text))
        return ServiceVehicle.objects.filter(lookup).first()

    def _create_vehicle_inventory(self, fields, row_num):
        from vehicles.models import VehicleInventoryItem

        data = self._inventory_common(fields)
        if not data['name']:
            return False

        vehicle = self._resolve_vehicle(fields.get('vehicle'))
        if vehicle is None:
            # Named explicitly rather than silently skipped: an unmatched van is
            # a data problem the operator can fix and re-run.
            self.job.add_log(
                f"Row {row_num}: no vehicle matches "
                f"{str(fields.get('vehicle') or '').strip()!r} — row not imported")
            return False

        data['location_in_vehicle'] = fields.get('location_in_vehicle', '').strip()
        item = VehicleInventoryItem.objects.create(vehicle=vehicle, **data)
        self._map('vehicle_inventory', fields, row_num, item)
        return True
