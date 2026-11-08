# Architecture and supported vertical slice

## Current runtime

The repository now has a local FastAPI application, a standard-library
SQLite persistence layer with versioned SQL migrations, a single background
generation worker, and a small browser UI served by the API. The solver
adapters remain outside the HTTP and persistence modules. SQLite is selected
for a reliable single-user/local first vertical slice; the schema uses
normalized relational records and a repository boundary so PostgreSQL and a
durable multi-process queue can be introduced without coupling them to solver
code.

The frontend is intentionally plain HTML/CSS/JavaScript with no build step.
Node/npm are not available in the inspected environment, and the local Docker
engine is not running. A full Next.js application and Compose smoke test
therefore remain future work; the current UI is functional and uses actual API
data rather than sample-only widgets.

## Data flow

```text
Browser UI -> FastAPI request schemas -> SQLite repositories/services
                                      -> queued run (single worker)
                                      -> normalized Instance -> CP-SAT
                                      -> independent validator
                                      -> persisted run and assignments
```

The worker marks interrupted in-progress rows as failed on startup. Only a
complete independently validated run becomes the current timetable. Failed,
unsupported, cancelled, or partial runs stay in history and do not replace a
previous successful result. A database guard and process lock prevent two
generation jobs from concurrently mutating a schedule in one application
process. Multi-process deployment requires a PostgreSQL-backed lock/queue.

## Persisted entities

`academic_terms`, `courses`, `instructors`, `rooms`, `student_groups`,
`timeslots`, `classes`, `class_groups`, `datasets`, `generation_runs`, and
`schedule_assignments` are initialized by
[001_initial.sql](../api/migrations/001_initial.sql). Foreign keys preserve
relationships. ITC XML datasets are stored with their source-format identity
and are reparsed through the existing parser instead of flattened into the
generic CSV schema.

## APIs

- `/api/health`, `/api/dashboard`
- `/api/academic/{terms,courses,instructors,rooms,groups,timeslots,classes}`
  CRUD; paginated list filters use `limit` and `offset`
- `/api/templates/{resource}` and `/api/import/csv/{resource}`
- `/api/import/itc`, `/api/datasets`
- `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/{id}/cancel`
- `/api/schedules/current`, `/api/schedules/{run_id}`,
  `/api/schedules/{run_id}/assignments/{class_id}`
- `/api/exports/{run_id}.csv` and `.xlsx`

The OpenAPI schema is available at `/docs`. There is no authentication in this
local-only first version; do not expose it to an untrusted network.

## Validation and unsupported data

The independent validator rechecks that the schedule is complete, assignments
belong to their class domains, rooms do not overlap, and required supported
distributions hold. It reports unknown hard constraints as incomplete
coverage. Room capacity is checked against explicit expected enrollment;
required-room classes without that input are reported as incomplete coverage.
The demo schema contains instructor and group relationships and
converts their shared attendees into explicit `SameAttendees` constraints.
The ITC parser retains individual course requests, class limits, optional
solution memberships, and course/configuration/subpart/parent relationships.
`sectioning.py` can solve and independently validate enrollment and student
conflicts for a fixed complete timetable. API job snapshots preserve those
normalized relationships. However, the timetable adapters still reject the
nonzero student objective until timetable placement and sectioning are
optimized jointly; the web job service does not yet call the fixed-timetable
sectioner. The ITC XML also has no class-to-instructor assignments, which are
reported as unavailable rather than inferred.

CSV import validates every row before opening a transaction; any row error
rejects the batch. Manual edits are revalidated before commit and invalid
changes are rejected. CSV/XLSX exports carry the term and run timestamp.

## Local operation and deployment

The local app uses `TIMETABLE_DB` (default `instance/timetable.sqlite3`) and
`TIMETABLE_ITC_PATH` (default `data/pu-d5-spr17.xml`). Database migrations run
on startup and seed a small clearly labeled demonstration dataset when the
tables are empty.

`Dockerfile` and `compose.yaml` describe a containerized local run. A
PostgreSQL service, Next.js frontend, distributed queue, production
authentication, and multi-instance deployment are not implemented in this
slice.
