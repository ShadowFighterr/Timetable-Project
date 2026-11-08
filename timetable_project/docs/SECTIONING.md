# Student requests, sectioning, and enrollment

## Source data contract

The ITC 2019 XML separates course requests from section assignment:

- `<student id>` and child `<course id>` elements state which course offerings
  the student requests.
- A course contains one or more `<config>` alternatives. A configuration
  contains scheduling `<subpart>` elements; a student selects one class from
  each subpart in the selected configuration.
- A class's optional `parent` identifies the class that must also be selected
  for that child section. A class `limit` is a section enrollment bound.
- Room `capacity` is a separate physical upper bound. Both limits apply to a
  selected, room-required section.
- An optional `<solution>` may contain `<class>` elements with nested
  `<student id>` entries representing supplied section memberships.

These facts are visible in the
[ITC 2019 DTD](https://www.itc2019.org/competition-format.dtd). The competition
loader additionally turns each student/course link into an offering request.
If no solution with section memberships is present, it calls the solver's
`initialSectioning` using the course's alternative configurations. Thus
preassigned sections are not required input; they are a solver decision.
See the pinned
[competition loader](https://github.com/tomas-muller/cpsolver-itc2019/blob/d1576ac94a8f7b6562e49f9476a89fb741cb226f/src/org/cpsolver/coursett/itc2019/ItcCompetitionLoader.java)
and its handling of
[lecture enrollment limits](https://github.com/tomas-muller/cpsolver-itc2019/blob/d1576ac94a8f7b6562e49f9476a89fb741cb226f/src/org/cpsolver/coursett/itc2019/ItcCompetitionLoader.java#L188-L210).

For `pu-d5-spr17`, parsing the supplied file found 13,497 unique students,
19,614 student/course requests for 166 distinct courses, 212 courses, 222
configurations, 294 subparts, and 1,061 classes. Every request references a
known course; every class has an explicit limit (including some zero limits),
and all 84 rooms have capacities. There are 424 class-parent links. The XML
has no `<solution>` and no supplied student-to-class memberships. It also has
no class instructor assignments. The optimization weights are time 3, room 1,
distribution 16, and student 8.

The absence of preassigned memberships does **not** make the sectioning
decision unknowable: the request, configuration, subpart, parent, class-limit,
room-capacity, and timetable data define the choices and constraints. Actual
enrollment per class is derivable only after a sectioning assignment is chosen;
it must not be inferred from the course request counts or class limit values.

## Implemented conditional sectioning stage

`sectioning.solve_sectioning(instance, schedule)` uses CP-SAT to assign each
student request for a **fixed complete timetable**. It chooses exactly one
configuration and one class per configuration subpart, honors parent links
and optional class-membership assignments supplied under `<solution>`, and
enforces both class and selected-room capacities. The report derives class
enrollment counts from selected memberships.

The sectioning-stage score is explicitly
`student_weight * number_of_student_class_conflict_pairs`. A pair is counted
once for a student when the selected meetings overlap or the available room
travel allowance is insufficient. This score is independently recomputed by
`validate_sectioning_independently`; conflicts are soft objective costs, not
automatic invalidity. Missing requests, invalid configurations/subparts,
parent mismatches, preassignment mismatches, unknown capacities, and
over-capacity sections prevent `valid_complete`.

This is a verifiable conditional component, **not** the official full ITC
objective. The reference loader apportions student-conflict terms between hard
and soft conflict weights (with a configurable split); the local conditional
stage currently minimizes a single weighted conflict-pair count. The official
total objective and all score normalization still require separate
cross-checking before reporting official ITC scores.

## Why the stage is not yet independent of timetable generation

For a fixed timetable, sectioning can be solved and validated as a separate
exact stage. It is not equivalent to joint timetable-and-sectioning
optimization: changing class times or selected rooms can change student
conflicts and room-capacity feasibility, and the schedule's other objective
terms compete with the student term. Therefore `CspAlgorithm` and
`CpSatAlgorithm` continue to reject a nonzero student objective with requests;
they do not yet optimize the sectioning decision jointly.

The sectioning CP-SAT model currently creates selection variables per
student/class alternative and conflict variables for possible conflicting
pairs. This is intended for focused instances and verification. It has not
been run at full `pu-d5-spr17` scale because no complete timetable is
available, and no runtime or full-instance score is claimed. The next solver
milestone is a joint model (or a documented decomposition with a valid
objective bound) that returns class assignments and sectioning together,
then independently validates both before lifting the adapters' student
objective guard.

The FastAPI job snapshot now preserves the normalized course/configuration/
subpart/request/optional-membership graph, but web job execution still uses
the timetable adapters and does not invoke this conditional sectioner.
