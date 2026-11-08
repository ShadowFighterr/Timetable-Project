from __future__ import annotations

from collections import Counter

from constraints import (
    required_distribution_violation,
    travel_time,
)
from model import Schedule
from parser import parse_instance
from solver import CSPSolver


TRIGGER_CLASS_ID = 568
CHECKED_CLASS_ID = 594


def _find_placement(
    instance,
    class_id: int,
    *,
    room_id: int,
    days: str,
    start: int,
    length: int,
    weeks: str,
):
    return next(
        placement
        for placement in instance.classes[class_id].placements
        if placement.room_id == room_id
        and placement.days == days
        and placement.start == start
        and placement.length == length
        and placement.weeks == weeks
    )


def _classify_candidates(
    solver: CSPSolver,
    class_id: int,
) -> tuple[Counter[str], dict[str, Counter[str]]]:
    overall: Counter[str] = Counter()
    distribution_results: dict[str, Counter[str]] = {}

    for placement in solver.domains[class_id]:
        if solver._room_conflict(class_id, placement):
            overall["room conflict"] += 1
            continue

        old = solver.schedule.get_placement(class_id)
        solver.schedule.assign(class_id, placement)
        try:
            rejected_by = None
            for distribution in solver.class_distributions[class_id]:
                violation = required_distribution_violation(
                    solver.instance,
                    distribution,
                    solver.schedule,
                )
                type_counts = distribution_results.setdefault(
                    distribution.type,
                    Counter(),
                )
                type_counts["evaluated"] += 1
                if violation:
                    type_counts["violation"] += 1
                    rejected_by = distribution.type
                    break
                type_counts["no violation"] += 1

            if rejected_by is None:
                overall["accepted"] += 1
            else:
                overall[f"required distribution: {rejected_by}"] += 1
        finally:
            if old is None:
                solver.schedule.unassign(class_id)
            else:
                solver.schedule.assign(class_id, old)

    return overall, distribution_results


def _independent_placements_overlap(first, second) -> bool:
    common_day = any(
        day_a == "1" and day_b == "1"
        for day_a, day_b in zip(first.days, second.days)
    )
    common_week = any(
        week_a == "1" and week_b == "1"
        for week_a, week_b in zip(first.weeks, second.weeks)
    )
    time_overlap = (
        first.start < second.start + second.length
        and second.start < first.start + first.length
    )
    return common_day and common_week and time_overlap


def _assigned_not_overlap_pairs(distribution, schedule: Schedule):
    assigned = [
        (class_id, schedule.get_placement(class_id))
        for class_id in distribution.class_ids
    ]
    assigned = [
        (class_id, placement)
        for class_id, placement in assigned
        if placement is not None
    ]
    return [
        (class_a, class_b)
        for index, (class_a, placement_a) in enumerate(assigned)
        for class_b, placement_b in assigned[index + 1:]
        if _independent_placements_overlap(placement_a, placement_b)
    ]


def _independent_same_attendees_violation(
    distribution,
    schedule: Schedule,
) -> bool | None:
    placements = [
        schedule.get_placement(class_id)
        for class_id in distribution.class_ids
    ]
    if any(placement is None for placement in placements):
        return None

    concrete_placements = [
        placement for placement in placements if placement is not None
    ]
    for index, first in enumerate(concrete_placements):
        for second in concrete_placements[index + 1:]:
            common_day = any(
                day_a == "1" and day_b == "1"
                for day_a, day_b in zip(first.days, second.days)
            )
            common_week = any(
                week_a == "1" and week_b == "1"
                for week_a, week_b in zip(first.weeks, second.weeks)
            )
            if not common_day or not common_week:
                continue

            first_before_second = (
                first.start + first.length
                + travel_time(
                    schedule.instance,
                    first.room_id,
                    second.room_id,
                )
                <= second.start
            )
            second_before_first = (
                second.start + second.length
                + travel_time(
                    schedule.instance,
                    second.room_id,
                    first.room_id,
                )
                <= first.start
            )
            if not first_before_second and not second_before_first:
                return True
    return False


def _print_class_details(instance, class_id: int) -> None:
    cls = instance.classes[class_id]
    print(
        f"Class {class_id}: course={cls.course_id}, "
        f"config={cls.config_id}, subpart={cls.subpart_id}, "
        f"domain={len(cls.placements)}, room_required={cls.room_required}, "
        f"parent={cls.parent_id}, limit={cls.limit}"
    )
    print(
        f"  fixed by singleton domain: {len(cls.placements) == 1}; "
        "the parsed Class model has no separate fixed-assignment field"
    )


def main() -> None:
    instance = parse_instance("data/pu-d5-spr17.xml")

    _print_class_details(instance, TRIGGER_CLASS_ID)
    _print_class_details(instance, CHECKED_CLASS_ID)

    trigger_class = instance.classes[TRIGGER_CLASS_ID]
    checked_class = instance.classes[CHECKED_CLASS_ID]
    print(
        "Direct class relationship: "
        f"same course={trigger_class.course_id == checked_class.course_id}, "
        f"same config={trigger_class.config_id == checked_class.config_id}, "
        f"same subpart={trigger_class.subpart_id == checked_class.subpart_id}"
    )

    distributions = [
        distribution
        for distribution in instance.distributions
        if distribution.required
        and (
            TRIGGER_CLASS_ID in distribution.class_ids
            or CHECKED_CLASS_ID in distribution.class_ids
        )
    ]
    print("Required distributions containing either class:")
    for distribution in distributions:
        contains_both = (
            TRIGGER_CLASS_ID in distribution.class_ids
            and CHECKED_CLASS_ID in distribution.class_ids
        )
        print(
            f"  type={distribution.type}, penalty={distribution.penalty}, "
            f"classes={distribution.class_ids}, shared={contains_both}"
        )

    trigger_placement = _find_placement(
        instance,
        TRIGGER_CLASS_ID,
        room_id=63,
        days="0100000",
        start=138,
        length=22,
        weeks="111111111111111",
    )
    prior_placements = {
        550: _find_placement(
            instance,
            550,
            room_id=51,
            days="0100000",
            start=114,
            length=22,
            weeks="111111111111111",
        ),
        565: _find_placement(
            instance,
            565,
            room_id=63,
            days="0100000",
            start=114,
            length=22,
            weeks="111111111111111",
        ),
    }
    print(f"Recorded class-568 trigger placement: {trigger_placement!r}")
    print("Recorded overlapping prior assignments:")
    for class_id, placement in prior_placements.items():
        print(f"  class {class_id}: {placement!r}")

    before_solver = CSPSolver(instance)
    for class_id, placement in prior_placements.items():
        before_solver.assign(class_id, placement)

    after_solver = CSPSolver(instance)
    for class_id, placement in prior_placements.items():
        after_solver.assign(class_id, placement)
    after_solver.assign(TRIGGER_CLASS_ID, trigger_placement)

    not_overlap = next(
        distribution
        for distribution in distributions
        if distribution.type == "NotOverlap"
        and TRIGGER_CLASS_ID in distribution.class_ids
        and CHECKED_CLASS_ID in distribution.class_ids
    )
    prior_overlaps_before = _assigned_not_overlap_pairs(
        not_overlap,
        before_solver.schedule,
    )
    prior_overlaps_after = _assigned_not_overlap_pairs(
        not_overlap,
        after_solver.schedule,
    )
    print(
        f"Before testing class {CHECKED_CLASS_ID}, unassigned "
        f"NotOverlap members="
        f"{[cid for cid in not_overlap.class_ids if cid not in before_solver.schedule.assignments]}; "
        f"assigned overlaps={prior_overlaps_before}"
    )
    print(
        f"After class {TRIGGER_CLASS_ID}, unassigned NotOverlap members="
        f"{[cid for cid in not_overlap.class_ids if cid not in after_solver.schedule.assignments]}; "
        f"assigned overlaps={prior_overlaps_after}"
    )

    before_counts, _ = _classify_candidates(
        before_solver,
        CHECKED_CLASS_ID,
    )
    after_counts, after_distribution_results = _classify_candidates(
        after_solver,
        CHECKED_CLASS_ID,
    )
    print(f"Class {CHECKED_CLASS_ID} before class {TRIGGER_CLASS_ID}: {dict(before_counts)}")
    print(f"Class {CHECKED_CLASS_ID} after class {TRIGGER_CLASS_ID}:  {dict(after_counts)}")
    print("Distribution rejection breakdown, after trigger:")
    for distribution_type, counts in after_distribution_results.items():
        print(f"  {distribution_type}: {dict(counts)}")

    print("Partial-assignment distribution cross-checks for class-594 candidates:")
    for distribution in distributions:
        checked = 0
        mismatches = 0
        observed_violations = 0
        for placement in after_solver.domains[CHECKED_CLASS_ID]:
            after_solver.schedule.assign(CHECKED_CLASS_ID, placement)
            try:
                if distribution.type == "NotOverlap":
                    expected = bool(
                        _assigned_not_overlap_pairs(
                            distribution,
                            after_solver.schedule,
                        )
                    )
                elif distribution.type == "SameAttendees":
                    expected = _independent_same_attendees_violation(
                        distribution,
                        after_solver.schedule,
                    )
                else:
                    expected = None
                actual = required_distribution_violation(
                    instance,
                    distribution,
                    after_solver.schedule,
                )
            finally:
                after_solver.schedule.unassign(CHECKED_CLASS_ID)

            if expected is None:
                continue
            checked += 1
            observed_violations += bool(actual)
            mismatches += expected != actual

        print(
            f"  {distribution.type} classes={distribution.class_ids}: "
            f"independently checkable candidate cases={checked}, "
            f"checker violations={observed_violations}, "
            f"independent mismatches={mismatches}"
        )


if __name__ == "__main__":
    main()
