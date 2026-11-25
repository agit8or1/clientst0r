"""Vehicle service alert generation.

Creates a pending ``VehicleServiceAlert`` when an active service schedule
comes within its warning window (by mileage or by date). Called when a
vehicle's page is opened and by the scheduler (task type
``vehicles_service_alerts``, ``manage.py vehicles_service_alerts``), so
alerts appear even for vehicles nobody opens.

Idempotent: a schedule that already has a pending alert gets no second one,
so the page and the scheduled job can both run without duplicates.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from vehicles.models import ServiceVehicle, VehicleServiceAlert, VehicleServiceSchedule


def generate_vehicle_service_alerts(vehicle, *, today=None):
    """Check the vehicle's active service schedules; return alerts created."""
    today = today or timezone.localdate()
    created = []

    for schedule in vehicle.service_schedules.filter(is_active=True):
        due_mileage = None
        due_date = None
        triggered = False

        if schedule.interval_miles and schedule.last_service_mileage is not None:
            next_mi = schedule.last_service_mileage + schedule.interval_miles
            if (vehicle.current_mileage or 0) >= next_mi - (schedule.warning_miles or 0):
                triggered = True
                due_mileage = next_mi

        if schedule.interval_days and schedule.last_service_date:
            next_dt = schedule.last_service_date + timedelta(days=schedule.interval_days)
            if today >= next_dt - timedelta(days=schedule.warning_days or 0):
                triggered = True
                due_date = next_dt

        if not triggered:
            continue

        with transaction.atomic():
            # Lock the schedule row (a no-op on SQLite, whose write lock
            # already serialises this) so a page view and the scheduled run
            # can't both pass the "no pending alert" check.
            VehicleServiceSchedule.objects.select_for_update().filter(pk=schedule.pk).first()
            if VehicleServiceAlert.objects.filter(schedule=schedule, status='pending').exists():
                continue
            created.append(VehicleServiceAlert.objects.create(
                vehicle=vehicle,
                schedule=schedule,
                title=f'{schedule.name} due',
                due_mileage=due_mileage,
                due_date=due_date,
                status='pending',
            ))
    return created


def generate_all_service_alerts(*, today=None):
    """Run the check for every vehicle that isn't retired; return the count created."""
    total = 0
    vehicles = (ServiceVehicle.objects.exclude(status='retired')
                .filter(service_schedules__is_active=True).distinct())
    for vehicle in vehicles:
        total += len(generate_vehicle_service_alerts(vehicle, today=today))
    return total
