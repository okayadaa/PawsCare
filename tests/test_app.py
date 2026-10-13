"""End-to-end tests that run app.py with Streamlit's built-in test runner."""

from pathlib import Path
from unittest import mock

import pytest
import streamlit.user_info
from streamlit.testing.v1 import AppTest

APP_FILE = str(Path(__file__).resolve().parent.parent / "app.py")


def _by_label(widgets, label):
    return next(widget for widget in widgets if widget.label == label)


def _app(database_url: str, *, auth: bool) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.secrets["database"] = {"url": database_url}
    if auth:
        at.secrets["auth"] = {"client_id": "test"}
    return at


def _as_user(user: dict):
    """Pretend a Google account is signed in (or signed out)."""
    return mock.patch.object(streamlit.user_info, "_get_user_info", return_value=user)


def _add_pet(at: AppTest, name: str) -> None:
    _by_label(at.text_input, "Pet name").input(name)
    _by_label(at.button, "Add pet").click().run()
    assert not at.exception, at.exception


ALICE = {"is_logged_in": True, "sub": "111", "email": "alice@example.com", "given_name": "Alice"}
BOB = {"is_logged_in": True, "sub": "222", "email": "bob@example.com", "given_name": "Bob"}


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'app.db'}"


def test_signed_out_visitor_only_sees_sign_in(db_url):
    with _as_user({"is_logged_in": False}):
        at = _app(db_url, auth=True).run()

    assert not at.exception, at.exception
    assert [button.label for button in at.button] == ["Sign in with Google"]
    assert not any(field.label == "Pet name" for field in at.text_input)


def test_signed_in_users_keep_separate_data(db_url):
    with _as_user(ALICE):
        at = _app(db_url, auth=True).run()
        assert at.text_input(key="owner_name").value == "Alice"
        _add_pet(at, "Mochi")

    with _as_user(BOB):
        at = _app(db_url, auth=True).run()
        assert at.session_state["owner"].pets == []

    # Alice comes back in a brand-new session and her pet is still there.
    with _as_user(ALICE):
        at = _app(db_url, auth=True).run()
        assert [pet.name for pet in at.session_state["owner"].pets] == ["Mochi"]


def test_local_mode_saves_between_sessions(db_url):
    at = _app(db_url, auth=False).run()
    assert "Local mode" in at.sidebar.warning[0].value
    _add_pet(at, "Mochi")

    at = _app(db_url, auth=False).run()
    assert [pet.name for pet in at.session_state["owner"].pets] == ["Mochi"]


def test_delete_my_data_removes_saved_pets(db_url):
    at = _app(db_url, auth=False).run()
    _add_pet(at, "Mochi")

    at.checkbox[0].check().run()
    _by_label(at.button, "Delete my data").click().run()
    assert not at.exception, at.exception

    at = _app(db_url, auth=False).run()
    assert at.session_state["owner"].pets == []


def test_database_outage_stops_instead_of_showing_empty_plan(tmp_path):
    # A path inside a missing folder can't be opened, like a database that's down.
    broken_url = f"sqlite:///{tmp_path / 'missing' / 'app.db'}"
    at = _app(broken_url, auth=False).run()

    assert not at.exception, at.exception
    assert "couldn't load your saved data" in at.error[0].value
    assert not any(field.label == "Pet name" for field in at.text_input)


def test_weekday_owner_can_add_tasks_any_day_and_schedule_defaults_to_weekday(db_url):
    """Regression test for the 'can't add tasks on a Sunday' bug.

    Runs the same way no matter what day the tests run on.
    """
    at = _app(db_url, auth=False).run()
    at.selectbox(key="days_preset").select("Weekdays (Mon–Fri)").run()
    _add_pet(at, "Bella")

    _by_label(at.text_input, "Task").input("Morning food")
    _by_label(at.text_input, "Time").input("10:00 AM")
    _by_label(at.button, "Add task").click().run()

    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert [t.task for t in at.session_state["owner"].todos] == ["Morning food"]

    # The schedule date starts on a weekday, so it can always be generated.
    plan_date = _by_label(at.date_input, "Schedule for").value
    assert plan_date.weekday() < 5
    _by_label(at.button, "Generate schedule").click().run()
    assert at.table[0].value["task"].tolist() == ["Morning food"]


def test_done_then_undo(db_url):
    at = _app(db_url, auth=False).run()
    _add_pet(at, "Bella")
    _by_label(at.button, "Add task").click().run()

    _by_label(at.button, "Done").click().run()
    assert at.session_state["owner"].todos[0].completed_on is not None
    assert any(button.label == "Undo" for button in at.button)

    _by_label(at.button, "Undo").click().run()
    assert at.session_state["owner"].todos[0].completed_on is None


# --- Ask PawsCare+ (Claude) ---------------------------------------------


def _ai_app(db_url, fake, *, api_key, daily_limit=20):
    """The app with an [anthropic] secret, using a fake Claude client.

    Each test passes its own api_key so Streamlit's cached client from one
    test isn't reused by another.
    """
    at = _app(db_url, auth=False)
    at.secrets["anthropic"] = {"api_key": api_key, "daily_limit": daily_limit}
    return at, mock.patch("anthropic.Anthropic", return_value=fake)


def _ask(at, question):
    _by_label(at.text_area, "Ask about your pet's aftercare").input(question)
    _by_label(at.button, "Ask").click().run()
    assert not at.exception, at.exception


def test_ai_tab_is_hidden_without_an_api_key(db_url):
    at = _app(db_url, auth=False).run()

    assert not any(t.label == "Ask about your pet's aftercare" for t in at.text_area)
    assert any(f.label == "Search the guides by keyword" for f in at.text_input)


def test_ask_shows_answer_and_its_sources(db_url):
    from tests.test_ai import FakeClaude

    fake = FakeClaude(
        {"covered": True, "answer": "Check the incision twice a day [1].", "source_numbers": [1], "call_vet": False}
    )
    at, patch = _ai_app(db_url, fake, api_key="key-answer")
    with patch:
        at.run()
        _ask(at, "How often should I check the incision?")

    assert len(fake.calls) == 1
    assert any(i.value == "Check the incision twice a day [1]." for i in at.info)
    assert any(e.label == "Where this answer comes from" for e in at.expander)
    assert any(c.value.startswith("Sources: [") for c in at.caption)
    assert any("19 of 20 questions left today" in c.value for c in at.caption)


def test_call_vet_answers_show_a_clear_warning(db_url):
    from tests.test_ai import FakeClaude

    fake = FakeClaude(
        {"covered": True, "answer": "Repeated vomiting needs a vet [1].", "source_numbers": [1], "call_vet": True}
    )
    at, patch = _ai_app(db_url, fake, api_key="key-vet")
    with patch:
        at.run()
        _ask(at, "My dog keeps vomiting after surgery")

    assert any("Call your vet now" in e.value for e in at.error)


def test_daily_limit_stops_calls_to_claude(db_url):
    from tests.test_ai import FakeClaude

    fake = FakeClaude({"covered": False, "answer": "Ask your vet.", "source_numbers": [], "call_vet": False})
    at, patch = _ai_app(db_url, fake, api_key="key-limit", daily_limit=2)
    with patch:
        at.run()
        _ask(at, "question one")
        _ask(at, "question two")
        _ask(at, "question three")

    assert len(fake.calls) == 2  # the third never reached Claude
    assert any("used all 2 questions" in w.value for w in at.warning)


def test_ai_outage_shows_a_friendly_error_and_does_not_count(db_url):
    from tests.test_ai import FakeClaude

    fake = FakeClaude(error=RuntimeError("503 overloaded"))
    at, patch = _ai_app(db_url, fake, api_key="key-outage")
    with patch:
        at.run()
        _ask(at, "incision care")

    assert any("isn't available right now" in e.value for e in at.error)
    assert any("20 of 20 questions left today" in c.value for c in at.caption)


# --- A pet's vet instructions -------------------------------------------


def _save_pasted_note(at, title, text):
    _by_label(at.text_input, "Title").input(title)
    _by_label(at.text_area, "Paste the instructions").input(text)
    _by_label(at.button, "Save instructions").click().run()
    assert not at.exception, at.exception


def test_paste_vet_instructions_saves_and_survives_reload(db_url):
    at = _app(db_url, auth=False).run()
    _add_pet(at, "Bella")

    _save_pasted_note(at, "Spay discharge", "Keep the cone on for 14 days. Carprofen twice daily.")

    note = at.session_state["owner"].pets[0].vet_notes[0]
    assert note.title == "Spay discharge"
    assert any("Bella's vet instructions (1)" == e.label for e in at.expander)

    at = _app(db_url, auth=False).run()  # a new session loads it from the database
    assert at.session_state["owner"].pets[0].vet_notes[0].text.startswith("Keep the cone")


def test_empty_vet_instructions_show_an_error(db_url):
    at = _app(db_url, auth=False).run()
    _add_pet(at, "Bella")

    _save_pasted_note(at, "Nothing", "   ")

    assert any("empty" in e.value for e in at.error)
    assert at.session_state["owner"].pets[0].vet_notes == []


def test_delete_vet_instructions(db_url):
    at = _app(db_url, auth=False).run()
    _add_pet(at, "Bella")
    _save_pasted_note(at, "Spay discharge", "Cone for 14 days.")

    _by_label(at.button, "Delete").click().run()  # the only Delete button: no tasks yet

    assert at.session_state["owner"].pets[0].vet_notes == []


def test_asking_about_a_pet_sends_its_vet_instructions(db_url):
    from tests.test_ai import FakeClaude

    fake = FakeClaude({"covered": True, "answer": "14 days.", "source_numbers": [1], "call_vet": False})
    at, patch = _ai_app(db_url, fake, api_key="key-vet-notes")
    with patch:
        at.run()
        _add_pet(at, "Bella")
        _save_pasted_note(at, "Spay discharge", "Keep the cone on for 14 days.")
        _by_label(at.selectbox, "Which pet is this about?").select(0).run()  # Bella
        _ask(at, "How long does the cone stay on?")

    message = fake.calls[0]["messages"][0]["content"]
    assert "VET INSTRUCTIONS: Bella's vet instructions" in message
    assert "Keep the cone on for 14 days." in message
    assert any(e.label == "Where this answer comes from" for e in at.expander)
