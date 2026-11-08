"""Exact student sectioning for a fixed, complete timetable."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import time
from typing import Any

from model import Schedule
from parser import Instance, Placement
from validation import student_section_conflict


@dataclass
class StudentSectioning:
    """Selected classes per student and requested course."""

    assignments: dict[int, dict[int, tuple[int, ...]]] = field(
        default_factory=dict
    )


@dataclass
class SectioningValidationReport:
    complete: bool
    valid_complete: bool
    total_requests: int
    assigned_requests: int
    missing_requests: list[dict[str, int]] = field(default_factory=list)
    unexpected_requests: list[dict[str, int]] = field(default_factory=list)
    invalid_selections: list[dict[str, Any]] = field(default_factory=list)
    missing_preassignments: list[dict[str, int]] = field(default_factory=list)
    enrollments: dict[int, int] = field(default_factory=dict)
    capacity_violations: list[dict[str, int]] = field(default_factory=list)
    unknown_capacity_classes: list[int] = field(default_factory=list)
    student_conflict_pairs: list[dict[str, int]] = field(default_factory=list)
    student_conflict_count: int = 0
    weighted_student_conflict_cost: int | None = None
    coverage_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SectioningResult:
    status: str
    runtime_s: float
    sectioning: StudentSectioning
    validation: SectioningValidationReport
    objective_score: int | None
    optimal: bool
    termination_reason: str
    error: str | None = None

    @property
    def successful(self) -> bool:
        return (
            self.status in {"optimal", "feasible"}
            and self.validation.valid_complete
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "runtime_s": self.runtime_s,
            "sectioning": {
                str(student_id): {
                    str(course_id): list(class_ids)
                    for course_id, class_ids in course_assignments.items()
                }
                for student_id, course_assignments
                in sorted(self.sectioning.assignments.items())
            },
            "validation": self.validation.to_dict(),
            "objective_score": self.objective_score,
            "optimal": self.optimal,
            "termination_reason": self.termination_reason,
            "error": self.error,
        }


def sectioning_from_instance(instance: Instance) -> StudentSectioning:
    """Convert supplied solution class/student elements into course selections."""
    assignments: dict[int, dict[int, list[int]]] = {}
    for student in instance.students.values():
        student_assignments: dict[int, list[int]] = {}
        for class_id in student.assigned_class_ids:
            cls = instance.classes.get(class_id)
            if cls is None:
                raise ValueError(
                    f"Student {student.id} is assigned to unknown class "
                    f"{class_id}"
                )
            student_assignments.setdefault(cls.course_id, []).append(class_id)
        assignments[student.id] = {
            course_id: tuple(sorted(class_ids))
            for course_id, class_ids in student_assignments.items()
        }
    return StudentSectioning(assignments=assignments)


def validate_sectioning_independently(
    instance: Instance,
    schedule: Schedule,
    sectioning: StudentSectioning,
) -> SectioningValidationReport:
    """Validate request coverage, hierarchy, capacity, and conflicts separately."""
    expected = {
        (student.id, course_id)
        for student in instance.students.values()
        for course_id in student.course_ids
    }
    provided = {
        (student_id, course_id)
        for student_id, course_assignments in sectioning.assignments.items()
        for course_id in course_assignments
    }
    missing = sorted(expected - provided)
    unexpected = sorted(provided - expected)
    invalid_selections: list[dict[str, Any]] = []
    missing_preassignments: list[dict[str, int]] = []
    enrollments = {class_id: 0 for class_id in instance.classes}
    selected_by_student: dict[int, list[int]] = {}

    schedule_is_complete = schedule.is_complete
    invalid_schedule_classes = [
        class_id
        for class_id, placement in schedule.assignments.items()
        if class_id not in instance.classes
        or placement not in instance.classes[class_id].placements
    ]
    if not schedule_is_complete or invalid_schedule_classes:
        invalid_selections.append(
            {
                "reason": "sectioning requires a complete timetable with "
                "in-domain placements",
                "invalid_schedule_classes": invalid_schedule_classes,
            }
        )

    for student_id, course_assignments in sectioning.assignments.items():
        student = instance.students.get(student_id)
        if student is None:
            invalid_selections.append(
                {"student_id": student_id, "reason": "unknown student"}
            )
            continue
        student_classes: list[int] = []
        for course_id, raw_class_ids in course_assignments.items():
            class_ids = list(raw_class_ids)
            if len(class_ids) != len(set(class_ids)):
                invalid_selections.append(
                    {
                        "student_id": student_id,
                        "course_id": course_id,
                        "reason": "duplicate class selection",
                    }
                )
            known_ids = [
                class_id for class_id in class_ids
                if class_id in instance.classes
            ]
            for class_id in class_ids:
                if class_id not in instance.classes:
                    invalid_selections.append(
                        {
                            "student_id": student_id,
                            "course_id": course_id,
                            "class_id": class_id,
                            "reason": "unknown class",
                        }
                    )
                else:
                    enrollments[class_id] += 1
                    student_classes.append(class_id)
                    if instance.classes[class_id].course_id != course_id:
                        invalid_selections.append(
                            {
                                "student_id": student_id,
                                "course_id": course_id,
                                "class_id": class_id,
                                "reason": "class belongs to a different course",
                            }
                        )
            if course_id not in instance.courses:
                invalid_selections.append(
                    {
                        "student_id": student_id,
                        "course_id": course_id,
                        "reason": "unknown course",
                    }
                )
                continue
            selected_classes = [
                instance.classes[class_id] for class_id in known_ids
            ]
            selected_configs = {cls.config_id for cls in selected_classes}
            if len(selected_configs) != 1:
                invalid_selections.append(
                    {
                        "student_id": student_id,
                        "course_id": course_id,
                        "reason": "selection must use exactly one configuration",
                    }
                )
                continue
            config_id = next(iter(selected_configs))
            config = instance.configs.get(config_id)
            if config is None or config.course_id != course_id:
                invalid_selections.append(
                    {
                        "student_id": student_id,
                        "course_id": course_id,
                        "reason": "configuration does not belong to course",
                    }
                )
                continue
            by_subpart: dict[int, list[int]] = {}
            for cls in selected_classes:
                by_subpart.setdefault(cls.subpart_id, []).append(cls.id)
            for subpart_id in config.subpart_ids:
                selected_in_subpart = by_subpart.get(subpart_id, [])
                if len(selected_in_subpart) != 1:
                    invalid_selections.append(
                        {
                            "student_id": student_id,
                            "course_id": course_id,
                            "subpart_id": subpart_id,
                            "reason": "select exactly one class per configuration subpart",
                        }
                    )
            expected_subparts = set(config.subpart_ids)
            if set(by_subpart) - expected_subparts:
                invalid_selections.append(
                    {
                        "student_id": student_id,
                        "course_id": course_id,
                        "reason": "selected class is outside the chosen configuration",
                    }
                )
            selected_ids = set(known_ids)
            for cls in selected_classes:
                if cls.parent_id is not None and cls.parent_id not in selected_ids:
                    invalid_selections.append(
                        {
                            "student_id": student_id,
                            "course_id": course_id,
                            "class_id": cls.id,
                            "parent_id": cls.parent_id,
                            "reason": "selected class parent is not selected",
                        }
                    )
        selected_by_student[student_id] = student_classes

    for student in instance.students.values():
        assigned = set(selected_by_student.get(student.id, []))
        for class_id in student.assigned_class_ids:
            if class_id not in assigned:
                missing_preassignments.append(
                    {"student_id": student.id, "class_id": class_id}
                )

    capacity_violations: list[dict[str, int]] = []
    unknown_capacity_classes: list[int] = []
    for class_id, enrollment in enrollments.items():
        if enrollment == 0:
            continue
        cls = instance.classes[class_id]
        if cls.limit is None:
            unknown_capacity_classes.append(class_id)
        elif enrollment > cls.limit:
            capacity_violations.append(
                {
                    "class_id": class_id,
                    "enrollment": enrollment,
                    "capacity": cls.limit,
                    "capacity_type": "class_limit",
                }
            )
        placement = schedule.assignments.get(class_id)
        if not cls.room_required:
            continue
        room = (
            None
            if placement is None or placement.room_id is None
            else instance.rooms.get(placement.room_id)
        )
        if room is None:
            invalid_selections.append(
                {
                    "class_id": class_id,
                    "reason": "room-required class has no known scheduled room",
                }
            )
        elif room.capacity is None:
            unknown_capacity_classes.append(class_id)
        elif enrollment > room.capacity:
            capacity_violations.append(
                {
                    "class_id": class_id,
                    "enrollment": enrollment,
                    "capacity": room.capacity,
                    "capacity_type": "room_capacity",
                }
            )

    student_conflict_pairs: list[dict[str, int]] = []
    for student_id, class_ids in selected_by_student.items():
        for index, class_a in enumerate(class_ids):
            placement_a = schedule.assignments.get(class_a)
            if placement_a is None:
                continue
            for class_b in class_ids[index + 1:]:
                placement_b = schedule.assignments.get(class_b)
                if placement_b is None:
                    continue
                if student_section_conflict(
                    instance, placement_a, placement_b
                ):
                    student_conflict_pairs.append(
                        {
                            "student_id": student_id,
                            "class_a": min(class_a, class_b),
                            "class_b": max(class_a, class_b),
                        }
                    )

    total_requests = len(expected)
    assigned_requests = len(expected & provided)
    complete = (
        total_requests == assigned_requests
        and not unexpected
        and schedule_is_complete
    )
    valid_complete = (
        complete
        and not invalid_selections
        and not missing_preassignments
        and not capacity_violations
        and not unknown_capacity_classes
    )
    coverage_notes: list[str] = []
    if unknown_capacity_classes:
        coverage_notes.append(
            "Class enrollment limits are missing for selected classes; "
            "capacity feasibility cannot be certified."
        )
    if student_conflict_pairs:
        coverage_notes.append(
            "Student conflicts are reported as selected class pairs that "
            "overlap or violate the available room-travel allowance."
        )
    weighted_cost = (
        instance.student_weight * len(student_conflict_pairs)
        if valid_complete
        else None
    )
    return SectioningValidationReport(
        complete=complete,
        valid_complete=valid_complete,
        total_requests=total_requests,
        assigned_requests=assigned_requests,
        missing_requests=[
            {"student_id": student_id, "course_id": course_id}
            for student_id, course_id in missing
        ],
        unexpected_requests=[
            {"student_id": student_id, "course_id": course_id}
            for student_id, course_id in unexpected
        ],
        invalid_selections=invalid_selections,
        missing_preassignments=missing_preassignments,
        enrollments={
            class_id: enrollment
            for class_id, enrollment in enrollments.items()
            if enrollment
        },
        capacity_violations=capacity_violations,
        unknown_capacity_classes=sorted(set(unknown_capacity_classes)),
        student_conflict_pairs=student_conflict_pairs,
        student_conflict_count=len(student_conflict_pairs),
        weighted_student_conflict_cost=weighted_cost,
        coverage_notes=coverage_notes,
    )


def solve_sectioning(
    instance: Instance,
    schedule: Schedule,
    *,
    time_limit_s: float = 30.0,
) -> SectioningResult:
    """Minimize weighted student conflicts for a fixed complete timetable."""
    started = time.perf_counter()

    def finish(
        status: str,
        sectioning: StudentSectioning,
        *,
        objective_score: int | None,
        optimal: bool,
        reason: str,
        error: str | None = None,
    ) -> SectioningResult:
        report = validate_sectioning_independently(
            instance, schedule, sectioning
        )
        return SectioningResult(
            status=status,
            runtime_s=time.perf_counter() - started,
            sectioning=sectioning,
            validation=report,
            objective_score=objective_score,
            optimal=optimal,
            termination_reason=reason,
            error=error,
        )

    if not math.isfinite(time_limit_s) or time_limit_s < 0:
        return finish(
            "error",
            StudentSectioning(),
            objective_score=None,
            optimal=False,
            reason="invalid_time_limit",
            error="time_limit_s must be non-negative",
        )
    if not schedule.is_complete:
        return finish(
            "unsupported",
            StudentSectioning(),
            objective_score=None,
            optimal=False,
            reason="complete_timetable_required",
            error="Sectioning requires a complete timetable.",
        )
    for class_id, placement in schedule.assignments.items():
        if (
            class_id not in instance.classes
            or placement not in instance.classes[class_id].placements
        ):
            return finish(
                "unsupported",
                StudentSectioning(),
                objective_score=None,
                optimal=False,
                reason="invalid_timetable_input",
                error=f"Timetable contains invalid placement for class {class_id}.",
            )

    requested_courses = {
        course_id
        for student in instance.students.values()
        for course_id in student.course_ids
    }
    for student in instance.students.values():
        if len(student.course_ids) != len(set(student.course_ids)):
            return finish(
                "unsupported",
                StudentSectioning(),
                objective_score=None,
                optimal=False,
                reason="ambiguous_duplicate_request",
                error=f"Student {student.id} requests a course more than once.",
            )
        for course_id in student.course_ids:
            course = instance.courses.get(course_id)
            if course is None or not course.config_ids:
                return finish(
                    "unsupported",
                    StudentSectioning(),
                    objective_score=None,
                    optimal=False,
                    reason="request_without_configuration",
                    error=(
                        f"Student {student.id} requests course {course_id}, "
                        "but no course configurations are available."
                    ),
                )
            for config_id in course.config_ids:
                config = instance.configs.get(config_id)
                if config is None or not config.subpart_ids:
                    return finish(
                        "unsupported",
                        StudentSectioning(),
                        objective_score=None,
                        optimal=False,
                        reason="ambiguous_configuration",
                        error=(
                            f"Course {course_id} has a missing or empty "
                            f"configuration {config_id}."
                        ),
                    )
                for subpart_id in config.subpart_ids:
                    subpart = instance.subparts.get(subpart_id)
                    if subpart is None or not subpart.class_ids:
                        return finish(
                            "unsupported",
                            StudentSectioning(),
                            objective_score=None,
                            optimal=False,
                            reason="empty_subpart",
                            error=(
                                f"Configuration {config_id} has missing or "
                                f"empty subpart {subpart_id}."
                            ),
                        )
                    for class_id in subpart.class_ids:
                        cls = instance.classes.get(class_id)
                        if cls is None or cls.limit is None:
                            return finish(
                                "unsupported",
                                StudentSectioning(),
                                objective_score=None,
                                optimal=False,
                                reason="class_capacity_missing",
                                error=(
                                    f"Class {class_id} has no explicit "
                                    "enrollment limit."
                                ),
                            )
                        if cls.limit < 0:
                            return finish(
                                "unsupported",
                                StudentSectioning(),
                                objective_score=None,
                                optimal=False,
                                reason="invalid_class_capacity",
                                error=f"Class {class_id} has a negative limit.",
                            )
                        if cls.room_required:
                            placement = schedule.assignments[class_id]
                            room = (
                                None
                                if placement.room_id is None
                                else instance.rooms.get(placement.room_id)
                            )
                            if room is None:
                                return finish(
                                    "unsupported",
                                    StudentSectioning(),
                                    objective_score=None,
                                    optimal=False,
                                    reason="room_capacity_missing",
                                    error=(
                                        f"Class {class_id} has no known "
                                        "scheduled room capacity."
                                    ),
                                )
                            if room.capacity is None:
                                return finish(
                                    "unsupported",
                                    StudentSectioning(),
                                    objective_score=None,
                                    optimal=False,
                                    reason="room_capacity_missing",
                                    error=(
                                        f"Room {room.id} has no explicit "
                                        "capacity."
                                    ),
                                )
                            if room.capacity < 0:
                                return finish(
                                    "unsupported",
                                    StudentSectioning(),
                                    objective_score=None,
                                    optimal=False,
                                    reason="invalid_room_capacity",
                                    error=f"Room {room.id} has a negative capacity.",
                                )
    if instance.student_weight < 0:
        return finish(
            "unsupported",
            StudentSectioning(),
            objective_score=None,
            optimal=False,
            reason="invalid_student_weight",
            error="Student objective weight must be non-negative.",
        )

    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        return finish(
            "error",
            StudentSectioning(),
            objective_score=None,
            optimal=False,
            reason="dependency_missing",
            error=f"OR-Tools is not installed: {exc}",
        )

    model = cp_model.CpModel()
    class_vars: dict[tuple[int, int], Any] = {}
    for student_id, student in instance.students.items():
        for course_id in student.course_ids:
            course = instance.courses[course_id]
            choices = []
            for config_id in course.config_ids:
                config_var = model.NewBoolVar(
                    f"config_s{student_id}_c{course_id}_g{config_id}"
                )
                choices.append(config_var)
                config = instance.configs[config_id]
                for subpart_id in config.subpart_ids:
                    subpart = instance.subparts[subpart_id]
                    section_vars = []
                    for class_id in subpart.class_ids:
                        cls = instance.classes[class_id]
                        if cls.parent_id is not None:
                            parent = instance.classes.get(cls.parent_id)
                            if (
                                parent is None
                                or parent.course_id != course_id
                                or parent.config_id != config_id
                            ):
                                return finish(
                                    "unsupported",
                                    StudentSectioning(),
                                    objective_score=None,
                                    optimal=False,
                                    reason="invalid_parent_hierarchy",
                                    error=(
                                        f"Class {class_id} has a parent outside "
                                        "its course configuration."
                                    ),
                                )
                        section_var = model.NewBoolVar(
                            f"section_s{student_id}_cl{class_id}"
                        )
                        class_vars[(student_id, class_id)] = section_var
                        section_vars.append(section_var)
                        model.Add(section_var <= config_var)
                    model.Add(sum(section_vars) == config_var)
            model.AddExactlyOne(choices)

    for (student_id, class_id), section_var in class_vars.items():
        parent_id = instance.classes[class_id].parent_id
        if parent_id is None:
            continue
        parent_var = class_vars.get((student_id, parent_id))
        if parent_var is None:
            return finish(
                "unsupported",
                StudentSectioning(),
                objective_score=None,
                optimal=False,
                reason="invalid_parent_hierarchy",
                error=(
                    f"Class {class_id} has no selectable parent class "
                    f"{parent_id} for this student."
                ),
            )
        model.Add(section_var <= parent_var)

    for student in instance.students.values():
        for class_id in student.assigned_class_ids:
            class_var = class_vars.get((student.id, class_id))
            if class_var is None:
                return finish(
                    "unsupported",
                    StudentSectioning(),
                    objective_score=None,
                    optimal=False,
                    reason="invalid_preassigned_section",
                    error=(
                        f"Student {student.id} has supplied section "
                        f"{class_id} outside a requested course choice."
                    ),
                )
            model.Add(class_var == 1)

    for class_id in {
        class_id
        for course_id in requested_courses
        for config_id in instance.courses[course_id].config_ids
        for subpart_id in instance.configs[config_id].subpart_ids
        for class_id in instance.subparts[subpart_id].class_ids
    }:
        cls = instance.classes[class_id]
        capacity = cls.limit
        if cls.room_required:
            room_id = schedule.assignments[class_id].room_id
            assert room_id is not None
            capacity = min(capacity, instance.rooms[room_id].capacity)
        enrollment_vars = [
            variable
            for (_, selected_class_id), variable in class_vars.items()
            if selected_class_id == class_id
        ]
        model.Add(sum(enrollment_vars) <= capacity)

    conflict_vars = []
    for student_id, student in instance.students.items():
        possible_classes = sorted({
            class_id
            for course_id in student.course_ids
            for config_id in instance.courses[course_id].config_ids
            for subpart_id in instance.configs[config_id].subpart_ids
            for class_id in instance.subparts[subpart_id].class_ids
        })
        for index, class_a in enumerate(possible_classes):
            placement_a = schedule.assignments[class_a]
            for class_b in possible_classes[index + 1:]:
                placement_b = schedule.assignments[class_b]
                if not _model_student_conflict(
                    instance, placement_a, placement_b
                ):
                    continue
                var_a = class_vars[(student_id, class_a)]
                var_b = class_vars[(student_id, class_b)]
                conflict = model.NewBoolVar(
                    f"conflict_s{student_id}_a{class_a}_b{class_b}"
                )
                model.Add(conflict <= var_a)
                model.Add(conflict <= var_b)
                model.Add(conflict >= var_a + var_b - 1)
                conflict_vars.append(conflict)

    model.Minimize(instance.student_weight * sum(conflict_vars))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    if status == cp_model.INFEASIBLE:
        return finish(
            "infeasible",
            StudentSectioning(),
            objective_score=None,
            optimal=False,
            reason="sectioning_infeasible_proven",
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return finish(
            "timeout_unknown",
            StudentSectioning(),
            objective_score=None,
            optimal=False,
            reason="sectioning_time_limit",
        )

    assignments: dict[int, dict[int, tuple[int, ...]]] = {
        student_id: {}
        for student_id in instance.students
    }
    for (student_id, class_id), variable in class_vars.items():
        if solver.BooleanValue(variable):
            course_id = instance.classes[class_id].course_id
            current = assignments[student_id].get(course_id, ())
            assignments[student_id][course_id] = (*current, class_id)
    sectioning = StudentSectioning(
        assignments={
            student_id: {
                course_id: tuple(sorted(class_ids))
                for course_id, class_ids in student_assignments.items()
            }
            for student_id, student_assignments in assignments.items()
        }
    )
    report = validate_sectioning_independently(
        instance, schedule, sectioning
    )
    optimal = status == cp_model.OPTIMAL
    if not report.valid_complete:
        return finish(
            "error",
            sectioning,
            objective_score=None,
            optimal=False,
            reason="independent_validation_failed",
            error="CP-SAT sectioning failed independent validation.",
        )
    score = report.weighted_student_conflict_cost
    return finish(
        "optimal" if optimal else "feasible",
        sectioning,
        objective_score=score,
        optimal=optimal,
        reason=(
            "student_objective_optimum_proven"
            if optimal
            else "feasible_sectioning_incumbent"
        ),
    )


def _model_student_conflict(
    instance: Instance,
    first: Placement,
    second: Placement,
) -> bool:
    """Solver-side student conflict predicate, distinct from validation."""
    if not (
        any(a == b == "1" for a, b in zip(first.days, second.days))
        and any(a == b == "1" for a, b in zip(first.weeks, second.weeks))
    ):
        return False
    first_end = first.start + first.length
    second_end = second.start + second.length
    if first.start < second_end and second.start < first_end:
        return True
    if first_end <= second.start:
        room = instance.rooms.get(first.room_id)
        travel = (
            0
            if first.room_id is None or second.room_id is None or room is None
            else room.travel.get(second.room_id, 0)
        )
        return first_end + travel > second.start
    if second_end <= first.start:
        room = instance.rooms.get(second.room_id)
        travel = (
            0
            if first.room_id is None or second.room_id is None or room is None
            else room.travel.get(first.room_id, 0)
        )
        return second_end + travel > first.start
    return False
