"""
Geocoding service for address resolution and coordinate fetching.

Supports multiple providers:
- Google Maps Geocoding API (primary)
- OpenStreetMap Nominatim (fallback, free)
"""

import requests
from django.conf import settings
from django.core.cache import cache
import logging
from typing import Optional, Dict
import time

logger = logging.getLogger('locations')


class GeocodingService:
    """Geocode addresses and fetch property data."""

    GOOGLE_GEOCODE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'
    NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
    NOMINATIM_DETAILS_URL = 'https://nominatim.openstreetmap.org/details'

    CACHE_TTL = 86400 * 30  # 30 days

    def __init__(self):
        self.google_api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
        self.use_google = bool(self.google_api_key)

    def geocode_address(self, address: str) -> Optional[Dict]:
        """
        Geocode an address to coordinates and structured data.

        Returns dict with:
        - latitude: float
        - longitude: float
        - formatted_address: str
        - address_components: dict
        - place_id: str (if Google)
        - provider: str (google or osm)
        """
        # Check cache first
        cache_key = f'geocode_{address}'
        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Geocode cache hit for: {address}")
            return cached

        # Try Google first if available
        if self.use_google:
            result = self._geocode_google(address)
            if result:
                cache.set(cache_key, result, self.CACHE_TTL)
                return result

        # Fallback to OSM
        result = self._geocode_osm(address)
        if result:
            cache.set(cache_key, result, self.CACHE_TTL)
            return result

        logger.warning(f"Failed to geocode address: {address}")
        return None

    def _geocode_google(self, address: str) -> Optional[Dict]:
        """Geocode using Google Maps API."""
        try:
            params = {
                'address': address,
                'key': self.google_api_key
            }

            response = requests.get(
                self.GOOGLE_GEOCODE_URL,
                params=params,
                timeout=10
            )
            response.raise_for_status()

            data = response.json()

            if data['status'] != 'OK' or not data.get('results'):
                logger.warning(f"Google geocode failed: {data.get('status')}")
                return None

            result = data['results'][0]
            location = result['geometry']['location']

            # Parse address components
            components = {}
            for comp in result.get('address_components', []):
                types = comp['types']
                if 'street_number' in types:
                    components['street_number'] = comp['long_name']
                elif 'route' in types:
                    components['street'] = comp['long_name']
                elif 'locality' in types:
                    components['city'] = comp['long_name']
                elif 'administrative_area_level_1' in types:
                    components['state'] = comp['short_name']
                elif 'postal_code' in types:
                    components['zip_code'] = comp['long_name']
                elif 'country' in types:
                    components['country'] = comp['long_name']
                    components['country_code'] = comp['short_name']

            return {
                'latitude': location['lat'],
                'longitude': location['lng'],
                'formatted_address': result['formatted_address'],
                'address_components': components,
                'place_id': result.get('place_id'),
                'provider': 'google',
                'location_type': result['geometry'].get('location_type'),
                'viewport': result['geometry'].get('viewport'),
            }

        except Exception as e:
            logger.error(f"Google geocoding error: {e}")
            return None

    def _geocode_osm(self, address: str) -> Optional[Dict]:
        """Geocode using OpenStreetMap Nominatim."""
        try:
            # Nominatim requires a user agent
            headers = {
                'User-Agent': 'HuduGlue/2.5.0 (IT Documentation Platform)'
            }

            params = {
                'q': address,
                'format': 'json',
                'addressdetails': 1,
                'limit': 1
            }

            # Rate limit: max 1 request per second
            time.sleep(1)

            response = requests.get(
                self.NOMINATIM_URL,
                params=params,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()

            data = response.json()

            if not data:
                logger.warning(f"OSM geocode returned no results")
                return None

            result = data[0]
            address_data = result.get('address', {})

            # Parse address components
            components = {
                'street_number': address_data.get('house_number', ''),
                'street': address_data.get('road', ''),
                'city': address_data.get('city') or address_data.get('town') or address_data.get('village', ''),
                'state': address_data.get('state', ''),
                'zip_code': address_data.get('postcode', ''),
                'country': address_data.get('country', ''),
                'country_code': address_data.get('country_code', '').upper(),
            }

            return {
                'latitude': float(result['lat']),
                'longitude': float(result['lon']),
                'formatted_address': result.get('display_name', ''),
                'address_components': components,
                'place_id': result.get('place_id'),
                'provider': 'osm',
                'osm_type': result.get('osm_type'),
                'osm_id': result.get('osm_id'),
            }

        except Exception as e:
            logger.error(f"OSM geocoding error: {e}")
            return None

    def reverse_geocode(self, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Reverse geocode coordinates to address.

        Returns similar dict structure as geocode_address.
        """
        cache_key = f'reverse_geocode_{latitude}_{longitude}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        if self.use_google:
            result = self._reverse_geocode_google(latitude, longitude)
        else:
            result = self._reverse_geocode_osm(latitude, longitude)

        if result:
            cache.set(cache_key, result, self.CACHE_TTL)

        return result

    def _reverse_geocode_google(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Reverse geocode using Google Maps."""
        try:
            params = {
                'latlng': f'{latitude},{longitude}',
                'key': self.google_api_key
            }

            response = requests.get(
                self.GOOGLE_GEOCODE_URL,
                params=params,
                timeout=10
            )
            response.raise_for_status()

            data = response.json()

            if data['status'] != 'OK' or not data.get('results'):
                return None

            result = data['results'][0]
            return self._parse_google_result(result)

        except Exception as e:
            logger.error(f"Google reverse geocode error: {e}")
            return None

    def _reverse_geocode_osm(self, latitude: float, longitude: float) -> Optional[Dict]:
        """Reverse geocode using OSM Nominatim."""
        try:
            headers = {
                'User-Agent': 'HuduGlue/2.5.0 (IT Documentation Platform)'
            }

            params = {
                'lat': latitude,
                'lon': longitude,
                'format': 'json',
                'addressdetails': 1
            }

            time.sleep(1)  # Rate limit

            response = requests.get(
                'https://nominatim.openstreetmap.org/reverse',
                params=params,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()

            data = response.json()

            if 'error' in data:
                return None

            return self._parse_osm_result(data)

        except Exception as e:
            logger.error(f"OSM reverse geocode error: {e}")
            return None

    def get_place_details(self, place_id: str) -> Optional[Dict]:
        """
        Get detailed information about a place (Google only).

        Returns:
        - name: Business/place name
        - types: List of place types
        - phone: Phone number
        - website: Website URL
        - rating: Google rating
        - opening_hours: Opening hours info
        """
        if not self.use_google:
            return None

        try:
            url = 'https://maps.googleapis.com/maps/api/place/details/json'
            params = {
                'place_id': place_id,
                'fields': 'name,formatted_phone_number,website,rating,opening_hours,types,geometry',
                'key': self.google_api_key
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data['status'] != 'OK':
                return None

            result = data['result']

            return {
                'name': result.get('name'),
                'phone': result.get('formatted_phone_number'),
                'website': result.get('website'),
                'rating': result.get('rating'),
                'types': result.get('types', []),
                'opening_hours': result.get('opening_hours', {}).get('weekday_text', []),
                'geometry': result.get('geometry'),
            }

        except Exception as e:
            logger.error(f"Place details error: {e}")
            return None

    def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two coordinates in miles.

        Uses Haversine formula.
        """
        from math import radians, sin, cos, sqrt, atan2

        # Earth radius in miles
        R = 3959.0

        lat1_rad = radians(lat1)
        lon1_rad = radians(lon1)
        lat2_rad = radians(lat2)
        lon2_rad = radians(lon2)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        distance = R * c
        return distance

    def find_nearby_places(
        self,
        latitude: float,
        longitude: float,
        place_type: str = 'establishment',
        radius: int = 500
    ) -> list:
        """
        Find nearby places of a given type (Google only).

        Args:
            latitude: Center latitude
            longitude: Center longitude
            place_type: Type of place (e.g., 'restaurant', 'bank', 'hospital')
            radius: Search radius in meters (max 50000)

        Returns:
            List of place dicts with name, address, location, types
        """
        if not self.use_google:
            return []

        try:
            url = 'https://maps.googleapis.com/maps/api/place/nearbysearch/json'
            params = {
                'location': f'{latitude},{longitude}',
                'radius': min(radius, 50000),
                'type': place_type,
                'key': self.google_api_key
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data['status'] != 'OK':
                return []

            results = []
            for place in data.get('results', []):
                results.append({
                    'name': place.get('name'),
                    'address': place.get('vicinity'),
                    'latitude': place['geometry']['location']['lat'],
                    'longitude': place['geometry']['location']['lng'],
                    'types': place.get('types', []),
                    'place_id': place.get('place_id'),
                    'rating': place.get('rating'),
                })

            return results

        except Exception as e:
            logger.error(f"Nearby places search error: {e}")
            return []


# Singleton instance
_geocoding_service = None


def get_geocoding_service() -> GeocodingService:
    """Get singleton geocoding service instance."""
    global _geocoding_service
    if _geocoding_service is None:
        _geocoding_service = GeocodingService()
    return _geocoding_service
