import json
from datetime import date, time
from pathlib import Path

import streamlit as st

from pawpal_system import (
    ALL_DAYS,
    DAY_PRESETS,
    PRIORITY_LABELS,
    PRIORITY_MAP,
    AvailabilityError,
    AvailabilityWindow,
    DocSearchIndex,
    Owner,
    PetInfo,
    ScheduleConflictError,
    Scheduler,
    ToDo,
    format_time,
    load_aftercare_sections,
    owner_from_dict,
    owner_to_dict,
    parse_task_time,
    search_aftercare,
)

DOCS_DIR = Path(__file__).resolve().parent / "docs"
SPECIES_OPTIONS = ["dog", "cat", "rabbit", "bird", "other"]
DAY_PRESET_LABELS = list(DAY_PRESETS.keys())


def _docs_cache_key(docs_dir: Path) -> str:
    return str(
        sorted((path.name, path.stat().st_mtime) for path in docs_dir.glob("*.md"))
    )


@st.cache_data
def _cached_doc_index(docs_dir: str, _cache_key: str) -> DocSearchIndex:
    return DocSearchIndex.build(load_aftercare_sections(docs_dir))


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


def new_owner() -> Owner:
    return Owner("", AvailabilityWindow(set(ALL_DAYS), time(8, 0), time(20, 0)))


def reset_owner_widgets() -> None:
    """Clear widget values so they re-read from the newly loaded owner."""
    for key in ("owner_name", "days_preset", "avail_start", "avail_end"):
        st.session_state.pop(key, None)


st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

if "owner" not in st.session_state:
    st.session_state.owner = new_owner()

owner: Owner = st.session_state.owner

# ---------------------------------------------------------------------------
# Sidebar: save and restore
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Save your plan")
    st.caption(
        "PawPal+ doesn't store your data on a server. Download a backup to "
        "keep your pets and tasks, then upload it next time."
    )
    st.download_button(
        "Download backup",
        data=json.dumps(owner_to_dict(owner), indent=2),
        file_name="pawpal_backup.json",
        mime="application/json",
        use_container_width=True,
    )

    uploaded = st.file_uploader("Restore from a backup", type="json")
    if uploaded is not None and st.session_state.get("loaded_file_id") != uploaded.file_id:
        try:
            st.session_state.owner = owner_from_dict(json.loads(uploaded.getvalue()))
        except (ValueError, json.JSONDecodeError) as exc:
            st.error(f"Couldn't load that file: {exc}")
        else:
            st.session_state.loaded_file_id = uploaded.file_id
            reset_owner_widgets()
            st.rerun()
    if st.session_state.get("loaded_file_id") and uploaded is not None:
        st.success("Backup loaded.")

    st.divider()
    if st.button("Start over", use_container_width=True):
        st.session_state.owner = new_owner()
        st.session_state.pop("loaded_file_id", None)
        reset_owner_widgets()
        st.rerun()

# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
logo_col, title_col = st.columns([1, 8], vertical_alignment="center")

with logo_col:
    st.image("assets/logo-image.png", width=80)

with title_col:
    st.title("PawsCare+")
st.markdown(
    "Plan your pets' daily care. Add your pets and their tasks (walks, "
    "feeding, medication, grooming), and PawPal+ builds a schedule that fits "
    "the hours you're available and warns you about overlapping tasks."
)

st.divider()

st.subheader("You")
owner_col1, owner_col2 = st.columns(2)
with owner_col1:
    owner_name = st.text_input(
        "Your name", value=owner.name, key="owner_name", placeholder="e.g. Sam"
    )
with owner_col2:
    days_preset = st.selectbox(
        "Days you're available",
        DAY_PRESET_LABELS,
        index=DAY_PRESET_LABELS.index(preset_label_for_days(owner.availability.days)),
        key="days_preset",
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

owner.name = owner_name.strip()
if avail_end <= avail_start:
    st.warning("'Available until' should be later than 'Available from'.")
else:
    owner.availability = AvailabilityWindow(
        set(DAY_PRESETS[days_preset]), avail_start, avail_end
    )

st.subheader("Your pets")
with st.form("add_pet", clear_on_submit=True):
    pet_col1, pet_col2 = st.columns(2)
    with pet_col1:
        new_pet_name = st.text_input("Pet name", placeholder="e.g. Mochi")
        new_pet_species = st.selectbox("Species", SPECIES_OPTIONS)
    with pet_col2:
        new_pet_age = st.number_input("Age (years)", min_value=0, max_value=40, value=2)
        new_pet_breed = st.text_input("Breed (optional)", placeholder="e.g. Shiba Inu")
    if st.form_submit_button("Add pet"):
        try:
            owner.add_pet(
                PetInfo(
                    new_pet_name,
                    int(new_pet_age),
                    new_pet_breed.strip(),
                    new_pet_species,
                )
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"Added {new_pet_name.strip()}.")

if owner.pets:
    for registered_pet in owner.pets:
        st.write(f"- {registered_pet.get_pet_info()}")
else:
    st.info("No pets yet. Add one above.")

st.divider()

st.subheader("Schedule a task")
st.caption("Each task belongs to one pet and happens at a set time today.")

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
        task_title = st.text_input("Task", value="Morning walk")
        task_time = st.text_input(
            "Time",
            value="10:00 AM",
            help="12-hour format with AM/PM, e.g. 10:00 AM or 5:30 PM",
        )
    with task_col2:
        duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
        priority = st.selectbox("Priority", list(PRIORITY_MAP), index=2)

    selected_pet = owner.pets[task_pet_index]

    if st.button("Add task"):
        if not task_title.strip():
            st.error("Give the task a name.")
        else:
            new_todo = ToDo(
                task_title.strip(),
                PRIORITY_MAP[priority],
                int(duration),
                task_time,
                selected_pet,
            )
            try:
                owner.add_todo(new_todo, date.today())
            except (AvailabilityError, ScheduleConflictError) as exc:
                st.error(str(exc))
            else:
                st.success(f"Scheduled {task_title.strip()!r} for {selected_pet.name}.")

    pet_tasks = Scheduler.sort_by_time(owner.get_tasks_for_pet(selected_pet))
    if pet_tasks:
        st.write(f"Tasks for {selected_pet.name}:")
        for index, todo in enumerate(pet_tasks):
            task_col, done_col, delete_col = st.columns([5, 1, 1])
            with task_col:
                label = (
                    f"**{todo.task}** at {format_time(todo.time)} "
                    f"({todo.duration_minutes} min, "
                    f"{PRIORITY_LABELS.get(todo.priority, todo.priority)} priority)"
                )
                st.write(f"~~{label}~~ ✅" if todo.status == "complete" else label)
            with done_col:
                if todo.status == "pending" and st.button(
                    "Done", key=f"complete_{selected_pet.name}_{index}"
                ):
                    todo.mark_complete()
                    st.rerun()
            with delete_col:
                if st.button("Delete", key=f"delete_{selected_pet.name}_{index}"):
                    owner.remove_todo(todo)
                    st.rerun()
    else:
        st.info(f"No tasks scheduled for {selected_pet.name} yet.")

st.divider()

st.subheader("Today's schedule")
st.caption("All your tasks for today, in time order.")

filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    status_filter = st.selectbox("Show", ["all", "pending", "complete"], index=0)
with filter_col2:
    pet_filter = st.selectbox(
        "Pet",
        ["all"] + [pet.name for pet in owner.pets],
        index=0,
        key="schedule_pet_filter",
    )

if st.button("Generate schedule"):
    if not owner.get_all_pet_tasks():
        st.warning("Add at least one task before generating a schedule.")
    else:
        try:
            plan = owner.generate_day_plan(date.today())
        except (AvailabilityError, ScheduleConflictError) as exc:
            st.error(str(exc))
        else:
            plan.tasks = Scheduler.filter_tasks(
                plan.tasks,
                status=None if status_filter == "all" else status_filter,
                pet_name=None if pet_filter == "all" else pet_filter,
            )
            count = len(plan.tasks)
            if count == 0:
                st.info("No tasks match those filters.")
            else:
                st.success(
                    f"Schedule for {plan.date:%A, %B} {plan.date.day}: {count} "
                    f"task{'s' if count != 1 else ''}, {plan.total_duration} minutes "
                    f"total ({plan.remaining_duration} minutes still to do)."
                )
                st.table(plan.display_schedule())

st.divider()

st.subheader("Aftercare guides")
st.caption(
    "Search the built-in guides for spay/neuter, dental, wound, and vaccination "
    "aftercare. This is general information, not a substitute for your vet."
)

doc_query = st.text_input(
    "What do you want to know?",
    placeholder="e.g. incision care, vomiting, bandage",
    key="doc_search_query",
)

if doc_query.strip():
    doc_index = _cached_doc_index(str(DOCS_DIR), _docs_cache_key(DOCS_DIR))
    response = search_aftercare(doc_query, DOCS_DIR, top_k=5, index=doc_index)
    if not response.confident:
        st.warning(
            "I'm not so sure. I couldn't find that topic in the aftercare guides. "
            "If you're worried about your pet, call your vet."
        )
    else:
        for match in response.matches:
            section = match.section
            st.markdown(f"**From:** {section.doc_title or section.source_file}")
            st.markdown(f"### {section.heading}")
            st.markdown(section.content)
            st.divider()
