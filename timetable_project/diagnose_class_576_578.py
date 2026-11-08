from __future__ import annotations

from collections import Counter

from constraints import (
    pair_distribution_violation,
    required_distribution_violation,
    travel_time,
)
from model import Schedule
from parser import parse_instance
from solver import CSPSolver


TRIGGER_CLASS_ID = 576
CHECKED_CLASS_ID = 578
REPLAY_TIME_LIMIT = 90.0


class TargetFailureCaptured(Exception):
    pass


class TargetReplaySolver(CSPSolver):
    TIME_LIMIT = REPLAY_TIME_LIMIT

    def forward_check(self, class_id: int) -> bool:
        if class_id != TRIGGER_CLASS_ID:
            return super().forward_check(class_id)

        for neighbor_id in self.neighbors[class_id]:
            if self.schedule.is_assigned(neighbor_id):
                continue

            has_value = False
            for placement in self.domains[neighbor_id]:
                if self.candidate_valid(neighbor_id, placement):
                    has_value = True
                    break

            if not has_value and neighbor_id == CHECKED_CLASS_ID:
                self.captured_assignments = dict(self.schedule.assignments)
                self.captured_trigger = class_id
                self.captured_blocked_class = neighbor_id
                raise TargetFailureCaptured

            if not has_value:
                return False

        return True


def _independent_same_attendees_violation(
    instance,
    first,
    second,
) -> bool:
    common_day = any(
        left == "1" and right == "1"
        for left, right in zip(first.days, second.days)
    )
    common_week = any(
        left == "1" and right == "1"
        for left, right in zip(first.weeks, second.weeks)
    )
    if not common_day or not common_week:
        return False

    first_before_second = (
        first.start + first.length
        + travel_time(instance, first.room_id, second.room_id)
        <= second.start
    )
    second_before_first = (
        second.start + second.length
        + travel_time(instance, second.room_id, first.room_id)
        <= first.start
    )
    return not first_before_second and not second_before_first


def _first_violating_pair(solver: CSPSolver, distribution):
    for index, first_id in enumerate(distribution.class_ids):
        first = solver.schedule.get_placement(first_id)
        if first is None:
            continue
        for second_id in distribution.class_ids[index + 1:]:
            second = solver.schedule.get_placement(second_id)
            if second is not None and pair_distribution_violation(
                solver.instance,
                distribution.type,
                first,
                second,
            ):
                return first_id, second_id
    return None


def _classify_candidates(
    solver: CSPSolver,
) -> tuple[Counter, Counter, Counter, Counter]:
    rejection_counts = Counter()
    distribution_counts = Counter()
    first_pair_counts = Counter()
    all_pair_counts = Counter()

    for candidate in solver.domains[CHECKED_CLASS_ID]:
        if solver._room_conflict(CHECKED_CLASS_ID, candidate):
            rejection_counts["room conflict"] += 1
            continue

        old = solver.schedule.get_placement(CHECKED_CLASS_ID)
        solver.schedule.assign(CHECKED_CLASS_ID, candidate)
        try:
            rejected = False
            for distribution in solver.class_distributions[CHECKED_CLASS_ID]:
                if not required_distribution_violation(
                    solver.instance,
                    distribution,
                    solver.schedule,
                ):
                    continue

                rejection_counts["required distribution"] += 1
                distribution_counts[
                    (distribution.type, tuple(distribution.class_ids))
                ] += 1
                rejected = True
                first_pair_counts[
                    (
                        tuple(distribution.class_ids),
                        _first_violating_pair(solver, distribution),
                    )
                ] += 1
                for index, first_id in enumerate(distribution.class_ids):
                    first = solver.schedule.get_placement(first_id)
                    if first is None:
                        continue
                    for second_id in distribution.class_ids[index + 1:]:
                        second = solver.schedule.get_placement(second_id)
                        if second is not None and pair_distribution_violation(
                            solver.instance,
                            distribution.type,
                            first,
                            second,
                        ):
                            all_pair_counts[
                                (first_id, second_id)
                            ] += 1

                break

            if not rejected:
                rejection_counts["accepted"] += 1
        finally:
            if old is None:
                solver.schedule.unassign(CHECKED_CLASS_ID)
            else:
                solver.schedule.assign(CHECKED_CLASS_ID, old)

    return (
        rejection_counts,
        distribution_counts,
        first_pair_counts,
        all_pair_counts,
    )


def main() -> None:
    instance = parse_instance("data/pu-d5-spr17.xml")
    solver = TargetReplaySolver(instance)

    for class_id in (TRIGGER_CLASS_ID, CHECKED_CLASS_ID):
        cls = instance.classes[class_id]
        print(
            f"Class {class_id}: course={cls.course_id}, config={cls.config_id}, "
            f"subpart={cls.subpart_id}, placements={len(cls.placements)}, "
            f"room_required={cls.room_required}, parent={cls.parent_id}, "
            f"limit={cls.limit}"
        )
        for distribution in instance.distributions:
            if distribution.required and class_id in distribution.class_ids:
                print(
                    f"  required {distribution.type}, "
                    f"penalty={distribution.penalty}, "
                    f"members={distribution.class_ids}"
                )

    print(
        f"Targeted replay (maximum {REPLAY_TIME_LIMIT:.0f}s); "
        f"stops at first class {TRIGGER_CLASS_ID} -> "
        f"class {CHECKED_CLASS_ID} zero-domain event."
    )
    try:
        solver.solve()
    except TargetFailureCaptured:
        pass
    else:
        print(
            f"Target event not reached within {REPLAY_TIME_LIMIT:.0f}s; "
            f"replay stopped at {solver.nodes} nodes."
        )
        return

    captured = solver.captured_assignments
    trigger_placement = captured[TRIGGER_CLASS_ID]
    print(
        f"Captured trigger placement: {trigger_placement!r}; "
        f"assigned count={len(captured)}"
    )
    group = next(
        distribution
        for distribution in instance.distributions
        if distribution.required
        and distribution.type == "SameAttendees"
        and TRIGGER_CLASS_ID in distribution.class_ids
        and CHECKED_CLASS_ID in distribution.class_ids
    )
    print("Captured placements for the shared SameAttendees distribution:")
    for class_id in group.class_ids:
        placement = captured.get(class_id)
        print(f"  {class_id}: {placement!r}")

    before_solver = CSPSolver(instance)
    for class_id, placement in captured.items():
        if class_id != TRIGGER_CLASS_ID:
            before_solver.assign(class_id, placement)

    after_solver = CSPSolver(instance)
    for class_id, placement in captured.items():
        after_solver.assign(class_id, placement)

    (
        before_counts,
        before_distributions,
        before_first_pairs,
        before_all_pairs,
    ) = _classify_candidates(before_solver)
    (
        after_counts,
        after_distributions,
        after_first_pairs,
        after_all_pairs,
    ) = _classify_candidates(after_solver)
    print(f"Class {CHECKED_CLASS_ID} before trigger: {dict(before_counts)}")
    print(f"Class {CHECKED_CLASS_ID} after trigger:  {dict(after_counts)}")
    print(f"Before-trigger distribution rejections: {dict(before_distributions)}")
    print(f"After-trigger distribution rejections:  {dict(after_distributions)}")
    print(
        "Before-trigger first rejecting pair by distribution/candidate: "
        f"{dict(before_first_pairs)}"
    )
    print(
        "After-trigger first rejecting pair by distribution/candidate:  "
        f"{dict(after_first_pairs)}"
    )
    print(f"After-trigger all violating pairs per candidate: {dict(after_all_pairs)}")

    print("Independent SameAttendees semantic check:")
    for distribution in after_solver.class_distributions[CHECKED_CLASS_ID]:
        if distribution.type != "SameAttendees":
            continue
        mismatches = 0
        checked_pairs = 0
        for first_index, first_id in enumerate(distribution.class_ids):
            first = after_solver.schedule.get_placement(first_id)
            if first is None:
                continue
            for second_id in distribution.class_ids[first_index + 1:]:
                second = after_solver.schedule.get_placement(second_id)
                if second is None:
                    continue
                checked_pairs += 1
                expected = _independent_same_attendees_violation(
                    instance,
                    first,
                    second,
                )
                actual = pair_distribution_violation(
                    instance,
                    "SameAttendees",
                    first,
                    second,
                )
                mismatches += expected != actual
        print(
            f"  members={distribution.class_ids}, assigned pairs={checked_pairs}, "
            f"mismatches={mismatches}"
        )


if __name__ == "__main__":
    main()
