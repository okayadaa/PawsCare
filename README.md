# PawPal+ (Module 2 Project)

You are building **PawPal+**, a Streamlit app that helps a pet owner plan care tasks for their pet.

## Scenario

A busy pet owner needs help staying consistent with pet care. They want an assistant that can:

- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

Your job is to design the system first (UML), then implement the logic in Python, then connect it to the Streamlit UI.

## What you will build

Your final app should:

- Let a user enter basic owner + pet info
- Let a user add/edit tasks (duration + priority at minimum)
- Generate a daily schedule/plan based on constraints and priorities
- Display the plan clearly (and ideally explain the reasoning)
- Include tests for the most important scheduling behaviors

## Getting started

### Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Suggested workflow

1. Read the scenario carefully and identify requirements and edge cases.
2. Draft a UML diagram (classes, attributes, methods, relationships).
3. Convert UML into Python class stubs (no logic yet).
4. Implement scheduling logic in small increments.
5. Add tests to verify key behaviors.
6. Connect your logic to the Streamlit UI in `app.py`.
7. Refine UML so it matches what you actually built.

## 🖥️ Sample Output

<img width="650" height="143" alt="Screenshot 2026-06-22 at 2 01 04 AM" src="https://github.com/user-attachments/assets/1c445e5b-a0bc-4d45-ae88-0fe0e226e978" />


## 🧪 Testing PawPal+

```bash
# Run the full test suite:
pytest

# Run with coverage:
pytest --cov
```

Sample test output:

<img width="813" height="137" alt="Screenshot 2026-06-22 at 9 51 59 PM" src="https://github.com/user-attachments/assets/1f62d3e7-7b7c-4bf4-8929-cfe59d643e39" />


## 📐 Smarter Scheduling

> Fill in once you've implemented scheduling logic.

| Feature | Method(s) | Notes |
|---------|-----------|-------|
| Task sorting | DayPlan.sort_by_time() | Sorts tasks by scheduled time or priority; day plans are built in chronological order.|
| Filtering | Scheduler.filter_tasks() | Filters by status and pet; excludes tasks for unregistered pets. Does not yet drop tasks when time runs out |
| Conflict handling | task_schedule_conflicts() | Blocks tasks outside the owner’s availability window and overlapping time slots; raises AvailabilityError or ScheduleConflictError |

