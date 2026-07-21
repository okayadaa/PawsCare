from datetime import date, time

import streamlit as st
from pathlib import Path

from pawpal_system import (
    DAY_PRESETS,
    AvailabilityError,
    AvailabilityWindow,
    DocSearchIndex,
    Owner,
    PetInfo,
    ScheduleConflictError,
    Scheduler,
    ToDo,
    WEEKDAYS,
    format_time,
    load_aftercare_sections,
    parse_task_time,
    search_aftercare,
)

DOCS_DIR = Path(__file__).resolve().parent / "docs"


def _docs_cache_key(docs_dir: Path) -> str:
    return str(
        sorted((path.name, path.stat().st_mtime) for path in docs_dir.glob("*.md"))
    )


@st.cache_data
def _cached_doc_index(docs_dir: str, _cache_key: str) -> DocSearchIndex:
    return DocSearchIndex.build(load_aftercare_sections(docs_dir))

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

PRIORITY_MAP = {"low": 1, "medium": 2, "high": 3}
PRIORITY_LABELS = {v: k for k, v in PRIORITY_MAP.items()}
SPECIES_OPTIONS = ["dog", "cat", "other"]
DAY_PRESET_LABELS = list(DAY_PRESETS.keys())


def parse_time_field(label: str, value: time, key: str) -> time:
    text = st.text_input(
        label,
        value=format_time(value),
        key=key,
        help="12-hour format with AM/PM, e.g. 9:00 AM",
    )
    try:
        return parse_task_time(text)
    except ValueError:
        st.warning(f"{label}: use a time like 9:00 AM or 5:30 PM.")
        return value


def preset_label_for_days(days: set[int]) -> str:
    for label, preset_days in DAY_PRESETS.items():
        if days == preset_days:
            return label
    return DAY_PRESET_LABELS[0]


if "owner" not in st.session_state:
    st.session_state.owner = Owner(
        "Jordan",
        AvailabilityWindow(WEEKDAYS, time(9, 0), time(18, 0)),
    )

owner = st.session_state.owner

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ starter app.
"""
)


st.divider()

st.subheader("Owner")
owner_col1, owner_col2 = st.columns(2)
with owner_col1:
    owner_name = st.text_input("Owner name", value=owner.name)
with owner_col2:
    days_preset = st.selectbox(
        "Available days",
        DAY_PRESET_LABELS,
        index=DAY_PRESET_LABELS.index(preset_label_for_days(owner.availability.days)),
    )

avail_col1, avail_col2 = st.columns(2)
with avail_col1:
    avail_start = parse_time_field(
        "Available from", owner.availability.start, "avail_start"
    )
with avail_col2:
    avail_end = parse_time_field(
        "Available until", owner.availability.end, "avail_end"
    )

if owner_name != owner.name:
    owner.name = owner_name

new_availability = AvailabilityWindow(DAY_PRESETS[days_preset], avail_start, avail_end)
if (
    owner.availability.days != new_availability.days
    or owner.availability.start != new_availability.start
    or owner.availability.end != new_availability.end
):
    owner.availability = new_availability

st.subheader("Add a Pet")
pet_col1, pet_col2, pet_col3 = st.columns(3)
with pet_col1:
    new_pet_name = st.text_input("Pet name", value="Mochi", key="new_pet_name")
with pet_col2:
    new_pet_age = st.number_input("Age", min_value=0, max_value=30, value=2, key="new_pet_age")
with pet_col3:
    new_pet_breed = st.selectbox("Species", SPECIES_OPTIONS, key="new_pet_breed")

if st.button("Add pet"):
    owner.add_pet(PetInfo(new_pet_name, int(new_pet_age), new_pet_breed))
    st.success(f"Added {new_pet_name!r} to {owner.name}'s pets.")

if owner.pets:
    st.write("Registered pets:")
    for registered_pet in owner.pets:
        pet_info = registered_pet.get_pet_info()
        st.write(pet_info if pet_info else f"- {registered_pet.name} ({registered_pet.breed}, age {registered_pet.age})")
else:
    st.info("No pets yet. Add one above.")

st.divider()

st.subheader("Schedule a Task")
st.caption("Tasks are added to the owner's list and linked to a registered pet.")

if not owner.pets:
    st.warning("Add at least one pet before scheduling tasks.")
else:
    task_col1, task_col2 = st.columns(2)
    with task_col1:
        task_pet_index = st.selectbox(
            "Pet",
            range(len(owner.pets)),
            format_func=lambda i: owner.pets[i].name,
        )
        task_title = st.text_input("Task title", value="Morning walk")
        availability = st.text_input(
            "Time",
            value="10:00 AM",
            help="12-hour format with AM/PM, e.g. 10:00 AM or 5:30 PM",
        )
    with task_col2:
        duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
        priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)

    selected_pet = owner.pets[task_pet_index]

    if st.button("Add task"):
        new_todo = ToDo(
            task_title,
            PRIORITY_MAP[priority],
            int(duration),
            availability,
            selected_pet,
        )
        try:
            owner.add_todo(new_todo, date.today())
        except (AvailabilityError, ScheduleConflictError) as exc:
            st.error(str(exc))
        else:
            st.success(f"Scheduled {task_title!r} for {selected_pet.name}.")

    pet_tasks = owner.get_tasks_for_pet(selected_pet)
    if pet_tasks:
        st.write(f"Tasks for {selected_pet.name}:")
        for index, todo in enumerate(pet_tasks):
            task_col, action_col = st.columns([4, 1])
            with task_col:
                st.write(
                    f"**{todo.task}** at {format_time(todo.time)} "
                    f"({todo.duration_minutes} min, {todo.status})"
                )
            with action_col:
                if todo.status == "pending" and st.button(
                    "Done", key=f"complete_{selected_pet.name}_{index}"
                ):
                    todo.mark_complete()
                    st.rerun()
        st.table(
            [
                {
                    "task": todo.task,
                    "time": format_time(todo.time),
                    "duration_minutes": todo.duration_minutes,
                    "priority": PRIORITY_LABELS.get(todo.priority, todo.priority),
                    "status": todo.status,
                }
                for todo in pet_tasks
            ]
        )
    elif owner.todos:
        st.info(f"No tasks scheduled for {selected_pet.name} yet.")
    else:
        st.info("No tasks yet. Add one above.")

st.divider()

st.subheader("Build Schedule")
st.caption("Generates a day plan sorted by time.")

filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    status_filter = st.selectbox(
        "Filter by status",
        ["all", "pending", "complete"],
        index=0,
    )
with filter_col2:
    pet_filter = st.selectbox(
        "Filter by pet",
        ["all"] + [pet.name for pet in owner.pets],
        index=0,
    )

if st.button("Generate schedule"):
    all_tasks = owner.get_all_pet_tasks()
    if not all_tasks:
        st.warning("Add at least one task before generating a schedule.")
    else:
        try:
            plan = owner.generate_day_plan(date.today())
        except (AvailabilityError, ScheduleConflictError) as exc:
            st.error(str(exc))
        else:
            filtered_tasks = Scheduler.filter_tasks(
                owner.todos,
                status=None if status_filter == "all" else status_filter,
                pet_name=None if pet_filter == "all" else pet_filter,
            )
            display_tasks = Scheduler.sort_by_time(filtered_tasks)
            st.success(
                f"Schedule for {plan.date} — {plan.total_duration} minutes total "
                f"({len(display_tasks)} task{'s' if len(display_tasks) != 1 else ''})"
            )
            st.table(
                [
                    {
                        "time": format_time(todo.time),
                        "pet": todo.pet.name if todo.pet else "—",
                        "task": todo.task,
                        "priority": PRIORITY_LABELS.get(todo.priority, todo.priority),
                        "duration_minutes": todo.duration_minutes,
                        "status": todo.status,
                    }
                    for todo in display_tasks
                ]
            )

st.divider()

st.subheader("Pet Documentation")
st.caption("Search aftercare instructions by keyword.")

doc_query = st.text_input(
    "Search pet documentation",
    placeholder="e.g. incision care, vomiting, bandage",
    key="doc_search_query",
)

if doc_query.strip():
    doc_index = _cached_doc_index(str(DOCS_DIR), _docs_cache_key(DOCS_DIR))
    response = search_aftercare(doc_query, DOCS_DIR, top_k=5, index=doc_index)
    if not response.confident:
        st.warning(
            "I'm not so sure — I couldn't find that topic in the aftercare docs."
        )
    elif not response.matches:
        st.info("No matching sections found.")
    else:
        for match in response.matches:
            section = match.section
            st.markdown(f"**Source:** `{section.source_file}`")
            st.markdown(f"### {section.heading}")
            st.markdown(section.content)
            st.divider()
