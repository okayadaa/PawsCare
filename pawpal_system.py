from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

WEEKDAYS = {0, 1, 2, 3, 4}
WEEKENDS = {5, 6}
ALL_DAYS = set(range(7))

DAY_PRESETS: dict[str, set[int]] = {
    "Every day": ALL_DAYS,
    "Weekdays (Mon–Fri)": WEEKDAYS,
    "Weekends (Sat–Sun)": WEEKENDS,
}

PRIORITY_MAP = {"low": 1, "medium": 2, "high": 3}
PRIORITY_LABELS = {value: label for label, value in PRIORITY_MAP.items()}


@dataclass
class AvailabilityWindow:
    days: set[int]
    start: time
    end: time


@dataclass
class VetNote:
    """Instructions from a pet's own vet, such as a discharge sheet.

    Only the text is kept (pasted, or pulled out of a PDF), never the
    original file.
    """

    title: str
    text: str
    added_on: date


MAX_VET_NOTES_PER_PET = 5
MAX_VET_NOTE_CHARS = 12_000


@dataclass
class PetInfo:
    name: str
    age: int
    breed: str = ""
    species: str = ""
    vet_notes: list[VetNote] = field(default_factory=list)

    def add_vet_note(self, title: str, text: str, added_on: date) -> VetNote:
        title = " ".join(title.split()) or "Vet instructions"
        text = text.strip()
        if not text:
            raise ValueError("The vet instructions are empty.")
        if len(text) > MAX_VET_NOTE_CHARS:
            raise ValueError(
                f"That's too long to save ({len(text):,} characters). Please keep "
                f"it under {MAX_VET_NOTE_CHARS:,}, for example by pasting only "
                "the aftercare part."
            )
        if len(self.vet_notes) >= MAX_VET_NOTES_PER_PET:
            raise ValueError(
                f"{self.name} already has {MAX_VET_NOTES_PER_PET} sets of vet "
                "instructions. Delete an old one first."
            )
        note = VetNote(title[:100], text, added_on)
        self.vet_notes.append(note)
        return note

    def remove_vet_note(self, note: VetNote) -> None:
        self.vet_notes = [n for n in self.vet_notes if n is not note]

    def get_pet_info(self) -> str:
        details = [part for part in (self.species, self.breed) if part]
        kind = f" ({', '.join(details)})" if details else ""
        years = "year" if self.age == 1 else "years"
        return f"{self.name}{kind}, {self.age} {years} old"


@dataclass
class ToDo:
    task: str
    priority: int
    duration_minutes: int
    availability: str
    pet: PetInfo | None = None
    completed_on: date | None = None

    # Tasks are a daily routine ("Breakfast at 8:00 AM" happens every day),
    # so a checkmark only counts for the day it was made. Instead of storing
    # "complete", each task remembers the date it was last completed.

    @property
    def time(self) -> time:
        return parse_task_time(self.availability)

    def status_on(self, day: date) -> str:
        return "complete" if self.completed_on == day else "pending"

    @property
    def status(self) -> str:
        """The task's status for today."""
        return self.status_on(date.today())

    def set_priority(self, priority: int) -> None:
        self.priority = priority

    def mark_complete(self, on: date | None = None) -> None:
        self.completed_on = on or date.today()

    def mark_incomplete(self) -> None:
        self.completed_on = None


class AvailabilityError(ValueError):
    pass


class ScheduleConflictError(ValueError):
    pass


class Owner:
    def __init__(self, name: str, availability: AvailabilityWindow) -> None:
        self.name = name
        self.availability = availability
        self.pets: list[PetInfo] = []
        self.todos: list[ToDo] = []
        self.day_plans: list[DayPlan] = []

    def add_pet(self, pet: PetInfo) -> None:
        name = pet.name.strip()
        if not name:
            raise ValueError("Pet name can't be empty.")
        if any(existing.name.lower() == name.lower() for existing in self.pets):
            raise ValueError(f"You already have a pet named {name!r}.")
        pet.name = name
        self.pets.append(pet)

    def remove_todo(self, todo: ToDo) -> None:
        self.todos = [existing for existing in self.todos if existing is not todo]

    def add_todo(self, todo: ToDo) -> None:
        """Add a daily task after checking it fits your hours and doesn't overlap.

        Tasks repeat on every day you're available, so only the time of day
        is checked here, not today's date.
        """
        if todo.pet is not None and todo.pet not in self.pets:
            raise ValueError(
                f"Pet {todo.pet.name!r} is not registered with this owner"
            )
        conflicts = self.check_time_window(todo)
        if conflicts:
            raise AvailabilityError(conflicts[0])
        overlap = task_schedule_conflicts(self.todos + [todo], date.today())
        if overlap:
            raise ScheduleConflictError(overlap[0])
        self.todos.append(todo)

    def is_available_on(self, day: date) -> bool:
        return day.weekday() in self.availability.days

    def next_available_day(self, start: date) -> date | None:
        """The first day on or after start that you're available, if any."""
        for offset in range(7):
            day = start + timedelta(days=offset)
            if self.is_available_on(day):
                return day
        return None

    def check_time_window(self, todo: ToDo) -> list[str]:
        return time_window_conflicts(
            self.availability, todo.availability, todo.duration_minutes, todo.task
        )

    def get_tasks_for_pet(self, pet: PetInfo) -> list[ToDo]:
        return [todo for todo in self.todos if todo.pet is pet]

    def get_all_pet_tasks(self) -> list[ToDo]:
        return [todo for todo in self.todos if todo.pet in self.pets]

    def check_todo_availability(self, todo: ToDo, plan_date: date) -> list[str]:
        return availability_conflicts(
            self.availability,
            plan_date,
            todo.availability,
            todo.duration_minutes,
            todo.task,
        )

    def generate_day_plan(self, plan_date: date) -> DayPlan:
        if not self.is_available_on(plan_date):
            raise AvailabilityError(
                f"You're not available on {plan_date:%A}s. Your available days "
                f"are {describe_days(self.availability.days)}."
            )
        for todo in self.todos:
            conflicts = self.check_time_window(todo)
            if conflicts:
                raise AvailabilityError(
                    f"Cannot build schedule: {conflicts[0]}"
                )
        overlap = task_schedule_conflicts(self.todos, plan_date)
        if overlap:
            raise ScheduleConflictError(
                f"Cannot build schedule: {overlap[0]}"
            )
        return Scheduler().build_plan(self, plan_date)


class DayPlan:
    """A snapshot of one day's tasks.

    The plan keeps its own task list, so sorting a plan never reorders
    the owner's master list of to-dos.
    """

    def __init__(
        self, plan_date: date, owner: Owner, tasks: list[ToDo] | None = None
    ) -> None:
        self.date = plan_date
        self.owner = owner
        self.tasks: list[ToDo] = list(owner.todos if tasks is None else tasks)

    @property
    def total_duration(self) -> int:
        return sum(todo.duration_minutes for todo in self.tasks)

    @property
    def remaining_duration(self) -> int:
        return sum(
            todo.duration_minutes
            for todo in self.tasks
            if todo.status_on(self.date) != "complete"
        )

    def sort_by_priority(self) -> None:
        self.tasks.sort(key=lambda t: t.priority, reverse=True)

    def sort_by_time(self) -> None:
        self.tasks.sort(key=lambda t: t.time)

    def display_schedule(self) -> list[dict[str, object]]:
        """Return the plan as table rows, one per task, in the plan's order."""
        return [
            {
                "time": format_time(todo.time),
                "pet": todo.pet.name if todo.pet else "—",
                "task": todo.task,
                "priority": PRIORITY_LABELS.get(todo.priority, todo.priority),
                "duration_minutes": todo.duration_minutes,
                "status": todo.status_on(self.date),
            }
            for todo in self.tasks
        ]


class Scheduler:
    def _get_tasks(self, owner: Owner) -> list[ToDo]:
        return [
            todo
            for todo in owner.todos
            if todo.pet in owner.pets or todo.pet is None
        ]

    @staticmethod
    def sort_by_time(tasks: list[ToDo]) -> list[ToDo]:
        return sorted(tasks, key=lambda t: t.time)

    @staticmethod
    def filter_tasks(
        tasks: list[ToDo],
        *,
        status: str | None = None,
        pet_name: str | None = None,
        on: date | None = None,
    ) -> list[ToDo]:
        """Filter tasks by status on a given day (default today) and/or pet."""
        filtered = tasks
        if status is not None:
            day = on or date.today()
            filtered = [todo for todo in filtered if todo.status_on(day) == status]
        if pet_name is not None:
            filtered = [
                todo
                for todo in filtered
                if todo.pet is not None and todo.pet.name == pet_name
            ]
        return filtered

    def build_plan(self, owner: Owner, plan_date: date) -> DayPlan:
        plan = DayPlan(plan_date, owner, self._get_tasks(owner))
        plan.sort_by_time()
        owner.day_plans.append(plan)
        return plan


def parse_task_time(time_str: str) -> time:
    text = time_str.strip()
    if not text:
        raise ValueError(f"Invalid time format: {time_str!r}")

    normalized = text.upper()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        for candidate in (text, normalized):
            try:
                return datetime.strptime(candidate, fmt).time()
            except ValueError:
                continue
    raise ValueError(f"Invalid time format: {time_str!r}")


def format_time(value: time) -> str:
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d} {value.strftime('%p')}"


def describe_days(days: set[int]) -> str:
    if days == WEEKDAYS:
        return "weekdays"
    if days == WEEKENDS:
        return "weekends"
    if days == ALL_DAYS:
        return "every day"
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return ", ".join(names[d] for d in sorted(days))


def availability_conflicts(
    window: AvailabilityWindow,
    task_date: date,
    time_str: str,
    duration_minutes: int,
    task_name: str = "Task",
) -> list[str]:
    """Check a task on a specific date: the day of the week and the time."""
    conflicts: list[str] = []
    if task_date.weekday() not in window.days:
        conflicts.append(
            f"{task_name} is on {task_date.strftime('%A')}, "
            f"but you're only available {describe_days(window.days)}."
        )
    return conflicts + time_window_conflicts(
        window, time_str, duration_minutes, task_name
    )


def time_window_conflicts(
    window: AvailabilityWindow,
    time_str: str,
    duration_minutes: int,
    task_name: str = "Task",
) -> list[str]:
    """Check that a task starts and ends inside your available hours."""
    try:
        start_time = parse_task_time(time_str)
    except (ValueError, IndexError):
        return [
            f"{task_name}: could not parse time {time_str!r} "
            f"(use a time like 9:00 AM or 17:30)."
        ]

    conflicts: list[str] = []
    task_start = datetime.combine(date.today(), start_time)
    task_end = task_start + timedelta(minutes=duration_minutes)
    window_label = (
        f"{format_time(window.start)}–{format_time(window.end)} "
        f"on {describe_days(window.days)}"
    )

    if task_end.date() != task_start.date():
        conflicts.append(f"{task_name} can't run past midnight.")
    elif start_time < window.start:
        conflicts.append(
            f"{task_name} at {format_time(start_time)} is before your window "
            f"({window_label})."
        )
    elif start_time > window.end:
        conflicts.append(
            f"{task_name} at {format_time(start_time)} is after your window "
            f"({window_label})."
        )
    elif task_end.time() > window.end:
        conflicts.append(
            f"{task_name} ends at {format_time(task_end.time())}, after your window "
            f"({format_time(window.end)})."
        )

    return conflicts


def _task_interval(todo: ToDo, plan_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(plan_date, todo.time)
    end = start + timedelta(minutes=todo.duration_minutes)
    return start, end


@dataclass
class DocSection:
    source_file: str
    heading: str
    content: str
    doc_title: str = ""
    # The guide's references, from its "## Sources" section, as markdown
    # list items like "[Title](https://...), Publisher".
    sources: list[str] = field(default_factory=list)
    # True for text from a pet's own vet (a VetNote), not a general guide.
    from_vet: bool = False


SOURCES_HEADING = "sources"


def normalize_doc_heading(text: str) -> str:
    heading = text.strip()
    if heading.startswith("##"):
        heading = heading[2:]
    return " ".join(heading.strip().lower().split())


def load_aftercare_sections(docs_dir: Path | str) -> list[DocSection]:
    """Split each guide into its "## " sections.

    A "## Sources" section isn't treated as guide content: its list items
    are attached to every section of that guide as ``sources``, so answers
    can show where the guidance comes from without the reference list
    itself being searched or sent to Claude as advice.
    """
    sections: list[DocSection] = []
    docs_path = Path(docs_dir)

    for md_file in sorted(docs_path.glob("*.md")):
        doc_title = ""
        parsed: list[tuple[str, list[str]]] = []  # (heading, lines)

        for line in md_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("# ") and not line.startswith("## "):
                doc_title = line[2:].strip()
            elif line.startswith("## "):
                parsed.append((line[3:].strip(), []))
            elif parsed:
                parsed[-1][1].append(line)

        sources: list[str] = []
        for heading, lines in parsed:
            if normalize_doc_heading(heading) == SOURCES_HEADING:
                sources = [
                    line.strip()[2:].strip()
                    for line in lines
                    if line.strip().startswith("- ")
                ]

        for heading, lines in parsed:
            if normalize_doc_heading(heading) == SOURCES_HEADING:
                continue
            sections.append(
                DocSection(
                    source_file=md_file.name,
                    heading=heading,
                    content="\n".join(lines).strip(),
                    doc_title=doc_title,
                    sources=list(sources),
                )
            )

    return sections


def get_aftercare_headings(docs_dir: Path | str = "docs") -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()

    for section in load_aftercare_sections(docs_dir):
        normalized = normalize_doc_heading(section.heading)
        if normalized not in seen:
            seen.add(normalized)
            headings.append(section.heading)

    return headings


STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "if",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "you",
        "your",
        "what",
        "whats",
        "how",
        "being",
        "my",
        "properly",
        "steps",
    }
)

MIN_CONFIDENCE_SCORE = 0.074


def _document_metadata_terms(section: DocSection) -> list[str]:
    stem = Path(section.source_file).stem.replace("-", " ")
    return tokenize(stem) + tokenize(section.doc_title)


def tokenize(text: str) -> list[str]:
    cleaned = text.lower()
    if cleaned.startswith("##"):
        cleaned = cleaned[2:]
    words = re.findall(r"[a-z0-9]+", cleaned)
    return [word for word in words if len(word) >= 2 and word not in STOPWORDS]


def _normalized_text(text: str) -> str:
    cleaned = text.lower()
    if cleaned.startswith("##"):
        cleaned = cleaned[2:]
    return " ".join(re.findall(r"[a-z0-9]+", cleaned))


def _query_phrases(query_terms: list[str]) -> list[str]:
    phrases: list[str] = []
    for size in range(2, len(query_terms) + 1):
        for start in range(len(query_terms) - size + 1):
            phrases.append(" ".join(query_terms[start : start + size]))
    return phrases


def _phrase_boost(query_terms: list[str], heading: str) -> float:
    # Compare against the heading's words with the same filler words removed
    # as the query, so "call vet" matches "Call the Vet Immediately If".
    # Spaces around both sides make sure only whole words match.
    heading_text = f" {' '.join(tokenize(heading))} "
    boost = 0.0
    for phrase in _query_phrases(query_terms):
        if f" {phrase} " in heading_text:
            boost += 0.15 * len(phrase.split())
    return boost


def _exclusive_topic_boost(
    query_terms: list[str],
    source_file: str,
    file_metadata: dict[str, set[str]],
) -> float:
    boost = 0.0
    for term in query_terms:
        matching_files = [
            filename
            for filename, metadata_terms in file_metadata.items()
            if term in metadata_terms
        ]
        if len(matching_files) == 1 and source_file == matching_files[0]:
            boost += 1.0
    return boost


@dataclass
class SearchMatch:
    section: DocSection
    score: float


@dataclass
class SearchResponse:
    matches: list[SearchMatch]
    confident: bool


def _term_in_index(term: str, index: dict[str, dict[int, int]]) -> bool:
    if term in index:
        return True
    if len(term) < 4:
        return False
    for indexed_term in index:
        if len(indexed_term) < 4:
            continue
        if indexed_term.startswith(term) or term.startswith(indexed_term):
            return True
    return False


def is_confident_query(
    query: str, index: DocSearchIndex, matches: list[SearchMatch]
) -> bool:
    query_terms = tokenize(query)
    if not query_terms or not matches:
        return False

    if not all(_term_in_index(term, index.index) for term in query_terms):
        return False

    return matches[0].score >= MIN_CONFIDENCE_SCORE


@dataclass
class DocSearchIndex:
    sections: list[DocSection]
    index: dict[str, dict[int, int]] = field(default_factory=dict)
    section_term_totals: dict[int, int] = field(default_factory=dict)
    file_metadata: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, sections: list[DocSection]) -> DocSearchIndex:
        doc_index = cls(sections=list(sections))
        for section_idx, section in enumerate(sections):
            term_counts: dict[str, int] = {}
            for term in tokenize(section.heading):
                term_counts[term] = term_counts.get(term, 0) + 2
            for term in tokenize(section.content):
                term_counts[term] = term_counts.get(term, 0) + 1
            for term in _document_metadata_terms(section):
                term_counts[term] = term_counts.get(term, 0) + 4

            doc_index.section_term_totals[section_idx] = sum(term_counts.values())
            for term, count in term_counts.items():
                doc_index.index.setdefault(term, {})[section_idx] = count

            if section.source_file not in doc_index.file_metadata:
                doc_index.file_metadata[section.source_file] = set(
                    _document_metadata_terms(section)
                )

        return doc_index

    def search(self, query: str, top_k: int = 5) -> list[SearchMatch]:
        scores = self.score_sections(query)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        matches: list[SearchMatch] = []
        seen_source_files: set[str] = set()

        for section_idx, score in ranked:
            section = self.sections[section_idx]
            if section.source_file in seen_source_files:
                continue
            seen_source_files.add(section.source_file)
            matches.append(SearchMatch(section=section, score=score))
            if len(matches) >= top_k:
                break

        return matches

    def score_sections(self, query: str) -> dict[int, float]:
        """TF-IDF score for every section that shares a word with the query."""
        query_terms = tokenize(query)
        if not query_terms or not self.sections:
            return {}

        num_sections = len(self.sections)
        scores: dict[int, float] = {}

        for term in query_terms:
            section_counts = self.index.get(term)
            if not section_counts:
                continue

            document_frequency = len(section_counts)
            idf = math.log((num_sections + 1) / (document_frequency + 1))

            for section_idx, count in section_counts.items():
                total_terms = self.section_term_totals[section_idx]
                if total_terms == 0:
                    continue
                tf = count / total_terms
                scores[section_idx] = scores.get(section_idx, 0.0) + tf * idf

        for section_idx, section in enumerate(self.sections):
            if section_idx not in scores:
                continue
            scores[section_idx] += _phrase_boost(query_terms, section.heading)
            scores[section_idx] += _exclusive_topic_boost(
                query_terms, section.source_file, self.file_metadata
            )

        return scores


def build_doc_search_index(docs_dir: Path | str = "docs") -> DocSearchIndex:
    return DocSearchIndex.build(load_aftercare_sections(docs_dir))


def search_aftercare(
    query: str,
    docs_dir: Path | str = "docs",
    *,
    top_k: int = 5,
    index: DocSearchIndex | None = None,
) -> SearchResponse:
    if not query.strip():
        return SearchResponse(matches=[], confident=False)

    doc_index = index or build_doc_search_index(docs_dir)
    matches = doc_index.search(query, top_k=top_k)
    confident = is_confident_query(query, doc_index, matches)
    return SearchResponse(matches=matches if confident else [], confident=confident)


def search_aftercare_docs(
    query: str,
    docs_dir: Path | str = "docs",
    *,
    top_k: int = 5,
) -> list[DocSection]:
    response = search_aftercare(query, docs_dir, top_k=top_k)
    return [match.section for match in response.matches]


def task_schedule_conflicts(
    tasks: list[ToDo], plan_date: date
) -> list[str]:
    # Every task repeats daily, so a task that's already done today still
    # takes up its time slot tomorrow. All tasks count for overlaps.
    conflicts: list[str] = []

    for index, first in enumerate(tasks):
        first_start, first_end = _task_interval(first, plan_date)
        for second in tasks[index + 1 :]:
            second_start, second_end = _task_interval(second, plan_date)
            if first_start < second_end and second_start < first_end:
                conflicts.append(
                    f"{first.task} ({format_time(first.time)}) overlaps with "
                    f"{second.task} ({format_time(second.time)})."
                )

    return conflicts


# ---------------------------------------------------------------------------
# Saving and loading
# ---------------------------------------------------------------------------

SAVE_FORMAT_VERSION = 1


def owner_to_dict(owner: Owner) -> dict:
    """Turn an owner, their pets, and their tasks into plain JSON-safe data."""
    return {
        "version": SAVE_FORMAT_VERSION,
        "owner": {
            "name": owner.name,
            "availability": {
                "days": sorted(owner.availability.days),
                "start": owner.availability.start.strftime("%H:%M"),
                "end": owner.availability.end.strftime("%H:%M"),
            },
        },
        "pets": [
            {
                "name": pet.name,
                "age": pet.age,
                "breed": pet.breed,
                "species": pet.species,
                "vet_notes": [
                    {
                        "title": note.title,
                        "text": note.text,
                        "added_on": note.added_on.isoformat(),
                    }
                    for note in pet.vet_notes
                ],
            }
            for pet in owner.pets
        ],
        "todos": [
            {
                "task": todo.task,
                "priority": todo.priority,
                "duration_minutes": todo.duration_minutes,
                "time": todo.availability,
                "pet": todo.pet.name if todo.pet else None,
                "completed_on": (
                    todo.completed_on.isoformat() if todo.completed_on else None
                ),
            }
            for todo in owner.todos
        ],
    }


def owner_from_dict(data: dict) -> Owner:
    """Rebuild an owner from data made by owner_to_dict.

    Raises ValueError with a readable message if the data is not a
    PawsCare+ save file.
    """
    try:
        if data.get("version") != SAVE_FORMAT_VERSION:
            raise ValueError("This isn't a PawsCare+ save file (unknown version).")

        owner_data = data["owner"]
        window = owner_data["availability"]
        owner = Owner(
            owner_data["name"],
            AvailabilityWindow(
                {int(day) for day in window["days"]},
                parse_task_time(window["start"]),
                parse_task_time(window["end"]),
            ),
        )

        pets_by_name: dict[str, PetInfo] = {}
        for pet_data in data["pets"]:
            pet = PetInfo(
                pet_data["name"],
                int(pet_data["age"]),
                pet_data.get("breed", ""),
                pet_data.get("species", ""),
                [
                    VetNote(
                        note["title"],
                        note["text"],
                        date.fromisoformat(note["added_on"]),
                    )
                    for note in pet_data.get("vet_notes", [])
                ],
            )
            owner.add_pet(pet)
            pets_by_name[pet.name] = pet

        for todo_data in data["todos"]:
            pet_name = todo_data.get("pet")
            if pet_name is not None and pet_name not in pets_by_name:
                raise ValueError(f"Task refers to an unknown pet {pet_name!r}.")
            todo = ToDo(
                todo_data["task"],
                int(todo_data["priority"]),
                int(todo_data["duration_minutes"]),
                todo_data["time"],
                pets_by_name.get(pet_name) if pet_name else None,
                date.fromisoformat(todo_data["completed_on"])
                if todo_data.get("completed_on")
                else None,
            )
            parse_task_time(todo.availability)  # reject unreadable times early
            # Saved tasks were already checked when they were added, and a
            # backup may be restored on a different day, so they are loaded
            # as-is instead of going back through add_todo's date checks.
            owner.todos.append(todo)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"This save file is missing data or is damaged ({exc}).") from exc

    return owner
