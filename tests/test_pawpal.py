from datetime import date, time
from pathlib import Path

import pytest

from pawpal_system import (
    AvailabilityError,
    AvailabilityWindow,
    DayPlan,
    DocSearchIndex,
    Owner,
    PetInfo,
    ScheduleConflictError,
    Scheduler,
    ToDo,
    WEEKDAYS,
    availability_conflicts,
    owner_from_dict,
    owner_to_dict,
    build_doc_search_index,
    get_aftercare_headings,
    load_aftercare_sections,
    search_aftercare,
    search_aftercare_docs,
    task_schedule_conflicts,
)

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
# A fixed Monday, so tests that use a weekday-only window pass on any day.
MONDAY = date(2026, 6, 22)


def _weekday_availability() -> AvailabilityWindow:
    return AvailabilityWindow(WEEKDAYS, time(9, 0), time(18, 0))


def test_mark_complete_changes_task_status():
    todo = ToDo("Morning walk", 3, 30, "08:00")

    assert todo.status == "pending"

    todo.mark_complete()

    assert todo.status == "complete"


def test_adding_task_increases_pet_task_count():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)

    assert len(owner.get_tasks_for_pet(buddy)) == 0

    owner.add_todo(ToDo("Morning walk", 3, 30, "10:00", buddy), MONDAY)
    assert len(owner.get_tasks_for_pet(buddy)) == 1

    owner.add_todo(ToDo("Feed breakfast", 2, 15, "11:00", buddy), MONDAY)
    assert len(owner.get_tasks_for_pet(buddy)) == 2


def test_add_todo_blocks_outside_availability():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)

    with pytest.raises(AvailabilityError, match="before your window"):
        owner.add_todo(ToDo("Morning walk", 3, 30, "08:00", buddy), MONDAY)

    assert len(owner.todos) == 0


def test_generate_day_plan_blocks_when_task_conflicts():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    owner.todos.append(ToDo("Morning walk", 3, 30, "08:00", buddy))

    with pytest.raises(AvailabilityError, match="Cannot build schedule"):
        owner.generate_day_plan(date(2026, 6, 22))


def test_availability_conflict_before_window():
    window = _weekday_availability()
    conflicts = availability_conflicts(
        window, date(2026, 6, 22), "08:00", 30, "Morning walk"
    )
    assert any("before your window" in message for message in conflicts)


def test_availability_conflict_after_window():
    window = _weekday_availability()
    conflicts = availability_conflicts(
        window, date(2026, 6, 22), "18:00", 25, "Evening grooming"
    )
    assert any("after your window" in message for message in conflicts)


def test_availability_no_conflict_inside_window():
    window = _weekday_availability()
    conflicts = availability_conflicts(
        window, date(2026, 6, 22), "12:00", 20, "Play session"
    )
    assert conflicts == []


def test_sort_by_priority_orders_high_before_low():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    owner.add_todo(ToDo("Afternoon play", 1, 20, "14:00", buddy), MONDAY)
    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy), MONDAY)
    owner.add_todo(ToDo("Lunch feeding", 2, 15, "12:00", buddy), MONDAY)

    plan = DayPlan(MONDAY, owner)
    plan.sort_by_priority()

    assert [todo.task for todo in plan.tasks] == [
        "Morning walk",
        "Lunch feeding",
        "Afternoon play",
    ]


def test_sort_by_time_orders_tasks_chronologically():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    owner.add_todo(ToDo("Afternoon play", 1, 20, "14:00", buddy), MONDAY)
    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy), MONDAY)
    owner.add_todo(ToDo("Lunch feeding", 2, 15, "12:00", buddy), MONDAY)

    sorted_tasks = Scheduler.sort_by_time(owner.todos)

    assert [todo.task for todo in sorted_tasks] == [
        "Morning walk",
        "Lunch feeding",
        "Afternoon play",
    ]


def test_filter_tasks_by_status():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    pending = ToDo("Morning walk", 3, 30, "10:00", buddy)
    done = ToDo("Feed breakfast", 2, 15, "11:00", buddy)
    done.mark_complete()
    owner.todos.extend([pending, done])

    pending_tasks = Scheduler.filter_tasks(owner.todos, status="pending")
    complete_tasks = Scheduler.filter_tasks(owner.todos, status="complete")

    assert [todo.task for todo in pending_tasks] == ["Morning walk"]
    assert [todo.task for todo in complete_tasks] == ["Feed breakfast"]


def test_filter_tasks_by_pet_name():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    luna = PetInfo("Luna", 5, "Siamese")
    owner.add_pet(buddy)
    owner.add_pet(luna)
    owner.add_todo(ToDo("Morning walk", 3, 30, "10:00", buddy), MONDAY)
    owner.add_todo(ToDo("Play session", 1, 20, "12:00", luna), MONDAY)

    buddy_tasks = Scheduler.filter_tasks(owner.todos, pet_name="Buddy")

    assert len(buddy_tasks) == 1
    assert buddy_tasks[0].task == "Morning walk"


def test_task_schedule_conflicts_detects_overlap():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    walk = ToDo("Morning walk", 3, 30, "10:00", buddy)
    grooming = ToDo("Grooming", 2, 30, "10:15", buddy)

    conflicts = task_schedule_conflicts([walk, grooming], date(2026, 6, 22))

    assert len(conflicts) == 1
    assert "overlaps with" in conflicts[0]


def test_add_todo_blocks_overlapping_tasks():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    owner.add_todo(ToDo("Morning walk", 3, 30, "10:00", buddy), MONDAY)

    with pytest.raises(ScheduleConflictError, match="overlaps with"):
        owner.add_todo(ToDo("Grooming", 2, 30, "10:15", buddy), MONDAY)

    assert len(owner.todos) == 1


def test_get_aftercare_headings_returns_unique_headings():
    headings = get_aftercare_headings(DOCS_DIR)

    assert "Wound Care Basics" in headings
    assert "First 24 Hours" in headings
    assert len(headings) == len({heading.lower() for heading in headings})


def test_search_aftercare_docs_finds_matching_section():
    results = search_aftercare_docs("##Wound Care Basics", DOCS_DIR)

    assert len(results) >= 1
    assert results[0].heading == "Wound Care Basics"
    assert "Check the wound **twice daily**" in results[0].content
    assert results[0].source_file == "wound-injury-aftercare.md"


def test_search_aftercare_docs_is_case_insensitive():
    results = search_aftercare_docs("##wound care basics", DOCS_DIR)

    assert len(results) >= 1
    assert results[0].heading == "Wound Care Basics"


def test_search_aftercare_docs_returns_empty_for_unknown_heading():
    results = search_aftercare_docs("##Unknown Section", DOCS_DIR)

    assert results == []


def test_doc_index_maps_terms_to_sections():
    doc_index = build_doc_search_index(DOCS_DIR)
    incision_sections = doc_index.index.get("incision", {})

    assert any(
        doc_index.sections[section_idx].heading == "Incision Care"
        for section_idx in incision_sections
    )


def test_search_ranks_relevant_section():
    results = search_aftercare_docs("incision care", DOCS_DIR)

    assert len(results) >= 1
    assert results[0].heading == "Incision Care"


def test_search_multi_word_query():
    results = search_aftercare_docs("call vet bleeding", DOCS_DIR)

    assert len(results) >= 1
    headings = {section.heading for section in results}
    assert headings & {
        "Call the Vet If You See",
        "Call the Vet Immediately If",
    }


def test_search_returns_empty_for_no_matches():
    results = search_aftercare_docs("zzzzunknown", DOCS_DIR)

    assert results == []


def test_search_respects_top_k():
    results = search_aftercare_docs("care", DOCS_DIR, top_k=2)

    assert len(results) <= 2


def test_search_spay_query_prefers_spay_neuter_doc():
    query = "what's the steps for first 24 hours for pets being spay?"
    results = search_aftercare_docs(query, DOCS_DIR)

    assert len(results) >= 1
    assert results[0].source_file == "spay-neuter-aftercare.md"
    assert results[0].heading == "First 24 Hours"


def test_search_spay_neuter_slash_query_prefers_spay_neuter_doc():
    query = "what's the steps for first 24 hours for pets being spay/neuter?"
    results = search_aftercare_docs(query, DOCS_DIR)

    assert len(results) >= 1
    assert results[0].source_file == "spay-neuter-aftercare.md"
    assert results[0].heading == "First 24 Hours"


def test_search_dedupes_by_source_file():
    results = search_aftercare_docs("care", DOCS_DIR, top_k=5)

    assert len(results) <= 5
    assert len({section.source_file for section in results}) == len(results)


def test_search_phrase_boost_prefers_matching_heading():
    results = search_aftercare_docs("first 24 hours", DOCS_DIR, top_k=5)

    assert len(results) >= 2
    assert all(section.heading == "First 24 Hours" for section in results[:2])


def test_search_not_confident_for_unknown_topic():
    query = "How do I clean properly my pet's ears"
    response = search_aftercare(query, DOCS_DIR)

    assert response.confident is False
    assert response.matches == []


def test_search_confident_for_known_topic():
    confident_queries = [
        "incision care",
        "call vet bleeding",
        "vaccination swelling",
    ]
    for query in confident_queries:
        response = search_aftercare(query, DOCS_DIR)
        assert response.confident is True, query
        assert len(response.matches) >= 1, query


def test_search_not_confident_for_gibberish():
    response = search_aftercare("zzzzunknown", DOCS_DIR)

    assert response.confident is False
    assert response.matches == []


def test_generate_day_plan_sorts_by_time():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    owner.add_todo(ToDo("Afternoon play", 1, 20, "14:00", buddy), MONDAY)
    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy), MONDAY)

    plan = owner.generate_day_plan(MONDAY)

    assert [todo.task for todo in plan.tasks] == ["Morning walk", "Afternoon play"]
    # Building a plan must not reorder the owner's own task list.
    assert [todo.task for todo in owner.todos] == ["Afternoon play", "Morning walk"]


def test_get_pet_info_describes_pet():
    assert PetInfo("Buddy", 3, "Golden Retriever", "dog").get_pet_info() == (
        "Buddy (dog, Golden Retriever), 3 years old"
    )
    assert PetInfo("Luna", 1).get_pet_info() == "Luna, 1 year old"


def test_add_pet_rejects_duplicate_and_empty_names():
    owner = Owner("Alex", _weekday_availability())
    owner.add_pet(PetInfo("Buddy", 3))

    with pytest.raises(ValueError, match="already have a pet"):
        owner.add_pet(PetInfo("buddy", 1))
    with pytest.raises(ValueError, match="can't be empty"):
        owner.add_pet(PetInfo("   ", 1))

    assert len(owner.pets) == 1


def test_remove_todo_deletes_only_that_task():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3)
    owner.add_pet(buddy)
    walk = ToDo("Morning walk", 3, 30, "10:00", buddy)
    feed = ToDo("Feed breakfast", 2, 15, "11:00", buddy)
    owner.add_todo(walk, MONDAY)
    owner.add_todo(feed, MONDAY)

    owner.remove_todo(walk)

    assert owner.todos == [feed]


def test_day_plan_totals_count_only_its_own_tasks():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3)
    owner.add_pet(buddy)
    walk = ToDo("Morning walk", 3, 30, "10:00", buddy)
    feed = ToDo("Feed breakfast", 2, 15, "11:00", buddy)
    owner.add_todo(walk, MONDAY)
    owner.add_todo(feed, MONDAY)
    feed.mark_complete()

    plan = owner.generate_day_plan(MONDAY)
    assert plan.total_duration == 45
    assert plan.remaining_duration == 30

    plan.tasks = Scheduler.filter_tasks(plan.tasks, status="pending")
    assert plan.total_duration == 30


def test_display_schedule_returns_rows_in_time_order():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3)
    owner.add_pet(buddy)
    owner.add_todo(ToDo("Afternoon play", 1, 20, "14:00", buddy), MONDAY)
    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy), MONDAY)

    rows = owner.generate_day_plan(MONDAY).display_schedule()

    assert [row["task"] for row in rows] == ["Morning walk", "Afternoon play"]
    assert rows[0] == {
        "time": "9:00 AM",
        "pet": "Buddy",
        "task": "Morning walk",
        "priority": "high",
        "duration_minutes": 30,
        "status": "pending",
    }


def test_save_and_load_round_trip_keeps_everything():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever", "dog")
    luna = PetInfo("Luna", 5, "Siamese", "cat")
    owner.add_pet(buddy)
    owner.add_pet(luna)
    owner.add_todo(ToDo("Morning walk", 3, 30, "10:00", buddy), MONDAY)
    meds = ToDo("Give meds", 3, 5, "12:00", luna)
    owner.add_todo(meds, MONDAY)
    meds.mark_complete()

    restored = owner_from_dict(owner_to_dict(owner))

    assert restored.name == "Alex"
    assert restored.availability == owner.availability
    assert [pet.get_pet_info() for pet in restored.pets] == [
        pet.get_pet_info() for pet in owner.pets
    ]
    assert owner_to_dict(restored) == owner_to_dict(owner)
    # Tasks point at the restored pet objects, so per-pet lookups still work.
    assert [t.task for t in restored.get_tasks_for_pet(restored.pets[1])] == ["Give meds"]


def test_load_rejects_files_that_are_not_pawpal_saves():
    with pytest.raises(ValueError, match="isn't a PawPal"):
        owner_from_dict({"hello": "world"})

    broken = owner_to_dict(Owner("Alex", _weekday_availability()))
    del broken["pets"]
    with pytest.raises(ValueError, match="missing data"):
        owner_from_dict(broken)


def test_load_rejects_task_for_unknown_pet():
    data = owner_to_dict(Owner("Alex", _weekday_availability()))
    data["todos"].append(
        {
            "task": "Walk",
            "priority": 1,
            "duration_minutes": 10,
            "time": "10:00",
            "pet": "Ghost",
            "status": "pending",
        }
    )
    with pytest.raises(ValueError, match="unknown pet"):
        owner_from_dict(data)
