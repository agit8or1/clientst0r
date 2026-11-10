"""Sample data group: operations (v3.17.655). See core/demo_samples/__init__.py.

Inventory, dispatch tasks, resourcing, vehicles, sites/WANs, field ops,
scheduled reports and one extra process. Kept inert on purpose: task alerts,
WAN monitoring and scheduled reports are switched off so no timer acts on
them; the wallboard is created disabled; resourcing rows go to the demo
technicians only (never the real superuser), and vehicle records hang off
demo-plated vehicles created here, so a real fleet is never touched.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.utils.text import slugify


# --- inventory -----------------------------------------------------------

CATEGORIES = [
    ('Laptops & Desktops', '#0d6efd', 'Imaged spares and new-hire stock.'),
    ('Docking Stations', '#6610f2', 'USB-C and Thunderbolt docks.'),
    ('Cabling', '#198754', 'Patch cables, bulk cable and connectors.'),
    ('Networking', '#fd7e14', 'Optics, small switches and access points.'),
    ('Printer Supplies', '#dc3545', 'Toner and drums for managed printers.'),
    ('Power', '#ffc107', 'Chargers and UPS batteries.'),
    ('Test Equipment', '#20c997', 'Testers, tools and site kit.'),
]

STOCK_LOCATIONS = [
    ('Main Stockroom', 'Back office, shelving A-D.'),
    ('Bench / Staging', 'Imaging bench; devices waiting for deployment.'),
    ('Cage B - Cable Wall', 'Cable hooks and connector bins.'),
]

# name, sku, mpn, type, category, location, qty, unit, min, reorder, unit_cost, shipped_out
ITEMS = [
    ('Dell Latitude 5450 14" (i5 / 16GB / 512GB)', 'LAP-DL5450', 'LAT5450-I5', 'hardware',
     'Laptops & Desktops', 'Bench / Staging', 4, 'ea', 2, 4, '1189.00', 2),
    ('Lenovo ThinkPad T14 Gen 5 (Ryzen 7 / 32GB)', 'LAP-T14G5', '21MC0012US', 'hardware',
     'Laptops & Desktops', 'Bench / Staging', 1, 'ea', 2, 3, '1449.00', 2),
    ('Dell WD19S USB-C Dock (130W)', 'DOCK-WD19S', 'WD19S130W', 'hardware',
     'Docking Stations', 'Main Stockroom', 6, 'ea', 3, 5, '189.99', 3),
    ('Lenovo ThinkPad Universal USB-C Dock', 'DOCK-LUC', '40AY0090US', 'hardware',
     'Docking Stations', 'Main Stockroom', 1, 'ea', 2, 4, '214.00', 2),
    ('Cat6 Patch Cable 3 ft (blue)', 'CBL-C6-03B', 'C6-UTP-03-BL', 'cable',
     'Cabling', 'Cage B - Cable Wall', 120, 'ea', 50, 100, '2.10', 40),
    ('Cat6 Patch Cable 7 ft (blue)', 'CBL-C6-07B', 'C6-UTP-07-BL', 'cable',
     'Cabling', 'Cage B - Cable Wall', 64, 'ea', 40, 100, '3.25', 24),
    ('Cat6 Bulk Cable 1000 ft (CMR, blue)', 'CBL-C6-1000', 'C6-CMR-1000-BL', 'cable',
     'Cabling', 'Cage B - Cable Wall', 2, 'box', 1, 2, '189.00', 1),
    ('RJ45 Cat6 Pass-Through Connectors (100 pk)', 'CON-RJ45-PT', 'RJ45-C6-PT100', 'consumable',
     'Cabling', 'Cage B - Cable Wall', 3, 'pack', 2, 4, '38.50', 2),
    ('10GBASE-SR SFP+ Multimode Module', 'SFP-10G-SR', 'UACC-OM-MM-10G-D', 'spare_part',
     'Networking', 'Main Stockroom', 8, 'ea', 4, 8, '19.00', 4),
    ('1000BASE-T Copper SFP Module', 'SFP-1G-T', 'UACC-OM-RJ45-1G', 'spare_part',
     'Networking', 'Main Stockroom', 3, 'ea', 4, 6, '17.00', 3),
    ('HP 58A Black Toner (CF258A)', 'TON-HP58A', 'CF258A', 'consumable',
     'Printer Supplies', 'Main Stockroom', 2, 'ea', 3, 6, '112.00', 4),
    ('Brother TN-760 High-Yield Toner', 'TON-TN760', 'TN760', 'consumable',
     'Printer Supplies', 'Main Stockroom', 5, 'ea', 2, 4, '64.99', 3),
    ('USB-C 65W Laptop Charger', 'PWR-USBC65', 'PA-1650-USBC', 'hardware',
     'Power', 'Main Stockroom', 7, 'ea', 4, 6, '29.00', 3),
    ('APC RBC7 Replacement UPS Battery', 'PWR-RBC7', 'RBC7', 'spare_part',
     'Power', 'Main Stockroom', 2, 'ea', 2, 2, '219.00', 2),
]

# code, name, category, home location, condition, van (index into VEHICLES or None), notes
TOOLS = [
    ('TL-001', 'Fluke Networks LinkIQ Cable + Network Tester', 'Test Equipment', 'Main Stockroom',
     'good', 0, 'Checked out to {tech} for the {customer} cabling refresh; back Friday.'),
    ('TL-002', 'Klein Tools Crimper + Punch-Down Kit', 'Test Equipment', None, 'good', 0, ''),
    ('TL-003', '8 ft Fiberglass Step Ladder', 'Test Equipment', None, 'good', 1, ''),
    ('TL-004', 'Fluke Networks Fiber OneShot PRO', 'Test Equipment', 'Main Stockroom',
     'needs_service', None, 'Reports intermittent fault on the SC adapter; RMA requested.'),
    ('TL-005', 'Brady BMP21-PLUS Label Printer', 'Test Equipment', 'Bench / Staging', 'good', None, ''),
    ('TL-006', 'Tone Generator + Probe Kit', 'Test Equipment', 'Main Stockroom', 'good', None, ''),
]

# --- dispatch tasks --------------------------------------------------------

# customer index, title, priority, due offset (days), recurrence, status, require_all,
# assignee tech indexes, description, comments [(tech index, body)]
TASKS = [
    (0, 'Quarterly firewall firmware review', 'high', 5, 'quarterly', 'pending', True, [0, 1],
     'Check FortiGate firmware against the vendor advisory list, schedule the upgrade window '
     'with the client and confirm config backup before upgrading.',
     [(1, 'Advisory list pulled; 7.4.5 fixes the SSL-VPN CVE. Proposing Thursday 7pm.')]),
    (0, 'Monthly backup restore test', 'normal', 2, 'monthly', 'in_progress', False, [2],
     'Restore one file share folder and one VM from last night\'s backup to the sandbox, '
     'record restore times in the backup runbook.',
     [(2, 'File-share restore done (4m 12s). VM restore running now.')]),
    (1, 'Replace UPS batteries in server closet', 'urgent', -3, 'none', 'pending', False, [1],
     'Smart-UPS 1500 is reporting "replace battery". Two RBC7 packs are in the stockroom.',
     [(1, 'Client asked to move this to after their payroll run - rescheduling.')]),
    (1, 'Onboard new hire laptop (Accounting)', 'normal', -4, 'none', 'completed', False, [0],
     'Image a Latitude 5450, enrol in Intune, set up the WD19S dock and walk the user through MFA.',
     [(0, 'Delivered and signed for. User enrolled in MFA.')]),
    (2, 'Weekly patch compliance check', 'low', 1, 'weekly', 'pending', False, [2],
     'Review the RMM patch report, chase any device more than 14 days behind.',
     []),
    (2, 'Annual network documentation walk-through', 'normal', 12, 'none', 'pending', True, [0, 2],
     'Walk the site with the office manager, verify rack labels and update the network diagram.',
     [(0, 'Booked for the 2nd week of next month; bring the label printer (TL-005).')]),
    (3, 'Wi-Fi survey - new conference wing', 'high', 7, 'none', 'pending', False, [1],
     'Predictive survey from floor plans, then on-site validation with the client\'s facilities lead.',
     []),
    (4, 'Renew SSL certificate on client portal', 'high', 9, 'none', 'pending', False, [0],
     'Certificate expires in three weeks. Renew via the registrar and update the reverse proxy.',
     []),
]

# --- resourcing ------------------------------------------------------------

# Per demo technician (by index).
SKILLS = [
    [('Microsoft 365 / Entra ID', 'expert', 8), ('Windows Server', 'advanced', 9),
     ('Intune / Autopilot', 'advanced', 4), ('Structured cabling', 'intermediate', 3)],
    [('Fortinet FortiGate', 'expert', 6), ('Cisco switching', 'advanced', 7),
     ('Wireless surveys', 'advanced', 5), ('Python scripting', 'intermediate', 2)],
    [('Veeam Backup & Replication', 'expert', 6), ('VMware vSphere', 'advanced', 6),
     ('Linux administration', 'intermediate', 4), ('PowerShell', 'advanced', 5)],
]

# name, issuer, credential id, issued (days ago), expires (days from now or None)
CERTS = [
    [('Microsoft 365 Certified: Modern Desktop Administrator Associate', 'Microsoft', 'MD-102-48211', 400, 330),
     ('CompTIA Security+', 'CompTIA', 'COMP001021884421', 900, 40)],
    [('Fortinet NSE 4 - FortiOS Administrator', 'Fortinet', 'NSE4-77310', 500, 230),
     ('Cisco CCNA', 'Cisco', 'CSCO14120771', 1200, -20)],
    [('Veeam Certified Engineer (VMCE)', 'Veeam', 'VMCE-2025-30418', 200, 530),
     ('VMware Certified Professional - Data Center Virtualization', 'VMware', 'VCP-DCV-55102', 700, None)],
]

# weekday windows per tech index: (weekdays, start, end, notes)
HOURS = [
    [(range(0, 5), time(8, 0), time(17, 0), '')],
    [(range(0, 5), time(7, 0), time(15, 30), 'Early shift - first on site'),
     ([5], time(9, 0), time(13, 0), 'Saturday on-call rotation')],
    [(range(0, 4), time(9, 0), time(18, 0), ''), ([4], time(9, 0), time(13, 0), 'Half day Friday')],
]

# rate history per tech index: (effective_from, rate)
COST_RATES = [
    [(date(2025, 1, 1), '52.00'), (date(2026, 1, 1), '56.50')],
    [(date(2025, 1, 1), '48.00'), (date(2026, 4, 1), '51.75')],
    [(date(2025, 6, 1), '45.00'), (date(2026, 6, 1), '47.25')],
]

# tech index, type, start offset (days), length (days), half day, status, notes
LEAVE = [
    (0, 'vacation', 18, 5, False, 'approved', 'Family trip.'),
    (1, 'personal', 9, 1, True, 'pending', 'Morning appointment, back by 1pm.'),
    (2, 'sick', -6, 2, False, 'approved', 'Out sick - covered by Jordan.'),
    (1, 'vacation', 40, 7, False, 'pending', 'Holiday break, flying out of state.'),
    (2, 'vacation', -30, 3, False, 'denied', 'Long weekend request (clashed with a client cut-over).'),
]

# --- vehicles --------------------------------------------------------------

VEHICLES = [
    dict(name='Service Van 1', vehicle_type='cargo_van', make='Ford', model='Transit 250', year=2023,
         color='White', license_plate='DEMO-101', current_mileage=18420, diagram_type='cargo_van',
         insurance_provider='Fleet Mutual (demo)', insurance_policy_number='FM-DEMO-55120',
         purchase_price=Decimal('48950.00')),
    dict(name='Pickup 2', vehicle_type='pickup', make='Ford', model='F-150 XL', year=2021,
         color='Silver', license_plate='DEMO-102', current_mileage=46210, diagram_type='pickup_truck',
         insurance_provider='Fleet Mutual (demo)', insurance_policy_number='FM-DEMO-55121',
         purchase_price=Decimal('38400.00')),
]

# vehicle index, mileage, days ago, gallons, price, station
FUEL = [
    (0, 17610, 34, '22.40', '3.389', 'Shell - Route 9'),
    (0, 17980, 20, '21.10', '3.299', 'Costco Fuel'),
    (0, 18420, 4, '24.75', '3.349', 'Shell - Route 9'),
    (1, 45390, 28, '19.80', '3.419', 'BP - Main St'),
    (1, 45820, 14, '18.60', '3.359', 'Costco Fuel'),
    (1, 46210, 2, '17.95', '3.389', 'BP - Main St'),
]

# vehicle index, type, description, days ago, mileage, labor, parts, performed_by, next miles, next days
MAINTENANCE = [
    (0, 'oil_change', 'Full synthetic oil + filter, multipoint inspection', 45, 17200, '35.00', '62.40',
     'Valley Ford Fleet Service', 22200, 135),
    (0, 'tire_rotation', 'Rotate and balance, tread 7/32 all round', 45, 17200, '40.00', None,
     'Valley Ford Fleet Service', 24700, None),
    (1, 'brake_service', 'Front pads and rotors replaced', 70, 44900, '180.00', '264.10',
     'Main Street Auto Care', None, None),
    (1, 'inspection', 'Annual state safety inspection - passed', 120, 43800, '35.00', None,
     'Main Street Auto Care', None, 245),
]

PROVIDERS = [
    (0, 'Valley Ford Fleet Service', 'Dana Ortiz', '(555) 014-2200', 'fleet@valleyford.example.com',
     'Oil change, tires, warranty work', True),
    (1, 'Main Street Auto Care', 'Sam Patel', '(555) 014-3310', 'service@mainstreetauto.example.com',
     'Brakes, inspections, general repair', True),
    (1, 'QuickLube Express', '', '(555) 014-9001', '', 'Oil change only', False),
]

# vehicle index, name, type, miles, days, last mileage, last service (days ago)
SERVICE_SCHEDULES = [
    (0, 'Oil change', 'oil_change', 5000, 180, 17200, 45),
    (0, 'Tire rotation', 'tire_rotation', 7500, None, 17200, 45),
    (1, 'Oil change', 'oil_change', 5000, 180, 41800, 160),
    (1, 'Annual inspection', 'inspection', None, 365, None, 120),
]

# --- sites / WAN -----------------------------------------------------------

# Fictional addresses; coordinates roughly match the cities.
SITES = [
    ('Headquarters', 'office', '1200 Commerce Way', 'Springfield', 'IL', '62701', '39.7990', '-89.6440'),
    ('Main Office', 'office', '455 Harbor Blvd', 'Tacoma', 'WA', '98402', '47.2529', '-122.4443'),
    ('Corporate Office', 'office', '88 Innovation Dr', 'Austin', 'TX', '78701', '30.2672', '-97.7431'),
    ('Head Office', 'office', '19 Market Square', 'Portland', 'ME', '04101', '43.6591', '-70.2568'),
    ('Main Campus', 'office', '700 Lakeview Pkwy', 'Madison', 'WI', '53703', '43.0731', '-89.4012'),
]

# name, type, isp, download, upload, monthly cost, primary. Addresses are RFC 5737
# documentation ranges and monitoring stays off, so check_wans never pings them.
WANS = [
    ('Primary Internet', 'fiber', 'Lumen Fiber', '1000', '1000', '649.00', True),
    ('Backup Broadband', 'cable', 'Spectrum Business', '600', '35', '189.99', False),
]

# --- reports ---------------------------------------------------------------

SAVED_QUERIES = [
    ('Critical (P1) tickets', 'psa.Ticket', [{'field': 'priority__code', 'op': 'equals', 'value': 'P1'}],
     'Every P1 ticket, newest first.', '-created_at'),
    ('Warranties ending before 2027', 'assets.Asset',
     [{'field': 'warranty_expiry', 'op': 'lt', 'value': '2027-01-01'}],
     'Hardware to quote for renewal or replacement.', 'warranty_expiry'),
]

# --- processes -------------------------------------------------------------

PROCESS = ('Workstation Replacement', 'deployment',
           'Swap an end-of-life workstation for a new imaged device with no data loss.', [
               ('Confirm hardware and user', 'Check the replacement is imaged and assigned to the right user.', False, 10),
               ('Back up user profile', 'Run the profile backup and confirm OneDrive sync is green.', True, 20),
               ('Swap device on site', 'Install the new device, connect dock and peripherals.', False, 30),
               ('Verify apps and printers', 'Walk through line-of-business apps and test printing with the user.', True, 15),
               ('Retire old device', 'Wipe, tag for recycling and update the asset record.', False, 10),
           ])


# --- helpers ---------------------------------------------------------------

def _ensure(ctx, model, lookup, /, **fields):
    """The first row matching `lookup`, or a new one with `fields`."""
    obj = model.objects.filter(**lookup).first()
    if obj is not None:
        return obj, False
    obj = model.objects.create(**lookup, **fields)
    ctx.created(model._meta.label)
    return obj, True


def _demo_techs(ctx):
    """Demo technicians only - the superuser is a real account."""
    admin_pk = getattr(ctx.admin, 'pk', None)
    return [u for u in ctx.techs if u.pk != admin_pk] or list(ctx.techs)


def _tech(ctx, i):
    techs = _demo_techs(ctx)
    return techs[i % len(techs)]


def _stock_org(ctx):
    return ctx.msp or ctx.customer(0)


def _has_location_webhook(org):
    """Saving a Location fires location.created webhooks; skip orgs that
    subscribe so demo seeding never posts to a real endpoint."""
    from core.models import Webhook
    return any('location.created' in (events or []) for events in
               Webhook.objects.filter(organization=org, is_active=True).values_list('events', flat=True))


# --- groups ----------------------------------------------------------------

def _seed_inventory(ctx, vans):
    from inventory.models import InventoryCategory, InventoryItem, InventoryLocation, InventoryTransaction, Tool
    org = _stock_org(ctx)
    cats = {name: _ensure(ctx, InventoryCategory, {'organization': org, 'name': name},
                          color=color, description=desc)[0]
            for name, color, desc in CATEGORIES}
    locs = {name: _ensure(ctx, InventoryLocation, {'organization': org, 'name': name}, description=desc)[0]
            for name, desc in STOCK_LOCATIONS}

    for n, (name, sku, mpn, kind, cat, loc, qty, unit, min_q, reorder, cost, out) in enumerate(ITEMS):
        item, made = _ensure(ctx, InventoryItem, {'organization': org, 'name': name},
                             sku=sku, manufacturer_part_number=mpn, item_type=kind,
                             category=cats[cat], storage_location=locs[loc], quantity=qty,
                             unit=unit, min_quantity=min_q, reorder_quantity=reorder,
                             unit_cost=Decimal(cost))
        if not made:
            continue
        # History that ends at the current quantity: one delivery, then use.
        steps = [('stock_in', qty + out, f'PO-DEMO-{3100 + n}', 'Received from distributor.', 21),
                 ('stock_out', -out, f'TKT-DEMO-{5400 + n}', 'Issued to a client job.', 6)]
        after = 0
        for kind_, change, ref, note, days in steps:
            after += change
            txn = InventoryTransaction.objects.create(
                item=item, transaction_type=kind_, quantity_change=change, quantity_after=after,
                notes=note, reference=ref, performed_by=_tech(ctx, n))
            InventoryTransaction.objects.filter(pk=txn.pk).update(created_at=ctx.now - timedelta(days=days, hours=n))
            ctx.created('inventory.InventoryTransaction')

    for code, name, cat, home, cond, van, notes in TOOLS:
        _ensure(ctx, Tool, {'organization': org, 'code': code}, name=name, category=cats[cat],
                home_location=locs.get(home), condition=cond,
                assigned_vehicle=vans[van] if van is not None and van < len(vans) else None,
                notes=notes.format(tech=_tech(ctx, 0).get_full_name(), customer=ctx.customer(0).name))


def _seed_scheduling(ctx):
    from scheduling.models import ScheduledTask, SchedulerWallboard, TaskAssignment, TaskComment
    for n, (ci, title, prio, due, recur, status, all_sign, who, desc, comments) in enumerate(TASKS):
        org = ctx.customer(ci)
        due_at = (ctx.now + timedelta(days=due)).replace(hour=15, minute=0, second=0, microsecond=0)
        done = status == 'completed'
        # Alerts off: check_scheduled_task_alerts would otherwise mail assignees.
        task, made = _ensure(ctx, ScheduledTask, {'organization': org, 'title': title},
                             description=desc, priority=prio, due_date=due_at, recurrence=recur,
                             status=status, require_all_signoffs=all_sign, created_by=ctx.admin,
                             completed_at=due_at if done else None,
                             completed_by=_tech(ctx, who[0]) if done else None,
                             alert_email=False, alert_sms=False)
        if not made:
            continue
        for ti in who:
            user = _tech(ctx, ti)
            if not TaskAssignment.objects.filter(task=task, user=user).exists():
                TaskAssignment.objects.create(task=task, user=user, acknowledged=done,
                                              acknowledged_at=due_at if done else None)
                ctx.created('scheduling.TaskAssignment')
        for ti, body in comments:
            TaskComment.objects.create(task=task, author=_tech(ctx, ti), body=body)
            ctx.created('scheduling.TaskComment')
    if not SchedulerWallboard.objects.exists():
        # Disabled: the public URL 404s until someone turns it on.
        SchedulerWallboard.objects.create(is_enabled=False, title='Dispatch board', days_ahead=2,
                                          show_client_names=False, created_by=ctx.admin)
        ctx.created('scheduling.SchedulerWallboard')


def _seed_resourcing(ctx):
    from resourcing.models import Holiday, LeaveRequest, TechCostRate, UserCertification, UserSkill, WorkingHours
    today = ctx.now.date()
    for i, user in enumerate(_demo_techs(ctx)):
        spec = i % len(SKILLS)
        for name, prof, years in SKILLS[spec]:
            _ensure(ctx, UserSkill, {'user': user, 'name': name}, proficiency=prof, years_experience=years)
        for name, issuer, cred, issued, expires in CERTS[spec]:
            _ensure(ctx, UserCertification, {'user': user, 'name': name}, issuer=issuer, credential_id=cred,
                    issued_at=today - timedelta(days=issued),
                    expires_at=today + timedelta(days=expires) if expires is not None else None)
        if not WorkingHours.objects.filter(user=user).exists():
            for days, start, end, notes in HOURS[spec]:
                for wd in days:
                    WorkingHours.objects.create(user=user, weekday=wd, start_time=start, end_time=end, notes=notes)
                    ctx.created('resourcing.WorkingHours')
        for effective, rate in COST_RATES[spec]:
            _ensure(ctx, TechCostRate, {'user': user, 'effective_from': effective},
                    rate_per_hour=Decimal(rate), notes='Loaded cost (salary + benefits + overhead).')

    for ti, kind, start, length, half, status, notes in LEAVE:
        user = _tech(ctx, ti)
        begin = today + timedelta(days=start)
        decided = status in ('approved', 'denied')
        _ensure(ctx, LeaveRequest, {'user': user, 'leave_type': kind, 'notes': notes},
                start_date=begin, end_date=begin + timedelta(days=length - 1), is_half_day=half,
                status=status, approver=ctx.admin if decided else None,
                decided_at=ctx.now - timedelta(days=max(1, -start)) if decided else None,
                decision_note='Approved - coverage arranged.' if status == 'approved' else
                ('Denied - project cut-over that week.' if status == 'denied' else ''))

    # Org-scoped to the MSP (a NULL organization would apply to every tenant).
    org = _stock_org(ctx)
    year = today.year
    thanksgiving = date(year, 11, 1)
    thanksgiving += timedelta(days=(3 - thanksgiving.weekday()) % 7 + 21)
    for name, day, yearly in [
        ('Thanksgiving Day', thanksgiving, False),
        ('Day after Thanksgiving', thanksgiving + timedelta(days=1), False),
        ('Christmas Eve (half day)', date(year, 12, 24), True),
        ('Christmas Day', date(year, 12, 25), True),
        ("New Year's Day", date(year, 1, 1), True),
        ('Independence Day', date(year, 7, 4), True),
        ('Company offsite', today + timedelta(days=60), False),
    ]:
        _ensure(ctx, Holiday, {'organization': org, 'name': name}, date=day, is_recurring_yearly=yearly)


def _seed_vehicles(ctx):
    from vehicles.models import (ServiceVehicle, VehicleAssignment, VehicleFuelLog, VehicleMaintenanceRecord,
                                 VehicleServiceProvider, VehicleServiceSchedule)
    today = ctx.now.date()
    vans = []
    for i, spec in enumerate(VEHICLES):
        van, _ = _ensure(ctx, ServiceVehicle, {'license_plate': spec['license_plate']},
                         **{k: v for k, v in spec.items() if k != 'license_plate'},
                         assigned_to=_tech(ctx, i), purchase_date=today - timedelta(days=500 + 300 * i),
                         insurance_expires_at=today + timedelta(days=160 - 140 * i),
                         registration_expires_at=today + timedelta(days=240),
                         notes='Demo vehicle.')
        vans.append(van)

    for vi, miles, ago, gallons, price, station in FUEL:
        _ensure(ctx, VehicleFuelLog, {'vehicle': vans[vi], 'mileage': miles}, date=today - timedelta(days=ago),
                gallons=Decimal(gallons), cost_per_gallon=Decimal(price),
                total_cost=(Decimal(gallons) * Decimal(price)).quantize(Decimal('0.01')), station=station)
    for vi, kind, desc, ago, miles, labor, parts, shop, next_miles, next_days in MAINTENANCE:
        _ensure(ctx, VehicleMaintenanceRecord, {'vehicle': vans[vi], 'maintenance_type': kind, 'description': desc},
                service_date=today - timedelta(days=ago), mileage_at_service=miles, performed_by=shop,
                labor_cost=Decimal(labor) if labor else None, parts_cost=Decimal(parts) if parts else None,
                is_scheduled=bool(next_miles or next_days), next_due_mileage=next_miles,
                next_due_date=today + timedelta(days=next_days) if next_days else None)
    for vi, name, contact, phone, email, types, preferred in PROVIDERS:
        _ensure(ctx, VehicleServiceProvider, {'vehicle': vans[vi], 'name': name}, contact_name=contact,
                phone=phone, email=email, service_types=types, is_preferred=preferred)
    for vi, name, kind, miles, days, last_miles, ago in SERVICE_SCHEDULES:
        _ensure(ctx, VehicleServiceSchedule, {'vehicle': vans[vi], 'name': name}, service_type=kind,
                interval_miles=miles, interval_days=days, last_service_mileage=last_miles,
                last_service_date=today - timedelta(days=ago))

    # Current drivers, plus one finished hand-over on the pickup.
    for vi, ti, start, end, start_miles, end_miles, notes in [
        (0, 0, 150, None, 9800, None, 'Primary driver.'),
        (1, 2, 400, 120, 31050, 43760, 'Handed over when Morgan moved to the backup team.'),
        (1, 1, 119, None, 43760, None, 'Primary driver.'),
    ]:
        _ensure(ctx, VehicleAssignment, {'vehicle': vans[vi], 'user': _tech(ctx, ti), 'starting_mileage': start_miles},
                start_date=today - timedelta(days=start),
                end_date=today - timedelta(days=end) if end is not None else None,
                ending_mileage=end_miles, notes=notes)
    return vans


def _seed_sites(ctx):
    """A site for customers with none, then WAN circuits on each customer's main site."""
    from locations.models import WAN, Location
    sites = []
    for i, org in enumerate(ctx.customers):
        loc = (Location.objects.filter(organization=org).order_by('-is_primary', 'pk').first())
        if loc is None and not _has_location_webhook(org):
            name, kind, street, city, state, postcode, lat, lon = SITES[i % len(SITES)]
            loc = Location.objects.create(organization=org, name=name, location_type=kind, street_address=street,
                                          city=city, state=state, postal_code=postcode, latitude=Decimal(lat),
                                          longitude=Decimal(lon), is_primary=True, phone='(555) 010-0100')
            ctx.created('locations.Location')
        if loc is None:
            continue
        sites.append((org, loc))
        for w, (name, kind, isp, down, up, cost, primary) in enumerate(WANS):
            if w and i % 2:  # backup circuits at every other customer
                continue
            net = '203.0.113' if primary else '198.51.100'
            _ensure(ctx, WAN, {'organization': org, 'name': name}, location=loc, wan_type=kind,
                    circuit_id=f'DEMO-{slugify(isp).upper()[:8]}-{4100 + i * 10 + w}', isp_name=isp,
                    isp_account_number=f'ACCT-{880000 + i * 37 + w}', isp_support_phone='(555) 010-4400',
                    bandwidth_download_mbps=Decimal(down), bandwidth_upload_mbps=Decimal(up),
                    static_ip=f'{net}.{10 + i * 8 + 2}', subnet_mask='255.255.255.248',
                    gateway=f'{net}.{10 + i * 8 + 1}', dns_primary='198.51.100.53', dns_secondary='198.51.100.54',
                    monitoring_enabled=False, monitor_target='', notify_on_down=False,
                    monthly_cost=Decimal(cost), contract_start_date=ctx.now.date() - timedelta(days=420),
                    contract_term_months=36, is_primary=primary)
    return sites


def _seed_field_ops(ctx, sites):
    from field_ops.models import ClientSiteGeofence, GeofenceVisit, OrganizationFieldOpsSettings, TimeclockEntry
    fences = []
    for org, loc in sites:
        _ensure(ctx, OrganizationFieldOpsSettings, {'organization': org}, geofence_only_mode=False, retention_days=90)
        if loc.latitude is None or loc.longitude is None:
            continue
        fence, _ = _ensure(ctx, ClientSiteGeofence, {'organization': org, 'name': f'{loc.name} (site)'},
                           location=loc, kind='radius', center_lat=Decimal(loc.latitude).quantize(Decimal('0.000001')),
                           center_lon=Decimal(loc.longitude).quantize(Decimal('0.000001')), radius_meters=150)
        fences.append((org, loc, fence))

    # Finished visits only: no open timeclock, no GPS pings, no ticket link
    # (a ticket would derive a billable time entry).
    for n, (org, loc, fence) in enumerate(fences[:3]):
        tech = _tech(ctx, n)
        start = (ctx.now - timedelta(days=2 + n)).replace(hour=9, minute=5, second=0, microsecond=0)
        end = start + timedelta(hours=3, minutes=40)
        note = f'On site at {org.name}: quarterly hardware check.'
        _ensure(ctx, TimeclockEntry, {'tech': tech, 'notes': note}, organization=org, location=loc,
                clocked_in_at=start, clocked_out_at=end, source='mobile')
        _ensure(ctx, GeofenceVisit, {'user': tech, 'geofence': fence}, entered_at=start - timedelta(minutes=3),
                exited_at=end + timedelta(minutes=2))


def _seed_reports(ctx):
    from reports.models import ReportTemplate, SavedQuery, ScheduledReport
    for i, org in enumerate(ctx.customers[:3]):
        template = (ReportTemplate.objects.filter(report_type='asset_summary', is_global=True).first()
                    or _ensure(ctx, ReportTemplate, {'organization': org, 'report_type': 'asset_summary'},
                               name='Asset Summary Report', description='Assets by type, status and location.',
                               query_template='', created_by=ctx.admin)[0])
        # Inactive + download-only: run_scheduled_reports only picks is_active rows.
        _ensure(ctx, ScheduledReport, {'organization': org, 'name': 'Monthly asset summary'}, template=template,
                frequency='monthly' if i else 'weekly', delivery_method='download',
                recipients=[f'it-reports@{org.slug}.example.com'], output_format='pdf', is_active=False,
                created_by=ctx.admin, next_run=ctx.now + timedelta(days=7 + i))
    for i, (name, target, filters, desc, sort) in enumerate(SAVED_QUERIES):
        org = ctx.customer(i)
        _ensure(ctx, SavedQuery, {'owner': ctx.admin, 'organization': org, 'name': name}, target_model=target,
                filters=filters, description=desc, sort_by=sort, is_shared=True)


def _seed_process(ctx):
    from processes.models import Process, ProcessStage
    title, category, desc, stages = PROCESS
    slug = slugify(title)
    if Process.objects.filter(organization__in=ctx.customers, slug=slug).exists():
        return
    org = next((o for o in ctx.customers if not Process.objects.filter(organization=o).exists()), None)
    if org is None:
        return
    process = Process.objects.create(organization=org, title=title, slug=slug, description=desc,
                                     category=category, created_by=ctx.admin, last_modified_by=ctx.admin)
    ctx.created('processes.Process')
    for order, (stitle, sdesc, confirm, minutes) in enumerate(stages, start=1):
        ProcessStage.objects.create(process=process, order=order, title=stitle, description=sdesc,
                                    requires_confirmation=confirm, estimated_duration_minutes=minutes)
        ctx.created('processes.ProcessStage')


def seed(ctx):
    vans = _seed_vehicles(ctx)
    _seed_inventory(ctx, vans)
    _seed_scheduling(ctx)
    _seed_resourcing(ctx)
    _seed_field_ops(ctx, _seed_sites(ctx))
    _seed_reports(ctx)
    _seed_process(ctx)
