"""
Views for locations app - Multi-location management with AI floor plan generation
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from .models import Location, LocationFloorPlan
from .forms import LocationForm, LocationFloorPlanForm, SendNavigationLinkForm
from .services import (
    get_geocoding_service,
    get_property_service,
    get_imagery_service,
    AIFloorPlanGenerator,
    generate_office_floor_plan
)
from docs.models import Diagram, DiagramVersion
import logging

logger = logging.getLogger('locations')


@login_required
def location_list(request):
    """List all locations for current organization."""
    organization = request.current_organization

    # Build query - allow superusers/staff to see all locations in global view
    if organization:
        locations = Location.objects.filter(organization=organization).select_related('organization')
    elif request.user.is_superuser or request.is_staff_user:
        locations = Location.objects.all().select_related('organization')
    else:
        # Regular users must have an organization context
        locations = Location.objects.filter(organization=organization).select_related('organization')

    # Filtering
    status_filter = request.GET.get('status')
    if status_filter:
        locations = locations.filter(status=status_filter)

    location_type = request.GET.get('type')
    if location_type:
        locations = locations.filter(location_type=location_type)

    # Search
    search_query = request.GET.get('q')
    if search_query:
        locations = locations.filter(name__icontains=search_query)

    # Pagination
    paginator = Paginator(locations, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'total_count': paginator.count,
        'status_filter': status_filter,
        'location_type': location_type,
        'search_query': search_query,
    }

    return render(request, 'locations/location_list.html', context)


@login_required
def location_detail(request, location_id):
    """Display location details with map, satellite imagery, and floor plans."""
    organization = request.current_organization

    # Build query - allow superusers/staff to access all locations in global view
    if organization:
        location = get_object_or_404(Location, id=location_id, organization=organization)
    elif request.user.is_superuser or request.is_staff_user:
        location = get_object_or_404(Location, id=location_id)
    else:
        # Regular users must have an organization context
        location = get_object_or_404(Location, id=location_id, organization=organization)

    # Get floor plans for this location
    floor_plans = location.floor_plans.all()

    # Get associated assets (if assets app has location FK)
    try:
        from assets.models import Asset
        assets = Asset.objects.filter(location=location)
    except:
        assets = []

    # Get property appraiser info for this location
    property_appraiser = location.get_property_appraiser_info()

    context = {
        'location': location,
        'floor_plans': floor_plans,
        'assets': assets,
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
        'property_appraiser': property_appraiser,
    }

    return render(request, 'locations/location_detail.html', context)


@login_required
def location_create(request):
    """Create new location with optional AI-assisted setup."""
    organization = request.current_organization

    # Require organization context for creating locations
    if not organization:
        messages.error(request, 'Organization context required to create locations.')
        return redirect('accounts:organization_list')

    if request.method == 'POST':
        form = LocationForm(request.POST, request.FILES, organization=organization)

        if form.is_valid():
            location = form.save(commit=False)
            location.organization = organization

            # Auto-geocode if requested
            if form.cleaned_data.get('auto_geocode'):
                geocoding = get_geocoding_service()
                geo_data = geocoding.geocode_address(location.full_address)

                if geo_data:
                    location.latitude = geo_data['latitude']
                    location.longitude = geo_data['longitude']
                    location.google_place_id = geo_data.get('place_id', '')

                    messages.success(request, f"Address geocoded successfully")
                else:
                    messages.warning(request, "Could not geocode address automatically")

            # Fetch property data if requested
            if form.cleaned_data.get('fetch_property_data'):
                property_service = get_property_service()
                property_data = property_service.get_property_data(location.full_address)

                if property_data:
                    location.property_id = property_data.get('parcel_id', '')
                    location.building_sqft = property_data.get('building_area')
                    location.year_built = property_data.get('year_built')
                    location.property_type = property_data.get('property_type', '')
                    location.external_data = property_data

                    messages.success(request, "Property data fetched successfully")
                else:
                    messages.warning(request, "Could not fetch property data")

            location.save()

            # Fetch satellite imagery if requested
            if form.cleaned_data.get('fetch_satellite_image') and location.has_coordinates:
                try:
                    imagery_service = get_imagery_service()
                    image_data, content_type = imagery_service.fetch_satellite_image(
                        float(location.latitude),
                        float(location.longitude),
                        zoom=18,
                        width=1200,
                        height=900
                    )

                    if image_data:
                        from django.core.files.base import ContentFile
                        location.satellite_image.save(
                            f'satellite_{location.id}.png',
                            ContentFile(image_data),
                            save=True
                        )
                        messages.success(request, "Satellite image fetched successfully")

                except Exception as e:
                    logger.error(f"Satellite image fetch failed: {e}")
                    messages.warning(request, "Could not fetch satellite imagery")

            messages.success(request, f"Location '{location.name}' created successfully")
            return redirect('locations:location_detail', location_id=location.id)
    else:
        form = LocationForm(organization=organization)

    context = {
        'form': form,
        'is_create': True,
    }

    return render(request, 'locations/location_form.html', context)


@login_required
def location_edit(request, location_id):
    """Edit existing location."""
    organization = request.current_organization
    location = get_object_or_404(
        Location,
        id=location_id,
        organization=organization
    )

    if request.method == 'POST':
        form = LocationForm(
            request.POST,
            request.FILES,
            instance=location,
            organization=organization
        )

        if form.is_valid():
            location = form.save()
            messages.success(request, f"Location '{location.name}' updated successfully")
            return redirect('locations:location_detail', location_id=location.id)
    else:
        form = LocationForm(instance=location, organization=organization)

    context = {
        'form': form,
        'location': location,
        'is_create': False,
    }

    return render(request, 'locations/location_form.html', context)


@login_required
def location_delete(request, location_id):
    """Delete location."""
    organization = request.current_organization
    location = get_object_or_404(
        Location,
        id=location_id,
        organization=organization
    )

    if request.method == 'POST':
        location_name = location.name
        location.delete()
        messages.success(request, f"Location '{location_name}' deleted successfully")
        return redirect('locations:location_list')

    context = {'location': location}
    return render(request, 'locations/location_confirm_delete.html', context)


@login_required
def generate_floor_plan(request, location_id):
    """
    Generate AI floor plan for a location.

    Shows form to configure generation parameters, then creates floor plan.
    """
    organization = request.current_organization
    location = get_object_or_404(
        Location,
        id=location_id,
        organization=organization
    )

    if request.method == 'POST':
        # Check if Anthropic API key is configured
        if not settings.ANTHROPIC_API_KEY:
            messages.error(
                request,
                "Anthropic API key is not configured. Please add your API key in Settings → AI & LLM to use floor plan generation."
            )
            return redirect('locations:location_detail', location_id=location.id)

        # Get generation parameters
        try:
            floor_number_raw = request.POST.get('floor_number', 1)
            floor_number = int(floor_number_raw[0] if isinstance(floor_number_raw, list) else floor_number_raw)
        except (ValueError, TypeError):
            floor_number = 1

        floor_name = request.POST.get('floor_name', 'Ground Floor')
        if isinstance(floor_name, list):
            floor_name = floor_name[0]

        try:
            num_employees_raw = request.POST.get('num_employees', 20)
            num_employees = int(num_employees_raw[0] if isinstance(num_employees_raw, list) else num_employees_raw)
        except (ValueError, TypeError):
            num_employees = 20

        departments = request.POST.getlist('departments')
        include_network = request.POST.get('include_network') == 'on'
        include_security = request.POST.get('include_security') == 'on'

        # Get dimensions
        try:
            width_feet_raw = request.POST.get('width_feet', 100)
            width_feet = float(width_feet_raw[0] if isinstance(width_feet_raw, list) else width_feet_raw)
        except (ValueError, TypeError):
            width_feet = 100.0

        try:
            length_feet_raw = request.POST.get('length_feet', 80)
            length_feet = float(length_feet_raw[0] if isinstance(length_feet_raw, list) else length_feet_raw)
        except (ValueError, TypeError):
            length_feet = 80.0

        try:
            logger.info(f"Starting floor plan generation for location {location.id} ({location.name})")
            logger.info(f"Parameters: {width_feet}x{length_feet} ft, {num_employees} employees, departments: {departments}")

            with transaction.atomic():
                # Generate floor plan using AI
                logger.debug("Initializing AIFloorPlanGenerator")
                generator = AIFloorPlanGenerator()

                logger.debug("Calling generator.generate_floor_plan()")
                builder, metadata = generator.generate_floor_plan(
                    building_name=location.name,
                    width_feet=width_feet,
                    length_feet=length_feet,
                    num_employees=num_employees,
                    departments=departments,
                    include_network=include_network,
                    include_security=include_security,
                    additional_requirements=request.POST.get('additional_requirements', '')
                )
                logger.debug("Floor plan generated successfully by AI")

                xml_content = builder.to_xml_string()

                # Ensure dimensions are numeric (final safety check)
                try:
                    width_feet = float(width_feet)
                    length_feet = float(length_feet)
                    total_sqft = int(width_feet * length_feet)
                except (ValueError, TypeError) as e:
                    logger.error(f"Type conversion error: width={width_feet}, length={length_feet}, error={e}")
                    raise Exception(f"Invalid dimensions: width={width_feet}, length={length_feet}")

                # Create or update floor plan record
                floor_plan, created = LocationFloorPlan.objects.update_or_create(
                    location=location,
                    floor_number=floor_number,
                    defaults={
                        'organization': organization,
                        'floor_name': floor_name,
                        'width_feet': width_feet,
                        'length_feet': length_feet,
                        'total_sqft': total_sqft,
                        'diagram_xml': xml_content,
                        'source': 'ai_estimate',
                        'ai_analysis': metadata,
                        'include_network': include_network,
                        'template_used': 'office',
                    }
                )

                # Create diagram in docs module
                diagram_title = f"{location.name} - {floor_name}"
                diagram, diagram_created = Diagram.objects.update_or_create(
                    organization=organization,
                    slug=f"{location.name.lower().replace(' ', '-')}-{floor_name.lower().replace(' ', '-')}",
                    defaults={
                        'title': diagram_title,
                        'diagram_type': 'floorplan',
                        'xml_data': xml_content,
                        'is_public': False,
                        'notes': f"AI-generated floor plan for {location.name}",
                    }
                )

                # Create diagram version
                DiagramVersion.objects.create(
                    organization=organization,
                    diagram=diagram,
                    xml_data=xml_content,
                    version_number=diagram.versions.count() + 1,
                    change_notes=f"Generated by AI for {location.name}",
                    created_by=request.user
                )

                # Link diagram to floor plan
                floor_plan.diagram = diagram
                floor_plan.save()

                # Update location generation status
                location.floorplan_generated = True
                location.floorplan_generated_at = timezone.now()
                location.floorplan_generation_status = 'completed'
                location.save()

                messages.success(
                    request,
                    f"Floor plan generated successfully for {floor_name}! "
                    f"Created {len(metadata.get('ai_design', {}).get('rooms', []))} rooms."
                )

                return redirect('docs:diagram_detail', slug=diagram.slug)

        except Exception as e:
            logger.error(f"Floor plan generation failed: {e}", exc_info=True)
            location.floorplan_generation_status = 'failed'
            location.floorplan_error = str(e)
            location.save()

            # Check if it's an API key issue
            if 'api key' in str(e).lower() or 'anthropic' in str(e).lower():
                messages.error(
                    request,
                    f"Floor plan generation failed: {e}. "
                    f"Please check your Anthropic API key in Settings → AI & LLM."
                )
            else:
                messages.error(request, f"Floor plan generation failed: {e}")

            return redirect('locations:location_detail', location_id=location.id)

    else:
        # Show generation form
        # Try to get dimensions from property data
        width_feet = 100
        length_feet = 80
        num_employees = 20

        if location.building_sqft:
            # Estimate dimensions
            property_service = get_property_service()
            dimensions = property_service.get_building_dimensions({
                'building_area': location.building_sqft,
                'property_type': location.property_type,
                'floors': location.floors_count or 1
            })
            if dimensions:
                width_feet = dimensions['width_feet']
                length_feet = dimensions['length_feet']

            # Estimate employees
            num_employees = property_service.estimate_employee_capacity(
                building_area=location.building_sqft / (location.floors_count or 1),
                property_type=location.location_type
            )

        context = {
            'location': location,
            'suggested_width': width_feet,
            'suggested_length': length_feet,
            'suggested_employees': num_employees,
        }

        return render(request, 'locations/generate_floor_plan.html', context)


@login_required
@require_http_methods(["POST"])
def refresh_geocoding(request, location_id):
    """Re-geocode location address (AJAX)."""
    organization = request.current_organization
    location = get_object_or_404(
        Location,
        id=location_id,
        organization=organization
    )

    try:
        geocoding = get_geocoding_service()
        geo_data = geocoding.geocode_address(location.full_address)

        if geo_data:
            location.latitude = geo_data['latitude']
            location.longitude = geo_data['longitude']
            location.google_place_id = geo_data.get('place_id', '')
            location.save()

            return JsonResponse({
                'success': True,
                'latitude': float(location.latitude),
                'longitude': float(location.longitude),
                'formatted_address': geo_data['formatted_address']
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Could not geocode address'
            }, status=400)

    except Exception as e:
        logger.error(f"Geocoding refresh failed: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def refresh_property_data(request, location_id):
    """Re-fetch property data (AJAX)."""
    organization = request.current_organization
    location = get_object_or_404(
        Location,
        id=location_id,
        organization=organization
    )

    try:
        property_service = get_property_service()
        property_data = property_service.get_property_data(location.full_address)

        if property_data:
            location.property_id = property_data.get('parcel_id', '')
            location.building_sqft = property_data.get('building_area')
            location.year_built = property_data.get('year_built')
            location.property_type = property_data.get('property_type', '')
            location.external_data = property_data
            location.save()

            return JsonResponse({
                'success': True,
                'property_data': property_data
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Could not fetch property data'
            }, status=400)

    except Exception as e:
        logger.error(f"Property data refresh failed: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def import_property_from_url(request, location_id):
    """Import property data from URL using AI (AJAX)."""
    organization = request.current_organization
    location = get_object_or_404(
        Location,
        id=location_id,
        organization=organization
    )

    try:
        import json
        body = json.loads(request.body)
        url = body.get('url', '').strip()

        if not url:
            return JsonResponse({
                'success': False,
                'error': 'URL is required'
            }, status=400)

        # Validate URL
        if not url.startswith(('http://', 'https://')):
            return JsonResponse({
                'success': False,
                'error': 'Invalid URL format'
            }, status=400)

        # Import using AI
        from locations.services.property_url_importer import get_property_url_importer

        importer = get_property_url_importer()
        property_data = importer.import_from_url(url)

        # Update location with extracted data
        updates_made = []

        if property_data.get('building_sqft'):
            location.building_sqft = int(property_data['building_sqft'])
            updates_made.append(f"Building: {property_data['building_sqft']} sqft")

        if property_data.get('year_built'):
            location.year_built = int(property_data['year_built'])
            updates_made.append(f"Year Built: {property_data['year_built']}")

        if property_data.get('property_type'):
            location.property_type = property_data['property_type']
            updates_made.append(f"Type: {property_data['property_type']}")

        if property_data.get('property_id'):
            location.property_id = property_data['property_id']
            updates_made.append(f"Parcel ID: {property_data['property_id']}")

        if property_data.get('floors_count'):
            location.floors_count = int(property_data['floors_count'])
            updates_made.append(f"Floors: {property_data['floors_count']}")

        # Store full data in external_data
        if not location.external_data:
            location.external_data = {}
        location.external_data['url_import'] = property_data

        location.save()

        logger.info(f"Successfully imported property data from URL for location {location.id}: {', '.join(updates_made)}")

        return JsonResponse({
            'success': True,
            'updates': updates_made,
            'property_data': property_data
        })

    except ValueError as e:
        logger.error(f"Property URL import validation error: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    except Exception as e:
        logger.error(f"Property URL import failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Import failed: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def refresh_satellite_image(request, location_id):
    """Re-fetch satellite image (AJAX)."""
    organization = request.current_organization
    location = get_object_or_404(
        Location,
        id=location_id,
        organization=organization
    )

    if not location.has_coordinates:
        return JsonResponse({
            'success': False,
            'error': 'Location has no coordinates. Geocode first.'
        }, status=400)

    try:
        imagery_service = get_imagery_service()
        result = imagery_service.fetch_satellite_image(
            float(location.latitude),
            float(location.longitude),
            zoom=18,
            width=1200,
            height=900
        )

        if result:
            image_data, content_type = result
            from django.core.files.base import ContentFile
            location.satellite_image.save(
                f'satellite_{location.id}.png',
                ContentFile(image_data),
                save=True
            )

            return JsonResponse({
                'success': True,
                'image_url': location.satellite_image.url
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Could not fetch satellite image. Please check your Google Maps API key in Settings → AI.'
            }, status=400)

    except Exception as e:
        logger.error(f"Satellite image refresh failed: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def floor_plan_import(request):
    """Import floor plans from MagicPlan JSON export."""
    from imports.models import ImportJob
    from imports.forms import ImportJobForm

    organization = request.current_organization

    if request.method == 'POST':
        # Create import job form with MagicPlan pre-selected
        form = ImportJobForm(request.POST, request.FILES, user=request.user, organization=organization)

        if form.is_valid():
            job = form.save(commit=False)
            job.source_type = 'magicplan'  # Force MagicPlan type
            job.started_by = request.user
            job.import_floor_plans = True
            # Disable other import types for floor plans
            job.import_assets = False
            job.import_passwords = False
            job.import_documents = False
            job.import_contacts = False
            job.import_locations = False
            job.import_networks = False
            job.save()

            messages.success(request, 'Floor plan import job created. Review and start the import.')
            return redirect('imports:import_detail', pk=job.pk)
    else:
        # Initialize form for MagicPlan import
        initial_data = {
            'source_type': 'magicplan',
            'target_organization': organization,
            'import_floor_plans': True,
            'import_assets': False,
            'import_passwords': False,
            'import_documents': False,
            'import_contacts': False,
            'import_locations': False,
            'import_networks': False,
            'dry_run': True,  # Default to dry run
        }
        form = ImportJobForm(initial=initial_data, user=request.user, organization=organization)

    # Get locations for the organization
    locations = Location.objects.filter(organization=organization)

    return render(request, 'locations/floor_plan_import.html', {
        'form': form,
        'locations': locations,
    })


@login_required
def location_map_data(request):
    """Return JSON data for location map (organization-specific)."""
    organization = request.current_organization

    if not organization:
        return JsonResponse({'error': 'No organization selected'}, status=400)

    # Get all locations for this organization with coordinates
    locations = Location.objects.filter(
        organization=organization,
        latitude__isnull=False,
        longitude__isnull=False
    ).values('id', 'name', 'street_address', 'city', 'state', 'postal_code',
             'latitude', 'longitude', 'location_type', 'status', 'is_primary')

    # Build GeoJSON feature collection
    features = []
    for loc in locations:
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(loc['longitude']), float(loc['latitude'])]
            },
            'properties': {
                'id': loc['id'],
                'name': loc['name'],
                'address': f"{loc['street_address']}, {loc['city']}, {loc['state']} {loc['postal_code']}",
                'location_type': loc['location_type'],
                'status': loc['status'],
                'is_primary': loc['is_primary'],
                'url': f"/locations/{loc['id']}/"
            }
        })

    return JsonResponse({
        'type': 'FeatureCollection',
        'features': features
    })


@login_required
def global_location_map_data(request):
    """Return JSON data for global location map (all organizations, superusers and staff only)."""
    # Check if user is staff (MSP tech) or superuser
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False

    if not (request.user.is_superuser or is_staff):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    from core.models import Organization

    # Get all locations with coordinates across all organizations
    locations = Location.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False
    ).select_related('organization').values(
        'id', 'name', 'street_address', 'city', 'state', 'postal_code',
        'latitude', 'longitude', 'location_type', 'status', 'is_primary',
        'organization__id', 'organization__name'
    )

    # Build GeoJSON feature collection
    features = []
    for loc in locations:
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(loc['longitude']), float(loc['latitude'])]
            },
            'properties': {
                'id': loc['id'],
                'name': loc['name'],
                'address': f"{loc['street_address']}, {loc['city']}, {loc['state']} {loc['postal_code']}",
                'location_type': loc['location_type'],
                'status': loc['status'],
                'is_primary': loc['is_primary'],
                'organization_id': loc['organization__id'],
                'organization_name': loc['organization__name'],
                'url': f"/locations/{loc['id']}/"
            }
        })

    return JsonResponse({
        'type': 'FeatureCollection',
        'features': features
    })


@login_required
@require_http_methods(["GET", "POST"])
def send_navigation_link(request, location_id):
    """Send navigation link for location via email or SMS."""
    location = get_object_or_404(Location, id=location_id)
    organization = request.current_organization

    # Check access - allow superusers/staff to access any location in global view
    if organization:
        if not location.can_organization_access(organization):
            messages.error(request, "You don't have access to this location.")
            return redirect('locations:location_list')
    elif not (request.user.is_superuser or request.is_staff_user):
        messages.error(request, "Organization context required.")
        return redirect('accounts:organization_list')

    if request.method == 'POST':
        form = SendNavigationLinkForm(request.POST)
        if form.is_valid():
            method = form.cleaned_data['method']
            map_service = form.cleaned_data['map_service']
            recipient_email = form.cleaned_data.get('recipient_email')
            recipient_phone = form.cleaned_data.get('recipient_phone')
            custom_message = form.cleaned_data.get('message', '')

            # Get navigation URLs
            nav_urls = location.get_all_navigation_urls()

            # Determine which URL(s) to send
            if map_service == 'all':
                urls_to_send = nav_urls
            else:
                urls_to_send = {map_service: nav_urls.get(map_service)}

            # Build message
            if custom_message:
                message_body = f"{custom_message}\n\n"
            else:
                message_body = f"Navigation to {location.name}\n{location.full_address}\n\n"

            for service_name, url in urls_to_send.items():
                if url:
                    service_label = service_name.replace('_', ' ').title()
                    message_body += f"{service_label}: {url}\n"

            success = False
            error_messages = []

            # Send via email
            if method in ['email', 'both']:
                try:
                    from django.core.mail import send_mail
                    from core.models import SystemSetting

                    settings = SystemSetting.get_settings()

                    send_mail(
                        subject=f"Navigation to {location.name}",
                        message=message_body,
                        from_email=settings.smtp_from_email or 'noreply@example.com',
                        recipient_list=[recipient_email],
                        fail_silently=False
                    )
                    messages.success(request, f"Navigation link sent to {recipient_email}")
                    success = True
                except Exception as e:
                    error_msg = f"Failed to send email: {str(e)}"
                    error_messages.append(error_msg)
                    logger.error(error_msg)

            # Send via SMS
            if method in ['sms', 'both']:
                try:
                    from core.sms import send_sms

                    result = send_sms(recipient_phone, message_body)

                    if result['success']:
                        messages.success(request, f"Navigation link sent to {recipient_phone}")
                        success = True
                    else:
                        error_msg = f"Failed to send SMS: {result.get('error', 'Unknown error')}"
                        error_messages.append(error_msg)
                        logger.error(error_msg)
                except Exception as e:
                    error_msg = f"Failed to send SMS: {str(e)}"
                    error_messages.append(error_msg)
                    logger.error(error_msg)

            if error_messages:
                for error in error_messages:
                    messages.error(request, error)

            if success:
                return redirect('locations:location_detail', location_id=location.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = SendNavigationLinkForm()

    # Check if SMS is enabled
    from core.models import SystemSetting
    system_settings = SystemSetting.get_settings()
    sms_enabled = system_settings.sms_enabled

    context = {
        'location': location,
        'form': form,
        'sms_enabled': sms_enabled,
        'nav_urls': location.get_all_navigation_urls(),
    }

    return render(request, 'locations/send_navigation_link.html', context)
