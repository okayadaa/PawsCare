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
