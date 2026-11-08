from __future__ import annotations

import csv
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
import queue
import sqlite3
import tempfile
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4
import xml.etree.ElementTree as ET

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook

from algorithms import CpSatAlgorithm, CspAlgorithm, RunConfig
from api.database import Database
from model import Schedule
from parser import (
    Class,
    Config,
    Course,
    Distribution,
    Instance,
    Placement,
    Room,
    Student,
    Subpart,
    parse_instance,
)
from validation import validate_schedule_independently


RESOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "terms": ("name", "start_date", "end_date", "active"),
    "courses": ("term_id", "code", "name"),
    "instructors": ("name", "email"),
    "rooms": ("name", "building", "capacity"),
    "groups": ("name", "size"),
    "timeslots": ("term_id", "label", "days", "start", "length", "weeks"),
    "classes": (
        "term_id",
        "course_id",
        "name",
        "instructor_id",
        "room_required",
        "expected_enrollment",
        "duration",
        "allowed_room_ids",
        "allowed_timeslot_ids",
        "preferred_timeslot_ids",
        "preferred_room_ids",
        "active",
        "group_ids",
    ),
}
TABLES = {**{key: key for key in RESOURCE_FIELDS}, "groups": "student_groups"}
REQUIRED_FIELDS = {
    "terms": {"name", "start_date", "end_date"},
    "courses": {"term_id", "code", "name"},
    "instructors": {"name"},
    "rooms": {"name", "capacity"},
    "groups": {"name"},
    "timeslots": {"term_id", "label", "days", "start", "length", "weeks"},
    "classes": {"term_id", "course_id", "name", "duration"},
}
INTEGER_FIELDS = {
    "term_id",
    "course_id",
    "instructor_id",
    "capacity",
    "size",
    "start",
    "length",
    "expected_enrollment",
    "duration",
}
BOOLEAN_FIELDS = {"active", "room_required"}
ID_LIST_FIELDS = {
    "allowed_room_ids",
    "allowed_timeslot_ids",
    "preferred_timeslot_ids",
    "preferred_room_ids",
}
JOB_ACTIVE_STATUSES = {"queued", "running", "cancel_requested"}


def _split_ids(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        parts = value
    else:
        parts = str(value).replace(";", ",").split(",")
    try:
        return sorted({int(item) for item in parts if str(item).strip()})
    except (TypeError, ValueError) as exc:
        raise ValueError("ID lists must contain integers separated by commas") from exc


def _normalize_resource(resource: str, values: dict[str, Any]) -> dict[str, Any]:
    if resource not in RESOURCE_FIELDS:
        raise HTTPException(status_code=404, detail="Unknown academic resource")
    allowed = set(RESOURCE_FIELDS[resource])
    unknown = set(values) - allowed
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported {resource} fields: {sorted(unknown)}",
        )
    result = dict(values)
    for field in INTEGER_FIELDS:
        if field in result and result[field] not in (None, ""):
            try:
                result[field] = int(result[field])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422, detail=f"{field} must be an integer"
                ) from exc
        elif field in result and result[field] == "":
            result[field] = None
    for field in BOOLEAN_FIELDS:
        if field in result:
            value = result[field]
            if value in (None, ""):
                result.pop(field)
                continue
            if isinstance(value, bool):
                result[field] = int(value)
            elif str(value).strip().lower() in {"true", "1", "yes"}:
                result[field] = 1
            elif str(value).strip().lower() in {"false", "0", "no"}:
                result[field] = 0
            else:
                raise HTTPException(
                    status_code=422, detail=f"{field} must be true or false"
                )
    for field in ID_LIST_FIELDS:
        if field in result:
            try:
                result[field] = ",".join(map(str, _split_ids(result[field])))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    if resource == "classes" and "group_ids" in result:
        try:
            result["group_ids"] = _split_ids(result["group_ids"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    missing = REQUIRED_FIELDS[resource] - {
        key for key, value in result.items() if value is not None and value != ""
    }
    if missing:
        raise HTTPException(
            status_code=422, detail=f"Missing required fields: {sorted(missing)}"
        )
    return result


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _db_ids(value: str) -> list[int]:
    return _split_ids(value)


def _parse_itc_xml(source_xml: str) -> Instance:
    with tempfile.TemporaryDirectory() as directory:
        xml_path = Path(directory) / "instance.xml"
        xml_path.write_text(source_xml, encoding="utf-8")
        return parse_instance(xml_path)


def _placement_dict(placement: Placement) -> dict[str, Any]:
    return {
        "room_id": placement.room_id,
        "days": placement.days,
        "start": placement.start,
        "length": placement.length,
        "weeks": placement.weeks,
        "time_penalty": placement.time_penalty,
        "room_penalty": placement.room_penalty,
    }


def _serialize_instance(instance: Instance) -> dict[str, Any]:
    return {
        "name": instance.name,
        "nr_days": instance.nr_days,
        "slots_per_day": instance.slots_per_day,
        "nr_weeks": instance.nr_weeks,
        "time_weight": instance.time_weight,
        "room_weight": instance.room_weight,
        "distribution_weight": instance.distribution_weight,
        "student_weight": instance.student_weight,
        "rooms": [
            {"id": room.id, "capacity": room.capacity}
            for room in instance.rooms.values()
        ],
        "courses": [
            {"id": course.id, "config_ids": course.config_ids}
            for course in instance.courses.values()
        ],
        "configs": [
            {
                "id": config.id,
                "course_id": config.course_id,
                "subpart_ids": config.subpart_ids,
            }
            for config in instance.configs.values()
        ],
        "subparts": [
            {
                "id": subpart.id,
                "config_id": subpart.config_id,
                "class_ids": subpart.class_ids,
            }
            for subpart in instance.subparts.values()
        ],
        "students": [
            {
                "id": student.id,
                "course_ids": student.course_ids,
                "assigned_class_ids": student.assigned_class_ids,
            }
            for student in instance.students.values()
        ],
        "classes": [
            {
                "id": cls.id,
                "course_id": cls.course_id,
                "config_id": cls.config_id,
                "subpart_id": cls.subpart_id,
                "limit": cls.limit,
                "parent_id": cls.parent_id,
                "room_required": cls.room_required,
                "expected_enrollment": cls.expected_enrollment,
                "instructor_ids": cls.instructor_ids,
                "student_group_ids": cls.student_group_ids,
                "placements": [_placement_dict(item) for item in cls.placements],
            }
            for cls in instance.classes.values()
        ],
        "distributions": [
            {
                "type": distribution.type,
                "required": distribution.required,
                "penalty": distribution.penalty,
                "class_ids": distribution.class_ids,
            }
            for distribution in instance.distributions
        ],
    }


def _deserialize_instance(payload: dict[str, Any]) -> Instance:
    rooms = {
        int(item["id"]): Room(
            id=int(item["id"]),
            capacity=(
                None
                if item["capacity"] is None
                else int(item["capacity"])
            ),
        )
        for item in payload["rooms"]
    }
    courses = {
        int(item["id"]): Course(
            id=int(item["id"]),
            config_ids=[int(value) for value in item["config_ids"]],
        )
        for item in payload.get("courses", [])
    }
    configs = {
        int(item["id"]): Config(
            id=int(item["id"]),
            course_id=int(item["course_id"]),
            subpart_ids=[int(value) for value in item["subpart_ids"]],
        )
        for item in payload.get("configs", [])
    }
    subparts = {
        int(item["id"]): Subpart(
            id=int(item["id"]),
            config_id=int(item["config_id"]),
            class_ids=[int(value) for value in item["class_ids"]],
        )
        for item in payload.get("subparts", [])
    }
    students = {
        int(item["id"]): Student(
            id=int(item["id"]),
            course_ids=[int(value) for value in item["course_ids"]],
            assigned_class_ids=[
                int(value) for value in item["assigned_class_ids"]
            ],
        )
        for item in payload.get("students", [])
    }
    classes = {}
    for item in payload["classes"]:
        class_id = int(item["id"])
        placements = [Placement(**placement) for placement in item["placements"]]
        classes[class_id] = Class(
            id=class_id,
            course_id=int(item["course_id"]),
            config_id=int(item["config_id"]),
            subpart_id=int(item["subpart_id"]),
            limit=(
                None
                if item["limit"] is None
                else int(item["limit"])
            ),
            parent_id=item["parent_id"],
            room_required=bool(item["room_required"]),
            placements=placements,
            expected_enrollment=item["expected_enrollment"],
            instructor_ids=[int(value) for value in item["instructor_ids"]],
            student_group_ids=[int(value) for value in item["student_group_ids"]],
        )
    distributions = [
        Distribution(
            type=item["type"],
            required=bool(item["required"]),
            penalty=int(item["penalty"]),
            class_ids=[int(value) for value in item["class_ids"]],
        )
        for item in payload["distributions"]
    ]
    return Instance(
        name=payload["name"],
        nr_days=int(payload["nr_days"]),
        slots_per_day=int(payload["slots_per_day"]),
        nr_weeks=int(payload["nr_weeks"]),
        rooms=rooms,
        courses=courses,
        configs=configs,
        subparts=subparts,
        classes=classes,
        distributions=distributions,
        students=students,
        time_weight=int(payload["time_weight"]),
        room_weight=int(payload["room_weight"]),
        distribution_weight=int(payload["distribution_weight"]),
        student_weight=int(payload["student_weight"]),
    )


def _platform_instance(database: Database, term_id: int) -> Instance:
    with database.connect() as connection:
        term = connection.execute(
            "SELECT id,name FROM terms WHERE id=?", (term_id,)
        ).fetchone()
        if term is None:
            raise HTTPException(status_code=404, detail="Term not found")
        room_rows = connection.execute(
            "SELECT id,capacity FROM rooms ORDER BY id"
        ).fetchall()
        course_terms = {
            row["id"]: row["term_id"]
            for row in connection.execute("SELECT id,term_id FROM courses")
        }
        slot_rows = connection.execute(
            "SELECT * FROM timeslots WHERE term_id=? ORDER BY id", (term_id,)
        ).fetchall()
        class_rows = connection.execute(
            "SELECT * FROM classes WHERE term_id=? AND active=1 ORDER BY id",
            (term_id,),
        ).fetchall()
        associations = connection.execute(
            "SELECT cg.class_id,cg.group_id FROM class_groups cg "
            "JOIN classes c ON c.id=cg.class_id "
            "WHERE c.term_id=? ORDER BY cg.group_id,cg.class_id",
            (term_id,),
        ).fetchall()
    if not class_rows:
        raise HTTPException(status_code=422, detail="Term has no active classes")
    rooms = {
        row["id"]: Room(id=row["id"], capacity=row["capacity"])
        for row in room_rows
    }
    class_groups: dict[int, list[int]] = {}
    for row in associations:
        class_groups.setdefault(row["class_id"], []).append(row["group_id"])
    if not slot_rows:
        raise HTTPException(status_code=422, detail="Term has no timeslots")
    if any(
        not row["days"]
        or set(row["days"]) - {"0", "1"}
        or not row["weeks"]
        or set(row["weeks"]) - {"0", "1"}
        or "1" not in row["days"]
        or "1" not in row["weeks"]
        for row in slot_rows
    ):
        raise HTTPException(
            status_code=422,
            detail="Timeslot day/week masks must be non-empty binary patterns with an active bit",
        )
    if len({len(row["days"]) for row in slot_rows}) != 1 or len(
        {len(row["weeks"]) for row in slot_rows}
    ) != 1:
        raise HTTPException(
            status_code=422,
            detail="All timeslots in a term must use matching day/week mask lengths",
        )
    nr_days = max(len(row["days"]) for row in slot_rows)
    nr_weeks = max(len(row["weeks"]) for row in slot_rows)
    slots_per_day = max(row["start"] + row["length"] for row in slot_rows)
    classes: dict[int, Class] = {}
    courses: dict[int, Course] = {}
    configs: dict[int, Config] = {}
    subparts: dict[int, Subpart] = {}
    for row in class_rows:
        if course_terms.get(row["course_id"]) != term_id:
            raise HTTPException(
                status_code=422,
                detail=f"Class {row['id']} references a course from another term",
            )
        allowed_slots = set(_db_ids(row["allowed_timeslot_ids"]))
        preferred_slots = set(_db_ids(row["preferred_timeslot_ids"]))
        allowed_rooms = set(_db_ids(row["allowed_room_ids"]))
        preferred_rooms = set(_db_ids(row["preferred_room_ids"]))
        unknown_rooms = (allowed_rooms | preferred_rooms) - rooms.keys()
        unknown_slots = (allowed_slots | preferred_slots) - {
            slot["id"] for slot in slot_rows
        }
        if unknown_rooms or unknown_slots:
            raise HTTPException(
                status_code=422,
                detail={
                    "class_id": row["id"],
                    "unknown_room_ids": sorted(unknown_rooms),
                    "unknown_timeslot_ids": sorted(unknown_slots),
                },
            )
        if row["room_required"] and not rooms:
            room_options: list[int | None] = []
        elif row["room_required"]:
            room_options = sorted(allowed_rooms or rooms.keys())
            room_options = [room_id for room_id in room_options if room_id in rooms]
        else:
            room_options = [None]
        placements = []
        for slot in slot_rows:
            if allowed_slots and slot["id"] not in allowed_slots:
                continue
            if row["duration"] > slot["length"]:
                continue
            if slot["start"] + row["duration"] > slots_per_day:
                continue
            for room_id in room_options:
                placements.append(
                    Placement(
                        room_id=room_id,
                        days=slot["days"],
                        start=slot["start"],
                        length=row["duration"],
                        weeks=slot["weeks"],
                        time_penalty=0 if not preferred_slots or slot["id"] in preferred_slots else 1,
                        room_penalty=(
                            0
                            if room_id is None
                            or not preferred_rooms
                            or room_id in preferred_rooms
                            else 1
                        ),
                    )
                )
        cls = Class(
            id=row["id"],
            course_id=row["course_id"],
            config_id=row["course_id"],
            subpart_id=row["id"],
            limit=row["expected_enrollment"] or 0,
            parent_id=None,
            room_required=bool(row["room_required"]),
            placements=placements,
            expected_enrollment=row["expected_enrollment"],
            instructor_ids=(
                [row["instructor_id"]] if row["instructor_id"] is not None else []
            ),
            student_group_ids=class_groups.get(row["id"], []),
        )
        classes[row["id"]] = cls
        subparts[row["id"]] = Subpart(
            id=row["id"], config_id=row["course_id"], class_ids=[row["id"]]
        )
        if row["course_id"] not in courses:
            courses[row["course_id"]] = Course(
                id=row["course_id"], config_ids=[row["course_id"]]
            )
            configs[row["course_id"]] = Config(
                id=row["course_id"],
                course_id=row["course_id"],
                subpart_ids=[],
            )
        configs[row["course_id"]].subpart_ids.append(row["id"])

    attendee_sets: dict[tuple[str, int], list[int]] = {}
    for cls in classes.values():
        for instructor_id in cls.instructor_ids:
            attendee_sets.setdefault(("instructor", instructor_id), []).append(cls.id)
        for group_id in cls.student_group_ids:
            attendee_sets.setdefault(("group", group_id), []).append(cls.id)
    distributions = [
        Distribution(
            type="SameAttendees",
            required=True,
            penalty=0,
            class_ids=class_ids,
        )
        for class_ids in attendee_sets.values()
        if len(class_ids) > 1
    ]
    return Instance(
        name=f"local-term-{term_id}",
        nr_days=nr_days,
        slots_per_day=slots_per_day,
        nr_weeks=nr_weeks,
        rooms=rooms,
        courses=courses,
        configs=configs,
        subparts=subparts,
        classes=classes,
        distributions=distributions,
        students={},
        time_weight=1,
        room_weight=1,
        distribution_weight=1,
        student_weight=0,
    )


class JobManager:
    def __init__(self, database: Database):
        self.database = database
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.lock = Lock()
        self.submit_lock = Lock()
        self.cancel_events: dict[str, Event] = {}
        self.thread: Thread | None = None

    def start(self) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE generation_runs SET status='error',error=?,finished_at=? "
                "WHERE status IN ('running','cancel_requested')",
                (
                    "Application restarted before the run completed.",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        self.thread = Thread(target=self._work, name="timetable-solver", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        with self.lock:
            for event in self.cancel_events.values():
                event.set()
        self.jobs.put(None)
        if self.thread is not None:
            self.thread.join(timeout=2)

    def submit(
        self,
        instance: Instance,
        algorithm: str,
        config: RunConfig,
        *,
        term_id: int | None = None,
        dataset_id: int | None = None,
    ) -> str:
        if algorithm not in {"cp-sat", "csp"}:
            raise HTTPException(status_code=422, detail="algorithm must be cp-sat or csp")
        if config.time_limit_s <= 0:
            raise HTTPException(status_code=422, detail="time_limit_s must be positive")
        identifier = str(uuid4())
        snapshot = _serialize_instance(instance)
        config_data = {
            "time_limit_s": config.time_limit_s,
            "random_seed": config.random_seed,
            "workers": config.workers,
            "algorithm": algorithm,
        }
        with self.submit_lock:
            with self.database.transaction() as connection:
                active = connection.execute(
                    "SELECT id FROM generation_runs "
                    "WHERE status IN ('queued','running','cancel_requested') LIMIT 1"
                ).fetchone()
                if active is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Generation job {active['id']} is already active",
                    )
                connection.execute(
                    "INSERT INTO generation_runs(id,status,algorithm,term_id,dataset_id,"
                    "configuration_json,instance_json) VALUES (?,?,?,?,?,?,?)",
                    (
                        identifier,
                        "queued",
                        algorithm,
                        term_id,
                        dataset_id,
                        json.dumps(config_data),
                        json.dumps(snapshot),
                    ),
                )
            with self.lock:
                self.cancel_events[identifier] = Event()
            self.jobs.put(identifier)
        return identifier

    def cancel(self, identifier: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM generation_runs WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Job not found")
            if row["status"] not in JOB_ACTIVE_STATUSES:
                return {"id": identifier, "status": row["status"]}
            with self.lock:
                event = self.cancel_events.get(identifier)
                if event is not None:
                    event.set()
            connection.execute(
                "UPDATE generation_runs SET status='cancel_requested' WHERE id=?",
                (identifier,),
            )
        return {"id": identifier, "status": "cancel_requested"}

    def _work(self) -> None:
        while True:
            identifier = self.jobs.get()
            if identifier is None:
                return
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM generation_runs WHERE id=?", (identifier,)
                ).fetchone()
            if row is None:
                continue
            with self.lock:
                cancel_event = self.cancel_events.setdefault(identifier, Event())
            if cancel_event.is_set():
                self._finish(identifier, "cancelled", None, None)
                continue
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE generation_runs SET status='running',started_at=? "
                    "WHERE id=? AND status='queued'",
                    (datetime.now(timezone.utc).isoformat(), identifier),
                )
            try:
                instance = _deserialize_instance(json.loads(row["instance_json"]))
                config_data = json.loads(row["configuration_json"])
                config = RunConfig(
                    time_limit_s=float(config_data["time_limit_s"]),
                    random_seed=int(config_data["random_seed"]),
                    cancellation_event=cancel_event,
                )
                algorithm = (
                    CpSatAlgorithm()
                    if row["algorithm"] == "cp-sat"
                    else CspAlgorithm()
                )
                result = algorithm.run(instance, config)
                payload = result.to_dict()
                if cancel_event.is_set():
                    self._finish(
                        identifier,
                        "cancelled",
                        payload,
                        "Cancellation requested by the user.",
                        result.schedule.assignments if result.schedule else {},
                    )
                elif result.successful:
                    self._finish(
                        identifier,
                        "complete",
                        payload,
                        None,
                        result.schedule.assignments if result.schedule else {},
                        make_current=True,
                    )
                else:
                    self._finish(
                        identifier,
                        "invalid_solution" if result.status == "complete" else result.status,
                        payload,
                        result.error,
                        result.schedule.assignments if result.schedule else {},
                    )
            except Exception as exc:
                self._finish(
                    identifier,
                    "error",
                    {"error": str(exc)},
                    f"{type(exc).__name__}: {exc}",
                )
            finally:
                with self.lock:
                    self.cancel_events.pop(identifier, None)

    def _finish(
        self,
        identifier: str,
        status: str,
        payload: dict[str, Any] | None,
        error: str | None,
        assignments: dict[int, Placement] | None = None,
        *,
        make_current: bool = False,
    ) -> None:
        finished = datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            if assignments:
                connection.executemany(
                    "INSERT OR REPLACE INTO schedule_assignments"
                    "(run_id,class_id,placement_json) VALUES (?,?,?)",
                    [
                        (identifier, str(class_id), json.dumps(_placement_dict(item)))
                        for class_id, item in assignments.items()
                    ],
                )
            connection.execute(
                "UPDATE generation_runs SET status=?,result_json=?,error=?,finished_at=? "
                "WHERE id=?",
                (
                    status,
                    json.dumps(payload) if payload is not None else None,
                    error,
                    finished,
                    identifier,
                ),
            )
            if make_current:
                connection.execute(
                    "INSERT INTO app_state(key,value) VALUES ('current_run',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (identifier,),
                )


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    item["configuration"] = json.loads(item.pop("configuration_json"))
    item.pop("instance_json", None)
    item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
    item.pop("result_json", None)
    return item


def create_app(
    database_path: str | Path | None = None,
) -> FastAPI:
    database = Database(database_path)
    manager = JobManager(database)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        manager.start()
        try:
            yield
        finally:
            manager.stop()

    app = FastAPI(
        title="University Timetabling Platform",
        version="0.1.0",
        description="Local-first course data management and validated schedule generation.",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.jobs = manager

    @app.get("/api/health")
    def health() -> dict[str, str]:
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "connected"}

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        with database.connect() as connection:
            totals = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "terms",
                    "courses",
                    "instructors",
                    "rooms",
                    "student_groups",
                    "timeslots",
                    "classes",
                )
            }
            recent = connection.execute(
                "SELECT id,status,algorithm,created_at,finished_at FROM "
                "generation_runs ORDER BY created_at DESC LIMIT 8"
            ).fetchall()
            current = connection.execute(
                "SELECT value FROM app_state WHERE key='current_run'"
            ).fetchone()
            active_term = connection.execute(
                "SELECT id,name FROM terms WHERE active=1 ORDER BY id LIMIT 1"
            ).fetchone()
        return {
            "counts": totals,
            "recent_runs": [_row_dict(row) for row in recent],
            "current_run_id": current["value"] if current else None,
            "active_term": _row_dict(active_term) if active_term else None,
        }

    @app.get("/api/academic/{resource}")
    def list_academic(
        resource: str,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        if resource not in RESOURCE_FIELDS:
            raise HTTPException(status_code=404, detail="Unknown academic resource")
        table = TABLES[resource]
        with database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            values = [_row_dict(row) for row in rows]
            if resource == "classes":
                for value in values:
                    value["group_ids"] = [
                        row["group_id"]
                        for row in connection.execute(
                            "SELECT group_id FROM class_groups WHERE class_id=? "
                            "ORDER BY group_id",
                            (value["id"],),
                        )
                    ]
        return {"items": values, "total": total, "limit": limit, "offset": offset}

    def save_resource(
        resource: str,
        values: dict[str, Any],
        identifier: int | None = None,
    ) -> dict[str, Any]:
        if resource not in RESOURCE_FIELDS:
            raise HTTPException(status_code=404, detail="Unknown academic resource")
        table = TABLES[resource]
        with database.transaction() as connection:
            if identifier is not None:
                existing = connection.execute(
                    f"SELECT * FROM {table} WHERE id=?", (identifier,)
                ).fetchone()
                if existing is None:
                    raise HTTPException(status_code=404, detail="Record not found")
                unknown = set(values) - set(RESOURCE_FIELDS[resource])
                if unknown:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Unsupported {resource} fields: {sorted(unknown)}",
                    )
                merged = _row_dict(existing)
                merged.pop("id", None)
                merged.update(values)
                if resource == "classes":
                    merged["group_ids"] = values.get("group_ids", [
                        row["group_id"]
                        for row in connection.execute(
                            "SELECT group_id FROM class_groups WHERE class_id=?",
                            (identifier,),
                        )
                    ])
                normalized = _normalize_resource(resource, merged)
                group_ids = normalized.pop("group_ids", [])
                columns = [key for key in RESOURCE_FIELDS[resource] if key in normalized]
                if not columns:
                    raise HTTPException(status_code=422, detail="No fields to update")
                assignments_sql = ",".join(f"{column}=?" for column in columns)
                connection.execute(
                    f"UPDATE {table} SET {assignments_sql} WHERE id=?",
                    [normalized[column] for column in columns] + [identifier],
                )
                saved_id = identifier
            else:
                normalized = _normalize_resource(resource, values)
                group_ids = normalized.pop("group_ids", [])
                missing = REQUIRED_FIELDS[resource] - set(normalized)
                if missing:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Missing required fields: {sorted(missing)}",
                    )
                columns = [key for key in RESOURCE_FIELDS[resource] if key in normalized]
                cursor = connection.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)})",
                    [normalized[column] for column in columns],
                )
                saved_id = int(cursor.lastrowid)
            if resource == "classes":
                connection.execute("DELETE FROM class_groups WHERE class_id=?", (saved_id,))
                connection.executemany(
                    "INSERT INTO class_groups(class_id,group_id) VALUES (?,?)",
                    [(saved_id, group_id) for group_id in group_ids],
                )
            saved = connection.execute(
                f"SELECT * FROM {table} WHERE id=?", (saved_id,)
            ).fetchone()
            result = _row_dict(saved)
            if resource == "classes":
                result["group_ids"] = group_ids
        return result

    @app.post("/api/academic/{resource}", status_code=201)
    def create_academic(resource: str, values: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return save_resource(resource, values)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/academic/{resource}/{identifier}")
    def update_academic(
        resource: str, identifier: int, values: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        try:
            return save_resource(resource, values, identifier)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/academic/{resource}/{identifier}", status_code=204)
    def delete_academic(resource: str, identifier: int) -> Response:
        if resource not in RESOURCE_FIELDS:
            raise HTTPException(status_code=404, detail="Unknown academic resource")
        try:
            with database.transaction() as connection:
                cursor = connection.execute(
                    f"DELETE FROM {TABLES[resource]} WHERE id=?", (identifier,)
                )
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Record not found")
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.get("/api/templates/{resource}")
    def csv_template(resource: str) -> Response:
        if resource not in RESOURCE_FIELDS:
            raise HTTPException(status_code=404, detail="Unknown academic resource")
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(RESOURCE_FIELDS[resource])
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{resource}-template.csv"'},
        )

    @app.post("/api/import/csv/{resource}")
    async def import_csv(resource: str, request: Request) -> dict[str, Any]:
        if resource not in RESOURCE_FIELDS:
            raise HTTPException(status_code=404, detail="Unknown academic resource")
        text = (await request.body()).decode("utf-8-sig")
        reader = csv.DictReader(StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(status_code=422, detail="CSV must include a header row")
        rows = list(reader)
        if not rows:
            raise HTTPException(status_code=422, detail="CSV has no data rows")
        parsed = [_normalize_resource(resource, row) for row in rows]
        table = TABLES[resource]
        inserted = []
        try:
            with database.transaction() as connection:
                for values in parsed:
                    groups = values.pop("group_ids", [])
                    columns = [key for key in RESOURCE_FIELDS[resource] if key in values]
                    cursor = connection.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) "
                        f"VALUES ({','.join('?' for _ in columns)})",
                        [values[column] for column in columns],
                    )
                    identifier = int(cursor.lastrowid)
                    if resource == "classes":
                        connection.executemany(
                            "INSERT INTO class_groups(class_id,group_id) VALUES (?,?)",
                            [(identifier, group_id) for group_id in groups],
                        )
                    inserted.append(identifier)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"CSV batch rolled back due to a data conflict: {exc}",
            ) from exc
        return {"resource": resource, "imported": len(inserted), "ids": inserted}

    @app.get("/api/datasets")
    def list_datasets() -> dict[str, Any]:
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT id,name,format,created_at FROM datasets ORDER BY id DESC"
            ).fetchall()
        return {"items": [_row_dict(row) for row in rows]}

    @app.post("/api/import/itc", status_code=201)
    async def import_itc(
        request: Request,
        name: str = Query(default="Imported ITC dataset", min_length=1, max_length=200),
    ) -> dict[str, Any]:
        source_xml = (await request.body()).decode("utf-8")
        if len(source_xml.encode("utf-8")) > 25_000_000:
            raise HTTPException(status_code=413, detail="XML import exceeds 25 MB")
        try:
            ET.fromstring(source_xml)
            instance = _parse_itc_xml(source_xml)
        except (ET.ParseError, KeyError, ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid ITC XML: {exc}") from exc
        with database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO datasets(name,format,source_xml) VALUES (?,?,?)",
                (name, "itc-2019-xml", source_xml),
            )
            dataset_id = int(cursor.lastrowid)
        return {
            "id": dataset_id,
            "name": name,
            "format": "itc-2019-xml",
            "classes": len(instance.classes),
            "rooms": len(instance.rooms),
            "distributions": len(instance.distributions),
        }

    @app.post("/api/jobs", status_code=202)
    def create_job(values: dict[str, Any] = Body(...)) -> dict[str, Any]:
        allowed = {"term_id", "dataset_id", "algorithm", "time_limit_s", "random_seed"}
        unknown = set(values) - allowed
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unsupported fields: {sorted(unknown)}")
        if ("term_id" in values) == ("dataset_id" in values):
            raise HTTPException(
                status_code=422, detail="Provide exactly one of term_id or dataset_id"
            )
        algorithm = values.get("algorithm", "cp-sat")
        try:
            time_limit_s = float(values.get("time_limit_s", 30))
            random_seed = int(values.get("random_seed", 0))
            if not 0 < time_limit_s <= 3600:
                raise ValueError("time_limit_s must be in (0, 3600]")
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        term_id = values.get("term_id")
        dataset_id = values.get("dataset_id")
        if term_id is not None:
            try:
                term_id = int(term_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="term_id must be an integer") from exc
            instance = _platform_instance(database, term_id)
        else:
            try:
                dataset_id = int(dataset_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="dataset_id must be an integer") from exc
            with database.connect() as connection:
                dataset = connection.execute(
                    "SELECT * FROM datasets WHERE id=?", (dataset_id,)
                ).fetchone()
            if dataset is None:
                raise HTTPException(status_code=404, detail="Dataset not found")
            if dataset["format"] != "itc-2019-xml" or not dataset["source_xml"]:
                raise HTTPException(status_code=422, detail="Dataset format is unsupported")
            try:
                instance = _parse_itc_xml(dataset["source_xml"])
            except (ET.ParseError, KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Invalid stored dataset: {exc}") from exc
        config = RunConfig(
            time_limit_s=time_limit_s,
            random_seed=random_seed,
            workers=1,
        )
        identifier = manager.submit(
            instance,
            algorithm,
            config,
            term_id=term_id,
            dataset_id=dataset_id,
        )
        return {"id": identifier, "status": "queued", "algorithm": algorithm}

    @app.get("/api/jobs")
    def list_jobs(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM generation_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return {"items": [_job_dict(row) for row in rows]}

    @app.get("/api/jobs/{identifier}")
    def get_job(identifier: str) -> dict[str, Any]:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_dict(row)

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel_job(identifier: str) -> dict[str, Any]:
        return manager.cancel(identifier)

    @app.get("/api/schedules/current")
    def current_schedule() -> dict[str, Any]:
        with database.connect() as connection:
            current = connection.execute(
                "SELECT value FROM app_state WHERE key='current_run'"
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="No validated schedule yet")
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (current["value"],)
            ).fetchone()
        return _job_dict(row)

    @app.get("/api/schedules/{identifier}")
    def get_schedule(identifier: str) -> dict[str, Any]:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Schedule run not found")
        result = _job_dict(row)
        if result["result"] is None:
            raise HTTPException(status_code=409, detail="Schedule result is not ready")
        return result

    @app.get("/api/schedules/{identifier}/domains/{class_id}")
    def assignment_domain(identifier: str, class_id: int) -> dict[str, Any]:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT instance_json FROM generation_runs WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Schedule run not found")
        instance = _deserialize_instance(json.loads(row["instance_json"]))
        cls = instance.classes.get(class_id)
        if cls is None:
            raise HTTPException(status_code=404, detail="Class not found in this run")
        return {
            "class_id": class_id,
            "placements": [
                {"placement_index": index, **_placement_dict(placement)}
                for index, placement in enumerate(cls.placements)
            ],
        }

    @app.put("/api/schedules/{identifier}/assignments/{class_id}")
    def edit_assignment(
        identifier: str, class_id: int, values: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        if set(values) != {"placement_index"}:
            raise HTTPException(status_code=422, detail="Provide only placement_index")
        try:
            placement_index = int(values["placement_index"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="placement_index must be an integer") from exc
        with database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Schedule run not found")
            if row["term_id"] is None or row["status"] != "complete":
                raise HTTPException(
                    status_code=409,
                    detail="Only completed local-term schedules can be edited",
                )
            instance = _deserialize_instance(json.loads(row["instance_json"]))
            cls = instance.classes.get(class_id)
            if cls is None or not 0 <= placement_index < len(cls.placements):
                raise HTTPException(status_code=422, detail="Placement is outside the class domain")
            payload = json.loads(row["result_json"])
            assignments = {
                int(item["class_id"]): Placement(
                    room_id=item["room_id"],
                    days=item["days"],
                    start=item["start"],
                    length=item["length"],
                    weeks=item["weeks"],
                    time_penalty=item["time_penalty"],
                    room_penalty=item["room_penalty"],
                )
                for item in payload["assignments"]
            }
            assignments[class_id] = cls.placements[placement_index]
            schedule = Schedule(instance)
            for assigned_class, placement in assignments.items():
                schedule.assign(assigned_class, placement)
            report = validate_schedule_independently(instance, schedule)
            if not report.valid_complete:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Edit rejected because the complete schedule is invalid",
                        "validation": report.to_dict(),
                    },
                )
            payload["assignments"] = [
                {
                    "class_id": assigned_class,
                    **_placement_dict(placement),
                }
                for assigned_class, placement in sorted(assignments.items())
            ]
            payload["validation"] = report.to_dict()
            payload["objective_score"] = report.objective_score
            connection.execute(
                "UPDATE generation_runs SET result_json=? WHERE id=?",
                (json.dumps(payload), identifier),
            )
            connection.execute(
                "DELETE FROM schedule_assignments WHERE run_id=?", (identifier,)
            )
            connection.executemany(
                "INSERT INTO schedule_assignments(run_id,class_id,placement_json) "
                "VALUES (?,?,?)",
                [
                    (identifier, str(assigned_class), json.dumps(_placement_dict(item)))
                    for assigned_class, item in assignments.items()
                ],
            )
        return {"id": identifier, "validation": report.to_dict(), "result": payload}

    @app.get("/api/exports/{identifier}.{file_format}")
    def export_schedule(identifier: str, file_format: str) -> Response:
        if file_format not in {"csv", "xlsx"}:
            raise HTTPException(status_code=404, detail="Export format must be csv or xlsx")
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id=?", (identifier,)
            ).fetchone()
            assignments = connection.execute(
                "SELECT class_id,placement_json FROM schedule_assignments "
                "WHERE run_id=? ORDER BY class_id",
                (identifier,),
            ).fetchall()
            names = {
                str(item["id"]): item["name"]
                for item in connection.execute("SELECT id,name FROM classes")
            }
        if row is None or row["result_json"] is None:
            raise HTTPException(status_code=404, detail="Schedule result not found")
        if file_format == "csv":
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(
                ["class_id", "class_name", "room_id", "days", "start", "length", "weeks"]
            )
            for item in assignments:
                placement = json.loads(item["placement_json"])
                writer.writerow(
                    [
                        item["class_id"],
                        names.get(item["class_id"], f"Class {item['class_id']}"),
                        placement["room_id"],
                        placement["days"],
                        placement["start"],
                        placement["length"],
                        placement["weeks"],
                    ]
                )
            return Response(
                output.getvalue(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="schedule-{identifier}.csv"'
                },
            )
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Schedule"
        sheet.append(
            ["Class ID", "Class name", "Room ID", "Days", "Start", "Length", "Weeks"]
        )
        for item in assignments:
            placement = json.loads(item["placement_json"])
            sheet.append(
                [
                    item["class_id"],
                    names.get(item["class_id"], f"Class {item['class_id']}"),
                    placement["room_id"],
                    placement["days"],
                    placement["start"],
                    placement["length"],
                    placement["weeks"],
                ]
            )
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        output = BytesIO()
        workbook.save(output)
        return Response(
            output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="schedule-{identifier}.xlsx"'
            },
        )

    static_directory = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_directory), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> Response:
        index = static_directory / "index.html"
        return Response(index.read_text(encoding="utf-8"), media_type="text/html")

    return app


app = create_app()
