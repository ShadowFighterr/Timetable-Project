# University Timetabling Platform

A local-first university course timetabling prototype. It combines the existing
CSP baseline and OR-Tools CP-SAT adapter with an independent validator, a
persisted FastAPI service, and a browser interface. The scope is deliberately
honest: this is a usable research/demo vertical slice, not a production
multi-tenant campus system or a complete ITC 2019 solver.

## Install

Use Python 3.10 or newer (Python 3.13 is supported by the tested dependency
set). From the repository directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

This installs OR-Tools, FastAPI, Uvicorn, openpyxl, and httpx (for API tests).
If `python` is already configured for another project environment, invoke that
environment's interpreter explicitly instead.

## Start the web application

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> for the browser UI and
<http://127.0.0.1:8000/docs> for the interactive API schema. The first start
creates `instance/timetable.sqlite3`, applies the versioned SQLite migration,
and seeds clearly labeled demonstration records only when the database has no
academic terms.

The UI manages terms, courses, instructors, rooms, student groups, timeslots,
and classes; supports validated CSV imports/templates and ITC 2019 XML import;
queues CP-SAT jobs; shows saved run history and independent validation; rejects
invalid manual placement edits; and exports schedules to CSV/XLSX. One
in-process worker runs one job at a time. CP-SAT and CSP both observe job
cancellation. Only complete schedules accepted by the independent validator
replace the current schedule.

The service has **no authentication** and is intended for local/trusted
development only. Do not bind it to an untrusted network.

## Reproducible algorithm benchmark

From the repository directory:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run --instance data/pu-d5-spr17.xml --time-limit 60
```

The command runs the CSP and CP-SAT adapters with one worker and a common
wall-clock budget, prints measured result summaries, and saves a timestamped
JSON record under `results/`. Choose another output path with `--output`.
For a small known positive-cost comparison, run:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run --synthetic-objective --time-limit 10 --output results/benchmark-synthetic-objective.json
```

The latest recorded full-instance run used a 10-second budget. Both timetable
adapters explicitly rejected the nonzero student objective before search;
there is no complete timetable on which to run the new conditional sectioning
stage. Neither adapter produced a timetable, and this does not prove
infeasibility. The saved full-instance run assigned 0/1,061 classes: CSP
returned `unsupported` in 0.000449 s and CP-SAT returned `unsupported` in
1.017551 s. On the small shared synthetic feasible case, both returned
complete independently valid assignments with objective score 0. On the
synthetic positive-cost case, both returned complete independently validated
assignments with score 15 and both solver search records reported `OPTIMAL`.
These tiny cases verify objective agreement, not scaling or algorithm
superiority. The raw measured runs are saved in
[results/benchmark-full-sectioning-check.json](results/benchmark-full-sectioning-check.json),
[results/benchmark-synthetic-current.json](results/benchmark-synthetic-current.json),
and
[results/benchmark-synthetic-objective.json](results/benchmark-synthetic-objective.json).

The CP-SAT hard-constraint model supports room non-overlap, required pairwise
rules, `Precedence`, `WorkDay`, `MinGap`, `MaxDays`, `MaxDayLoad`, and
`MaxBreaks(R,S)`. Multi-class `MaxBreaks` uses an exact day/week timeline model;
its break threshold is in the instance's time slots. The independent validator
uses a separate interval-based implementation. CP-SAT minimizes weighted
time/room placement costs and weighted soft pairwise distribution penalties
for the supported pairwise, `Precedence`, `WorkDay`, and `MinGap` types.
`MaxBlock`, soft global distributions, unknown hard/soft rules, and a
nonzero student objective with student requests are rejected explicitly.

This is not yet full ITC 2019 support. The supplied instance has 13,497 student
records, 19,614 course requests, 1,061 classes, 222 configurations, and 294
subparts. All class limits and all 84 room capacities are supplied; no
student-to-class section memberships are supplied. Those memberships can be
chosen from the course/configuration/subpart/parent data, and the new
CP-SAT-based sectioning component does so for a **fixed complete timetable**.
It derives actual section enrollments and checks class and room capacities
without inventing them. The full timetable adapters still reject the student
objective because its decisions must be optimized jointly with class
placements for an overall optimum. Use synthetic instances or normalized
instances with zero student objective and complete validation coverage for
class-placement algorithm comparisons.

The conditional sectioning API and its input semantics, score boundary, and
remaining joint-optimization blocker are documented in
[docs/SECTIONING.md](docs/SECTIONING.md).

The CSP adapter uses branch-and-bound to minimize the same supported weighted
placement and soft-pair objective as CP-SAT; its result distinguishes a
validated complete incumbent from a proven objective optimum. The saved
positive-cost synthetic comparison exercises a soft `NotOverlap` cost and
gets independently validated score 15 from both engines. It is a deterministic
functional fixture, not evidence about comparative performance on realistic
instances. Compare algorithms only when both have identical modeled hard-rule
coverage and complete validation coverage.

See [docs/LITERATURE_REVIEW.md](docs/LITERATURE_REVIEW.md) for the
source-backed comparison of algorithm families and
[docs/ALGORITHM_SELECTION.md](docs/ALGORITHM_SELECTION.md) for the scoped
CP-SAT recommendation. The benchmark limitation and product architecture are
documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Data, validation, and limits

The ITC parser reads room/time placement domains, course structure,
distribution rules, individual course requests, class limits, and optional
solution student memberships. The fixed-timetable sectioner can choose the
missing class memberships and derive enrollments. No class-to-instructor
assignment is present, so direct instructor conflicts cannot be reconstructed.
Explicit `SameAttendees` relations are checked. The independent timetable
validator reports completeness, missing assignments, invalid domain choices,
room overlaps, room compatibility, explicit expected-enrollment capacity,
supported required distributions, and unsupported constraint coverage. A
separate sectioning validator checks section choices and derives class/room
capacity from those choices. A partial assignment is never a valid complete
timetable.

For the local platform schema, instructor assignments and explicit student
groups are available and their simultaneous conflicts are checked. These
records are a simplified model: class groups are fixed; fixed-timetable
sectioning is not yet integrated into timetable generation or the web UI;
room closures/availability calendars are not yet editable in the web data
model; and travel-time rules are not configurable in the UI. Required
relationships are passed to the solvers as
`SameAttendees` constraints and rechecked independently.

Persisted data can be relocated with `TIMETABLE_DB`. ITC XML is imported from
the Imports page or `POST /api/import/itc` as `application/xml`; the import is
validated before it is stored. The platform uses SQLite and a process-local
queue for the first vertical slice. PostgreSQL, multi-process queue/locking,
authentication/authorization, and a separate Next.js frontend are deferred.
The no-build browser client is served directly by FastAPI.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m compileall -q algorithms api benchmarks tests
.\.venv\Scripts\python.exe -m pip check
```

The latest full suite passed 80 tests in 9.083 seconds. It covers existing
constraint and solver behavior, independent validation, algorithm statuses,
SQLite migrations/seeding, academic CRUD, transactional CSV import, ITC XML
import, background runs, safe schedule editing, history, and CSV/XLSX output.

## Container option

`Dockerfile` and `compose.yaml` provide an optional local container run. They
are supplied for portability but have not been smoke-tested in an environment
where the Docker engine is available.
