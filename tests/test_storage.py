from datetime import date, time

import pytest

from pawpal_system import ALL_DAYS, AvailabilityWindow, Owner, PetInfo, ToDo, owner_to_dict
from storage import delete_owner, load_owner, make_engine, save_owner

MONDAY = date(2026, 6, 22)


@pytest.fixture
def engine(tmp_path):
    # A throwaway SQLite file for each test, so tests never touch real data.
    return make_engine(f"sqlite:///{tmp_path / 'test.db'}")


def _sample_owner(name: str = "Sam", pet_name: str = "Mochi") -> Owner:
    owner = Owner(name, AvailabilityWindow(set(ALL_DAYS), time(8, 0), time(20, 0)))
    pet = PetInfo(pet_name, 2, "Shiba Inu", "dog")
    owner.add_pet(pet)
    owner.add_todo(ToDo("Morning walk", 3, 30, "9:00 AM", pet))
    return owner


def test_load_returns_none_for_new_user(engine):
    assert load_owner(engine, "nobody") is None


def test_save_then_load_returns_same_data(engine):
    owner = _sample_owner()
    owner.todos[0].mark_complete()

    save_owner(engine, "user-1", "sam@example.com", owner)
    loaded = load_owner(engine, "user-1")

    assert loaded is not None
    assert owner_to_dict(loaded) == owner_to_dict(owner)


def test_saving_again_updates_instead_of_duplicating(engine):
    owner = _sample_owner()
    save_owner(engine, "user-1", "sam@example.com", owner)

    owner.add_pet(PetInfo("Luna", 5, "Siamese", "cat"))
    save_owner(engine, "user-1", "sam@example.com", owner)

    loaded = load_owner(engine, "user-1")
    assert [pet.name for pet in loaded.pets] == ["Mochi", "Luna"]


def test_users_only_see_their_own_data(engine):
    save_owner(engine, "user-1", "sam@example.com", _sample_owner("Sam", "Mochi"))
    save_owner(engine, "user-2", "ada@example.com", _sample_owner("Ada", "Biscuit"))

    assert load_owner(engine, "user-1").pets[0].name == "Mochi"
    assert load_owner(engine, "user-2").pets[0].name == "Biscuit"


def test_delete_removes_only_that_user(engine):
    save_owner(engine, "user-1", "sam@example.com", _sample_owner("Sam", "Mochi"))
    save_owner(engine, "user-2", "ada@example.com", _sample_owner("Ada", "Biscuit"))

    delete_owner(engine, "user-1")

    assert load_owner(engine, "user-1") is None
    assert load_owner(engine, "user-2") is not None


def test_data_survives_reconnecting(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    save_owner(make_engine(url), "user-1", None, _sample_owner())

    # A brand-new connection, like the app restarting.
    assert load_owner(make_engine(url), "user-1").pets[0].name == "Mochi"


def test_ai_usage_counts_per_user_per_day(engine):
    from datetime import date, timedelta

    from storage import ai_uses_on, record_ai_use

    today = date(2026, 10, 13)
    assert ai_uses_on(engine, "user-1", today) == 0

    record_ai_use(engine, "user-1", today)
    record_ai_use(engine, "user-1", today)
    record_ai_use(engine, "user-2", today)
    record_ai_use(engine, "user-1", today + timedelta(days=1))

    assert ai_uses_on(engine, "user-1", today) == 2
    assert ai_uses_on(engine, "user-2", today) == 1
    assert ai_uses_on(engine, "user-1", today + timedelta(days=1)) == 1


def test_delete_owner_also_clears_ai_usage(engine):
    from datetime import date

    from storage import ai_uses_on, record_ai_use

    today = date(2026, 10, 13)
    save_owner(engine, "user-1", None, _sample_owner())
    record_ai_use(engine, "user-1", today)

    delete_owner(engine, "user-1")

    assert ai_uses_on(engine, "user-1", today) == 0
