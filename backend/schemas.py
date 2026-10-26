"""Schemas: the shape of the data that comes IN to the API and goes OUT of it (Pydantic).

VALIDATION   - reject bad input before any code runs: wrong type, empty, too long...
               FastAPI answers 422 with the reason, and the controller is never called.
TRANSFORMATION - clean the input into one standard form: trim spaces, " MUMBAI " -> "Mumbai",
               and on the way out turn database rows (text dates) into proper JSON.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------- requests (IN) ----------
class ConversationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str | None = Field(default=None, max_length=100)

    @field_validator("title")
    @classmethod
    def empty_title_means_none(cls, v: str | None) -> str | None:
        return v or None  # "" -> None, so the service picks a title


class MessageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " becomes "" and fails min_length
    content: str = Field(min_length=1, max_length=1000, examples=["What is overfitting, according to my PDF?"])


class WeatherQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    city: str = Field(min_length=2, max_length=80)

    @field_validator("city")
    @classmethod
    def normalise_city(cls, v: str) -> str:
        # "  new   DELHI" -> "New Delhi". Same city, same cache key -> more cache hits.
        return " ".join(v.split()).title()


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    q: str = Field(min_length=3, max_length=500, description="What to look for in your PDFs")
    intent: Literal["fact", "summary", "compare", "list"] = "fact"


# ---------- responses (OUT) ----------
class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    groundedness: float | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationPage(BaseModel):
    items: list[ConversationOut]
    total: int
    limit: int
    offset: int


class ChatReply(BaseModel):
    conversation_id: int
    question: MessageOut
    reply: MessageOut
    from_cache: bool = False  # True = a saved answer, given instantly without calling Gemini


class DocumentOut(BaseModel):
    name: str
    pages: int


class UploadOut(BaseModel):
    id: int
    filename: str
    status: Literal["pending", "indexing", "ready", "failed"]
    chunks: int | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class Passage(BaseModel):
    source: str
    page: int
    section: str = ""
    relevance: float
    text: str


class SearchResult(BaseModel):
    answer_found: bool
    reason: str | None = None
    passages: list[Passage] = []


class WeatherOut(BaseModel):
    location: str
    condition: str
    temperature_c: float
    humidity_percent: float
    wind_kmh: float
    today_max_c: float
    today_min_c: float
    rain_chance_percent: float | None = None
    cached: bool


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    pending_migrations: list[str]
    cache: dict
