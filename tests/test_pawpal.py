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
    build_doc_search_index,
    get_aftercare_headings,
    load_aftercare_sections,
    search_aftercare_docs,
    task_schedule_conflicts,
)

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


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

    owner.add_todo(ToDo("Morning walk", 3, 30, "10:00", buddy))
    assert len(owner.get_tasks_for_pet(buddy)) == 1

    owner.add_todo(ToDo("Feed breakfast", 2, 15, "11:00", buddy))
    assert len(owner.get_tasks_for_pet(buddy)) == 2


def test_add_todo_blocks_outside_availability():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)

    with pytest.raises(AvailabilityError, match="before your window"):
        owner.add_todo(ToDo("Morning walk", 3, 30, "08:00", buddy))

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
    owner.add_todo(ToDo("Afternoon play", 1, 20, "14:00", buddy))
    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy))
    owner.add_todo(ToDo("Lunch feeding", 2, 15, "12:00", buddy))

    DayPlan(date(2026, 6, 22), owner).sort_by_priority()

    assert [todo.task for todo in owner.todos] == [
        "Morning walk",
        "Lunch feeding",
        "Afternoon play",
    ]


def test_sort_by_time_orders_tasks_chronologically():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    owner.add_todo(ToDo("Afternoon play", 1, 20, "14:00", buddy))
    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy))
    owner.add_todo(ToDo("Lunch feeding", 2, 15, "12:00", buddy))

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
    owner.add_todo(ToDo("Morning walk", 3, 30, "10:00", buddy))
    owner.add_todo(ToDo("Play session", 1, 20, "12:00", luna))

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
    owner.add_todo(ToDo("Morning walk", 3, 30, "10:00", buddy))

    with pytest.raises(ScheduleConflictError, match="overlaps with"):
        owner.add_todo(ToDo("Grooming", 2, 30, "10:15", buddy))

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


def test_generate_day_plan_sorts_by_time():
    owner = Owner("Alex", _weekday_availability())
    buddy = PetInfo("Buddy", 3, "Golden Retriever")
    owner.add_pet(buddy)
    owner.add_todo(ToDo("Afternoon play", 1, 20, "14:00", buddy))
    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy))

    owner.generate_day_plan(date(2026, 6, 22))

    assert [todo.task for todo in owner.todos] == ["Morning walk", "Afternoon play"]
