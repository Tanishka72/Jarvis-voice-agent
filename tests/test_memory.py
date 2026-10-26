"""Tests for long-term memory: saved answers (answer cache) and the desktop chat memory.
Fresh temporary database each time; no Gemini, no internet."""
import pytest

from backend import config, migrate
from backend.database import connect
from backend.services import answer_cache
from backend.services.answer_cache import AnswerCache, is_reusable, normalize
from backend.services.desktop_memory import DesktopMemory


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(answer_cache, "_docs_version", lambda: 100)  # pretend 100 PDF chunks are indexed
    db = connect()
    migrate.up(db)
    db.close()
    return tmp_path / "memory.db"


def test_the_same_question_in_different_words_matches():
    key = "what is overfitting"
    assert normalize("Hey Jarvis, can you tell me what is Overfitting?") == key
    assert normalize("what is overfitting") == key
    assert normalize("What is overfitting, please.") == key
    assert normalize("245 * 18") != normalize("24518")  # maths symbols are kept


def test_only_questions_that_cant_go_out_of_date_are_reusable():
    assert is_reusable("what is overfitting according to my pdf")
    assert not is_reusable("how can i prevent it")            # "it" depends on the chat
    assert not is_reusable("what is the weather in mumbai")   # changes every hour
    assert not is_reusable("open notepad for me")             # an action must really run
    assert not is_reusable("thanks")                          # too short to be a real question


def test_a_saved_answer_comes_back(db_path):
    cache = AnswerCache()
    assert cache.lookup("What is overfitting according to my PDF?") is None
    assert cache.store("What is overfitting according to my PDF?", "Overfitting is ...", ["search_documents"], 0.62)
    # Asked again later, worded slightly differently (as speech-to-text would give it):
    assert cache.lookup("hey jarvis what is overfitting according to my pdf") == ("Overfitting is ...", 0.62)
    assert cache.count() == 1


def test_answers_from_changing_tools_or_errors_are_never_saved(db_path):
    cache = AnswerCache()
    assert not cache.store("convert one hundred dollars to rupees", "8,300 rupees", ["convert_currency"], None)
    assert not cache.store("what is the capital of india", "Sorry, Gemini is very busy right now.", [], None)
    assert cache.count() == 0


def test_pdf_answers_are_forgotten_when_the_pdfs_change(db_path, monkeypatch):
    cache = AnswerCache()
    cache.store("what does my pdf say about pca", "PCA reduces dimensions ...", ["search_documents"], 0.7)
    assert cache.lookup("what does my pdf say about pca") is not None
    monkeypatch.setattr(answer_cache, "_docs_version", lambda: 120)  # a new PDF was uploaded
    assert cache.lookup("what does my pdf say about pca") is None


def test_voice_chats_are_remembered_after_a_restart(db_path):
    first_day = DesktopMemory()
    first_day.save("What is overfitting?", "Overfitting is ...", 0.6)

    two_days_later = DesktopMemory()  # Jarvis started again: same conversation, history reloaded
    assert two_days_later.conversation_id == first_day.conversation_id
    assert two_days_later.history() == [("user", "What is overfitting?"), ("assistant", "Overfitting is ...")]
