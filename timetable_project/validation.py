"""Independent validation and objective reporting for generated schedules."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any

from model import Schedule
from parser import Distribution, Instance, Placement


PAIRWISE_TYPES = frozenset({
    "SameStart",
    "SameTime",
    "DifferentTime",
    "SameDays",
    "DifferentDays",
    "SameWeeks",
    "DifferentWeeks",
    "SameRoom",
    "DifferentRoom",
    "Overlap",
    "NotOverlap",
    "SameAttendees",
})
PARAMETERIZED_PAIR_PATTERNS = (
    re.compile(r"WorkDay\(\d+\)"),
    re.compile(r"MinGap\(\d+\)"),
)
GLOBAL_PATTERNS = (
    re.compile(r"MaxDays\(\d+\)"),
    re.compile(r"MaxDayLoad\(\d+\)"),
    re.compile(r"MaxBreaks\(\d+,\d+\)"),
    re.compile(r"MaxBlock\(\d+,\d+\)"),
)
VALIDATION_SUPPORTED_TYPES = PAIRWISE_TYPES | {"Precedence"}


@dataclass
class ValidationReport:
    complete: bool
    validation_complete: bool
    valid_complete: bool
    assigned_count: int
    total_classes: int
    assignment_coverage: float
    missing_assignments: list[int] = field(default_factory=list)
    invalid_assignments: list[int] = field(default_factory=list)
    room_occupancy_conflicts: list[dict[str, int]] = field(default_factory=list)
    room_compatibility_violations: list[int] = field(default_factory=list)
    room_capacity_violations: list[int] = field(default_factory=list)
    room_capacity_evaluated: bool = False
    instructor_conflicts: int | None = None
    student_conflicts: int | None = None
    same_attendees_violations: int = 0
    required_distribution_violations: list[dict[str, Any]] = field(
        default_factory=list
    )
    unsupported_constraints: list[dict[str, Any]] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)
    objective_score: int | None = None
    objective_components: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _overlap(a: Placement, b: Placement) -> bool:
    return (
        any(x == y == "1" for x, y in zip(a.weeks, b.weeks))
        and any(x == y == "1" for x, y in zip(a.days, b.days))
        and a.start < b.start + b.length
        and b.start < a.start + a.length
    )


def _bits_intersect(a: str, b: str) -> bool:
    return any(left == right == "1" for left, right in zip(a, b))


def _bits_contained(a: str, b: str) -> bool:
    return all(left != "1" or right == "1" for left, right in zip(a, b))


def _first_active(bits: str) -> int:
    return next((index for index, value in enumerate(bits) if value == "1"), 10**9)


def _travel(instance: Instance, room_a: int | None, room_b: int | None) -> int:
    if room_a is None or room_b is None or room_a == room_b:
        return 0
    room = instance.rooms.get(room_a)
    return 0 if room is None else room.travel.get(room_b, 0)


def student_section_conflict(
    instance: Instance,
    first: Placement,
    second: Placement,
) -> bool:
    if not (
        _bits_intersect(first.days, second.days)
        and _bits_intersect(first.weeks, second.weeks)
    ):
        return False
    if _overlap(first, second):
        return True
    if first.start + first.length <= second.start:
        return (
            first.start + first.length
            + _travel(instance, first.room_id, second.room_id)
            > second.start
        )
    if second.start + second.length <= first.start:
        return (
            second.start + second.length
            + _travel(instance, second.room_id, first.room_id)
            > first.start
        )
    return False


def _pair_violation(
    instance: Instance,
    kind: str,
    first: Placement,
    second: Placement,
) -> bool:
    if kind == "Precedence":
        first_week = _first_active(first.weeks)
        second_week = _first_active(second.weeks)
        if first_week != second_week:
            return first_week > second_week
        first_day = _first_active(first.days)
        second_day = _first_active(second.days)
        if first_day != second_day:
            return first_day > second_day
        return first.start + first.length > second.start
    if kind == "SameStart":
        return first.start != second.start
    if kind == "SameTime":
        first_end = first.start + first.length
        second_end = second.start + second.length
        return not (
            (first.start <= second.start and second_end <= first_end)
            or (second.start <= first.start and first_end <= second_end)
        )
    if kind == "DifferentTime":
        return not (
            first.start + first.length <= second.start
            or second.start + second.length <= first.start
        )
    if kind == "SameDays":
        return not (
            _bits_contained(first.days, second.days)
            or _bits_contained(second.days, first.days)
        )
    if kind == "DifferentDays":
        return _bits_intersect(first.days, second.days)
    if kind == "SameWeeks":
        return not (
            _bits_contained(first.weeks, second.weeks)
            or _bits_contained(second.weeks, first.weeks)
        )
    if kind == "DifferentWeeks":
        return _bits_intersect(first.weeks, second.weeks)
    if kind == "SameRoom":
        return first.room_id != second.room_id
    if kind == "DifferentRoom":
        return first.room_id == second.room_id
    if kind == "Overlap":
        return not _overlap(first, second)
    if kind == "NotOverlap":
        return _overlap(first, second)
    if kind == "SameAttendees":
        if not (
            _bits_intersect(first.days, second.days)
            and _bits_intersect(first.weeks, second.weeks)
        ):
            return False
        return not (
            first.start + first.length
            + _travel(instance, first.room_id, second.room_id)
            <= second.start
            or second.start + second.length
            + _travel(instance, second.room_id, first.room_id)
            <= first.start
        )

    match = re.fullmatch(r"WorkDay\((\d+)\)", kind)
    if match:
        if not (
            _bits_intersect(first.days, second.days)
            and _bits_intersect(first.weeks, second.weeks)
        ):
            return False
        start = min(first.start, second.start)
        end = max(first.start + first.length, second.start + second.length)
        return end - start > int(match.group(1))

    match = re.fullmatch(r"MinGap\((\d+)\)", kind)
    if match:
        if not (
            _bits_intersect(first.days, second.days)
            and _bits_intersect(first.weeks, second.weeks)
        ):
            return False
        gap = int(match.group(1))
        return not (
            first.start + first.length + gap <= second.start
            or second.start + second.length + gap <= first.start
        )
    raise ValueError(f"Unsupported pairwise distribution: {kind}")


def is_supported_distribution(kind: str) -> bool:
    return (
        kind in VALIDATION_SUPPORTED_TYPES
        or any(pattern.fullmatch(kind) for pattern in PARAMETERIZED_PAIR_PATTERNS)
        or any(pattern.fullmatch(kind) for pattern in GLOBAL_PATTERNS)
    )


def is_soft_objective_supported(kind: str) -> bool:
    return (
        kind in PAIRWISE_TYPES
        or kind == "Precedence"
        or any(pattern.fullmatch(kind) for pattern in PARAMETERIZED_PAIR_PATTERNS)
    )


def objective_lower_bound(
    instance: Instance,
    assigned: dict[int, Placement],
) -> int:
    """Return the exact cost already fixed by a partial assignment."""
    placement_cost = 0
    for class_id, placement in assigned.items():
        if class_id not in instance.classes:
            continue
        cost = (
            instance.time_weight * placement.time_penalty
            + instance.room_weight * placement.room_penalty
        )
        if cost < 0:
            raise ValueError("Objective lower bound requires nonnegative costs")
        placement_cost += cost

    soft_penalty = 0
    for distribution in instance.distributions:
        if distribution.required or distribution.penalty == 0:
            continue
        if not is_soft_objective_supported(distribution.type):
            raise ValueError(
                f"Unsupported soft objective: {distribution.type}"
            )
        if distribution.penalty < 0:
            raise ValueError("Objective lower bound requires nonnegative costs")
        selected = [
            assigned[class_id]
            for class_id in distribution.class_ids
            if class_id in assigned
        ]
        soft_penalty += distribution.penalty * sum(
            _pair_violation(instance, distribution.type, first, second)
            for first, second in combinations(selected, 2)
        )
    if instance.distribution_weight < 0:
        raise ValueError("Objective lower bound requires nonnegative costs")
    return placement_cost + instance.distribution_weight * soft_penalty


def unsupported_distributions(instance: Instance) -> list[dict[str, Any]]:
    return [
        {
            "type": distribution.type,
            "required": distribution.required,
            "class_ids": list(distribution.class_ids),
        }
        for distribution in instance.distributions
        if not is_supported_distribution(distribution.type)
    ]


def _global_violation(
    instance: Instance,
    distribution: Distribution,
    placements: list[Placement],
) -> bool:
    kind = distribution.type
    match = re.fullmatch(r"MaxDays\((\d+)\)", kind)
    if match:
        active_days = {
            day
            for placement in placements
            for day, bit in enumerate(placement.days)
            if bit == "1"
        }
        return len(active_days) > int(match.group(1))

    match = re.fullmatch(r"MaxDayLoad\((\d+)\)", kind)
    if match:
        limit = int(match.group(1))
        return any(
            sum(
                placement.length
                for placement in placements
                if placement.days[day] == "1"
                and placement.weeks[week] == "1"
            ) > limit
            for day in range(instance.nr_days)
            for week in range(instance.nr_weeks)
        )

    match = re.fullmatch(r"MaxBreaks\((\d+),(\d+)\)", kind)
    if match:
        max_breaks, gap_limit = map(int, match.groups())
        for day in range(instance.nr_days):
            for week in range(instance.nr_weeks):
                intervals = sorted(
                    (p.start, p.start + p.length)
                    for p in placements
                    if p.days[day] == "1" and p.weeks[week] == "1"
                )
                blocks = 0
                current_end: int | None = None
                for start, end in intervals:
                    if current_end is None or start - current_end > gap_limit:
                        blocks += 1
                    current_end = max(current_end or end, end)
                if max(0, blocks - 1) > max_breaks:
                    return True
        return False

    match = re.fullmatch(r"MaxBlock\((\d+),(\d+)\)", kind)
    if match:
        max_block, gap_limit = map(int, match.groups())
        for day in range(instance.nr_days):
            for week in range(instance.nr_weeks):
                intervals = sorted(
                    (p.start, p.start + p.length)
                    for p in placements
                    if p.days[day] == "1" and p.weeks[week] == "1"
                )
                if not intervals:
                    continue
                block_start, block_end = intervals[0]
                for start, end in intervals[1:]:
                    if start - block_end <= gap_limit:
                        block_end = max(block_end, end)
                        if block_end - block_start > max_block:
                            return True
                    else:
                        block_start, block_end = start, end
        return False

    raise ValueError(f"Unsupported global distribution: {kind}")


def _precedence_violation(placements: list[Placement]) -> bool:
    for first, second in zip(placements, placements[1:]):
        first_week = _first_active(first.weeks)
        second_week = _first_active(second.weeks)
        if first_week != second_week:
            if first_week > second_week:
                return True
            continue
        first_day = _first_active(first.days)
        second_day = _first_active(second.days)
        if first_day != second_day:
            if first_day > second_day:
                return True
            continue
        if first.start + first.length > second.start:
            return True
    return False


def _distribution_violates(
    instance: Instance,
    distribution: Distribution,
    assigned: dict[int, Placement],
    complete: bool,
) -> bool:
    selected = [
        (class_id, assigned[class_id])
        for class_id in distribution.class_ids
        if class_id in assigned
    ]
    kind = distribution.type
    if kind in PAIRWISE_TYPES or any(
        pattern.fullmatch(kind) for pattern in PARAMETERIZED_PAIR_PATTERNS
    ):
        return any(
            _pair_violation(instance, kind, first, second)
            for (_, first), (_, second) in combinations(selected, 2)
        )
    if not complete or len(selected) != len(distribution.class_ids):
        return False
    placements = [placement for _, placement in selected]
    if kind == "Precedence":
        return _precedence_violation(placements)
    return _global_violation(instance, distribution, placements)


def _soft_pair_violation_count(
    instance: Instance,
    distribution: Distribution,
    assigned: dict[int, Placement],
) -> int:
    selected = [
        (class_id, assigned[class_id])
        for class_id in distribution.class_ids
        if class_id in assigned
    ]
    return sum(
        _pair_violation(instance, distribution.type, first, second)
        for (_, first), (_, second) in combinations(selected, 2)
    )


def validate_schedule_independently(
    instance: Instance,
    schedule: Schedule,
) -> ValidationReport:
    class_ids = set(instance.classes)
    assigned = schedule.assignments
    missing = sorted(class_ids - assigned.keys())
    unknown_assignment_ids = sorted(assigned.keys() - class_ids)
    invalid_assignments = list(unknown_assignment_ids)
    room_compatibility: list[int] = []
    room_capacity_violations: list[int] = []
    room_capacity_unknown: list[int] = []

    for class_id, placement in assigned.items():
        cls = instance.classes.get(class_id)
        if cls is None:
            continue
        if placement not in cls.placements:
            invalid_assignments.append(class_id)
            room_compatibility.append(class_id)
        if (
            cls.room_required
            and (
                placement.room_id is None
                or placement.room_id not in instance.rooms
            )
        ):
            room_compatibility.append(class_id)
        if (
            cls.room_required
            and cls.expected_enrollment is not None
            and placement.room_id is not None
        ):
            room = instance.rooms.get(placement.room_id)
            if room is not None and room.capacity is None:
                room_capacity_unknown.append(class_id)
            elif (
                room is not None
                and room.capacity is not None
                and room.capacity < cls.expected_enrollment
            ):
                room_capacity_violations.append(class_id)

    room_conflicts: list[dict[str, int]] = []
    instructor_conflicts = 0
    student_conflicts = 0
    has_instructor_metadata = any(
        cls.instructor_ids for cls in instance.classes.values()
    )
    has_student_group_metadata = any(
        cls.student_group_ids for cls in instance.classes.values()
    )
    scheduled = list(assigned.items())
    for index, (class_a, first) in enumerate(scheduled):
        for class_b, second in scheduled[index + 1:]:
            if not _overlap(first, second):
                continue
            if first.room_id is not None and second.room_id == first.room_id:
                room_conflicts.append(
                    {"class_a": class_a, "class_b": class_b, "room_id": first.room_id}
                )
            class_a_data = instance.classes.get(class_a)
            class_b_data = instance.classes.get(class_b)
            if class_a_data is None or class_b_data is None:
                continue
            if set(class_a_data.instructor_ids) & set(class_b_data.instructor_ids):
                instructor_conflicts += 1
            if set(class_a_data.student_group_ids) & set(class_b_data.student_group_ids):
                student_conflicts += 1

    unsupported = unsupported_distributions(instance)
    capacity_unknown = [
        class_id
        for class_id, cls in instance.classes.items()
        if cls.room_required and cls.expected_enrollment is None
    ]
    if capacity_unknown:
        unsupported.append(
            {
                "type": "RoomCapacity(actual enrollment unavailable)",
                "required": True,
                "class_ids": capacity_unknown,
            }
        )
    if room_capacity_unknown:
        unsupported.append(
            {
                "type": "RoomCapacity(room capacity unavailable)",
                "required": True,
                "class_ids": sorted(set(room_capacity_unknown)),
            }
        )
    room_capacity_evaluated = not capacity_unknown and not room_capacity_unknown
    complete = not missing and not unknown_assignment_ids
    distribution_violations: list[dict[str, Any]] = []
    same_attendees_violations = 0
    for index, distribution in enumerate(instance.distributions):
        if not distribution.required or not is_supported_distribution(distribution.type):
            continue
        if _distribution_violates(instance, distribution, assigned, complete):
            distribution_violations.append(
                {
                    "index": index,
                    "type": distribution.type,
                    "class_ids": list(distribution.class_ids),
                }
            )
            if distribution.type == "SameAttendees":
                same_attendees_violations += 1

    required_unsupported = any(item["required"] for item in unsupported)
    validation_complete = not required_unsupported
    coverage_notes = []
    if not room_capacity_evaluated:
        coverage_notes.append(
            "Room capacity is only certified when both actual enrollment and "
            "the selected room capacity are known."
        )
    if not has_instructor_metadata:
        coverage_notes.append(
            "Direct instructor conflicts are unavailable because no class-instructor "
            "assignments are present."
        )
    if not has_student_group_metadata and instance.students:
        coverage_notes.append(
            "Student-to-class conflicts cannot be reconstructed from course enrollment "
            "without sectioning decisions; SameAttendees distributions are checked."
        )
    elif not instance.students and not has_student_group_metadata:
        coverage_notes.append(
            "No student enrollment or class-group data is available for direct student "
            "conflict checks."
        )
    if unsupported:
        coverage_notes.append(
            "Unsupported distributions are listed explicitly and required ones prevent "
            "a complete validation claim."
        )

    room_compatibility.extend(
        class_id
        for class_id, placement in assigned.items()
        if class_id in instance.classes
        and instance.classes[class_id].room_required
        and placement.room_id is None
    )
    room_compatibility = sorted(set(room_compatibility))

    placement_cost = sum(
        instance.time_weight * placement.time_penalty
        + instance.room_weight * placement.room_penalty
        for class_id, placement in assigned.items()
        if class_id in instance.classes
    )
    soft_penalty = 0
    soft_supported = True
    unsupported_soft_objectives = []
    if complete:
        for distribution in instance.distributions:
            if distribution.required or distribution.penalty == 0:
                continue
            if (
                distribution.type in PAIRWISE_TYPES
                or distribution.type == "Precedence"
                or any(
                    pattern.fullmatch(distribution.type)
                    for pattern in PARAMETERIZED_PAIR_PATTERNS
                )
            ):
                soft_penalty += distribution.penalty * _soft_pair_violation_count(
                    instance, distribution, assigned
                )
            else:
                soft_supported = False
                unsupported_soft_objectives.append(distribution.type)
    else:
        soft_supported = False
    if instance.student_weight > 0 and instance.students:
        soft_supported = False
        unsupported_soft_objectives.append("StudentSectioning")
    if unsupported_soft_objectives:
        coverage_notes.append(
            "Objective score is unavailable for unsupported soft objective terms: "
            + ", ".join(sorted(set(unsupported_soft_objectives)))
        )

    can_score = (
        complete
        and validation_complete
        and soft_supported
        and instance.student_weight == 0
    )
    objective_components = {
        "placement_penalty": placement_cost,
        "soft_distribution_penalty": instance.distribution_weight * soft_penalty,
    }
    violations_exist = bool(
        missing
        or unknown_assignment_ids
        or invalid_assignments
        or room_conflicts
        or instructor_conflicts
        or student_conflicts
        or room_compatibility
        or room_capacity_violations
        or distribution_violations
    )
    coverage = (
        len(assigned.keys() & class_ids) / len(class_ids)
        if class_ids
        else 1.0
    )
    return ValidationReport(
        complete=complete,
        validation_complete=validation_complete,
        valid_complete=complete and validation_complete and not violations_exist,
        assigned_count=len(assigned.keys() & class_ids),
        total_classes=len(class_ids),
        assignment_coverage=coverage,
        missing_assignments=missing,
        invalid_assignments=sorted(set(invalid_assignments)),
        room_occupancy_conflicts=room_conflicts,
        room_compatibility_violations=room_compatibility,
        room_capacity_violations=room_capacity_violations,
        room_capacity_evaluated=room_capacity_evaluated,
        instructor_conflicts=(
            instructor_conflicts if has_instructor_metadata else None
        ),
        student_conflicts=(
            student_conflicts if has_student_group_metadata else None
        ),
        same_attendees_violations=same_attendees_violations,
        required_distribution_violations=distribution_violations,
        unsupported_constraints=unsupported,
        coverage_notes=coverage_notes,
        objective_score=(
            objective_components["placement_penalty"]
            + objective_components["soft_distribution_penalty"]
            if can_score
            else None
        ),
        objective_components=objective_components,
    )
