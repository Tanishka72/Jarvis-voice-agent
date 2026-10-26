"""API tests. Each test gets a fresh, empty database and a fake Jarvis, so they are fast and
use no Gemini quota and no internet.

    .venv\\Scripts\\python.exe -m pytest -v
"""
import pytest
from fastapi.testclient import TestClient

from backend import config, migrate
from backend.database import connect
from backend.dependencies import app_cache, get_jarvis, get_weather_service
from backend.main import app
from backend.middlewares import rate_limiter
from backend.repositories import ApiKeyRepository
from backend.services.auth_service import AuthService
from backend.services.document_service import safe_filename
from backend.services.weather_service import WeatherService


class FakeJarvis:
    def __init__(self):
        self.calls = []

    def reply(self, history, question):
        self.calls.append((history, question))
        return f"You said: {question}", None, False


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")
    db = connect()
    migrate.up(db)
    auth = AuthService(ApiKeyRepository(db))
    _, key = auth.create_key("tester")
    _, other_key = auth.create_key("someone else")
    db.close()
    rate_limiter.reset()
    app_cache.clear()

    jarvis = FakeJarvis()
    app.dependency_overrides[get_jarvis] = lambda: jarvis
    c = TestClient(app)  # not used as `with`: skips startup, so no PDF indexing in tests
    c.headers["X-API-Key"] = key
    c.jarvis, c.other_key = jarvis, other_key
    yield c
    app.dependency_overrides.clear()


def test_health_is_public(client):
    r = client.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_missing_or_wrong_key_is_rejected(client):
    for key in ("", "jv_wrong"):
        r = client.get("/api/conversations", headers={"X-API-Key": key})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"
        assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]


def test_conversation_lifecycle(client):
    r = client.post("/api/conversations", json={})
    assert r.status_code == 201
    conv = r.json()
    assert conv["title"] == "New chat" and conv["message_count"] == 0
    assert r.headers["Location"] == f"/api/conversations/{conv['id']}"

    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "  What is overfitting?  "})
    assert r.status_code == 201
    assert r.json()["question"]["content"] == "What is overfitting?"  # spaces trimmed
    assert r.json()["reply"]["content"] == "You said: What is overfitting?"
    assert r.json()["from_cache"] is False

    # Stateless: the second question is sent with the history loaded from the database.
    client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "Give an example"})
    history, _ = client.jarvis.calls[-1]
    assert history == [("user", "What is overfitting?"), ("assistant", "You said: What is overfitting?")]

    detail = client.get(f"/api/conversations/{conv['id']}").json()
    assert detail["title"] == "What is overfitting?"  # named after the first question
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]

    page = client.get("/api/conversations?limit=10").json()
    assert page["total"] == 1 and page["items"][0]["message_count"] == 4

    assert client.delete(f"/api/conversations/{conv['id']}").status_code == 204
    assert client.get(f"/api/conversations/{conv['id']}").status_code == 404


def test_validation_errors(client):
    conv = client.post("/api/conversations", json={"title": "Test"}).json()
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "    "})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "content"
    assert client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "x" * 1001}).status_code == 422
    assert client.get("/api/conversations?limit=0").status_code == 422
    assert client.get("/api/documents/search?q=hi&intent=poem").status_code == 422
    assert client.jarvis.calls == []  # invalid input never reaches Jarvis


def test_users_cannot_see_each_others_conversations(client):
    conv = client.post("/api/conversations", json={"title": "Private"}).json()
    other = {"X-API-Key": client.other_key}
    assert client.get(f"/api/conversations/{conv['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/conversations/{conv['id']}", headers=other).status_code == 404
    assert client.get("/api/conversations", headers=other).json()["total"] == 0


def test_weather_is_cached(client):
    calls = []

    def fake_weather(city):
        calls.append(city)
        return {"location": f"{city}, India", "condition": "clear sky", "temperature_c": 26,
                "humidity_percent": 80, "wind_kmh": 10, "today_max_c": 31, "today_min_c": 24,
                "rain_chance_percent": 5}

    app.dependency_overrides[get_weather_service] = lambda: WeatherService(app_cache, fetch=fake_weather)
    first = client.get("/api/weather", params={"city": "mumbai"})
    second = client.get("/api/weather", params={"city": "  MUMBAI "})  # transformed to the same key
    assert first.headers["X-Cache"] == "MISS" and second.headers["X-Cache"] == "HIT"
    assert second.json()["cached"] is True
    assert calls == ["Mumbai"]  # the real service was called only once


def test_upload_rejects_files_that_are_not_pdfs(client):
    r = client.post("/api/documents", files={"file": ("notes.pdf", b"just some text", "application/pdf")})
    assert r.status_code == 400
    r = client.post("/api/documents", files={"file": ("virus.exe", b"%PDF-1.7", "application/pdf")})
    assert r.status_code == 400


def test_safe_filename_blocks_path_traversal():
    assert safe_filename("../../Windows/evil.pdf") == "evil.pdf"
    assert safe_filename("C:\\Users\\me\\My Notes.pdf") == "My Notes.pdf"
    assert safe_filename("rep<o>rt.pdf") == "rep_o_rt.pdf"


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 3)
    codes = [client.get("/api/conversations").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    r = client.get("/api/conversations")
    assert int(r.headers["Retry-After"]) > 0
    # Limits are per key: the other user is not affected.
    assert client.get("/api/conversations", headers={"X-API-Key": client.other_key}).status_code == 200


def test_migrations_go_down_and_up_again(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "m.db")
    db = connect()
    assert migrate.up(db) == migrate.available()
    columns = lambda: [r["name"] for r in db.execute("PRAGMA table_info(messages)")]  # noqa: E731
    assert "groundedness" in columns()

    assert migrate.down(db) == "005_create_answer_cache"
    assert migrate.down(db) == "004_add_groundedness_to_messages"
    assert "groundedness" not in columns()
    assert migrate.pending(db) == ["004_add_groundedness_to_messages", "005_create_answer_cache"]

    assert migrate.up(db) == ["004_add_groundedness_to_messages", "005_create_answer_cache"]
    assert "groundedness" in columns()
    db.close()
