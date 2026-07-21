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
    "Weekdays (Mon–Fri)": WEEKDAYS,
    "Weekends (Sat–Sun)": WEEKENDS,
    "Every day": ALL_DAYS,
}


@dataclass
class AvailabilityWindow:
    days: set[int]
    start: time
    end: time


@dataclass
class PetInfo:
    name: str
    age: int
    breed: str

    def get_pet_info(self) -> str:
        pass


@dataclass
class ToDo:
    task: str
    priority: int
    duration_minutes: int
    availability: str
    pet: PetInfo | None = None
    status: str = "pending"

    @property
    def time(self) -> time:
        return parse_task_time(self.availability)

    def set_priority(self, priority: int) -> None:
        self.priority = priority

    def mark_complete(self) -> None:
        self.status = "complete"


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
        self.pets.append(pet)

    def add_todo(self, todo: ToDo, plan_date: date | None = None) -> None:
        if todo.pet is not None and todo.pet not in self.pets:
            raise ValueError(
                f"Pet {todo.pet.name!r} is not registered with this owner"
            )
        when = plan_date or date.today()
        conflicts = self.check_todo_availability(todo, when)
        if conflicts:
            raise AvailabilityError(conflicts[0])
        overlap = task_schedule_conflicts(self.todos + [todo], when)
        if overlap:
            raise ScheduleConflictError(overlap[0])
        self.todos.append(todo)

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
        for todo in self.todos:
            conflicts = self.check_todo_availability(todo, plan_date)
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
    def __init__(self, plan_date: date, owner: Owner) -> None:
        self.date = plan_date
        self.owner = owner

    @property
    def total_duration(self) -> int:
        return sum(todo.duration_minutes for todo in self.owner.todos)

    def sort_by_priority(self) -> None:
        self.owner.todos.sort(key=lambda t: t.priority, reverse=True)

    def sort_by_time(self) -> None:
        self.owner.todos.sort(key=lambda t: t.time)

    def display_schedule(self) -> None:
        pass


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
    ) -> list[ToDo]:
        filtered = tasks
        if status is not None:
            filtered = [todo for todo in filtered if todo.status == status]
        if pet_name is not None:
            filtered = [
                todo
                for todo in filtered
                if todo.pet is not None and todo.pet.name == pet_name
            ]
        return filtered

    def build_plan(self, owner: Owner, plan_date: date) -> DayPlan:
        tasks = self._get_tasks(owner)
        plan = DayPlan(plan_date, owner)
        if tasks:
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
    try:
        start_time = parse_task_time(time_str)
    except (ValueError, IndexError):
        return [
            f"{task_name}: could not parse time {time_str!r} "
            f"(use a time like 9:00 AM or 17:30)."
        ]

    conflicts: list[str] = []
    task_start = datetime.combine(task_date, start_time)
    task_end = task_start + timedelta(minutes=duration_minutes)
    window_label = (
        f"{format_time(window.start)}–{format_time(window.end)} "
        f"on {describe_days(window.days)}"
    )

    if task_date.weekday() not in window.days:
        conflicts.append(
            f"{task_name} is on {task_date.strftime('%A')}, "
            f"but you're only available {describe_days(window.days)}."
        )

    if start_time < window.start:
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


def normalize_doc_heading(text: str) -> str:
    heading = text.strip()
    if heading.startswith("##"):
        heading = heading[2:]
    return " ".join(heading.strip().lower().split())


def load_aftercare_sections(docs_dir: Path | str) -> list[DocSection]:
    sections: list[DocSection] = []
    docs_path = Path(docs_dir)

    for md_file in sorted(docs_path.glob("*.md")):
        current_heading: str | None = None
        current_original: str | None = None
        current_lines: list[str] = []
        doc_title = ""

        for line in md_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("# ") and not line.startswith("## "):
                doc_title = line[2:].strip()
            elif line.startswith("## "):
                if current_heading is not None and current_original is not None:
                    sections.append(
                        DocSection(
                            source_file=md_file.name,
                            heading=current_original,
                            content="\n".join(current_lines).strip(),
                            doc_title=doc_title,
                        )
                    )
                current_original = line[3:].strip()
                current_heading = normalize_doc_heading(current_original)
                current_lines = []
            elif current_heading is not None:
                current_lines.append(line)

        if current_heading is not None and current_original is not None:
            sections.append(
                DocSection(
                    source_file=md_file.name,
                    heading=current_original,
                    content="\n".join(current_lines).strip(),
                    doc_title=doc_title,
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
    }
)


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
    heading_text = _normalized_text(heading)
    boost = 0.0
    for phrase in _query_phrases(query_terms):
        if phrase in heading_text:
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
        query_terms = tokenize(query)
        if not query_terms or not self.sections:
            return []

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


def build_doc_search_index(docs_dir: Path | str = "docs") -> DocSearchIndex:
    return DocSearchIndex.build(load_aftercare_sections(docs_dir))


def search_aftercare_docs(
    query: str,
    docs_dir: Path | str = "docs",
    *,
    top_k: int = 5,
) -> list[DocSection]:
    if not query.strip():
        return []

    matches = build_doc_search_index(docs_dir).search(query, top_k=top_k)
    return [match.section for match in matches]


def task_schedule_conflicts(
    tasks: list[ToDo], plan_date: date
) -> list[str]:
    active = [todo for todo in tasks if todo.status != "complete"]
    conflicts: list[str] = []

    for index, first in enumerate(active):
        first_start, first_end = _task_interval(first, plan_date)
        for second in active[index + 1 :]:
            second_start, second_end = _task_interval(second, plan_date)
            if first_start < second_end and second_start < first_end:
                conflicts.append(
                    f"{first.task} ({format_time(first.time)}) overlaps with "
                    f"{second.task} ({format_time(second.time)})."
                )

    return conflicts
