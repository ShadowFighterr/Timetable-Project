# Algorithm selection

## Decision

Use **OR-Tools CP-SAT** as the first engine for the platform's explicitly
supported constraint subset. Retain the static CSP solver as a tested
branch-and-bound baseline. This recommendation is conditional on a rule being
modeled by the adapter and covered by the independent validator; it is not a
claim that CP-SAT is universally best.

## Why it fits this product

- Required placement, room, and attendee rules can be represented as integer
  constraints and reviewed alongside the product's rule catalog.
- Hard rules are constraints, not penalty weights. The adapter returns
  `infeasible_proven`, `timeout_unknown`, `unsupported`, or `error` distinctly.
- OR-Tools' documented statuses distinguish a feasible incumbent from an
  optimal result, proof of infeasibility, invalid models, and unknown stop
  outcomes.
- Placement penalties and supported soft pair penalties are integer-valued.
  The adapter minimizes weighted time/room placement costs plus the weighted
  penalty for each violated pair in a supported soft distribution. The local
  demo has no student objective.
- A final timetable is only marked valid after independent complete-assignment
  validation.

## Current model boundary

The engine accepts the existing normalized `Instance` model. Its hard model
supports room non-overlap, required pairwise distributions, `Precedence`,
`WorkDay`, `MinGap`, `MaxDays`, `MaxDayLoad`, and `MaxBreaks(R,S)`. The
multi-class `MaxBreaks` encoding counts long gaps in each day/week separately;
the independent validator checks the same semantics using a separate interval
scan. `MaxBlock`, unsupported rule types, positive-penalty soft global rules,
and nonzero student objective with student requests stop with `unsupported`.
Positive-penalty soft pairwise, `Precedence`, `WorkDay`, and `MinGap` rules are
modeled as per-violated-pair objective terms and independently scored.

This does not establish full ITC 2019 support. The supplied file contains
13,497 student records and 19,614 course requests but no preassigned
student-to-class memberships. It does supply the course/configuration/
subpart/class hierarchy, 1,061 class limits, and 84 room capacities, so
section choices and resulting enrollments can be solved rather than guessed.
The new CP-SAT sectioner does this conditionally for a fixed complete
timetable, and its separate validator checks selected memberships, capacities,
and a scoped student-conflict score. See [SECTIONING.md](./SECTIONING.md) for
the data contract and semantics.

Sectioning cannot yet be treated as a separate full-instance optimization:
the student-conflict term depends on timetable placements, so a sequential
sectioning solution is only optimal conditional on that fixed timetable. The
CSP and timetable CP-SAT adapters retain explicit `unsupported` outcomes for a
nonzero student objective until the student choices are modeled jointly (or a
formally valid decomposition is supplied). The file also has no instructor
assignments, so this project cannot validate instructor conflicts that are
not explicitly represented by distributions.

## How to operate it safely

1. Model each class as exactly one finite-domain placement.
2. Add room-time no-overlap and explicit required distribution constraints.
3. Minimize integer time/room placement penalties where enabled.
4. Run under a wall-clock budget; distinguish feasible, optimal, unknown,
   infeasible, and unsupported outcomes.
5. Independently validate assignment coverage and hard constraints before
   presenting the result as a complete valid schedule.
6. Persist algorithm version, weights, budget, termination status, validator
   output, and the assignment for later review.

There is no random feasible-seed stage: CP-SAT constructs a solution directly.
The current web job service records partial/unsupported/timeout outcomes as
history and updates the current timetable only after a full independent
validation succeeds. Cancellation is cooperative and checked by the job and
solver adapter.

## Evidence and next evaluation

The decision follows the qualitative fit discussed in
[LITERATURE_REVIEW.md](./LITERATURE_REVIEW.md): explicit hard rules and
machine-readable statuses make constraints easier to inspect and expose in an
administration UI. Published MIP, MaxSAT, and metaheuristic results are
instance-specific; they have not been treated as interchangeable scores.

Current tests include independently validated three-class `MaxBreaks`
assignments and objective checks for both adapters. The CSP adapter now uses
branch-and-bound to minimize the supported weighted placement and soft-pair
objective, distinguishing an incumbent from a proven optimum. Both engines
solve the saved tiny synthetic smoke case (objective 0) and independently
validate a positive-cost synthetic solution (objective 15, with optimality
reported by both solver search records). These deterministic two-class cases
validate interface and objective agreement, not performance. On
`pu-d5-spr17`, both adapters reject the nonzero
student objective before search because their timetable objective has not
been extended to sectioning decisions. This is neither a fair performance
comparison nor evidence of infeasibility. A comparable ITC evaluation still
requires a joint objective model, official score cross-checks (including the
reference implementation's hard/soft student-conflict split), and fixed-
budget runs across multiple instances.

## Alternatives not selected for the first engine

Genetic algorithms, simulated annealing, and tabu search can be useful
anytime/local-improvement engines but need carefully designed neighborhoods,
repair/penalty mechanisms, and independent hard-validity checks. A hybrid
metaheuristic/hyper-heuristic may become a valuable alternative if measured
CP-SAT model growth or first-feasible time is poor. It is deferred until the
data model and objective are comparable and a reproducible evaluation can
justify the extra operational and maintenance complexity.
The next blocker is integrating section selection with timetable placement in
the timetable adapters and independently validating the resulting combined
solution. The source data supplies requests and capacities; preassigned
sections are not required. A separate validation obligation remains to compare
the project's student-conflict scoring and normalization against the official
ITC scoring semantics.
