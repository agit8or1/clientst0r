"""
MagicPlan import service

Imports floor plans from MagicPlan JSON exports.
MagicPlan is a popular mobile app for creating floor plans.
"""
import json
import logging
from decimal import Decimal
from django.db import transaction
from .base import BaseImportService
from locations.models import Location, LocationFloorPlan

logger = logging.getLogger('imports')


class MagicPlanImportService(BaseImportService):
    """
    Import floor plans from MagicPlan JSON exports.

    MagicPlan JSON structure typically contains:
    - project: Project metadata
    - plans: Array of floor plans
    - rooms: Array of rooms with dimensions
    - objects: Array of placed objects/assets
    """

    def __init__(self, import_job):
        # Don't call super().__init__ because MagicPlan doesn't need API auth
        self.job = import_job
        self.organization = import_job.target_organization
        self.org_matcher = None
        self.org_map = {}
        self.source_org_names = {}
        self.errors = []
        self._plan_seq = 0

    def _get_auth_headers(self):
        """MagicPlan doesn't use API - reads from uploaded file."""
        return {}

    def _parse_magicplan_file(self):
        """
        Parse uploaded MagicPlan JSON file.

        Returns:
            dict: Parsed JSON data
        """
        if not self.job.source_file:
            raise ValueError("No MagicPlan file uploaded")

        try:
            with self.job.source_file.open('r') as f:
                data = json.load(f)
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON file: {e}")
        except Exception as e:
            raise ValueError(f"Failed to read file: {e}")

    def list_organizations(self):
        """MagicPlan doesn't have organizations - returns empty list."""
        return []

    def run_import(self):
        """
        Run the MagicPlan import process.

        Returns: dict with statistics
        """
        try:
            self.job.mark_running()
            self.job.reset_counters()
            self.job.add_log(f"Starting MagicPlan import")

            stats = {
                'locations': 0,
                'floor_plans': 0,
                'errors': []
            }

            # Parse MagicPlan file
            self.job.add_log("Parsing MagicPlan export file...")
            magicplan_data = self._parse_magicplan_file()

            # Import floor plans
            if self.job.import_floor_plans:
                stats['floor_plans'] = self.import_floor_plans(magicplan_data)

            # Update job statistics (items_failed is counted per plan)
            self.job.items_imported = stats['floor_plans']
            self.job.floor_plans_imported = stats['floor_plans']
            self.job.save(update_fields=['floor_plans_imported'])

            self.job.finish()
            self.job.add_log(
                f"Import finished: {self.job.get_status_display()} - "
                f"{stats['floor_plans']} floor plan(s) imported, "
                f"{self.job.items_failed} failed")

            return stats

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"MagicPlan import failed: {error_msg}")
            self.job.mark_failed(error_msg)
            self.job.add_log(f"ERROR: {error_msg}")
            raise

    def import_floor_plans(self, magicplan_data):
        """
        Import floor plans from MagicPlan data.

        Args:
            magicplan_data: Parsed MagicPlan JSON

        Returns:
            int: Number of floor plans imported
        """
        count = 0

        # Extract project info
        project = magicplan_data.get('project', {})
        project_name = project.get('name', 'Imported Floor Plan')
        project_address = project.get('address', {})

        # Get or create location
        location = self._get_or_create_location(project_name, project_address, project)

        # Import each floor plan
        plans = magicplan_data.get('plans', [])
        if not plans:
            # Fallback: try 'floors' key
            plans = magicplan_data.get('floors', [])

        self.job.add_log(f"Found {len(plans)} floor plan(s) to import")

        for plan_data in plans:
            try:
                with transaction.atomic():
                    floor_plan = self._create_floor_plan(location, plan_data)
                count += 1
                self.job.add_log(f"Imported floor plan: {floor_plan.floor_name}")
            except Exception as e:
                logger.error(f"Failed to import floor plan: {e}")
                self.job.items_failed += 1
                self.job.add_log(f"ERROR importing floor plan: {e}")

        self.job.save()
        return count

    def _get_or_create_location(self, project_name, address_data, project_data):
        """
        Get or create location for the floor plans.

        Args:
            project_name: Name of the MagicPlan project
            address_data: Address dictionary from MagicPlan
            project_data: Full project data

        Returns:
            Location instance
        """
        # If target organization is set, use it
        if not self.organization:
            raise ValueError("Target organization must be specified for MagicPlan imports")

        # If target_location is specified, use it
        if self.job.target_location:
            self.job.add_log(f"Using specified location: {self.job.target_location.name}")
            return self.job.target_location

        # Extract address components
        street = address_data.get('street', '')
        city = address_data.get('city', 'Unknown')
        state = address_data.get('state', 'Unknown')
        postal_code = address_data.get('zip', '') or address_data.get('postalCode', '')
        country = address_data.get('country', 'United States')

        # Try to find existing location by name and address
        existing_location = Location.objects.filter(
            organization=self.organization,
            name=project_name,
            city=city
        ).first()

        if existing_location:
            self.job.add_log(f"Using existing location: {existing_location.name}")
            return existing_location

        # Create new location
        if self.job.dry_run:
            self.job.add_log(f"[DRY RUN] Would create location: {project_name}")
            # Return dummy location for dry run
            return Location(
                organization=self.organization,
                name=project_name,
                street_address=street,
                city=city,
                state=state,
                postal_code=postal_code,
                country=country
            )
        else:
            location = Location.objects.create(
                organization=self.organization,
                name=project_name,
                location_type='office',  # Default type
                street_address=street,
                city=city,
                state=state,
                postal_code=postal_code,
                country=country,
                notes=f"Imported from MagicPlan: {project_data.get('description', '')}"
            )
            # Recorded so rollback can remove it.
            self.create_mapping('location', f"magicplan:{project_name}", location,
                                organization=self.organization)
            self.job.add_log(f"Created new location: {location.name}")
            return location

    def _create_floor_plan(self, location, plan_data):
        """
        Create floor plan from MagicPlan data.

        Args:
            location: Location instance
            plan_data: Floor plan data from MagicPlan

        Returns:
            LocationFloorPlan instance
        """
        # Extract floor info
        floor_name = plan_data.get('name', 'Floor Plan')
        floor_number = plan_data.get('level', 1)

        # Extract dimensions - MagicPlan uses various units
        # Common keys: width, length, area, rooms
        dimensions = plan_data.get('dimensions', {})
        rooms = plan_data.get('rooms', [])

        # Calculate total dimensions from rooms if not directly available
        width_m = dimensions.get('width', 0) or self._calculate_width_from_rooms(rooms)
        length_m = dimensions.get('length', 0) or self._calculate_length_from_rooms(rooms)

        # MagicPlan typically uses meters, convert to feet
        width_feet = self._meters_to_feet(width_m)
        length_feet = self._meters_to_feet(length_m)
        total_sqft = int(width_feet * length_feet)

        # Extract ceiling height if available
        ceiling_height = dimensions.get('height', dimensions.get('ceilingHeight'))
        ceiling_height_feet = self._meters_to_feet(ceiling_height) if ceiling_height else None

        if self.job.dry_run:
            self.job.add_log(f"[DRY RUN] Would create floor plan: {floor_name} ({width_feet:.1f}' x {length_feet:.1f}', {total_sqft} sqft)")
            return LocationFloorPlan(
                location=location,
                floor_number=floor_number,
                floor_name=floor_name,
                width_feet=Decimal(str(width_feet)),
                length_feet=Decimal(str(length_feet)),
                total_sqft=total_sqft,
                source='magicplan'
            )
        else:
            floor_plan = LocationFloorPlan.objects.create(
                location=location,
                floor_number=floor_number,
                floor_name=floor_name,
                width_feet=Decimal(str(round(width_feet, 2))),
                length_feet=Decimal(str(round(length_feet, 2))),
                ceiling_height_feet=Decimal(str(round(ceiling_height_feet, 2))) if ceiling_height_feet else None,
                total_sqft=total_sqft,
                source='magicplan',
                confidence_score=Decimal('1.00'),  # MagicPlan data is directly measured
                ai_analysis={
                    'magicplan_data': plan_data,
                    'rooms': rooms,
                    'room_count': len(rooms),
                    'import_source': 'magicplan_json'
                }
            )
            # Recorded so rollback can remove it.
            self._plan_seq += 1
            self.create_mapping('floor_plan', f"{location.pk}:{self._plan_seq}:{floor_name}"[:100],
                                floor_plan, organization=self.organization)

            return floor_plan

    def _calculate_width_from_rooms(self, rooms):
        """Calculate total width from room data."""
        if not rooms:
            return 10.0  # Default 10 meters

        max_x = 0
        for room in rooms:
            corners = room.get('corners', [])
            for corner in corners:
                x = abs(corner.get('x', 0))
                max_x = max(max_x, x)

        return max_x or 10.0

    def _calculate_length_from_rooms(self, rooms):
        """Calculate total length from room data."""
        if not rooms:
            return 10.0  # Default 10 meters

        max_y = 0
        for room in rooms:
            corners = room.get('corners', [])
            for corner in corners:
                y = abs(corner.get('y', 0))
                max_y = max(max_y, y)

        return max_y or 10.0

    def _meters_to_feet(self, meters):
        """Convert meters to feet."""
        if not meters:
            return 0.0
        return float(meters) * 3.28084

    # Stub methods for compatibility with BaseImportService
    def import_assets(self):
        """Not applicable for MagicPlan."""
        return 0

    def import_passwords(self):
        """Not applicable for MagicPlan."""
        return 0

    def import_documents(self):
        """Not applicable for MagicPlan."""
        return 0

    def import_contacts(self):
        """Not applicable for MagicPlan."""
        return 0

    def import_locations(self):
        """Not applicable for MagicPlan."""
        return 0

    def import_networks(self):
        """Not applicable for MagicPlan."""
        return 0
