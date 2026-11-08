from __future__ import annotations

from collections import Counter

from constraints import (
    pair_distribution_violation,
    required_distribution_violation,
    travel_time,
)
from parser import parse_instance
from solver import CSPSolver


TRIGGER_CLASS_ID = 573
CHECKED_CLASS_ID = 576
REPLAY_TIME_LIMIT = 180.0


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

            if any(
                self.candidate_valid(neighbor_id, placement)
                for placement in self.domains[neighbor_id]
            ):
                continue

            if neighbor_id == CHECKED_CLASS_ID:
                self.captured_assignments = dict(self.schedule.assignments)
                self.captured_trigger_placement = self.schedule.get_placement(
                    class_id
                )
                raise TargetFailureCaptured
            return False

        return True


def _independent_same_attendees_violation(instance, first, second) -> bool:
    common_days = any(
        first_day == "1" and second_day == "1"
        for first_day, second_day in zip(first.days, second.days)
    )
    common_weeks = any(
        first_week == "1" and second_week == "1"
        for first_week, second_week in zip(first.weeks, second.weeks)
    )
    if not common_days or not common_weeks:
        return False

    first_to_second = (
        first.start + first.length
        + travel_time(instance, first.room_id, second.room_id)
        <= second.start
    )
    second_to_first = (
        second.start + second.length
        + travel_time(instance, second.room_id, first.room_id)
        <= first.start
    )
    return not first_to_second and not second_to_first


def _format_placement(placement) -> str:
    return (
        f"room={placement.room_id}, days={placement.days}, "
        f"start={placement.start}, length={placement.length}, "
        f"weeks={placement.weeks}"
    )


def _candidate_breakdown(
    solver: CSPSolver,
) -> tuple[Counter, Counter, list, Counter]:
    rejection_counts = Counter()
    distribution_counts = Counter()
    explanations = []
    room_blockers = Counter()
    class_id = CHECKED_CLASS_ID

    for placement in solver.domains[class_id]:
        if solver._room_conflict(class_id, placement):
            blockers = [
                (other_id, other_placement)
                for other_id, other_placement in solver.room_occupancy[
                    placement.room_id
                ]
                if other_id != class_id
                and solver._time_overlap(placement, other_placement)
            ]
            for other_id, _ in blockers:
                room_blockers[other_id] += 1
            rejection_counts["room conflict"] += 1
            explanations.append((placement, "room conflict", blockers))
            continue

        old = solver.schedule.get_placement(class_id)
        solver.schedule.assign(class_id, placement)
        try:
            rejected_by = None
            first_pair = None
            for distribution in solver.class_distributions[class_id]:
                if not required_distribution_violation(
                    solver.instance,
                    distribution,
                    solver.schedule,
                ):
                    continue

                rejected_by = distribution
                distribution_counts[
                    (distribution.type, tuple(distribution.class_ids))
                ] += 1
                assigned_members = [
                    member_id
                    for member_id in distribution.class_ids
                    if solver.schedule.is_assigned(member_id)
                ]
                for index, first_id in enumerate(assigned_members):
                    first_placement = solver.schedule.get_placement(first_id)
                    for second_id in assigned_members[index + 1:]:
                        second_placement = solver.schedule.get_placement(
                            second_id
                        )
                        if pair_distribution_violation(
                            solver.instance,
                            distribution.type,
                            first_placement,
                            second_placement,
                        ):
                            first_pair = (
                                first_id,
                                first_placement,
                                second_id,
                                second_placement,
                            )
                            break
                    if first_pair is not None:
                        break

                rejection_counts["required distribution"] += 1
                explanations.append((placement, rejected_by, first_pair))
                break

            if rejected_by is None:
                rejection_counts["accepted"] += 1
                explanations.append((placement, None, None))
        finally:
            if old is None:
                solver.schedule.unassign(class_id)
            else:
                solver.schedule.assign(class_id, old)

    return rejection_counts, distribution_counts, explanations, room_blockers


def _independent_same_attendees_pair_counts(solver: CSPSolver) -> tuple[int, int]:
    checked_pairs = 0
    mismatches = 0
    for distribution in solver.class_distributions[CHECKED_CLASS_ID]:
        if distribution.type != "SameAttendees":
            continue
        for index, first_id in enumerate(distribution.class_ids):
            first = solver.schedule.get_placement(first_id)
            if first is None:
                continue
            for second_id in distribution.class_ids[index + 1:]:
                second = solver.schedule.get_placement(second_id)
                if second is None:
                    continue
                checked_pairs += 1
                expected = _independent_same_attendees_violation(
                    solver.instance,
                    first,
                    second,
                )
                actual = pair_distribution_violation(
                    solver.instance,
                    "SameAttendees",
                    first,
                    second,
                )
                mismatches += expected != actual
    return checked_pairs, mismatches


def main() -> None:
    instance = parse_instance("data/pu-d5-spr17.xml")
    solver = TargetReplaySolver(instance)

    for class_id in (TRIGGER_CLASS_ID, CHECKED_CLASS_ID):
        cls = instance.classes[class_id]
        print(
            f"Class {class_id}: course={cls.course_id}, config={cls.config_id}, "
            f"subpart={cls.subpart_id}, initial domain={len(cls.placements)}, "
            f"room_required={cls.room_required}, parent={cls.parent_id}, "
            f"limit={cls.limit}"
        )
        for distribution in solver.class_distributions[class_id]:
            print(
                f"  required {distribution.type}, "
                f"members={distribution.class_ids}"
            )

    print(
        f"Targeted replay capped at {REPLAY_TIME_LIMIT:.0f}s; "
        "stop at class 573 -> class 576 forward-check failure."
    )
    try:
        solver.solve()
    except TargetFailureCaptured:
        pass
    else:
        print(
            f"Target failure not reached; stopped after {solver.nodes} nodes."
        )
        return

    captured = solver.captured_assignments
    print(
        f"Captured failure state: {len(captured)} assignments before class "
        f"{CHECKED_CLASS_ID}; trigger class {TRIGGER_CLASS_ID} placement: "
        f"{_format_placement(solver.captured_trigger_placement)}"
    )
    relevant_ids = {
        CHECKED_CLASS_ID,
        *(
            member_id
            for distribution in solver.class_distributions[CHECKED_CLASS_ID]
            for member_id in distribution.class_ids
        ),
    }
    print("Assignments relevant to class 576 distributions:")
    for class_id in sorted(relevant_ids):
        placement = captured.get(class_id)
        print(
            f"  class {class_id}: "
            f"{_format_placement(placement) if placement else 'unassigned'}"
        )

    before_solver = CSPSolver(instance)
    after_solver = CSPSolver(instance)
    for class_id, placement in captured.items():
        if class_id != TRIGGER_CLASS_ID:
            before_solver.assign(class_id, placement)
        after_solver.assign(class_id, placement)

    assert before_solver.schedule.assignments == {
        class_id: placement
        for class_id, placement in captured.items()
        if class_id != TRIGGER_CLASS_ID
    }
    assert after_solver.schedule.assignments == captured
    assert {
        class_id: placement
        for entries in after_solver.room_occupancy.values()
        for class_id, placement in entries
    } == {
        class_id: placement
        for class_id, placement in captured.items()
        if placement.room_id is not None
    }

    before_results = _candidate_breakdown(before_solver)
    after_results = _candidate_breakdown(after_solver)
    for label, results in (
        ("before class 573", before_results),
        ("after class 573", after_results),
    ):
        (
            outcome_counts,
            distribution_counts,
            explanations,
            room_blockers,
        ) = results
        print(f"Class 576 {label}: {dict(outcome_counts)}")
        print(f"  Distribution rejections: {dict(distribution_counts)}")
        if room_blockers:
            print(f"  Room-conflict blockers by assigned class: {dict(room_blockers)}")
        if label == "after class 573":
            print("  Candidate-by-candidate first rejection:")
            for placement, distribution, detail in explanations:
                reason = "accepted"
                if distribution == "room conflict":
                    blocker_text = ", ".join(
                        f"class {other_id} ({_format_placement(other)})"
                        for other_id, other in detail
                    )
                    reason = f"room conflict with {blocker_text}"
                elif distribution is not None:
                    if detail is None:
                        reason = (
                            f"{distribution.type}; no violating pair located"
                        )
                    else:
                        first_id, first, second_id, second = detail
                        reason = (
                            f"{distribution.type} pair {first_id}/{second_id}; "
                            f"{_format_placement(first)} vs "
                            f"{_format_placement(second)}"
                        )
                print(f"    {_format_placement(placement)} -> {reason}")

    before_accepted = [
        placement
        for placement, reason, _ in before_results[2]
        if reason is None
    ]
    newly_room_blocked = [
        (placement, blockers)
        for placement, reason, blockers in after_results[2]
        if reason == "room conflict" and placement in before_accepted
    ]
    print(
        f"Before trigger, legal candidates: "
        f"{[_format_placement(p) for p in before_accepted]}"
    )
    print("Previously legal candidates newly blocked by class 573:")
    for placement, blockers in newly_room_blocked:
        print(
            f"  {_format_placement(placement)} blocked by "
            + ", ".join(f"class {class_id}" for class_id, _ in blockers)
        )

    pair_count, mismatches = _independent_same_attendees_pair_counts(
        after_solver
    )
    print(
        "Independent SameAttendees check of already-assigned pairs: "
        f"{pair_count} pairs, {mismatches} mismatches"
    )

    print("Incomplete-distribution members after trigger:")
    for distribution in solver.class_distributions[CHECKED_CLASS_ID]:
        unassigned = [
            class_id
            for class_id in distribution.class_ids
            if class_id not in captured
        ]
        print(
            f"  {distribution.type} {distribution.class_ids}: "
            f"unassigned={unassigned}"
        )


if __name__ == "__main__":
    main()
