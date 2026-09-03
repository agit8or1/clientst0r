"""
Spreadsheet import for Shop + VAN inventory (v3.17.523).

Two things are being added: a reader that makes .xlsx indistinguishable from
.csv to everything downstream, and two new import targets. The tests cover the
reader's type coercion (Excel hands back floats and datetimes where CSV hands
back strings) and the vehicle matching, since an unmatched van is the most
likely real-world failure.
"""
from __future__ import annotations

import io

from django.contrib.auth.models import User
from django.test import TestCase

from imports.services.tabular import TabularError, read_tabular


def _xlsx(rows):
    """Build an in-memory .xlsx from a list of row tuples."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = 'stock.xlsx'
    return buf


def _csv(text):
    buf = io.BytesIO(text.encode('utf-8'))
    buf.name = 'stock.csv'
    return buf


class TabularReaderTests(TestCase):
    def test_csv_and_xlsx_produce_identical_results(self):
        """The whole point of the shared reader."""
        csv_headers, csv_rows = read_tabular(
            _csv('name,quantity\nCAT6 Cable,12\nRJ45,500\n'), 'stock.csv')
        xl_headers, xl_rows = read_tabular(
            _xlsx([('name', 'quantity'), ('CAT6 Cable', 12), ('RJ45', 500)]), 'stock.xlsx')
        self.assertEqual(csv_headers, xl_headers)
        self.assertEqual(csv_rows, xl_rows)

    def test_excel_integers_do_not_arrive_as_floats(self):
        """Excel stores 12 as 12.0; '12.0' would fail an IntegerField parse."""
        _h, rows = read_tabular(_xlsx([('name', 'quantity'), ('Cable', 12)]), 'x.xlsx')
        self.assertEqual(rows[0]['quantity'], '12')

    def test_blank_rows_are_skipped(self):
        _h, rows = read_tabular(
            _xlsx([('name', 'qty'), ('A', 1), (None, None), ('B', 2)]), 'x.xlsx')
        self.assertEqual([r['name'] for r in rows], ['A', 'B'])

    def test_trailing_empty_headers_are_trimmed(self):
        headers, _rows = read_tabular(
            _xlsx([('name', 'qty', None, None), ('A', 1)]), 'x.xlsx')
        self.assertEqual(headers, ['name', 'qty'])

    def test_legacy_xls_is_refused_with_guidance(self):
        with self.assertRaises(TabularError) as ctx:
            read_tabular(io.BytesIO(b'\xd0\xcf\x11\xe0'), 'old.xls')
        self.assertIn('.xlsx', str(ctx.exception))

    def test_unsupported_extension_is_refused(self):
        with self.assertRaises(TabularError):
            read_tabular(io.BytesIO(b'x'), 'notes.pdf')

    def test_max_rows_limits_the_preview(self):
        _h, rows = read_tabular(
            _xlsx([('name',), ('A',), ('B',), ('C',)]), 'x.xlsx', max_rows=2)
        self.assertEqual(len(rows), 2)

    def test_sheet_with_no_header_row_is_refused(self):
        with self.assertRaises(TabularError):
            read_tabular(_xlsx([(None, None)]), 'x.xlsx')


class InventoryImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        from vehicles.models import ServiceVehicle
        cls.org = Organization.objects.create(name='InvCo', slug='inv-co')
        cls.user = User.objects.create_user('inv', 'i@x.com', 'pw', is_superuser=True)
        cls.van = ServiceVehicle.objects.create(
            name='Van 3', make='Ford', model='Transit', year=2022,
            license_plate='ABC-123', vin='1FTBW2CM5NKA00001')

    def _service(self, target, rows):
        from imports.models import ImportJob
        from imports.services.csv_importer import CSVImportService
        job = ImportJob.objects.create(
            source_type='csv', csv_target_model=target,
            target_organization=self.org, started_by=self.user)
        svc = CSVImportService(job)
        svc.org = self.org
        return svc, job

    def test_shop_inventory_row_creates_an_item(self):
        from vehicles.models import ShopInventoryItem
        svc, _job = self._service('shop_inventory', None)
        ok = svc._create_shop_inventory(
            {'name': 'CAT6 Cable', 'quantity': '12', 'unit': 'ft',
             'unit_cost': '$1,234.50', 'location_in_shop': 'Bin 4'}, 1)
        self.assertTrue(ok)
        item = ShopInventoryItem.objects.get(name='CAT6 Cable')
        self.assertEqual(item.quantity, 12)
        self.assertEqual(item.location_in_shop, 'Bin 4')
        self.assertEqual(str(item.unit_cost), '1234.50')

    def test_row_without_a_name_is_rejected(self):
        svc, _job = self._service('shop_inventory', None)
        self.assertFalse(svc._create_shop_inventory({'name': '  ', 'quantity': '5'}, 1))

    def test_junk_quantity_falls_back_instead_of_aborting(self):
        from vehicles.models import ShopInventoryItem
        svc, _job = self._service('shop_inventory', None)
        svc._create_shop_inventory({'name': 'Widget', 'quantity': 'twelve'}, 1)
        self.assertEqual(ShopInventoryItem.objects.get(name='Widget').quantity, 0)

    def test_vehicle_matched_by_name_plate_or_vin(self):
        svc, _job = self._service('vehicle_inventory', None)
        for value in ('Van 3', 'van 3', 'ABC-123', 'abc-123', '1FTBW2CM5NKA00001'):
            self.assertEqual(svc._resolve_vehicle(value), self.van, f'failed for {value!r}')
        self.assertIsNone(svc._resolve_vehicle('Nonexistent Van'))
        self.assertIsNone(svc._resolve_vehicle(''))

    def test_vehicle_inventory_row_creates_an_item(self):
        from vehicles.models import VehicleInventoryItem
        svc, _job = self._service('vehicle_inventory', None)
        ok = svc._create_vehicle_inventory(
            {'vehicle': 'ABC-123', 'name': 'RJ45', 'quantity': '500'}, 1)
        self.assertTrue(ok)
        self.assertEqual(VehicleInventoryItem.objects.get(name='RJ45').vehicle, self.van)

    def test_unmatched_vehicle_skips_the_row_and_logs_why(self):
        from vehicles.models import VehicleInventoryItem
        svc, job = self._service('vehicle_inventory', None)
        ok = svc._create_vehicle_inventory({'vehicle': 'Van 99', 'name': 'RJ45'}, 7)
        self.assertFalse(ok)
        self.assertEqual(VehicleInventoryItem.objects.count(), 0)
        job.refresh_from_db()
        self.assertIn('Van 99', job.import_log or '')

    def test_both_targets_are_registered(self):
        from imports.models import ImportJob
        from imports.services.csv_importer import TARGET_FIELDS
        keys = dict(ImportJob.CSV_TARGET_CHOICES)
        for target in ('shop_inventory', 'vehicle_inventory'):
            self.assertIn(target, keys)
            self.assertIn(target, TARGET_FIELDS)
