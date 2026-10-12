<p align="center"><img src="assets/logo-image.png" alt="PawsCare+ logo" width="140"></p>

# PawsCare+

PawsCare+ is a Streamlit app that helps busy pet owners stay consistent with daily pet care. You add your pets and their care tasks (walks, feeding, medication, grooming), tell it when you're available, and it builds a schedule for the day. It blocks tasks that fall outside your available hours or overlap with each other, so you catch problems before they happen.

It also includes a searchable set of aftercare guides (spay/neuter, dental, wound, and vaccination). If your question isn't covered by the guides, it says so instead of guessing.

## Features

- **Pets and daily tasks.** Add multiple pets, then give each a daily routine: tasks with a time, duration, and priority, like "Breakfast at 8:00 AM." Check tasks off (checkmarks reset each day), undo, or delete them.
- **Guardrails.** A task is rejected if it starts before or ends after your available hours, or overlaps another task, with a message explaining what's wrong.
- **Schedule for any day.** Pick a date (it starts on your next available day) to see one time-ordered plan across all your pets, filterable by pet or status, with total and remaining minutes.
- **Aftercare search.** A TF-IDF search over the guides in `docs/`, with a confidence check that answers "I'm not so sure" rather than returning a weak match.
- **Accounts and automatic saving.** Sign in with Google and your pets and tasks are saved to a PostgreSQL database, so they're there next time on any device. Each account only sees its own data.
- **Your data, your control.** Download a copy of your data as JSON, restore it later, or delete everything saved for your account.

## Running it

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

streamlit run app.py             # the web app
python main.py                   # a command-line demo with sample pets
```

### Local mode vs. sign-in mode

With no settings, the app runs in **local mode**: there's no sign-in, and your data is saved in a file called `pawpal_local.db` on your computer. That's all you need to try it out.

To turn on Google sign-in and a hosted database, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in:

- `[database]`: a PostgreSQL connection string (this project uses a free [Neon](https://neon.com) database).
- `[auth]`: a Google OAuth client ID and secret from Google Cloud Console, plus a random `cookie_secret`.

`secrets.toml` holds passwords, so it's listed in `.gitignore` and never pushed to GitHub. When deploying to Streamlit Community Cloud, paste the same contents into the app's **Secrets** setting instead.

## Testing

```bash
pytest
```

The tests in `tests/test_pawpal.py` cover the scheduling rules (availability, overlaps, sorting, filtering, totals), pet and task management, saving and loading, and the aftercare search (ranking, deduplication, and the confidence check). They use a fixed date, so they give the same result on any day of the week.

`tests/test_storage.py` checks the database layer (saving, updating, keeping users separate, deleting) against a temporary SQLite file, and `tests/test_app.py` runs the whole app with Streamlit's test runner, including simulated Google sign-ins for two different users.

## How it's built

```mermaid
flowchart TB
    subgraph INPUT["Input (Human)"]
        User(["Pet owner"])
        UI["Streamlit UI - app.py"]
    end

    subgraph CORE["Processing - pawpal_system.py"]
        Agent["Scheduler<br/>Owner + Scheduler + DayPlan"]
        Guard["Guardrails<br/>availability + overlap checks"]
        Retriever["Retriever - TF-IDF search"]
        Evaluator["Evaluator - confidence threshold"]
        Store["Storage - storage.py<br/>load / save / delete per user"]
    end

    Docs[("Aftercare guides - docs/*.md")]
    DB[("PostgreSQL<br/>one row per user")]
    Google(["Google sign-in"])

    subgraph OUTPUT["Output (Human reviews)"]
        Plan["Day plan / schedule table"]
        Answer["Matching aftercare section<br/>or 'I'm not so sure' notice"]
    end

    User --> UI
    UI -->|task input| Agent
    Agent --> Guard
    Guard -->|valid| Plan
    Guard -.->|conflict error| UI
    UI -->|search query| Retriever
    Docs --> Retriever
    Retriever --> Evaluator
    Evaluator --> Answer
    User -.->|sign in| Google
    Google -.->|user ID + email| UI
    UI <-->|autosave / load| Store
    Store <--> DB
    Plan --> User
    Answer --> User
```

**Scheduling.** The app (`app.py`) collects pets, tasks, and availability and passes them to the `Owner` and `Scheduler` classes in `pawpal_system.py`. Before a task is added, guardrails check that it fits inside the owner's available hours and doesn't overlap another task. Generating a schedule produces a `DayPlan`, a time-sorted snapshot of the day's tasks.

**Aftercare guides.** The user types a question, and a TF-IDF retriever searches the markdown files in `docs/`. An evaluator checks whether the best match is strong enough. If it isn't, the app says "I'm not so sure" instead of guessing.

**Accounts and saving.** Users sign in with Google through Streamlit's built-in `st.login()`. Google gives each account a permanent ID, and `storage.py` uses it as the key for that user's row in a `pawpal_owners` table. The row's `data` column holds their owner, pets, and tasks as JSON (made by `owner_to_dict`). After every click, the app compares the current data to what it last saved and writes to the database only if something changed.

## Design decisions

**I kept the logic separate from the UI.** Most of the real work lives in `pawpal_system.py` (scheduling, conflict checks, doc search, saving). `app.py` is mostly Streamlit forms and tables. That way I can test the important behavior with pytest without clicking through the app.

**I block bad schedules instead of fixing them automatically.** If a task is outside the owner's availability or overlaps another task, `add_todo()` and `generate_day_plan()` raise an error right away. I didn't want the app to silently move tasks around. I'd rather tell the user what's wrong and let them fix it.

- *Trade-off:* The app won't suggest a better time slot, so the user has to find a valid time on their own.

**Tasks are a daily routine, not one-off events.** Pet care repeats: breakfast at 8 AM happens every day. So adding a task only checks that it fits your hours and doesn't overlap another task. The day of the week only matters when you pick a date to schedule. Each task remembers the date it was last checked off, so checkmarks reset on their own each day.

- *Trade-off:* One-off tasks (a vet visit next Thursday) and limited-time tasks (meds for 7 days) aren't supported yet.
- *Why it changed:* The first version scheduled every task for "today" and checked today's day of the week, so someone available only on weekdays couldn't add any task on a weekend. A regression test now covers that case.

**"Today" means today where the user is.** Hosted servers run on UTC, which is already tomorrow in New York by 8 PM. The app uses the browser's timezone to decide what "today" is, so checkmarks reset at the user's midnight.

**I sort by time, not priority.** The user picks when each task happens, and the schedule shows tasks in chronological order. Priority is stored and shown in the table, but the scheduler doesn't reshuffle tasks based on it.

- *Trade-off:* Priority is more of a label than something that changes the plan. I think that makes sense for pet care: you usually know meds need to happen at 8 AM, and you mainly need help catching conflicts.

**A day plan is a snapshot.** `DayPlan` keeps its own copy of the task list, so sorting or filtering a plan never reorders the owner's master list.

**I used TF-IDF for doc search instead of an LLM.** The aftercare search uses a simple TF-IDF index over local markdown files. If the query doesn't match well enough (`is_confident_query`), the app refuses to answer. I wanted something that works offline, doesn't need an API key, and is easy to test.

- *Trade-off:* It only catches keyword matches, so a question like "my dog threw up" might not find a section about vomiting.

**One JSON row per user instead of separate tables.** Each user's pets and tasks are stored together as one JSON document rather than in separate `pets` and `tasks` tables. A user only ever loads and saves their own data as a whole, so this keeps the database code small and reuses the same format as the backup file.

- *Trade-off:* I can't easily run queries across users, like "how many cats are registered." If I needed that, I'd split it into proper tables.

**Stop rather than start empty when the database is down.** If loading fails, the app shows an error instead of an empty plan. Otherwise the next autosave would overwrite the user's real data with nothing.

**Overbooked days aren't trimmed.** `Scheduler.filter_tasks()` filters by pet or status, but it doesn't drop tasks when the total time is longer than your available window.

- *Trade-off:* The schedule might show more than you have time for. I'd rather show everything and let the owner decide what to skip than hide tasks.

## Limitations and next steps

- Every task repeats daily. There are no one-off or limited-time tasks yet (for example, "medication every 12 hours for 7 days").
- The aftercare search only covers the four built-in guides. You can't add your own vet's instructions yet.
- Aftercare guides are general information and not a substitute for advice from a veterinarian.

## Project files

| File | What it does |
|------|--------------|
| `app.py` | Streamlit web app |
| `pawpal_system.py` | Scheduling, guardrails, aftercare search, JSON save/load |
| `storage.py` | Database: load, save, and delete each user's data |
| `.streamlit/secrets.toml.example` | Template for sign-in and database settings |
| `main.py` | Command-line demo |
| `tests/` | Test suite (scheduling, storage, and full-app tests) |
| `docs/` | Aftercare guides used by the search |
| `diagrams/` | System and UML diagrams (Mermaid) |
| `reflection.md` | Project reflection |
| `ai_interactions.md` | Notes on working with AI tools |
