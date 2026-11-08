CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id INTEGER NOT NULL REFERENCES terms(id),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE (term_id, code)
);

CREATE TABLE IF NOT EXISTS instructors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    building TEXT NOT NULL DEFAULT '',
    capacity INTEGER NOT NULL CHECK (capacity >= 0)
);

CREATE TABLE IF NOT EXISTS student_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL DEFAULT 0 CHECK (size >= 0)
);

CREATE TABLE IF NOT EXISTS timeslots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id INTEGER NOT NULL REFERENCES terms(id),
    label TEXT NOT NULL,
    days TEXT NOT NULL,
    start INTEGER NOT NULL CHECK (start >= 0),
    length INTEGER NOT NULL CHECK (length > 0),
    weeks TEXT NOT NULL,
    UNIQUE (term_id, label)
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id INTEGER NOT NULL REFERENCES terms(id),
    course_id INTEGER NOT NULL REFERENCES courses(id),
    name TEXT NOT NULL,
    instructor_id INTEGER REFERENCES instructors(id),
    room_required INTEGER NOT NULL DEFAULT 1 CHECK (room_required IN (0, 1)),
    expected_enrollment INTEGER CHECK (
        expected_enrollment IS NULL OR expected_enrollment >= 0
    ),
    duration INTEGER NOT NULL CHECK (duration > 0),
    allowed_room_ids TEXT NOT NULL DEFAULT '',
    allowed_timeslot_ids TEXT NOT NULL DEFAULT '',
    preferred_timeslot_ids TEXT NOT NULL DEFAULT '',
    preferred_room_ids TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS class_groups (
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES student_groups(id) ON DELETE CASCADE,
    PRIMARY KEY (class_id, group_id)
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    format TEXT NOT NULL,
    source_xml TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    term_id INTEGER REFERENCES terms(id),
    dataset_id INTEGER REFERENCES datasets(id),
    configuration_json TEXT NOT NULL,
    instance_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS schedule_assignments (
    run_id TEXT NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
    class_id TEXT NOT NULL,
    placement_json TEXT NOT NULL,
    PRIMARY KEY (run_id, class_id)
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_courses_term ON courses(term_id);
CREATE INDEX IF NOT EXISTS idx_timeslots_term ON timeslots(term_id);
CREATE INDEX IF NOT EXISTS idx_classes_term ON classes(term_id);
CREATE INDEX IF NOT EXISTS idx_runs_created ON generation_runs(created_at);
