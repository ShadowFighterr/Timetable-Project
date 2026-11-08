from __future__ import annotations

import re
from itertools import combinations

from model import Schedule
from parser import (
    Instance,
    Placement,
)


# ============================================================
# BASIC PLACEMENT RELATIONS
# ============================================================

def placements_overlap(
    a: Placement,
    b: Placement,
) -> bool:

    # Different weeks -> no overlap
    if not _bits_overlap(a.weeks, b.weeks):
        return False

    # Different weekdays -> no overlap
    if not _bits_overlap(a.days, b.days):
        return False

    a_end = a.start + a.length
    b_end = b.start + b.length

    return (
        a.start < b_end
        and b.start < a_end
    )


def _bits_overlap(a: str, b: str) -> bool:
    return any(
        x == "1" and y == "1"
        for x, y in zip(a, b)
    )


def _bits_subset(a: str, b: str) -> bool:
    """
    True if every active bit in a is also active in b.
    """

    return all(
        x != "1" or y == "1"
        for x, y in zip(a, b)
    )


def _first_bit(bits: str) -> int:
    """
    Return index of first active bit.

    Example:
        0010100 -> 2
    """

    for i, bit in enumerate(bits):
        if bit == "1":
            return i

    return 10**9


def _count_bits(bits: str) -> int:
    return bits.count("1")


# ============================================================
# ROOM CONFLICT
# ============================================================

def has_room_conflict(
    instance: Instance,
    class_id: int,
    placement: Placement,
    schedule: Schedule,
) -> bool:

    if placement.room_id is None:
        return False

    for other_id, other_placement in (
        schedule.assignments.items()
    ):

        if other_id == class_id:
            continue

        if other_placement.room_id != placement.room_id:
            continue

        if placements_overlap(
            placement,
            other_placement,
        ):
            return True

    return False


# ============================================================
# TRAVEL / SAME ATTENDEES
# ============================================================

def travel_time(
    instance: Instance,
    room_a: int | None,
    room_b: int | None,
) -> int:

    if room_a is None or room_b is None:
        return 0

    if room_a == room_b:
        return 0

    room = instance.rooms[room_a]

    return room.travel.get(
        room_b,
        0,
    )


def same_attendees_violation(
    instance: Instance,
    a: Placement,
    b: Placement,
) -> bool:

    # Different weeks
    if not _bits_overlap(a.weeks, b.weeks):
        return False

    # Different days
    if not _bits_overlap(a.days, b.days):
        return False

    a_end = a.start + a.length
    b_end = b.start + b.length

    travel_ab = travel_time(
        instance,
        a.room_id,
        b.room_id,
    )

    travel_ba = travel_time(
        instance,
        b.room_id,
        a.room_id,
    )

    # A -> B
    if a_end + travel_ab <= b.start:
        return False

    # B -> A
    if b_end + travel_ba <= a.start:
        return False

    return True


# ============================================================
# PAIR DISTRIBUTION CONSTRAINTS
# ============================================================

def pair_distribution_violation(
    instance: Instance,
    distribution_type: str,
    a: Placement,
    b: Placement,
) -> bool:

    # --------------------------------------------------------
    # SameStart
    # --------------------------------------------------------

    if distribution_type == "SameStart":

        return a.start != b.start

    # --------------------------------------------------------
    # SameTime
    # --------------------------------------------------------

    if distribution_type == "SameTime":

        a_end = a.start + a.length
        b_end = b.start + b.length

        return not (
            (
                a.start <= b.start
                and b_end <= a_end
            )
            or
            (
                b.start <= a.start
                and a_end <= b_end
            )
        )

    # --------------------------------------------------------
    # DifferentTime
    # --------------------------------------------------------

    if distribution_type == "DifferentTime":

        a_end = a.start + a.length
        b_end = b.start + b.length

        return not (
            a_end <= b.start
            or b_end <= a.start
        )

    # --------------------------------------------------------
    # SameDays
    # --------------------------------------------------------

    if distribution_type == "SameDays":

        return not (
            _bits_subset(a.days, b.days)
            or _bits_subset(b.days, a.days)
        )

    # --------------------------------------------------------
    # DifferentDays
    # --------------------------------------------------------

    if distribution_type == "DifferentDays":

        return _bits_overlap(
            a.days,
            b.days,
        )

    # --------------------------------------------------------
    # SameWeeks
    # --------------------------------------------------------

    if distribution_type == "SameWeeks":

        return not (
            _bits_subset(a.weeks, b.weeks)
            or _bits_subset(b.weeks, a.weeks)
        )

    # --------------------------------------------------------
    # DifferentWeeks
    # --------------------------------------------------------

    if distribution_type == "DifferentWeeks":

        return _bits_overlap(
            a.weeks,
            b.weeks,
        )

    # --------------------------------------------------------
    # SameRoom
    # --------------------------------------------------------

    if distribution_type == "SameRoom":

        return a.room_id != b.room_id

    # --------------------------------------------------------
    # DifferentRoom
    # --------------------------------------------------------

    if distribution_type == "DifferentRoom":

        return a.room_id == b.room_id

    # --------------------------------------------------------
    # Overlap
    # --------------------------------------------------------

    if distribution_type == "Overlap":

        return not placements_overlap(a, b)

    # --------------------------------------------------------
    # NotOverlap
    # --------------------------------------------------------

    if distribution_type == "NotOverlap":

        return placements_overlap(a, b)

    # --------------------------------------------------------
    # SameAttendees
    # --------------------------------------------------------

    if distribution_type == "SameAttendees":

        return same_attendees_violation(
            instance,
            a,
            b,
        )

    # --------------------------------------------------------
    # WorkDay(S)
    # --------------------------------------------------------

    match = re.fullmatch(
        r"WorkDay\((\d+)\)",
        distribution_type,
    )

    if match:

        limit = int(match.group(1))

        if not _bits_overlap(
            a.days,
            b.days,
        ):
            return False

        if not _bits_overlap(
            a.weeks,
            b.weeks,
        ):
            return False

        earliest = min(
            a.start,
            b.start,
        )

        latest = max(
            a.start + a.length,
            b.start + b.length,
        )

        return latest - earliest > limit

    # --------------------------------------------------------
    # MinGap(G)
    # --------------------------------------------------------

    match = re.fullmatch(
        r"MinGap\((\d+)\)",
        distribution_type,
    )

    if match:

        gap = int(match.group(1))

        if not _bits_overlap(
            a.days,
            b.days,
        ):
            return False

        if not _bits_overlap(
            a.weeks,
            b.weeks,
        ):
            return False

        a_end = a.start + a.length
        b_end = b.start + b.length

        return not (
            a_end + gap <= b.start
            or b_end + gap <= a.start
        )

    return False


# ============================================================
# PRECEDENCE
# ============================================================

def precedence_violation(
    placements: list[Placement],
) -> bool:

    for a, b in zip(
        placements,
        placements[1:],
    ):

        week_a = _first_bit(a.weeks)
        week_b = _first_bit(b.weeks)

        if week_a < week_b:
            continue

        if week_a > week_b:
            return True

        day_a = _first_bit(a.days)
        day_b = _first_bit(b.days)

        if day_a < day_b:
            continue

        if day_a > day_b:
            return True

        a_end = a.start + a.length

        if a_end <= b.start:
            continue

        return True

    return False


# ============================================================
# GLOBAL DISTRIBUTION CONSTRAINTS
# ============================================================

def global_distribution_violation(
    instance: Instance,
    distribution_type: str,
    placements: list[Placement],
) -> bool:

    # --------------------------------------------------------
    # MaxDays(D)
    # --------------------------------------------------------

    match = re.fullmatch(
        r"MaxDays\((\d+)\)",
        distribution_type,
    )

    if match:

        limit = int(match.group(1))

        union_days = "0" * instance.nr_days

        bits = [False] * instance.nr_days

        for placement in placements:

            for i, value in enumerate(
                placement.days
            ):
                if value == "1":
                    bits[i] = True

        return sum(bits) > limit

    # --------------------------------------------------------
    # MaxDayLoad(S)
    # --------------------------------------------------------

    match = re.fullmatch(
        r"MaxDayLoad\((\d+)\)",
        distribution_type,
    )

    if match:

        limit = int(match.group(1))

        for day in range(
            instance.nr_days
        ):

            for week in range(
                instance.nr_weeks
            ):

                total = 0

                for p in placements:

                    if (
                        p.days[day] == "1"
                        and p.weeks[week] == "1"
                    ):
                        total += p.length

                if total > limit:
                    return True

        return False

    # --------------------------------------------------------
    # MaxBreaks(R,S)
    # --------------------------------------------------------

    match = re.fullmatch(
        r"MaxBreaks\((\d+),(\d+)\)",
        distribution_type,
    )

    if match:

        max_breaks = int(
            match.group(1)
        )

        gap_limit = int(
            match.group(2)
        )

        for day in range(
            instance.nr_days
        ):

            for week in range(
                instance.nr_weeks
            ):

                intervals = []

                for p in placements:

                    if (
                        p.days[day] == "1"
                        and p.weeks[week] == "1"
                    ):

                        intervals.append(
                            (
                                p.start,
                                p.start + p.length,
                            )
                        )

                if len(intervals) <= 1:
                    continue

                intervals.sort()

                blocks = 1

                current_end = intervals[0][1]

                for start, end in intervals[1:]:

                    if start - current_end > gap_limit:
                        blocks += 1

                    current_end = max(
                        current_end,
                        end,
                    )

                breaks = blocks - 1

                if breaks > max_breaks:
                    return True

        return False

    # --------------------------------------------------------
    # MaxBlock(M,S)
    # --------------------------------------------------------

    match = re.fullmatch(
        r"MaxBlock\((\d+),(\d+)\)",
        distribution_type,
    )

    if match:

        max_block = int(
            match.group(1)
        )

        gap_limit = int(
            match.group(2)
        )

        for day in range(
            instance.nr_days
        ):

            for week in range(
                instance.nr_weeks
            ):

                intervals = []

                for p in placements:

                    if (
                        p.days[day] == "1"
                        and p.weeks[week] == "1"
                    ):

                        intervals.append(
                            (
                                p.start,
                                p.start + p.length,
                            )
                        )

                if len(intervals) <= 1:
                    continue

                intervals.sort()

                block_start = intervals[0][0]
                block_end = intervals[0][1]
                block_count = 1

                for start, end in intervals[1:]:

                    if start - block_end <= gap_limit:

                        block_end = max(
                            block_end,
                            end,
                        )

                        block_count += 1

                        if (
                            block_count >= 2
                            and block_end - block_start
                            > max_block
                        ):
                            return True

                    else:

                        block_start = start
                        block_end = end
                        block_count = 1

        return False

    return False


# ============================================================
# REQUIRED DISTRIBUTION CHECK
# ============================================================

def required_distribution_violation(
    instance: Instance,
    distribution,
    schedule: Schedule,
) -> bool:

    class_ids = distribution.class_ids
    distribution_type = distribution.type

    pairwise_types = {
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
    }

    is_pairwise = (
        distribution_type in pairwise_types
        or distribution_type.startswith("WorkDay(")
        or distribution_type.startswith("MinGap(")
    )

    if is_pairwise:
        assigned_placements = [
            schedule.assignments[class_id]
            for class_id in class_ids
            if class_id in schedule.assignments
        ]

        for a, b in combinations(
            assigned_placements,
            2,
        ):
            if pair_distribution_violation(
                instance,
                distribution_type,
                a,
                b,
            ):
                return True

        # Pairwise relations can still be satisfiable later
        # when the remaining classes are assigned, so we do not
        # reject a partial schedule solely because it is incomplete.
        if len(assigned_placements) < len(class_ids):
            return False

    # If the constraint isn't fully assigned yet,
    # don't reject the partial schedule.
    if any(
        class_id not in schedule.assignments
        for class_id in class_ids
    ):
        return False

    placements = [
        schedule.assignments[class_id]
        for class_id in class_ids
    ]

    # --------------------------------------------------------
    # Precedence
    # --------------------------------------------------------

    if distribution_type == "Precedence":

        return precedence_violation(
            placements
        )

    # --------------------------------------------------------
    # Pairwise constraints
    # --------------------------------------------------------

    if distribution_type in pairwise_types:

        for a, b in combinations(
            placements,
            2,
        ):

            if pair_distribution_violation(
                instance,
                distribution_type,
                a,
                b,
            ):
                return True

        return False

    # --------------------------------------------------------
    # Parameterized pair constraints
    # --------------------------------------------------------

    if (
        distribution_type.startswith("WorkDay(")
        or distribution_type.startswith("MinGap(")
    ):

        for a, b in combinations(
            placements,
            2,
        ):

            if pair_distribution_violation(
                instance,
                distribution_type,
                a,
                b,
            ):
                return True

        return False

    # --------------------------------------------------------
    # Global constraints
    # --------------------------------------------------------

    return global_distribution_violation(
        instance,
        distribution_type,
        placements,
    )


# ============================================================
# CLASS ASSIGNMENT CHECK
# ============================================================

def validate_class_assignment(
    instance: Instance,
    schedule: Schedule,
    class_id: int,
    placement: Placement,
) -> bool:

    # --------------------------------------------------------
    # 1. Room conflict
    # --------------------------------------------------------

    if has_room_conflict(
        instance,
        class_id,
        placement,
        schedule,
    ):
        return False

    # --------------------------------------------------------
    # 2. Required distributions involving
    #    this class
    # --------------------------------------------------------

    old = schedule.assignments.get(
        class_id
    )

    schedule.assignments[class_id] = placement

    try:

        for distribution in instance.distributions:

            if not distribution.required:
                continue

            if class_id not in distribution.class_ids:
                continue

            if required_distribution_violation(
                instance,
                distribution,
                schedule,
            ):
                return False

        return True

    finally:

        if old is None:
            schedule.assignments.pop(
                class_id,
                None,
            )
        else:
            schedule.assignments[class_id] = old


# ============================================================
# FULL SCHEDULE VALIDATION
# ============================================================

def validate_schedule(
    instance: Instance,
    schedule: Schedule,
) -> dict[str, int]:

    violations = {
        "unassigned": 0,
        "room": 0,
        "required_distribution": 0,
        "other": 0,
    }

    # --------------------------------------------------------
    # Unassigned
    # --------------------------------------------------------

    violations["unassigned"] = (
        len(instance.classes)
        - schedule.assigned_count
    )

    # --------------------------------------------------------
    # Room conflicts
    # --------------------------------------------------------

    assigned = list(
        schedule.assignments.items()
    )

    for i in range(len(assigned)):

        class_a, placement_a = assigned[i]

        if placement_a.room_id is None:
            continue

        for j in range(i + 1, len(assigned)):

            class_b, placement_b = assigned[j]

            if (
                placement_b.room_id
                != placement_a.room_id
            ):
                continue

            if placements_overlap(
                placement_a,
                placement_b,
            ):
                violations["room"] += 1

    # --------------------------------------------------------
    # Required distributions
    # --------------------------------------------------------

    for distribution in instance.distributions:

        if not distribution.required:
            continue

        if required_distribution_violation(
            instance,
            distribution,
            schedule,
        ):
            violations[
                "required_distribution"
            ] += 1

    return violations


# ============================================================
# FEASIBILITY
# ============================================================

def is_feasible(
    instance: Instance,
    schedule: Schedule,
) -> bool:

    if not schedule.is_complete:
        return False

    violations = validate_schedule(
        instance,
        schedule,
    )

    return (
        violations["unassigned"] == 0
        and violations["room"] == 0
        and violations["required_distribution"] == 0
        and violations["other"] == 0
    )


# ============================================================
# SUMMARY
# ============================================================

def summarize_violations(
    instance: Instance,
    schedule: Schedule,
) -> None:

    violations = validate_schedule(
        instance,
        schedule,
    )

    print(
        f"Assigned classes: "
        f"{schedule.assigned_count}"
    )

    print(
        f"Total classes: "
        f"{len(instance.classes)}"
    )

    print()

    print(
        f"Unassigned: "
        f"{violations['unassigned']}"
    )

    print(
        f"Room violations: "
        f"{violations['room']}"
    )

    print(
        f"Required distribution violations: "
        f"{violations['required_distribution']}"
    )

    print(
        f"Other violations: "
        f"{violations['other']}"
    )

    print()

    print(
        "Feasible:",
        is_feasible(
            instance,
            schedule,
        ),
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    from parser import (
        parse_instance,
        validate_instance,
    )

    instance = parse_instance(
        "data/pu-d5-spr17.xml"
    )

    validate_instance(instance)

    print(
        f"Loaded instance: {instance.name}"
    )

    # Empty schedule
    schedule = Schedule(instance)

    print()
    print("Empty schedule:")

    summarize_violations(
        instance,
        schedule,
    )

    # First placement baseline
    print()
    print("=" * 60)
    print("FIRST-PLACEMENT BASELINE")
    print("=" * 60)

    for class_id, cls in instance.classes.items():

        if cls.placements:

            schedule.assign(
                class_id,
                cls.placements[0],
            )

    summarize_violations(
        instance,
        schedule,
    )