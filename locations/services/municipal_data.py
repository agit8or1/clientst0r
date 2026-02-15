"""
Municipal Tax Collector & Public Records Service

Fetches property data from public municipal databases:
- County tax assessor websites
- Public GIS systems
- Open data portals
- Property appraiser APIs
"""

import requests
from django.core.cache import cache
import logging
from typing import Optional, Dict
import re

logger = logging.getLogger('locations')


class MunicipalDataService:
    """Fetch property data from public municipal sources."""

    CACHE_TTL = 86400 * 7  # 7 days

    def __init__(self):
        pass

    def get_property_data(self, address: str, city: str = None, state: str = None, zip_code: str = None) -> Optional[Dict]:
        """
        Try to fetch property data from public municipal sources.

        Returns dict with property details or None if not found.
        """
        # Check cache first
        cache_key = f'municipal_data_{address}_{city}_{state}'
        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Municipal data cache hit: {address}")
            return cached

        property_data = None

        # Try Florida counties (common case)
        if state and state.upper() in ['FL', 'FLORIDA']:
            property_data = self._try_florida_counties(address, city, zip_code)

        # Try other states
        if not property_data and state:
            property_data = self._try_state_databases(address, city, state, zip_code)

        # Try general open data portals
        if not property_data:
            property_data = self._try_open_data_portals(address, city, state)

        if property_data:
            cache.set(cache_key, property_data, self.CACHE_TTL)

        return property_data

    def _try_florida_counties(self, address: str, city: str, zip_code: str) -> Optional[Dict]:
        """
        Try Florida county property appraisers (many have public APIs or accessible data).

        Common Florida counties with public data:
        - Duval (Jacksonville)
        - Miami-Dade
        - Broward
        - Orange (Orlando)
        - Pinellas (St. Petersburg)
        - Hillsborough (Tampa)
        """
        # Determine county from city or zip
        county = self._get_florida_county_from_city(city, zip_code)

        if not county:
            return None

        logger.info(f"Trying {county} County, FL property appraiser")

        if county == 'duval':
            return self._fetch_duval_county_data(address)
        elif county == 'miami-dade':
            return self._fetch_miami_dade_data(address)
        elif county == 'broward':
            return self._fetch_broward_data(address)
        # Add more counties as needed

        return None

    def _get_florida_county_from_city(self, city: str, zip_code: str) -> Optional[str]:
        """Map Florida city to county."""
        if not city:
            return None

        city_lower = city.lower()

        # Florida city to county mapping
        county_map = {
            'jacksonville': 'duval',
            'miami': 'miami-dade',
            'fort lauderdale': 'broward',
            'orlando': 'orange',
            'tampa': 'hillsborough',
            'st petersburg': 'pinellas',
            'clearwater': 'pinellas',
        }

        return county_map.get(city_lower)

    def _fetch_duval_county_data(self, address: str) -> Optional[Dict]:
        """
        Fetch from Duval County Property Appraiser (Jacksonville, FL).

        Public search available at: https://paopropertysearch.coj.net/
        This uses Duval County's public property records API.
        """
        try:
            logger.info(f"Searching Duval County property records for: {address}")

            # Try to parse address for search
            # Duval County API typically needs street number and name
            import re
            address_match = re.match(r'(\d+)\s+(.+)', address.strip())
            if not address_match:
                logger.warning(f"Could not parse address for Duval County search: {address}")
                return None

            street_number = address_match.group(1)
            street_name = address_match.group(2)

            # Duval County Public API endpoint (if available)
            # Many FL counties use Socrata open data platform
            api_url = "https://opendata.coj.net/resource/jj2e-6w6r.json"

            params = {
                '$where': f"upper(site_address) like upper('%{street_number}%{street_name}%')",
                '$limit': 10
            }

            headers = {
                'User-Agent': 'Client St0r/2.11 (Property Research Tool)'
            }

            response = requests.get(api_url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    # Get first matching property
                    prop = data[0]

                    # Parse building data from Duval County records
                    building_sqft = None
                    if 'total_living_area' in prop:
                        try:
                            building_sqft = float(prop['total_living_area'])
                        except (ValueError, TypeError):
                            pass
                    elif 'building_area' in prop:
                        try:
                            building_sqft = float(prop['building_area'])
                        except (ValueError, TypeError):
                            pass

                    year_built = None
                    if 'year_built' in prop:
                        try:
                            year_built = int(prop['year_built'])
                        except (ValueError, TypeError):
                            pass
                    elif 'actual_year_built' in prop:
                        try:
                            year_built = int(prop['actual_year_built'])
                        except (ValueError, TypeError):
                            pass

                    # Extract property type
                    property_type = prop.get('land_use_description', 'unknown')
                    if property_type.lower() in ['unknown', 'vacant', '']:
                        property_type = prop.get('property_use', 'unknown')

                    # Get parcel/property ID
                    property_id = prop.get('parcel_id') or prop.get('re_no') or prop.get('propertyid')

                    # Get floors count (if available)
                    floors_count = None
                    if 'stories' in prop:
                        try:
                            floors_count = int(prop['stories'])
                        except (ValueError, TypeError):
                            pass

                    logger.info(f"Found Duval County property: {building_sqft} sqft, built {year_built}, type: {property_type}")

                    return {
                        'source': 'duval_county_pa',
                        'building_sqft': building_sqft,
                        'year_built': year_built,
                        'property_type': property_type,
                        'property_id': property_id,
                        'floors_count': floors_count,
                        'raw_data': prop,
                        'data_url': f"https://paopropertysearch.coj.net/Basic/Detail.aspx?RE={property_id}" if property_id else None,
                    }

            logger.warning(f"Duval County API returned status {response.status_code}")
            return None

        except requests.RequestException as e:
            logger.error(f"Duval County API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Duval County data fetch failed: {e}", exc_info=True)
            return None

    def _fetch_miami_dade_data(self, address: str) -> Optional[Dict]:
        """
        Fetch from Miami-Dade Property Appraiser.

        Public API available at: https://www.miamidade.gov/pa/
        """
        try:
            # Miami-Dade has public property data
            logger.info(f"Miami-Dade property search available for: {address}")
            return None

        except Exception as e:
            logger.error(f"Miami-Dade data fetch failed: {e}")
            return None

    def _fetch_broward_data(self, address: str) -> Optional[Dict]:
        """Fetch from Broward County Property Appraiser."""
        try:
            logger.info(f"Broward County property search available for: {address}")
            return None

        except Exception as e:
            logger.error(f"Broward data fetch failed: {e}")
            return None

    def _try_state_databases(self, address: str, city: str, state: str, zip_code: str) -> Optional[Dict]:
        """
        Try state-specific property databases.

        Many states have centralized property record systems.
        """
        state_upper = state.upper()

        # Add state-specific implementations
        if state_upper in ['CA', 'CALIFORNIA']:
            return self._try_california_data(address, city)
        elif state_upper in ['TX', 'TEXAS']:
            return self._try_texas_data(address, city)
        elif state_upper in ['NY', 'NEW YORK']:
            return self._try_new_york_data(address, city)

        return None

    def _try_california_data(self, address: str, city: str) -> Optional[Dict]:
        """California property data sources."""
        logger.info(f"California property data lookup for {address}, {city}")
        # Would implement county-specific lookups
        return None

    def _try_texas_data(self, address: str, city: str) -> Optional[Dict]:
        """Texas property data sources."""
        logger.info(f"Texas property data lookup for {address}, {city}")
        # Would implement county-specific lookups
        return None

    def _try_new_york_data(self, address: str, city: str) -> Optional[Dict]:
        """New York property data sources."""
        logger.info(f"New York property data lookup for {address}, {city}")
        # Would implement NYC ACRIS or other sources
        return None

    def _try_open_data_portals(self, address: str, city: str, state: str) -> Optional[Dict]:
        """
        Try general open data portals.

        Many cities publish property data on open data platforms like:
        - Socrata
        - CKAN
        - ArcGIS Open Data
        """
        try:
            # Check if city has Socrata open data
            if city and state:
                return self._try_socrata_search(address, city, state)

        except Exception as e:
            logger.error(f"Open data portal search failed: {e}")

        return None

    def _try_socrata_search(self, address: str, city: str, state: str) -> Optional[Dict]:
        """
        Search Socrata-powered open data portals.

        Many US cities use Socrata for open data.
        """
        try:
            # Common Socrata city domains
            socrata_domains = {
                'jacksonville': 'data.jacksonville.gov',
                'seattle': 'data.seattle.gov',
                'san francisco': 'data.sfgov.org',
                'chicago': 'data.cityofchicago.org',
                'new york': 'data.cityofnewyork.us',
            }

            city_lower = city.lower()
            if city_lower not in socrata_domains:
                return None

            domain = socrata_domains[city_lower]
            logger.info(f"Found Socrata portal for {city}: {domain}")

            # Would implement actual Socrata API search here
            # Example: https://data.seattle.gov/resource/property-data.json?address=...

            return None

        except Exception as e:
            logger.error(f"Socrata search failed: {e}")
            return None


# Singleton instance
_municipal_service = None


def get_municipal_service() -> MunicipalDataService:
    """Get singleton municipal data service instance."""
    global _municipal_service
    if _municipal_service is None:
        _municipal_service = MunicipalDataService()
    return _municipal_service
