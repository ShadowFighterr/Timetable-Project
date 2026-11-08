from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Generator


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Database:
    def __init__(self, path: str | Path | None = None):
        configured = path or os.environ.get(
            "TIMETABLE_DB", "instance/timetable.sqlite3"
        )
        self.path = Path(configured)
        if not self.path.is_absolute():
            self.path = PROJECT_ROOT / self.path

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        with self.connect() as connection:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL "
                "DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                )
            }
            migration = PROJECT_ROOT / "api" / "migrations" / "001_initial.sql"
            if 1 not in applied:
                connection.executescript(
                    migration.read_text(encoding="utf-8")
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (1)"
                )
        self.seed_demo_data()

    def seed_demo_data(self) -> None:
        with self.transaction() as connection:
            if connection.execute("SELECT 1 FROM terms LIMIT 1").fetchone():
                return

            term_id = connection.execute(
                "INSERT INTO terms(name,start_date,end_date,active) "
                "VALUES ('Demonstration term','2026-09-01','2026-12-20',1)"
            ).lastrowid
            course_ids = []
            for code, name in (
                ("CS101", "Introduction to Computing"),
                ("MATH120", "Discrete Mathematics"),
                ("ENG105", "Technical Communication"),
            ):
                course_ids.append(
                    connection.execute(
                        "INSERT INTO courses(term_id,code,name) VALUES (?,?,?)",
                        (term_id, code, name),
                    ).lastrowid
                )
            instructor_ids = [
                connection.execute(
                    "INSERT INTO instructors(name,email) VALUES (?,?)",
                    (name, f"{name.split()[0].lower()}@example.edu"),
                ).lastrowid
                for name in ("Alex Morgan", "Riley Chen", "Sam Patel")
            ]
            room_ids = [
                connection.execute(
                    "INSERT INTO rooms(name,building,capacity) VALUES (?,?,?)",
                    (name, "North Hall", capacity),
                ).lastrowid
                for name, capacity in (("N101", 40), ("N202", 28))
            ]
            group_ids = [
                connection.execute(
                    "INSERT INTO student_groups(name,size) VALUES (?,?)",
                    (name, size),
                ).lastrowid
                for name, size in (("Cohort A", 24), ("Cohort B", 18))
            ]
            timeslot_ids = [
                connection.execute(
                    "INSERT INTO timeslots(term_id,label,days,start,length,weeks) "
                    "VALUES (?,?,?,?,?,?)",
                    (term_id, label, "10000", start, 2, "1"),
                ).lastrowid
                for label, start in (("Monday 09:00", 9), ("Monday 11:00", 11))
            ]
            class_specs = (
                ("CS101 lecture", course_ids[0], instructor_ids[0], group_ids[0]),
                ("MATH120 lecture", course_ids[1], instructor_ids[1], group_ids[0]),
                ("ENG105 seminar", course_ids[2], instructor_ids[2], group_ids[1]),
            )
            for name, course_id, instructor_id, group_id in class_specs:
                class_id = connection.execute(
                    "INSERT INTO classes(term_id,course_id,name,instructor_id,"
                    "room_required,expected_enrollment,duration) "
                    "VALUES (?,?,?,?,1,2,2)",
                    (term_id, course_id, name, instructor_id),
                ).lastrowid
                connection.execute(
                    "INSERT INTO class_groups(class_id,group_id) VALUES (?,?)",
                    (class_id, group_id),
                )
            connection.executemany(
                "INSERT INTO app_state(key,value) VALUES (?,?)",
                [
                    ("schema_name", "Timetable local demo"),
                    ("seeded_timeslots", ",".join(map(str, timeslot_ids))),
                    ("seeded_rooms", ",".join(map(str, room_ids))),
                ],
            )
