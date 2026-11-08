# Project status

## Repository and evidence caveats

This assessment is based on the source, tests, documentation, and saved results
in this repository. The project directory and its parent are not inside a Git
repository (`git status` and recent-commit inspection are unavailable), so
there is no verifiable clean/dirty state or commit history to report.

Status labels below describe evidence, not intent:

- **Implemented and verified** — exercised by a test, command, or observed
  workflow.
- **Implemented but unverified** — code exists, but no sufficient verification
  was found.
- **Partially implemented** — some stated scope works, but material behavior
  or coverage is missing.
- **Not implemented** — no implementation was found.

## 1. Literature review

**Status: Implemented and verified (focused review; not a systematic review).**

The repository contains a comparative review of CSP, CP-SAT/MIP, MaxSAT,
metaheuristics, and hybrid approaches in
[docs/LITERATURE_REVIEW.md](docs/LITERATURE_REVIEW.md). The bibliography's
publication metadata was cross-checked against Crossref/OpenAlex records and
publisher DOI records. Verified records include:

- Chen et al. (2021), DOI `10.1109/ACCESS.2021.3100613`
- Abdipoor et al. (2023), DOI `10.1016/j.iswa.2023.200253`
- Ceschia et al. (2023), DOI `10.1016/j.ejor.2022.07.011`
- Asín Achá and Nieuwenhuis (2014), DOI `10.1007/s10479-012-1081-x`
- Holm et al. (2022), DOI `10.1007/s10951-022-00724-y`
- Lemos et al. (2022), DOI `10.1007/s10951-021-00695-6`
- Müller et al. (2025), DOI `10.1007/s10951-023-00801-w`
- Lewis (2008), DOI `10.1007/s00291-007-0097-0`
- Sylejmani et al. (2023 print issue), DOI `10.1007/s10951-022-00747-5`

The review itself notes that Abdullah et al.'s publication-page details should
be rechecked against the publisher before formal submission. The review is not
evidence that a particular algorithm is empirically superior on this project's
data.

## 2. Scheduling algorithm decision

**Status: Partially implemented.**

[docs/ALGORITHM_SELECTION.md](docs/ALGORITHM_SELECTION.md) selects OR-Tools
CP-SAT as the first engine for the subset the adapter explicitly models, while
retaining the existing CSP as a baseline. This is a conditional engineering
choice, not a proven best-algorithm result. The evidence is that both engines
can produce complete, independently validated solutions on the small
synthetic cases. The latest full ITC run is not comparable: both timetable
adapters reject the nonzero student objective before search. No performance
winner has been established.

## 3. Implementation status

| Area or feature | Status | Evidence and boundary |
|---|---|---|
| FastAPI backend and academic-data API | **Implemented and verified** | API tests exercise health, dashboard, CRUD, import, scheduling, edits, and exports. |
| Browser frontend | **Implemented and verified** | Static browser client is served by FastAPI; startup/UI route and static assets are covered by API tests, and a prior live browser smoke check loaded the dashboard. No automated browser interaction suite exists. |
| SQLite database and migrations | **Implemented and verified** | A fresh temporary database is initialized, migrated, seeded, used for a run, and reopened in the end-to-end API test. |
| CSP baseline | **Implemented and verified** | Synthetic feasibility, infeasibility, timeout, partial assignment, capacity, cancellation, supported weighted objective, incumbent, and optimum-status behavior are tested. |
| OR-Tools CP-SAT adapter | **Partially implemented** | Synthetic tests cover required rules including exact multi-class `MaxBreaks`, plus weighted soft pairwise/Precedence/WorkDay/MinGap objective terms. It rejects `MaxBlock`, soft global constraints, unknown rules, and nonzero student objective when student requests exist. |
| Fixed-timetable student sectioning | **Partially implemented** | CP-SAT chooses one configuration and one class per subpart, observes parent links and class/room limits, honors optional source memberships, and minimizes a scoped student-conflict cost. Synthetic cases only; it is not jointly integrated with timetable placement. |
| Independent schedule and sectioning validators | **Partially implemented** | Schedule completeness, placements, room conflicts/capacity, required distributions, and supported soft terms are checked. A separate sectioning validator checks request coverage, configuration/subpart/parent consistency, capacities, and student conflict pairs. Full objective coverage and unsupported rules still prevent full ITC claims. |
| Background jobs and run history | **Implemented and verified** | API tests cover generation, saved history, cancellation/status behavior, and protection of the current schedule from failed runs. The queue is in-process and single-worker. |
| Academic data CRUD and CSV import/templates | **Implemented and verified** | Test coverage includes CRUD and transactional CSV import/template retrieval. |
| ITC XML import | **Implemented and verified** | An API test imports and validates XML before persistence. Import support does not imply full solver support for every imported rule. |
| Manual schedule edits | **Implemented and verified** | The end-to-end API test rejects an invalid edit, accepts a valid edit, and checks the edited timetable after application restart. |
| CSV/XLSX schedule export | **Implemented and verified** | End-to-end API test checks CSV output and XLSX file response; edited data is reflected in CSV. |
| Fresh dependency installation from scratch | **Implemented but unverified** | Requirements and install instructions are present; this assessment used the existing project virtual environment rather than a newly provisioned environment. |
| Docker deployment | **Implemented but unverified** | Docker files exist; Docker engine was unavailable for a container smoke test. |
| Authentication and authorization | **Not implemented** | The service is documented for trusted local development only. |
| PostgreSQL and durable multi-process job queue | **Not implemented** | SQLite and an in-process queue are the current local-first implementation. |
| Joint timetable and student-sectioning optimization | **Not implemented** | The fixed-timetable sectioner is separate; class placements and section choices are not optimized together. Timetable adapters still reject nonzero student-objective instances. |
| ITC direct instructor assignments | **Not implemented** | The supplied instance has no class-to-instructor records; none are fabricated. |
| Official full ITC 2019 objective/scoring | **Not implemented** | Student-conflict weights/split and final total-score normalization have not been verified end to end. |
| Production multi-tenant campus deployment | **Not implemented** | Current application is a local research/demo vertical slice. |

### `pu-d5-spr17` distribution support matrix

Counts below were measured from the parsed `data/pu-d5-spr17.xml` instance.
“CP-SAT supported” describes implemented rule semantics, not a claim that the
entire dataset has a supported objective or fits within the model-build budget.

| Distribution type | Required / soft count | Parser | Independent validator | CP-SAT hard / soft objective |
|---|---:|---|---|---|
| `SameAttendees` | 768 / 2 | Stores type, class IDs, penalty, required flag | Supported | Supported / supported per violated pair |
| `SameDays` | 152 / 14 | Stores distribution records | Supported | Supported / supported per violated pair |
| `Precedence` | 84 / 11 | Stores distribution records | Supported | Supported / supported per violating ordered pair |
| `WorkDay(*)` | 115 / 11 | Stores distribution records | Supported | Supported / supported per violated pair |
| `DifferentDays` | 49 / 0 | Stores distribution records | Supported | Supported / not present as soft |
| `NotOverlap` | 36 / 116 | Stores distribution records | Supported | Supported / supported per violated pair |
| `SameRoom` | 28 / 90 | Stores distribution records | Supported | Supported / supported per violated pair |
| `MaxBreaks(0,72)` | 15 / 0 | Stores distribution records | Supported, day/week interval scan | Supported, including the 3-class group / no soft instance |
| `MinGap(6)` | 9 / 1 | Stores distribution records | Supported | Supported / supported per violated pair |
| `SameTime` | 4 / 28 | Stores distribution records | Supported | Supported / supported per violated pair |
| `SameStart` | 2 / 0 | Stores distribution records | Supported | Supported / not present as soft |

The dataset has **1,262 required** and **273 soft** distributions. All observed
distribution type names are retained by the parser. The independent validator
and CP-SAT hard model recognize every required type present in this instance.
Soft rules found in this file are supported by the pairwise weighted objective;
`MaxDays`, `MaxDayLoad`, `MaxBreaks`, and `MaxBlock` soft costs are not modeled
by CP-SAT (none occur as soft rules in this file). CP-SAT's shared pair-check
build limit and wall-clock deadline can still stop full model construction.

The XML provides 84 room capacities, 1,061 class limits, 13,497 unique
students, and 19,614 course requests for 166 distinct courses. There are 212
courses, 222 configurations, 294 subparts, and 424 class-parent links. Every
request references a course; all class limits and room capacities are present.
The optional `<solution>` section contains zero class/student membership
entries, and the XML contains no class-to-instructor assignments. This means
sections are not preassigned, not that choices are unknowable: request,
configuration/subpart/class, parent, limit, capacity, and timetable data
provide the inputs needed for sectioning. The parser now retains optional
solution memberships and represents missing limits/capacities distinctly
from zero.

`sectioning.py` provides a CP-SAT stage for a fixed complete timetable. It
derives enrollments from student choices, validates the hierarchy and class
and room capacities, detects student conflict pairs, and optimizes the scoped
`student_weight * conflict_pairs` cost. Tests cover valid/invalid sectioning,
parent links, capacity, conflict scoring, missing/ambiguous inputs,
infeasibility, and independent validation. This is not the official full ITC
score: the timetable solvers still need a joint model, and student-conflict
weight splitting/score normalization requires official cross-checking.

## 4. Implemented versus missing product features

**Status: Partially implemented.** The usable local workflow covers academic
records, CSV/XML import, bounded schedule generation, independently reported
validation, run history, safe manual edits, and CSV/XLSX export. Fixed
demonstration student groups and instructor assignments are supported by the
local schema. A conditional fixed-timetable sectioning library now exists, but
it is not invoked by timetable jobs or exposed in the UI. The product does not
yet provide authentication, multi-user access, a configurable
travel/availability-rule editor, or a production deployment architecture.
The browser client is served directly by FastAPI; a separate Next.js
application is deferred.

## 5. Tests actually executed

The current test suite was run with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

The latest complete suite passed: **80 tests in 9.083 seconds**. Coverage
includes three-class `MaxBreaks` boundary/bridge/equivalence cases, weighted
soft-pair objective scoring including soft `Precedence`, CSP objective optimum
and unsupported-scope behavior, fixed-timetable sectioning and capacity cases,
CP-SAT optimality-status reporting, and the end-to-end application persistence
workflow. Python compilation passed with
`.\.venv\Scripts\python.exe -m compileall -q algorithms api benchmarks tests`;
`.\.venv\Scripts\python.exe -m pip check` reported no broken requirements.
The suite emits a non-failing Starlette deprecation warning about using
`httpx` with `starlette.testclient`.

Tests establish correctness only for the tested synthetic and platform cases;
they do not establish full ITC feasibility, solver scalability, or algorithm
superiority.

## 6. Clean-start assessment

**Status: Implemented and verified for a fresh database; clean dependency
installation is unverified.** The API test starts the application against a
new temporary SQLite file, applies its migration and demo seed, generates a
schedule, closes the app, and restarts against the same database. This is a
clean-database application-start test, not a clean machine or fresh package
installation test. The existing venv's compile and `pip check` passed.

## 7. End-to-end timetable workflow

| Workflow step | Status | Verification |
|---|---|---|
| Generate a timetable | **Implemented and verified** | CP-SAT completes the local three-class demo in the API test. |
| Independently validate it | **Implemented and verified** | Test asserts complete assignment coverage and `valid_complete`. |
| Persist it | **Implemented and verified** | Current schedule and valid edit survive closing and reopening the app on the same temporary SQLite database. |
| View it | **Implemented and verified** | Schedule API/current-schedule routes and served dashboard/static UI are exercised; a prior live browser smoke check loaded the dashboard. |
| Edit it | **Implemented and verified** | Invalid conflicting edit is rejected; a valid edit is accepted and read back. |
| Export it | **Implemented and verified** | CSV and XLSX endpoints return output; edited values are reflected in CSV. |
| Complete workflow on the full ITC instance | **Partially implemented** | Parser and conditional sectioning understand the student request graph, but timetable adapters still reject the student objective; there is no complete timetable to section or score. |

## 8. Benchmark results, blockers, and next task

The zero-cost synthetic comparison in [results/benchmark-synthetic-current.json](results/benchmark-synthetic-current.json)
shows both adapters returned complete independently validated schedules with
objective score 0. Runtime was 0.000211 seconds for CSP and 1.648382 seconds
for CP-SAT. Both search records reported `OPTIMAL`. This two-class smoke test
is not a meaningful speed ranking.

The new common positive-cost fixture is recorded in
[results/benchmark-synthetic-objective.json](results/benchmark-synthetic-objective.json).
Both adapters returned complete independently validated schedules with the
same weighted soft `NotOverlap` objective score of 15. Both search records
reported `OPTIMAL`. CSP runtime was 0.000251 seconds; CP-SAT runtime was
3.161188 seconds. This deterministic fixture verifies objective agreement
only; it does not show realistic scaling or algorithm superiority.

The latest 10-second common-budget full-instance run is saved in
[results/benchmark-full-sectioning-check.json](results/benchmark-full-sectioning-check.json):

| Algorithm | Status | Runtime | Coverage | Independently valid complete schedule |
|---|---|---:|---:|---|
| CSP | `unsupported` | 0.000449 s | 0/1,061 (0%) | No; student objective is not jointly modeled |
| OR-Tools CP-SAT | `unsupported` | 1.017551 s | 0/1,061 (0%) | No; student objective is not jointly modeled |

The synthetic and full-instance outcomes are not a fair head-to-head
performance comparison. Neither full-instance status establishes
infeasibility. The instance supplies the request/configuration/class hierarchy
and class/room capacities; actual enrollments can be derived from section
choices, but the current timetable adapters do not jointly choose those
sections and placements. No complete `pu-d5-spr17` timetable was generated or
independently validated.

**Current blockers:** joint timetable-sectioning optimization and the official
student objective's hard/soft split and normalization are not implemented.
The fixed-timetable sectioner has not been run on a realistic complete
timetable. There is no comparable multi-instance benchmark evidence. Git
history cannot be reviewed because the repository metadata is absent. Docker
and a fresh dependency installation have not been verified.

**Single highest-priority next task:** extend the timetable CP-SAT model to
choose student sections jointly with class placements, with a separately
implemented validator for the combined result. Before comparing official
scores, verify its student-conflict split and total-score normalization against
the competition reference implementation. Do not remove the existing
unsupported guard until those checks pass.
