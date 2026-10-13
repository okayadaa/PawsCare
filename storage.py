"""Saving each user's pets and tasks in a database.

Every signed-in user gets one row in the ``pawpal_owners`` table. The row is
found by ``user_id`` (the permanent ID Google gives each account), and the
``data`` column holds that user's owner, pets, and tasks as JSON, made by
``owner_to_dict`` in pawpal_system.py.

The same code works with SQLite (a single file, used on your own computer
and in the tests) and PostgreSQL (the hosted database used in production).
SQLAlchemy is the library that hides the differences between them.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Engine,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)

from pawpal_system import Owner, owner_from_dict, owner_to_dict

metadata = MetaData()

owners_table = Table(
    "pawpal_owners",
    metadata,
    Column("user_id", String(255), primary_key=True),
    Column("email", String(320), nullable=True),
    Column("data", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# How many AI requests each user made per day, so one person can't use up
# the app's Claude credit. One row per user per day.
ai_usage_table = Table(
    "pawpal_ai_usage",
    metadata,
    Column("user_id", String(255), primary_key=True),
    Column("day", Date, primary_key=True),
    Column("count", Integer, nullable=False),
)


def make_engine(database_url: str) -> Engine:
    """Connect to the database and create the table if it doesn't exist yet.

    ``pool_pre_ping`` checks that a pooled connection is still alive before
    using it. Hosted databases close idle connections, and without this the
    first request after a quiet period would fail.
    """
    engine = create_engine(database_url, pool_pre_ping=True)
    metadata.create_all(engine)
    return engine


def load_owner(engine: Engine, user_id: str) -> Owner | None:
    """Return the saved owner for this user, or None if they have no data yet."""
    with engine.connect() as conn:
        row = conn.execute(
            select(owners_table.c.data).where(owners_table.c.user_id == user_id)
        ).first()
    if row is None:
        return None
    return owner_from_dict(json.loads(row.data))


def save_owner(engine: Engine, user_id: str, email: str | None, owner: Owner) -> None:
    """Save this user's owner, replacing whatever was saved before."""
    values = {
        "email": email,
        "data": json.dumps(owner_to_dict(owner)),
        "updated_at": datetime.now(timezone.utc),
    }
    # engine.begin() opens a transaction: either both steps below happen,
    # or neither does.
    with engine.begin() as conn:
        result = conn.execute(
            update(owners_table)
            .where(owners_table.c.user_id == user_id)
            .values(**values)
        )
        if result.rowcount == 0:
            conn.execute(insert(owners_table).values(user_id=user_id, **values))


def delete_owner(engine: Engine, user_id: str) -> None:
    """Remove everything saved for this user, including their AI usage counts."""
    with engine.begin() as conn:
        conn.execute(delete(owners_table).where(owners_table.c.user_id == user_id))
        conn.execute(delete(ai_usage_table).where(ai_usage_table.c.user_id == user_id))


def ai_uses_on(engine: Engine, user_id: str, day: date) -> int:
    """How many AI requests this user has made on this day."""
    with engine.connect() as conn:
        count = conn.execute(
            select(ai_usage_table.c.count).where(
                ai_usage_table.c.user_id == user_id, ai_usage_table.c.day == day
            )
        ).scalar()
    return count or 0


def record_ai_use(engine: Engine, user_id: str, day: date) -> None:
    """Add one to this user's AI request count for the day."""
    match = (ai_usage_table.c.user_id == user_id) & (ai_usage_table.c.day == day)
    with engine.begin() as conn:
        result = conn.execute(
            update(ai_usage_table)
            .where(match)
            .values(count=ai_usage_table.c.count + 1)
        )
        if result.rowcount == 0:
            conn.execute(insert(ai_usage_table).values(user_id=user_id, day=day, count=1))
