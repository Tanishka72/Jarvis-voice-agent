"""Weather, with a cache in front of Open-Meteo.

Without the cache, 100 people asking about Mumbai = 200 calls to Open-Meteo (it looks up the
city, then the weather). With it, that's 2 calls every 10 minutes, and repeat answers come
back in about a millisecond instead of about half a second.
"""
import requests

import tools
from backend import config
from backend.cache import TTLCache
from backend.errors import NotFoundError, ServiceUnavailableError


class WeatherService:
    def __init__(self, cache: TTLCache, fetch=tools.get_weather):
        self.cache = cache
        self.fetch = fetch  # the same weather tool Jarvis uses; tests pass a fake one

    def current(self, city: str) -> tuple[dict, bool]:
        """Return (weather, came_from_cache)."""
        key = f"weather:{city.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached, True
        try:
            data = self.fetch(city)
        except (requests.RequestException, KeyError, ValueError) as e:
            raise ServiceUnavailableError("The weather service can't be reached right now.") from e
        if "error" in data:
            raise NotFoundError(data["error"])  # errors are not cached
        self.cache.set(key, data, config.WEATHER_CACHE_SECONDS)
        return data, False
