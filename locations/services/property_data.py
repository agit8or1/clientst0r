"""
Property data integration service.

Fetches building information from:
- Public tax assessor records
- Building permit databases
- Property records APIs
- Zillow/Redfin data (if available)
"""

import requests
from django.conf import settings
from django.core.cache import cache
import logging
from typing import Optional, Dict
from .geocoding import get_geocoding_service

logger = logging.getLogger('locations')


class PropertyDataService:
    """Fetch property and building data from various sources."""

    CACHE_TTL = 86400 * 7  # 7 days

    def __init__(self):
        self.geocoding = get_geocoding_service()

    def get_property_data(self, address: str) -> Optional[Dict]:
        """
        Get comprehensive property data for an address.

        Returns dict with:
        - parcel_id: Tax parcel identifier
        - owner: Property owner name
        - year_built: Construction year
        - building_area: Square footage
        - lot_size: Lot size in sq ft or acres
        - bedrooms: Number of bedrooms (residential)
        - bathrooms: Number of bathrooms (residential)
        - property_type: residential, commercial, industrial, etc.
        - assessed_value: Tax assessed value
        - market_value: Estimated market value
        - zoning: Zoning classification
        - last_sale_date: Date of last sale
        - last_sale_price: Last sale price
        """
        # Check cache
        cache_key = f'property_data_{address}'
        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Property data cache hit: {address}")
            return cached

        # First geocode the address
        geo_data = self.geocoding.geocode_address(address)
        if not geo_data:
            logger.warning(f"Cannot get property data - geocoding failed: {address}")
            return None

        latitude = geo_data['latitude']
        longitude = geo_data['longitude']

        # Try various data sources
        property_data = None

        # Try Regrid (formerly Loveland) - requires API key
        if hasattr(settings, 'REGRID_API_KEY'):
            property_data = self._fetch_regrid_data(latitude, longitude)

        # Try AttomData API - requires API key
        if not property_data and hasattr(settings, 'ATTOM_API_KEY'):
            property_data = self._fetch_attom_data(address)

        # Try local government APIs (example: some counties have open APIs)
        if not property_data:
            property_data = self._fetch_local_government_data(geo_data)

        # Fallback to basic data from geocoding
        if not property_data:
            property_data = self._create_basic_property_data(geo_data)

        if property_data:
            # Add geocoding data
            property_data['latitude'] = latitude
            property_data['longitude'] = longitude
            property_data['formatted_address'] = geo_data['formatted_address']

            # Cache the result
            cache.set(cache_key, property_data, self.CACHE_TTL)

        return property_data

    def _fetch_regrid_data(self, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Fetch property data from Regrid API.

        Regrid provides parcel boundaries, ownership, and building data.
        """
        try:
            url = 'https://app.regrid.com/api/v2/parcels.json'
            headers = {
                'Authorization': f'Bearer {settings.REGRID_API_KEY}'
            }
            params = {
                'latitude': latitude,
                'longitude': longitude,
                'limit': 1
            }

            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if not data.get('features'):
                return None

            parcel = data['features'][0]['properties']

            return {
                'parcel_id': parcel.get('parcelnumb'),
                'owner': parcel.get('owner'),
                'year_built': parcel.get('yearbuilt'),
                'building_area': parcel.get('improvval'),  # Improvement value
                'lot_size': parcel.get('acres'),
                'property_type': parcel.get('usedesc', 'unknown'),
                'assessed_value': parcel.get('assessed_total'),
                'market_value': parcel.get('market_total'),
                'zoning': parcel.get('zoning'),
                'address': parcel.get('address'),
                'city': parcel.get('city'),
                'state': parcel.get('state'),
                'zip_code': parcel.get('zip'),
                'county': parcel.get('county'),
                'data_source': 'regrid',
            }

        except Exception as e:
            logger.error(f"Regrid API error: {e}")
            return None

    def _fetch_attom_data(self, address: str) -> Optional[Dict]:
        """
        Fetch property data from AttomData API.

        AttomData provides property details, valuations, and ownership.
        """
        try:
            url = 'https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/address'
            headers = {
                'apikey': settings.ATTOM_API_KEY,
                'accept': 'application/json'
            }
            params = {
                'address1': address
            }

            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if not data.get('property'):
                return None

            prop = data['property'][0]
            building = prop.get('building', {})
            lot = prop.get('lot', {})
            sale = prop.get('sale', {})
            assessment = prop.get('assessment', {})

            return {
                'parcel_id': prop.get('identifier', {}).get('apn'),
                'year_built': building.get('yearbuilt'),
                'building_area': building.get('size', {}).get('bldgsize'),
                'lot_size': lot.get('lotsize1'),
                'bedrooms': building.get('rooms', {}).get('beds'),
                'bathrooms': building.get('rooms', {}).get('bathstotal'),
                'property_type': prop.get('summary', {}).get('proptype', 'unknown'),
                'assessed_value': assessment.get('assessed', {}).get('assdttlvalue'),
                'market_value': assessment.get('market', {}).get('mktttlvalue'),
                'last_sale_date': sale.get('saleTransDate'),
                'last_sale_price': sale.get('amount', {}).get('saleamt'),
                'data_source': 'attom',
            }

        except Exception as e:
            logger.error(f"AttomData API error: {e}")
            return None

    def _fetch_local_government_data(self, geo_data: dict) -> Optional[Dict]:
        """
        Try to fetch data from local government APIs.

        Many counties and cities have open data portals with property records.
        This is a placeholder for custom integrations.
        """
        # Example: Check if address is in a supported jurisdiction
        state = geo_data.get('address_components', {}).get('state')
        county = geo_data.get('address_components', {}).get('county')

        # TODO: Add custom integrations for specific jurisdictions
        # Example: Cook County, IL has an open API
        # Example: King County, WA has property data
        # Example: San Francisco has open data portal

        logger.debug(f"No local government API integration for {state}, {county}")
        return None

    def _create_basic_property_data(self, geo_data: dict) -> Dict:
        """
        Create basic property data structure from geocoding results.

        This is the fallback when no detailed property data is available.
        """
        components = geo_data.get('address_components', {})

        return {
            'parcel_id': None,
            'owner': None,
            'year_built': None,
            'building_area': None,
            'lot_size': None,
            'property_type': 'unknown',
            'assessed_value': None,
            'market_value': None,
            'zoning': None,
            'address': geo_data.get('formatted_address'),
            'city': components.get('city'),
            'state': components.get('state'),
            'zip_code': components.get('zip_code'),
            'country': components.get('country'),
            'data_source': 'basic',
            'note': 'Limited data available - no property records API configured'
        }

    def get_building_dimensions(self, property_data: dict) -> Optional[Dict]:
        """
        Extract or estimate building dimensions from property data.

        Returns:
        - width_feet: Estimated building width
        - length_feet: Estimated building length
        - square_feet: Total building area
        - floors: Number of floors
        - confidence: 'high', 'medium', 'low'
        """
        building_area = property_data.get('building_area')

        if not building_area:
            return None

        # Estimate dimensions based on square footage
        # Assume rectangular building with common aspect ratios
        square_feet = float(building_area)

        # Common commercial building aspect ratios: 1.5:1 to 2:1
        # Residential: 1:1 to 1.5:1

        property_type = property_data.get('property_type', '').lower()

        if 'commercial' in property_type or 'office' in property_type:
            aspect_ratio = 1.8  # Longer rectangular
            floors = property_data.get('floors', 1)
        elif 'residential' in property_type:
            aspect_ratio = 1.3
            floors = property_data.get('floors', 1)
        else:
            aspect_ratio = 1.5
            floors = 1

        # Calculate floor area
        floor_area = square_feet / floors

        # Calculate dimensions assuming rectangular
        # area = width * length
        # length = width * aspect_ratio
        # area = width * (width * aspect_ratio) = width^2 * aspect_ratio
        # width = sqrt(area / aspect_ratio)

        import math
        width_feet = math.sqrt(floor_area / aspect_ratio)
        length_feet = width_feet * aspect_ratio

        return {
            'width_feet': round(width_feet, 1),
            'length_feet': round(length_feet, 1),
            'square_feet': square_feet,
            'floors': floors,
            'confidence': 'medium' if building_area else 'low',
            'note': 'Dimensions estimated from square footage and typical aspect ratios'
        }

    def estimate_employee_capacity(self, building_area: float, property_type: str = 'office') -> int:
        """
        Estimate employee capacity based on building size.

        Industry standards:
        - Office: 150-200 sq ft per employee
        - Call center: 100 sq ft per employee
        - Private offices: 200-400 sq ft per employee
        - Open plan: 100-150 sq ft per employee
        """
        if not building_area:
            return 0

        sq_ft_per_employee = {
            'office': 175,
            'call_center': 100,
            'private_office': 300,
            'open_plan': 125,
            'mixed': 175,
            'coworking': 100,
        }

        per_employee = sq_ft_per_employee.get(property_type.lower(), 175)

        # Account for common areas (hallways, restrooms, storage)
        # Typically 30-40% of space is non-workable
        usable_space = building_area * 0.65

        capacity = int(usable_space / per_employee)

        return capacity


# Singleton instance
_property_service = None


def get_property_service() -> PropertyDataService:
    """Get singleton property data service instance."""
    global _property_service
    if _property_service is None:
        _property_service = PropertyDataService()
    return _property_service
