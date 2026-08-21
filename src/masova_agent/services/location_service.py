"""
Location service for geolocation
"""
import httpx
from typing import Optional, Dict
from datetime import datetime, timedelta

from ..data.models import Location
from ..exceptions import LocationServiceError
from ..utils import get_logger, get_config

logger = get_logger(__name__)


class LocationService:
    """Service for handling geolocation"""

    def __init__(self):
        """Initialize location service"""
        self.config = get_config()
        self._cache: Dict[str, tuple[Location, datetime]] = {}

    def get_location(self, customer_id: Optional[str] = None) -> Location:
        """
        Get geographic location

        Args:
            customer_id: Optional customer ID for caching

        Returns:
            Location object

        Raises:
            LocationServiceError: If location cannot be determined
        """
        # Check cache if customer_id provided
        if customer_id and self.config.cache.enabled:
            cached_location = self._get_cached_location(customer_id)
            if cached_location:
                logger.debug(f"Using cached location for {customer_id}")
                return cached_location

        # Fetch fresh location
        try:
            location = self._fetch_location()

            # Cache if customer_id provided
            if customer_id and self.config.cache.enabled:
                self._cache_location(customer_id, location)
                logger.info(f"Cached location for {customer_id}: {location}")

            return location

        except Exception as e:
            logger.error(f"Location fetch failed: {e}")
            raise LocationServiceError(f"Failed to fetch location: {str(e)}")

    def _fetch_location(self) -> Location:
        """
        Fetch location from external API

        Returns:
            Location object

        Raises:
            LocationServiceError: If API call fails
        """
        try:
            response = httpx.get(
                self.config.api.location_api_url,
                timeout=self.config.api.location_timeout
            )
            response.raise_for_status()
            data = response.json()

            return Location(
                city=data.get("city", "Unknown"),
                country=data.get("country", "Unknown"),
                latitude=data.get("lat"),
                longitude=data.get("lon"),
                region=data.get("regionName")
            )

        except httpx.HTTPError as e:
            raise LocationServiceError(f"HTTP error: {str(e)}")
        except httpx.TimeoutException:
            raise LocationServiceError("Location API timeout")
        except KeyError as e:
            raise LocationServiceError(f"Invalid API response: missing {e}")
        except Exception as e:
            raise LocationServiceError(f"Unexpected error: {str(e)}")

    def _get_cached_location(self, customer_id: str) -> Optional[Location]:
        """Get location from cache if not expired"""
        if customer_id not in self._cache:
            return None

        location, cached_at = self._cache[customer_id]

        # Check if cache is expired
        ttl = timedelta(seconds=self.config.cache.ttl_seconds)
        if datetime.now() - cached_at > ttl:
            del self._cache[customer_id]
            logger.debug(f"Cache expired for {customer_id}")
            return None

        return location

    def _cache_location(self, customer_id: str, location: Location) -> None:
        """Cache location for customer"""
        self._cache[customer_id] = (location, datetime.now())

        # Enforce max cache size (LRU-like)
        if len(self._cache) > self.config.cache.max_size:
            # Remove oldest entry
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
            logger.debug(f"Evicted {oldest_key} from cache (size limit)")

    def clear_cache(self) -> None:
        """Clear all cached locations"""
        self._cache.clear()
        logger.info("Location cache cleared")
