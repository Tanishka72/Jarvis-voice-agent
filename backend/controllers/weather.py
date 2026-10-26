from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from backend.dependencies import api_key_header, get_weather_service
from backend.schemas import WeatherOut, WeatherQuery
from backend.services.weather_service import WeatherService

router = APIRouter(prefix="/api/weather", tags=["weather"], dependencies=[Depends(api_key_header)])


@router.get("", response_model=WeatherOut)
def current_weather(query: Annotated[WeatherQuery, Query()], response: Response,
                    service: WeatherService = Depends(get_weather_service)):
    """Today's weather. Cached for 10 minutes: the X-Cache header says HIT or MISS."""
    data, cached = service.current(query.city)
    response.headers["X-Cache"] = "HIT" if cached else "MISS"
    return {**data, "cached": cached}
