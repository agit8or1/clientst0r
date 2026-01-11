"""
Satellite and aerial imagery service.

Fetches aerial/satellite images of properties from:
- Google Maps Static API (satellite view)
- Mapbox Static Images API
- Bing Maps Imagery API
"""

import requests
from django.conf import settings
from django.core.files.base import ContentFile
import logging
from typing import Optional, Tuple
import os

logger = logging.getLogger('locations')


class SatelliteImageryService:
    """Fetch satellite and aerial imagery for properties."""

    GOOGLE_STATIC_URL = 'https://maps.googleapis.com/maps/api/staticmap'
    MAPBOX_STATIC_URL = 'https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static'
    BING_STATIC_URL = 'https://dev.virtualearth.net/REST/v1/Imagery/Map'

    def __init__(self):
        self.google_api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
        self.mapbox_token = getattr(settings, 'MAPBOX_ACCESS_TOKEN', None)
        self.bing_api_key = getattr(settings, 'BING_MAPS_API_KEY', None)

        # Determine which provider to use
        if self.google_api_key:
            self.provider = 'google'
        elif self.mapbox_token:
            self.provider = 'mapbox'
        elif self.bing_api_key:
            self.provider = 'bing'
        else:
            self.provider = None
            logger.warning("No satellite imagery API key configured")

    def fetch_satellite_image(
        self,
        latitude: float,
        longitude: float,
        zoom: int = 18,
        width: int = 800,
        height: int = 600,
        add_marker: bool = True
    ) -> Optional[Tuple[bytes, str]]:
        """
        Fetch satellite image for coordinates.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            zoom: Zoom level (1-22, higher = closer)
            width: Image width in pixels
            height: Image height in pixels
            add_marker: Add marker at center point

        Returns:
            (image_bytes, content_type) or None if failed
        """
        if not self.provider:
            logger.error("No satellite imagery provider configured")
            return None

        try:
            if self.provider == 'google':
                return self._fetch_google_satellite(
                    latitude, longitude, zoom, width, height, add_marker
                )
            elif self.provider == 'mapbox':
                return self._fetch_mapbox_satellite(
                    latitude, longitude, zoom, width, height, add_marker
                )
            elif self.provider == 'bing':
                return self._fetch_bing_satellite(
                    latitude, longitude, zoom, width, height, add_marker
                )

        except Exception as e:
            logger.error(f"Satellite image fetch failed: {e}")
            return None

    def _fetch_google_satellite(
        self,
        latitude: float,
        longitude: float,
        zoom: int,
        width: int,
        height: int,
        add_marker: bool
    ) -> Optional[Tuple[bytes, str]]:
        """Fetch satellite image from Google Maps Static API."""
        params = {
            'center': f'{latitude},{longitude}',
            'zoom': min(zoom, 22),
            'size': f'{width}x{height}',
            'maptype': 'satellite',
            'key': self.google_api_key,
            'scale': 2,  # Retina/high-DPI
        }

        if add_marker:
            params['markers'] = f'color:red|{latitude},{longitude}'

        response = requests.get(
            self.GOOGLE_STATIC_URL,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', 'image/png')
        return response.content, content_type

    def _fetch_mapbox_satellite(
        self,
        latitude: float,
        longitude: float,
        zoom: int,
        width: int,
        height: int,
        add_marker: bool
    ) -> Optional[Tuple[bytes, str]]:
        """Fetch satellite image from Mapbox Static Images API."""
        # Mapbox URL format:
        # https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/{overlay}/{lon},{lat},{zoom}/{width}x{height}@2x

        overlay = ''
        if add_marker:
            # Add red pin marker
            overlay = f'pin-s+ff0000({longitude},{latitude})/'

        url = (
            f'{self.MAPBOX_STATIC_URL}/'
            f'{overlay}'
            f'{longitude},{latitude},{min(zoom, 22)}/{width}x{height}@2x'
        )

        params = {
            'access_token': self.mapbox_token
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        return response.content, 'image/png'

    def _fetch_bing_satellite(
        self,
        latitude: float,
        longitude: float,
        zoom: int,
        width: int,
        height: int,
        add_marker: bool
    ) -> Optional[Tuple[bytes, str]]:
        """Fetch satellite image from Bing Maps Imagery API."""
        # Bing URL format:
        # /REST/v1/Imagery/Map/Aerial/{centerPoint}/{zoomLevel}?mapSize={width},{height}&key={key}

        url = (
            f'{self.BING_STATIC_URL}/Aerial/'
            f'{latitude},{longitude}/{min(zoom, 21)}'
        )

        params = {
            'mapSize': f'{width},{height}',
            'key': self.bing_api_key
        }

        if add_marker:
            params['pushpin'] = f'{latitude},{longitude};66;RED'

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', 'image/jpeg')
        return response.content, content_type

    def fetch_street_view_image(
        self,
        latitude: float,
        longitude: float,
        heading: int = 0,
        pitch: int = 0,
        width: int = 800,
        height: int = 600
    ) -> Optional[Tuple[bytes, str]]:
        """
        Fetch street view image (Google only).

        Args:
            latitude: Location latitude
            longitude: Location longitude
            heading: Camera heading (0-360, 0=North)
            pitch: Camera pitch (-90 to 90, 0=horizontal)
            width: Image width
            height: Image height

        Returns:
            (image_bytes, content_type) or None
        """
        if not self.google_api_key:
            logger.warning("Google API key required for Street View")
            return None

        try:
            url = 'https://maps.googleapis.com/maps/api/streetview'
            params = {
                'location': f'{latitude},{longitude}',
                'size': f'{width}x{height}',
                'heading': heading,
                'pitch': pitch,
                'fov': 90,  # Field of view
                'key': self.google_api_key
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            # Check if Street View is available
            # Google returns 200 but with error image if not available
            if len(response.content) < 5000:  # Error images are small
                logger.warning("Street View not available for this location")
                return None

            return response.content, 'image/jpeg'

        except Exception as e:
            logger.error(f"Street view fetch failed: {e}")
            return None

    def check_street_view_availability(self, latitude: float, longitude: float) -> bool:
        """
        Check if Street View is available at location (Google only).

        Returns:
            True if Street View imagery exists
        """
        if not self.google_api_key:
            return False

        try:
            url = 'https://maps.googleapis.com/maps/api/streetview/metadata'
            params = {
                'location': f'{latitude},{longitude}',
                'key': self.google_api_key
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            return data.get('status') == 'OK'

        except Exception as e:
            logger.error(f"Street view availability check failed: {e}")
            return False

    def save_image_to_file(
        self,
        image_data: bytes,
        content_type: str,
        filename_prefix: str = 'satellite'
    ) -> str:
        """
        Save image bytes to a file.

        Args:
            image_data: Image bytes
            content_type: MIME type (e.g., 'image/png')
            filename_prefix: Prefix for filename

        Returns:
            Relative file path
        """
        # Determine file extension from content type
        ext_map = {
            'image/png': 'png',
            'image/jpeg': 'jpg',
            'image/jpg': 'jpg',
            'image/gif': 'gif',
        }
        extension = ext_map.get(content_type, 'png')

        # Generate filename
        from django.utils import timezone
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{filename_prefix}_{timestamp}.{extension}'

        # Save to media directory
        from django.core.files.storage import default_storage
        file_path = f'locations/satellite/{filename}'

        # Ensure directory exists
        directory = os.path.join(settings.MEDIA_ROOT, 'locations', 'satellite')
        os.makedirs(directory, exist_ok=True)

        # Save file
        saved_path = default_storage.save(file_path, ContentFile(image_data))

        logger.info(f"Saved satellite image to {saved_path}")
        return saved_path

    def get_map_tile_url(
        self,
        latitude: float,
        longitude: float,
        zoom: int = 18,
        map_type: str = 'satellite'
    ) -> Optional[str]:
        """
        Get embeddable map tile URL for use in iframes/HTML.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            zoom: Zoom level
            map_type: 'satellite', 'roadmap', 'hybrid', 'terrain'

        Returns:
            Embeddable map URL
        """
        if self.provider == 'google':
            # Google Maps Embed API
            return (
                f'https://www.google.com/maps/embed/v1/view'
                f'?key={self.google_api_key}'
                f'&center={latitude},{longitude}'
                f'&zoom={zoom}'
                f'&maptype={map_type}'
            )
        elif self.provider == 'mapbox':
            # Mapbox GL JS iframe
            return (
                f'https://api.mapbox.com/styles/v1/mapbox/{map_type}-v9.html'
                f'?access_token={self.mapbox_token}'
                f'#center={longitude},{latitude}'
                f'&zoom={zoom}'
            )
        else:
            return None


# Singleton instance
_imagery_service = None


def get_imagery_service() -> SatelliteImageryService:
    """Get singleton satellite imagery service instance."""
    global _imagery_service
    if _imagery_service is None:
        _imagery_service = SatelliteImageryService()
    return _imagery_service
