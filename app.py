import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

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
    describe_days,
    format_time,
    load_aftercare_sections,
    owner_from_dict,
    owner_to_dict,
    parse_task_time,
    search_aftercare,
)
from storage import delete_owner, load_owner, make_engine, save_owner

APP_DIR = Path(__file__).resolve().parent
DOCS_DIR = APP_DIR / "docs"
LOGO_PATH = APP_DIR / "assets" / "logo-image.png"
LOCAL_DATABASE_URL = f"sqlite:///{APP_DIR / 'pawpal_local.db'}"
LOCAL_USER_ID = "local-dev"
SPECIES_OPTIONS = ["dog", "cat", "rabbit", "bird", "other"]
DAY_PRESET_LABELS = list(DAY_PRESETS.keys())


def _docs_cache_key(docs_dir: Path) -> str:
    return str(
        sorted((path.name, path.stat().st_mtime) for path in docs_dir.glob("*.md"))
    )


@st.cache_data
def _cached_doc_index(docs_dir: str, _cache_key: str) -> DocSearchIndex:
    return DocSearchIndex.build(load_aftercare_sections(docs_dir))


@st.cache_resource
def get_engine(database_url: str):
    # cache_resource keeps ONE database connection pool for the whole app,
    # shared by every visitor, instead of reconnecting on every click.
    return make_engine(database_url)


def has_secret_section(name: str) -> bool:
    """True if .streamlit/secrets.toml (or the cloud Secrets box) has [name]."""
    try:
        return name in st.secrets
    except Exception:  # no secrets file at all
        return False


def user_today() -> date:
    """Today's date where the visitor is, not where the server is.

    Hosted servers usually run on UTC, which is already "tomorrow" for
    New York by 8 PM. The browser reports its timezone, so use that.
    """
    try:
        return datetime.now(ZoneInfo(st.context.timezone)).date()
    except Exception:  # timezone unknown (e.g. in tests)
        return date.today()


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


def new_owner(name: str = "") -> Owner:
    return Owner(name, AvailabilityWindow(set(ALL_DAYS), time(8, 0), time(20, 0)))


def reset_owner_widgets() -> None:
    """Clear widget values so they re-read from the newly loaded owner."""
    for key in ("owner_name", "days_preset", "avail_start", "avail_end"):
        st.session_state.pop(key, None)


def show_header() -> None:
    logo_col, title_col = st.columns([1, 8], vertical_alignment="center")
    with logo_col:
        st.image(str(LOGO_PATH), width=80)
    with title_col:
        st.title("PawsCare+")


st.set_page_config(page_title="PawsCare+", page_icon="🐾", layout="centered")

# ---------------------------------------------------------------------------
# Who is using the app?
#
# With an [auth] section in secrets, people sign in with Google and each
# account gets its own saved data. Without it (on your own computer), the app
# runs in local mode: no sign-in, one shared user, saved to a SQLite file.
# ---------------------------------------------------------------------------

AUTH_ENABLED = has_secret_section("auth")

if AUTH_ENABLED:
    if not st.user.is_logged_in:
        show_header()
        st.markdown(
            "Plan your pets' daily care. Add your pets and their tasks (walks, "
            "feeding, medication, grooming), and PawsCare+ builds a schedule "
            "that fits the hours you're available and warns you about "
            "overlapping tasks."
        )
        st.button("Sign in with Google", type="primary", on_click=st.login)
        st.caption(
            "Signing in lets PawsCare+ save your pets and tasks so they're "
            "there next time, on any device. We store your email address and "
            "the pets and tasks you enter, and nothing else. You can delete "
            "your data at any time from the sidebar."
        )
        st.stop()  # nothing below this line runs until the user signs in
    user_id = st.user.sub  # Google's permanent ID for this account
    user_email = st.user.get("email")
    display_name = st.user.get("given_name") or st.user.get("name") or ""
else:
    user_id = LOCAL_USER_ID
    user_email = None
    display_name = ""

database_url = (
    st.secrets["database"]["url"]
    if has_secret_section("database")
    else LOCAL_DATABASE_URL
)

# ---------------------------------------------------------------------------
# Load this user's saved data once per visit
# ---------------------------------------------------------------------------

if st.session_state.get("loaded_user_id") != user_id:
    try:
        engine = get_engine(database_url)
        saved_owner = load_owner(engine, user_id)
    except (SQLAlchemyError, ValueError) as exc:
        # Stop instead of starting with an empty plan: saving an empty plan
        # would overwrite the user's real data once the database is back.
        show_header()
        st.error(
            "PawsCare+ couldn't load your saved data right now. "
            "Please refresh the page in a minute."
        )
        print(f"Database load failed: {exc!r}")  # visible in the app logs
        st.stop()
    st.session_state.owner = saved_owner or new_owner(display_name)
    st.session_state.loaded_user_id = user_id
    st.session_state.last_saved = json.dumps(
        owner_to_dict(st.session_state.owner), sort_keys=True
    )
    reset_owner_widgets()

owner: Owner = st.session_state.owner

# ---------------------------------------------------------------------------
# Sidebar: account and data
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Your account")
    if AUTH_ENABLED:
        st.write(f"Signed in as **{user_email}**")
        st.button("Sign out", on_click=st.logout, use_container_width=True)
        st.caption("Your pets and tasks are saved automatically.")
    else:
        where = (
            "your database"
            if database_url != LOCAL_DATABASE_URL
            else "`pawpal_local.db` on this computer"
        )
        st.warning(
            "**Local mode.** Sign-in isn't set up, so everyone using this copy "
            f"of the app shares the same data, saved in {where}. "
            "That's fine for testing, but don't deploy it this way."
        )

    st.divider()
    with st.expander("Manage my data"):
        # Download -------------------------------------------------------
        st.caption("Download a copy of your pets and tasks to keep.")
        st.download_button(
            "Download a copy of my data",
            data=json.dumps(owner_to_dict(owner), indent=2),
            file_name="pawscare_backup.json",
            mime="application/json",
            use_container_width=True,
        )

        # Restore --------------------------------------------------------
        # Changing the uploader's key after a restore gives a fresh, empty
        # uploader, so the same file isn't offered again.
        uploader_key = f"restore_file_{st.session_state.get('restore_count', 0)}"
        uploaded = st.file_uploader(
            "Restore from a downloaded copy",
            type="json",
            key=uploader_key,
            max_upload_size=1,
        )
        if uploaded is not None:
            try:
                restored = owner_from_dict(json.loads(uploaded.getvalue()))
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(f"Couldn't read that file: {exc}")
            else:
                pets, tasks = len(restored.pets), len(restored.todos)
                st.warning(
                    f"This file has {pets} pet{'s' if pets != 1 else ''} and "
                    f"{tasks} task{'s' if tasks != 1 else ''}. Restoring "
                    "**replaces** all your current pets and tasks."
                )
                if st.button("Restore this copy", use_container_width=True):
                    st.session_state.owner = restored
                    st.session_state.restore_count = (
                        st.session_state.get("restore_count", 0) + 1
                    )
                    st.session_state.just_restored = True
                    reset_owner_widgets()
                    st.rerun()
        if st.session_state.pop("just_restored", False):
            st.success("Restored.")

        st.divider()

        # Start over -----------------------------------------------------
        st.caption("Start over clears your pets and tasks but keeps your account.")
        if st.button("Start over", use_container_width=True):
            st.session_state.owner = new_owner(display_name)
            reset_owner_widgets()
            st.rerun()

        # Delete ---------------------------------------------------------
        st.caption("Delete removes everything PawsCare+ has saved for you.")
        confirm_delete = st.checkbox("I understand this can't be undone")
        if st.button(
            "Delete my data",
            type="primary",
            disabled=not confirm_delete,
            use_container_width=True,
        ):
            try:
                delete_owner(get_engine(database_url), user_id)
            except SQLAlchemyError as exc:
                print(f"Database delete failed: {exc!r}")
                st.error("Couldn't delete your data right now. Please try again.")
            else:
                for key in ("owner", "loaded_user_id", "last_saved"):
                    st.session_state.pop(key, None)
                if AUTH_ENABLED:
                    st.logout()
                else:
                    st.rerun()

# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

show_header()
st.markdown(
    "Plan your pets' daily care. Add your pets and their tasks (walks, "
    "feeding, medication, grooming), and PawsCare+ builds a schedule that fits "
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

today = user_today()

st.subheader("Daily tasks")
st.caption(
    "Tasks repeat every day you're available, like \"Breakfast at 8:00 AM.\" "
    "Checkmarks reset each day."
)

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
                owner.add_todo(new_todo)
            except (AvailabilityError, ScheduleConflictError) as exc:
                st.error(str(exc))
            else:
                st.success(f"Scheduled {task_title.strip()!r} for {selected_pet.name}.")

    pet_tasks = Scheduler.sort_by_time(owner.get_tasks_for_pet(selected_pet))
    if pet_tasks:
        st.write(f"{selected_pet.name}'s tasks (today, {today:%A}):")
        for index, todo in enumerate(pet_tasks):
            done_today = todo.status_on(today) == "complete"
            task_col, done_col, delete_col = st.columns([5, 1, 1])
            with task_col:
                label = (
                    f"**{todo.task}** at {format_time(todo.time)} "
                    f"({todo.duration_minutes} min, "
                    f"{PRIORITY_LABELS.get(todo.priority, todo.priority)} priority)"
                )
                st.write(f"~~{label}~~ ✅" if done_today else label)
            with done_col:
                if done_today:
                    if st.button("Undo", key=f"undo_{selected_pet.name}_{index}"):
                        todo.mark_incomplete()
                        st.rerun()
                elif st.button("Done", key=f"complete_{selected_pet.name}_{index}"):
                    todo.mark_complete(on=today)
                    st.rerun()
            with delete_col:
                if st.button("Delete", key=f"delete_{selected_pet.name}_{index}"):
                    owner.remove_todo(todo)
                    st.rerun()
    else:
        st.info(f"No tasks scheduled for {selected_pet.name} yet.")

st.divider()

st.subheader("Schedule")
st.caption("All your tasks for one day, in time order.")

default_day = owner.next_available_day(today) or today
plan_date = st.date_input(
    "Schedule for",
    value=default_day,
    min_value=today,
    format="MM/DD/YYYY",
    help="Starts on your next available day.",
)
available = owner.is_available_on(plan_date)
if not available:
    st.info(
        f"You're not available on {plan_date:%A}s, so there's nothing to "
        f"schedule. Your available days are {describe_days(owner.availability.days)}. "
        "Pick another date or change your days above."
    )

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

if st.button("Generate schedule", disabled=not available):
    if not owner.get_all_pet_tasks():
        st.warning("Add at least one task before generating a schedule.")
    else:
        try:
            plan = owner.generate_day_plan(plan_date)
        except (AvailabilityError, ScheduleConflictError) as exc:
            st.error(str(exc))
        else:
            plan.tasks = Scheduler.filter_tasks(
                plan.tasks,
                status=None if status_filter == "all" else status_filter,
                pet_name=None if pet_filter == "all" else pet_filter,
                on=plan_date,
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

# ---------------------------------------------------------------------------
# Autosave
#
# Streamlit reruns this whole file after every click, so reaching this line
# means the click has been handled. If anything changed since the last save,
# write it to the database.
# ---------------------------------------------------------------------------

current = json.dumps(owner_to_dict(owner), sort_keys=True)
if current != st.session_state.get("last_saved"):
    try:
        save_owner(get_engine(database_url), user_id, user_email, owner)
    except SQLAlchemyError as exc:
        print(f"Database save failed: {exc!r}")
        st.toast("Couldn't save your latest changes. They'll be retried on your next click.")
    else:
        st.session_state.last_saved = current
