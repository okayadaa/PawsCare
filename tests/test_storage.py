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
